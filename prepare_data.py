import os
import json
import time
# Kendi özel scraper dosyamızdan TuikScraper sınıfını import ediyoruz
from custom_tuik_scraper import TuikScraper 

# Kategori listesini tüm TÜİK kategorilerini içerecek şekilde güncelliyoruz.
KATEGORILER = [
    ('Adalet ve Seçim', 'adalet'),
    ('Bilim, Teknoloji ve Bilgi Toplumu', 'bilim'),
    ('Çevre ve Enerji', 'cevre'),
    ('Dış Ticaret', 'dis_ticaret'),
    ('Eğitim, Kültür, Spor ve Turizm', 'egitim'),
    ('Ekonomik Güven', 'ekonomik_guven'),
    ('Enflasyon ve Fiyat', 'enflasyon'),
    ('Gelir, Yaşam, Tüketim ve Yoksulluk', 'gelir'),
    ('İnşaat ve Konut', 'konut'),
    ('İstihdam, İşsizlik ve Ücret', 'istihdam'),
    ('Nüfus ve Demografi', 'nufus'),
    ('Sağlık ve Sosyal Koruma', 'saglik'),
    ('Sanayi', 'sanayi'),
    ('Tarım', 'tarim'),
    ('Ticaret ve Hizmet', 'ticaret'),
    ('Ulaştırma ve Haberleşme', 'ulastirma'),
    ('Ulusal Hesaplar', 'ulusal')
]

def download_all_categories():
    """
    Tüm TÜİK kategorilerindeki verileri, her birini kendi klasörüne olacak şekilde indirir.
    """
    print("TÜM KATEGORİLER İÇİN VERİ İNDİRME İŞLEMİ BAŞLATILIYOR...")
    print("="*60)
    
    base_path = os.path.dirname(os.path.abspath(__file__))

    for kategori_adi, kategori_klasor_adi in KATEGORILER:
        # Her kategori için hedef indirme yolunu belirliyoruz.
        download_path = os.path.join(base_path, "data", kategori_klasor_adi)
        
        print(f"\n'{kategori_adi}' kategorisi için hazırlanılıyor...")
        
        try:
            # TuikScraper'ı başlatırken, dosyaları indirmesini istediğimiz klasörün yolunu veriyoruz.
            # Bu, güncellediğimiz custom_tuik_scraper.py'nin özelliğidir.
            tuik = TuikScraper(download_folder_path=download_path)
            tuik.indir(kategori_adi)
            
            print(f"'{kategori_adi}' kategorisi için indirme komutu tamamlandı.")
        except Exception as e:
            print(f"'{kategori_adi}' kategorisi indirilirken bir hata oluştu: {e}")
            
    print("="*60)
    print("Tüm indirme işlemleri tamamlandı.")

def create_data_json():
    """
    'data' klasörünü tarar ve indirilen dosyaları listeleyen 'data.json' dosyasını oluşturur.
    """
    print("\n'data.json' dosyası oluşturuluyor (veri haritası)...")
    print("="*60)
    
    base_path = os.path.dirname(os.path.abspath(__file__))
    data_dir = os.path.join(base_path, "data")
    
    all_data = []

    for kategori_adi, kategori_klasor_adi in KATEGORILER:
        kategori_yolu = os.path.join(data_dir, kategori_klasor_adi)
        
        if os.path.isdir(kategori_yolu):
            files = [f for f in os.listdir(kategori_yolu) if f.endswith(('.xls', '.xlsx'))]
            
            if files:
                print(f"-> '{kategori_adi}' kategorisinde {len(files)} dosya bulundu ve listeye eklendi.")
                kategori_data = {
                    "name": kategori_adi,
                    "kategori": kategori_klasor_adi,
                    "files": files
                }
                all_data.append(kategori_data)

    output_path = os.path.join(base_path, 'data.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(all_data, f, ensure_ascii=False, indent=4)
    
    print("="*60)
    print(f"Veri haritası başarıyla oluşturuldu: {output_path}")

if __name__ == "__main__":
    download_all_categories()
    create_data_json()
