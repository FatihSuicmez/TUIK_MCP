import os
import json
import pickle
import faiss
import numpy as np
import asyncio
import jwt
import click
from collections import namedtuple
from typing import Dict, Any, Optional

from mcp.server.fastmcp import FastMCP
from sentence_transformers import SentenceTransformer
# Orijinal kodunuzda olan ama bizim RAG sunucusunda olmayan bazı importları geri ekledik
from utils.logging import setup_logger

# --- YENİ EKLENEN RAG BİLEŞENLERİ ---
# Modelleri ve veritabanını sunucu başlamadan önce bir kez yükle
try:
    print("Embedding modeli yükleniyor...")
    MODEL = SentenceTransformer('paraphrase-multilingual-mpnet-base-v2')
    print("✅ Embedding modeli yüklendi.")
    print("FAISS veritabanı ve metin chunk'ları yükleniyor...")
    FAISS_INDEX = faiss.read_index('tuik_faiss.index')
    with open('tuik_chunks.pkl', 'rb') as f:
        CHUNKS = pickle.load(f)
    print(f"✅ Veritabanı ve {len(CHUNKS)} adet chunk başarıyla yüklendi.")
except Exception as e:
    print(f"❌ HATA: Model veya veritabanı dosyaları yüklenirken bir sorun oluştu: {e}")
    MODEL, FAISS_INDEX, CHUNKS = None, None, None

# --- ORİJİNAL KODUNUZDAN KORUNAN YAPILAR ---
# --- GÜVENLİK AYARLARI ---
PUBLIC_KEY_FILE = "public_key.pem"
ISSUER_URL = "http://127.0.0.1:8070" 
AUDIENCE = "tuik-mcp-server"

AuthInfo = namedtuple("AuthInfo", ["claims", "expires_at", "scopes", "client_id"])

class SimpleBearerAuthProvider:
    def __init__(self, public_key: bytes, issuer: str, audience: str):
        self.public_key = public_key
        self.issuer = issuer
        self.audience = audience
        self.logger = setup_logger(__name__)

    async def verify_token(self, token: str) -> Dict[str, Any]:
        try:
            decoded_token = jwt.decode(
                token, self.public_key, algorithms=["RS256"],
                audience=self.audience, issuer=self.issuer,
            )
            client_id = decoded_token.get("sub")
            return AuthInfo(claims=decoded_token, expires_at=decoded_token.get("exp"), scopes=[], client_id=client_id)
        except jwt.PyJWTError as e:
            self.logger.error(f"Token verification failed: {e}")
            raise Exception("Invalid token")

class ConfigurationError(Exception):
    pass

