import os
import json
import pandas as pd
import asyncio
import click
import jwt
from typing import List, Dict, Any, Optional
from collections import namedtuple

# fastmcp kütüphanesinden sunucu oluşturmak için gerekli olan ana sınıfı içe aktarıyoruz.
from mcp.server.fastmcp import FastMCP
# Daha önce yazdığımız loglama yardımcısını içe aktarıyoruz.
from utils.logging import setup_logger

# --- GÜVENLİK AYARLARI ---
PUBLIC_KEY_FILE = "public_key.pem"
ISSUER_URL = "http://127.0.0.1:8070" 
AUDIENCE = "tuik-mcp-server"

AuthInfo = namedtuple("AuthInfo", ["claims", "expires_at", "scopes", "client_id"])

class SimpleBearerAuthProvider:
    """
    Gelen isteklerdeki JWT (JSON Web Token) formatındaki Bearer token'ları doğrulayan sınıf.
    """
    def __init__(self, public_key: bytes, issuer: str, audience: str):
        self.public_key = public_key
        self.issuer = issuer
        self.audience = audience
        self.logger = setup_logger(__name__)

    async def verify_token(self, token: str) -> Optional[AuthInfo]:
        """Token'ın imzasını, süresini ve taleplerini doğrular."""
        try:
            decoded_token = jwt.decode(
                token,
                self.public_key,
                algorithms=["RS256"],
                audience=self.audience,
                issuer=self.issuer,
            )
            client_id = decoded_token.get("sub")
            return AuthInfo(claims=decoded_token, expires_at=decoded_token.get("exp"), scopes=[], client_id=client_id)
        except jwt.PyJWTError as e:
            self.logger.error(f"Token doğrulama hatası: {e}")
            return None

class ConfigurationError(Exception):
    """Yapılandırma hatası için özel exception sınıfı."""
    pass

