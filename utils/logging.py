"""
Proje için loglama (günlük tutma) yardımcı programları.
"""
import os
import logging
from datetime import datetime
from typing import Optional

class DayNameFormatter(logging.Formatter):
    """Log kayıtlarına gün adını ekleyen özel formatlayıcı."""
    
    def format(self, record):
        """
        Log kaydını formatlar.

        Args:
            record: Log kaydı nesnesi.

        Returns:
            Formatlanmış log kaydı.
        """
        day_name = datetime.now().strftime('%A')
        record.day_name = day_name
        return super().format(record)

def setup_logger(
    name: str,
    log_dir: Optional[str] = None,
    level: int = logging.INFO
) -> logging.Logger:
    """
    Dosya çıktısı ve gün adı formatlaması ile bir logger (günlükleyici) ayarlar.
    
    Args:
        name: Logger'ın adı.
        log_dir: Logların kaydedileceği dizin (varsayılan: ./logs).
        level: Loglama seviyesi.
        
    Returns:
        Yapılandırılmış logger nesnesi.
    """
    # Ana betiğin bulunduğu dizini al
    if log_dir is None:
        # Bu dosyanın bulunduğu dizin (utils)
        script_dir = os.path.dirname(os.path.abspath(__file__))
        # Ana proje dizinine çıkıp 'logs' klasörünü hedefle
        log_dir = os.path.join(os.path.dirname(script_dir), "logs")
    
    # 'logs' dizini yoksa oluştur
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
    # Mevcut tarih ve gün adıyla log dosya adı oluştur
    current_date = datetime.now()
    day_name = current_date.strftime('%A')
    date_str = current_date.strftime('%Y-%m-%d')
    log_filename = os.path.join(log_dir, f"mcp_sunucu_{date_str}_{day_name}.log")
    
    # Logger oluştur
    logger = logging.getLogger(name)
    logger.setLevel(level)
    
    # Tekrarlanan logları önlemek için mevcut handler'ları temizle
    if logger.hasHandlers():
        logger.handlers.clear()
    
    # Dosya handler'ı oluştur
    file_handler = logging.FileHandler(log_filename, mode='a', encoding='utf-8')
    file_handler.setLevel(level)
    
    # Formatlayıcı oluştur
    formatter = DayNameFormatter(
        '%(asctime)s - %(day_name)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    file_handler.setFormatter(formatter)
    
    # Handler'ı logger'a ekle
    logger.addHandler(file_handler)
    
    # Konsol handler'ı da ekleyelim ki terminalde de logları görelim
    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)
    
    logger.info(f"Logger '{name}' başlatıldı. Loglar şu dosyaya kaydedilecek: {log_filename}")
    
    return logger