class PaymentMCPServer: # Orijinal sınıf adınızı koruyoruz
    def __init__(self, host: str, port: int, transport: str, auth_token: Optional[str] = None):
        self.logger = setup_logger(__name__)
        self.mcp = None
        self.host = host
        self.port = port
        self.transport = transport
        self.auth_token = auth_token
    
    async def initialize(self) -> FastMCP:
        self.logger.info(f"Initializing MCP server")
        auth_provider = None
        if self.transport == 'sse':
            self.logger.info("SSE transport: setting up Simple Bearer authentication.")
            try:
                with open(PUBLIC_KEY_FILE, "rb") as f:
                    public_key = f.read()
                auth_provider = SimpleBearerAuthProvider(
                    public_key=public_key, issuer=ISSUER_URL, audience=AUDIENCE
                )
                self.logger.info("Authentication provider loaded with public key.")
            except FileNotFoundError:
                self.logger.error(f"{PUBLIC_KEY_FILE} not found. Please run dashboard.py to generate it.")
                raise ConfigurationError(f"{PUBLIC_KEY_FILE} not found.")

        auth_config = None
        if auth_provider:
            resource_server_url = f"http://{self.host}:{self.port}"
            auth_config = {
                "issuer_url": ISSUER_URL,
                "resource_server_url": resource_server_url,
            }

        self.mcp = FastMCP(
            name="TUIK RAG MCP Server", # İsmi güncelledik
            host=self.host, port=self.port,
            token_verifier=auth_provider,
            auth=auth_config,
        )
        
        self._register_tools()
        
        self.logger.info("MCP server initialized successfully")
        return self.mcp
        
    # --- DEĞİŞTİRİLEN KISIM: Araçlar ---
    def _register_tools(self):
        """Register MCP tools."""
        
        # Eski 'analyze_question_and_select_files' ve 'read_and_convert_files' araçları silindi.
        # Yerine tek ve güçlü RAG aracı geldi.
        @self.mcp.tool()
        async def answer_question_with_rag(user_question: str, top_k: int = 5) -> str:
            """
            Kullanıcının sorusunu alır, vektör veritabanında arar, en alakalı
            bilgileri bulur ve nihai bir cevap oluşturmak için bir prompt hazırlar.
            """
            if not all([MODEL, FAISS_INDEX, CHUNKS]):
                return json.dumps({"error": "Sunucu başlangıcında RAG modelleri yüklenemedi."})

            print(f"\n🔎 Gelen Soru: '{user_question}'")
            question_embedding = MODEL.encode(user_question)
            question_embedding = np.array([question_embedding]).astype('float32')
            
            print(f"🧠 FAISS veritabanında en yakın {top_k} sonuç aranıyor...")
            distances, indices = FAISS_INDEX.search(question_embedding, top_k)
            
            retrieved_chunks = [CHUNKS[i] for i in indices[0]]
            context = "\n\n---\n\n".join([chunk['text'] for chunk in retrieved_chunks])
            sources = list(set([chunk['metadata']['source'] for chunk in retrieved_chunks]))
            print("📚 İlgili metinler başarıyla bulundu.")
            
            final_prompt = f"""## GÖREV ##\nSen, Türkiye İstatistik Kurumu (TÜİK) verileri konusunda uzman bir veri analistisin...\n\n## BAĞLAM ##\n{context}\n\n## KAYNAKLAR ##\n{', '.join(sources)}\n\n## KULLANICI SORUSU ##\n{user_question}\n\n## CEVAP ##"""
            
            result = {"user_question": user_question, "retrieved_context": context, "retrieved_sources": sources, "final_prompt_for_llm": final_prompt}
            return json.dumps(result, ensure_ascii=False, indent=2)

# --- ORİJİNAL KODUNUZDAN KORUNAN BAŞLATMA YAPISI ---
@click.command()
@click.option('--host', default='0.0.0.0', help='Server host (default: 0.0.0.0)')
@click.option('--port', default=8070, help='Server port (default: 8070)') # Portu orijinal haline (8070) geri getirdik
@click.option('--transport', envvar='TRANSPORT', default='sse', help='Transport type (default: sse)')
@click.option('--auth-token', envvar='AUTH_TOKEN', help='Bearer token for SSE transport.')
def main(host, port, transport, auth_token):
    """Start the TUIK RAG MCP server."""
    
    logger = setup_logger(__name__)
    
    try:
        valid_transports = ['stdio', 'sse']
        if transport not in valid_transports:
            raise ConfigurationError(f"Unsupported transport '{transport}'. Available: {', '.join(valid_transports)}")
        
        logger.info(f"Starting TUIK RAG MCP server")
        logger.info(f"Transport: {transport}")
        logger.info(f"Server will run on {host}:{port}")
        
        async def _run():
            server = PaymentMCPServer(host=host, port=port, transport=transport, auth_token=auth_token)
            mcp = await server.initialize()
            logger.info("MCP server started successfully")
            return mcp
        
        mcp = asyncio.run(_run())
        # Not: run_sse_async hatası almamak için doğrudan kütüphanenin run metodunu kullanalım
        # Kütüphane transport tipine göre doğru çalıştırıcıyı seçecektir.
        mcp.run(transport=transport)
        
    except Exception as e:
        logger.error(f"Failed to start server: {str(e)}")
        raise

if __name__ == "__main__":
    main()