class TUIKMCPServer:
    """
    TÜİK verilerini işlemek için tasarlanmış ana MCP sunucu sınıfı.
    """
    def __init__(self, host: str = "0.0.0.0", port: int = 8070):
        self.logger = setup_logger(__name__)
        self.mcp = None
        self.host = host
        self.port = port
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
    
    async def initialize(self) -> FastMCP:
        """
        MCP sunucusunu başlatır, kimlik doğrulama mekanizmasını kurar ve araçları kaydeder.
        """
        self.logger.info(f"MCP sunucusu {self.host}:{self.port} adresinde başlatılıyor...")

        auth_provider = None
        auth_config = None # auth_config'i başlangıçta None olarak ayarlıyoruz.
        try:
            public_key_path = os.path.join(self.base_dir, PUBLIC_KEY_FILE)
            with open(public_key_path, "rb") as f:
                public_key = f.read()
            
            auth_provider = SimpleBearerAuthProvider(
                public_key=public_key,
                issuer=ISSUER_URL,
                audience=AUDIENCE
            )
            self.logger.info("Kimlik doğrulama sağlayıcısı genel anahtar (public key) ile yüklendi.")
            
            # --- HATA DÜZELTMESİ: auth_config'i burada tanımlıyoruz ---
            # Eğer bir auth_provider varsa, auth ayarlarını da oluşturmalıyız.
            if auth_provider:
                auth_config = {
                    "issuer_url": ISSUER_URL,
                    "resource_server_url": f"http://{self.host}:{self.port}",
                }
            # ---------------------------------------------------------

        except FileNotFoundError:
            self.logger.warning(f"{PUBLIC_KEY_FILE} bulunamadı. Sunucu kimlik doğrulaması olmadan çalışacak.")
            self.logger.warning("Bu sadece geliştirme ortamı için önerilir.")
        
        # FastMCP nesnesini kimlik doğrulama ayarlarıyla birlikte oluşturuyoruz.
        self.mcp = FastMCP(
            name="TUIK Veri Analiz Sunucusu",
            host=self.host,
            port=self.port,
            token_verifier=auth_provider,
            auth=auth_config, # DÜZELTME: Eksik olan parametreyi ekledik.
        )
        
        self._register_tools()
        
        self.logger.info("MCP sunucusu başarıyla başlatıldı ve araçlar kaydedildi.")
        return self.mcp

    def load_data_map_from_json(self) -> List[Dict[str, Any]]:
        """
        'data.json' dosyasını yükleyerek veri haritasını belleğe alır.
        """
        try:
            json_path = os.path.join(self.base_dir, 'data.json')
            with open(json_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except FileNotFoundError:
            self.logger.error("'data.json' bulunamadı. Lütfen 'prepare_data.py' betiğini çalıştırın.")
            return []

    def _register_tools(self):
        """
        Yapay zekanın kullanabileceği araçları (fonksiyonları) MCP sunucusuna kaydeder.
        """
        @self.mcp.tool()
        async def analyze_question_and_select_files(user_question: str) -> str:
            """
            Kullanıcının sorusunu analiz eder ve ilgili veri dosyalarını seçer.
            """
            self.logger.info(f"Gelen soru analiz ediliyor: '{user_question}'")
            all_data = self.load_data_map_from_json()
            if not all_data:
                return json.dumps({"error": "'data.json' dosyası boş veya bulunamadı."}, ensure_ascii=False)

            question_lower = user_question.lower()
            selected_files = []
            
            for category in all_data:
                category_name_lower = category['name'].lower()
                if any(word in category_name_lower for word in question_lower.split()):
                    selected_files.append({
                        "category_name": category['name'],
                        "category_path": category['kategori'],
                        "files": category['files'][:5]
                    })

            if not selected_files:
                for category in all_data:
                    for file_name in category['files']:
                        if any(word in file_name.lower() for word in question_lower.split()):
                             selected_files.append({
                                "category_name": category['name'],
                                "category_path": category['kategori'],
                                "files": [file_name]
                            })
            
            if not selected_files:
                return json.dumps({"error": "Soruyla ilgili uygun dosya bulunamadı."}, ensure_ascii=False)

            self.logger.info(f"{len(selected_files)} adet ilgili dosya grubu bulundu.")
            return json.dumps(selected_files, ensure_ascii=False, indent=2)

        @self.mcp.tool()
        async def read_and_process_files(selected_files_json: str) -> str:
            """
            Seçilen Excel dosyalarını okur ve içeriğini JSON formatına dönüştürür.
            """
            try:
                selected_groups = json.loads(selected_files_json)
                processed_data = {}

                for group in selected_groups:
                    category_path = group['category_path']
                    for file_name in group['files']:
                        file_path = os.path.join(self.base_dir, 'data', category_path, file_name)
                        
                        self.logger.info(f"'{file_path}' dosyası okunuyor...")
                        
                        try:
                            if os.path.exists(file_path):
                                engine = 'openpyxl' if file_name.endswith('.xlsx') else 'xlrd'
                                df = pd.read_excel(file_path, engine=engine, nrows=15)
                                df = df.where(pd.notnull(df), None)
                                processed_data[file_name] = df.to_dict('records')
                            else:
                                processed_data[file_name] = {"error": "Dosya bulunamadı."}
                        except Exception as e:
                            self.logger.error(f"'{file_name}' dosyası okunurken hata: {e}")
                            processed_data[file_name] = {"error": f"Dosya okunurken hata oluştu: {str(e)}"}
                
                return json.dumps(processed_data, ensure_ascii=False, indent=2, default=str)
            except Exception as e:
                self.logger.error(f"JSON verisi işlenirken hata: {e}")
                return json.dumps({"error": f"Gelen veri formatı hatalı: {str(e)}"}, ensure_ascii=False)

@click.command()
@click.option('--host', default='0.0.0.0', help='Sunucu adresi (varsayılan: 0.0.0.0)')
@click.option('--port', default=8070, help='Sunucu portu (varsayılan: 8070)')
def main(host, port):
    """TÜİK Veri Analizi MCP Sunucusunu başlatır."""
    
    async def _run():
        server = TUIKMCPServer(host=host, port=port)
        mcp_app = await server.initialize()
        mcp_app.run(transport='sse')

    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        print("\nSunucu kapatılıyor.")

if __name__ == "__main__":
    main()
