import os
import json
import pandas as pd
import google.generativeai as genai
from io import StringIO
import time
import numpy as np
import faiss
from sentence_transformers import SentenceTransformer
import pickle
from multiprocessing import Pool, cpu_count, freeze_support
import argparse
import csv
from datetime import datetime

# --- KONTROL NOKTASI VE LOG DOSYA ADLARI ---
PROCESSED_LOG_FILE = 'processed_files.log'
FAILED_LOG_FILE = 'failed_files.log'
CHUNKS_CHECKPOINT_FILE = 'all_chunks.pkl'

# ==============================================================================
# FONKSİYON 1: Tüm Dosya Bilgilerini Yükleme
# ==============================================================================
def load_all_files_from_data_json():
    """
    data.json dosyasını okur ve her dosya için tam yolunu ve kategori adını
    içeren bir liste döndürür.
    """
    print("data.json okunuyor ve dosya yolları hazırlanıyor...")
    try:
        with open('data.json', 'r', encoding='utf-8') as f:
            all_data = json.load(f)
    except FileNotFoundError:
        print("HATA: data.json dosyası bulunamadı. Lütfen önce prepare_data.py betiğini çalıştırın.")
        return []

    file_info_list = []
    base_data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data')
    for category in all_data:
        kategori_folder = category.get("kategori")
        kategori_adi = category.get("name", "Bilinmeyen Kategori")
        files = category.get("files", [])
        for file_name in files:
            full_path = os.path.join(base_data_dir, kategori_folder, file_name)
            if os.path.exists(full_path):
                file_info_list.append({
                    "path": full_path,
                    "category": kategori_adi
                })
    print(f"Toplam {len(file_info_list)} adet Excel dosyası bulundu.")
    return file_info_list

# ==============================================================================
# FONKSİYON 2: Ayrıntılı Hata Kaydı
# ==============================================================================
def log_failure(file_info, error_message):
    """Başarısız olan dosyaları ve hata nedenlerini CSV dosyasına yazar."""
    file_basename = os.path.basename(file_info['path'])
    category_name = file_info['category']
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    write_header = not os.path.exists(FAILED_LOG_FILE)
    with open(FAILED_LOG_FILE, 'a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        if write_header:
            writer.writerow(['timestamp', 'category', 'filename', 'error_message'])
        writer.writerow([timestamp, category_name, file_basename, str(error_message)])

# ==============================================================================
# FONKSİYON 3: Gemini ile Chunk Oluşturma (Tekrar Deneme Mekanizmalı)
# ==============================================================================
def get_llm_chunks_from_gemini(table_as_csv_string: str, file_name: str, max_retries: int = 3) -> list:
    model = genai.GenerativeModel('gemini-2.5-pro')
    prompt = f"""
    Sen, karmaşık ve düzensiz TÜİK Excel tablolarını analiz etme konusunda uzman bir veri analistisin.
    Görevin, sana CSV formatında verilen bir tabloyu inceleyip, içindeki her anlamlı veri noktasını,
    kendi başına bir anlam ifade eden, bağlamı zenginleştirilmiş tam bir cümleye dönüştürmektir.
    - Sadece gerçek veri içeren satırlara odaklan.
    - Sonucu, her cümlenin bir eleman olduğu bir JSON Array (liste) olarak döndür.
    - Sadece ve sadece JSON listesini döndür, başka hiçbir açıklama veya metin ekleme.
    İşte analiz edilecek tablo. Dosya Adı: {file_name}\n\nTablo (CSV Formatı):\n{table_as_csv_string}
    """
    for attempt in range(max_retries):
        try:
            response = model.generate_content(prompt, generation_config=genai.types.GenerationConfig(temperature=0.0))
            if not response.parts:
                if response.prompt_feedback.block_reason:
                    raise Exception(f"Cevap güvenlik nedeniyle engellendi (Sebep: {response.prompt_feedback.block_reason.name})")
                else:
                    raise Exception("Model boş bir cevap döndürdü.")
            content = response.text
            if content.strip().startswith("```json"):
                content = content.strip()[7:-3].strip()
            generated_chunks = json.loads(content)
            final_chunks = []
            if isinstance(generated_chunks, list):
                for text in generated_chunks:
                    final_chunks.append({'text': str(text), 'metadata': {'source': file_name, 'type': 'llm_generated_data_point'}})
            return final_chunks
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** (attempt + 1)
                print(f"     ⚠️ Hata (Deneme {attempt + 1}/{max_retries}), {wait_time} saniye sonra tekrar denenecek: {e}")
                time.sleep(wait_time)
            else:
                raise e
    return []

# ==============================================================================
# FONKSİYON 4: Tek Dosyayı İşleme
# ==============================================================================
def process_file_with_llm(file_path):
    try:
        df = pd.read_excel(file_path, header=None, engine='openpyxl' if file_path.endswith('.xlsx') else 'xlrd')
        df.dropna(how='all', inplace=True); df.dropna(how='all', axis=1, inplace=True)
        csv_buffer = StringIO()
        df.to_csv(csv_buffer, index=False, header=False)
        csv_string = csv_buffer.getvalue()
        if len(csv_string.splitlines()) > 250:
            csv_string = "\n".join(csv_string.splitlines()[:250])
        return get_llm_chunks_from_gemini(csv_string, os.path.basename(file_path))
    except Exception as e:
        raise e

# ==============================================================================
# FONKSİYON 5: Multiprocessing için Sarmalayıcı Fonksiyon
# ==============================================================================
def process_file_wrapper(args):
    index, total, file_info = args
    file_basename = os.path.basename(file_info['path'])
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key: raise ValueError("GOOGLE_API_KEY worker process'te bulunamadı.")
        genai.configure(api_key=api_key)
        print(f"  -> [{index}/{total} | {file_info['category']}] İşleniyor: {file_basename}")
        result_chunks = process_file_with_llm(file_info['path'])
        return (file_basename, result_chunks)
    except Exception as e:
        log_failure(file_info, e)
        return (file_basename, [])

# ==============================================================================
# FONKSİYON 6: Ana Fonksiyon
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="TÜİK verilerini işleyip RAG veritabanı oluşturan betik.")
    parser.add_argument('--reprocess-failed', action='store_true', help="Sadece 'failed_files.log' dosyasındaki başarısız dosyaları yeniden işler.")
    args = parser.parse_args()
    print(f"--- RAG Veritabanı Oluşturucu Başlatıldı ---")
    
    try:
        api_key = os.environ.get("GOOGLE_API_KEY")
        if not api_key: raise ValueError("GOOGLE_API_KEY ortam değişkeni bulunamadı.")
        genai.configure(api_key=api_key)
        print("✅ Google API anahtarı başarıyla yüklendi.")
    except Exception as e:
        print(f"❌ HATA: {e}"); exit()

    full_file_info_list = load_all_files_from_data_json()
    if not full_file_info_list: exit()

    files_to_process_info = []
    if args.reprocess_failed:
        print(f"** Yeniden İşleme Modu Aktif **")
        if not os.path.exists(FAILED_LOG_FILE): print(f"'{FAILED_LOG_FILE}' bulunamadı."); exit()
        with open(FAILED_LOG_FILE, 'r', newline='', encoding='utf-8') as f:
            reader = csv.reader(f)
            try:
                next(reader); failed_filenames = {row[2] for row in reader}
            except StopIteration: failed_filenames = set()
        if not failed_filenames: print("Başarısız dosya bulunamadı."); exit()
        print(f"'{FAILED_LOG_FILE}' dosyasından {len(failed_filenames)} adet başarısız dosya yeniden işlenecek.")
        files_to_process_info = [info for info in full_file_info_list if os.path.basename(info['path']) in failed_filenames]
        os.remove(FAILED_LOG_FILE)
    else:
        print("** Normal İşleme Modu Aktif **")
        processed_files = set()
        if os.path.exists(PROCESSED_LOG_FILE):
            with open(PROCESSED_LOG_FILE, 'r', encoding='utf-8') as f:
                processed_files = set(line.strip() for line in f)
        files_to_process_info = [info for info in full_file_info_list if os.path.basename(info['path']) not in processed_files]

    if not files_to_process_info:
        print("✅ İşlenecek yeni dosya bulunamadı. Gömme (embedding) adımına geçiliyor.")
    else:
        print(f"\n{len(files_to_process_info)} adet dosya Gemini ile işlenecek (paralel olarak)...")
        worker_count = 8
        print(f"Kullanılacak paralel işlemci sayısı: {worker_count}")
        tasks_with_metadata = [(idx + 1, len(files_to_process_info), info) for idx, info in enumerate(files_to_process_info)]
        
        with Pool(processes=worker_count) as pool:
            for file_basename, result_chunks in pool.imap_unordered(process_file_wrapper, tasks_with_metadata):
                if result_chunks:
                    print(f"     ... {file_basename} için {len(result_chunks)} adet chunk başarıyla oluşturuldu.")
                    with open(PROCESSED_LOG_FILE, 'a', encoding='utf-8') as f_log:
                        f_log.write(f"{file_basename}\n")
                    with open(CHUNKS_CHECKPOINT_FILE, 'ab') as f_chunks:
                        pickle.dump(result_chunks, f_chunks)

    print("\nParalel işlemler tamamlandı. Sonuçlar birleştiriliyor...")
    all_chunks = []
    if os.path.exists(CHUNKS_CHECKPOINT_FILE):
        try:
            file_size_mb = os.path.getsize(CHUNKS_CHECKPOINT_FILE) / (1024 * 1024)
            print(f"'{CHUNKS_CHECKPOINT_FILE}' okunuyor ({file_size_mb:.2f} MB). Bu işlem biraz sürebilir...")
            with open(CHUNKS_CHECKPOINT_FILE, 'rb') as f:
                while True:
                    all_chunks.extend(pickle.load(f))
        except EOFError:
            pass
        except Exception as e:
            print(f"Checkpoint dosyası okunurken hata: {e}")
    
    if not all_chunks:
        print("❌ Hiç metin parçası (chunk) oluşturulamadı. Gömme işlemi atlanıyor."); exit()
    print(f"✅ Hafızaya toplam {len(all_chunks)} adet chunk yüklendi.")
    
    model_name = 'paraphrase-multilingual-mpnet-base-v2'
    print(f"\nEmbedding modeli ('{model_name}') yükleniyor...")
    print("Not: Bu model ~1.11 GB boyutundadır ve hafızaya yüklenmesi zaman alabilir.")
    model = SentenceTransformer(model_name)
    print("✅ Embedding modeli başarıyla yüklendi.")
    
    texts_to_embed = [chunk['text'] for chunk in all_chunks]
    print(f"\n{len(texts_to_embed)} adet metin parçası vektörlere dönüştürülüyor...")
    embeddings = model.encode(texts_to_embed, show_progress_bar=True)
    embeddings = np.array(embeddings).astype('float32')
    
    embedding_dimension = embeddings.shape[1]
    index = faiss.IndexFlatL2(embedding_dimension)
    index.add(embeddings)
    faiss.write_index(index, 'tuik_faiss.index')
    print(f"✅ FAISS veritabanı 'tuik_faiss.index' olarak kaydedildi.")

    with open('tuik_chunks.pkl', 'wb') as f:
        pickle.dump(all_chunks, f)
    print("✅ Metin parçaları kalıcı olarak 'tuik_chunks.pkl' dosyasına kaydedildi.")
    print("\n🎉 Tebrikler! RAG veritabanınız başarıyla oluşturuldu! 🎉")

# ==============================================================================
# Betik Başlatma Noktası
# ==============================================================================
if __name__ == "__main__":
    freeze_support()
    main()