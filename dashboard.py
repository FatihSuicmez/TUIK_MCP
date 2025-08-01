import os
import json
import jwt
from datetime import datetime, timedelta
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from flask import Flask, request, jsonify, render_template_string

# --- Yapılandırma Ayarları ---
PRIVATE_KEY_FILE = "private_key.pem"
PUBLIC_KEY_FILE = "public_key.pem"
TOKENS_FILE = "tokens.json" # Üretilen tokenları takip etmek için
ISSUER_URL = "http://127.0.0.1:8070" # MCP sunucumuzun adresi
AUDIENCE = "tuik-mcp-server" # Token'ın kimin için üretildiği

# --- Flask Web Sunucusu Başlatma ---
app = Flask(__name__)

# --- Anahtar Yönetimi Fonksiyonları ---
def generate_and_save_keys():
    """Yeni bir RSA anahtar çifti oluşturur ve bunları PEM dosyalarına kaydeder."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()

    # Özel anahtarı kaydet
    with open(PRIVATE_KEY_FILE, "wb") as f:
        f.write(private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ))
    print(f"'{PRIVATE_KEY_FILE}' oluşturuldu.")

    # Genel anahtarı kaydet
    with open(PUBLIC_KEY_FILE, "wb") as f:
        f.write(public_key.public_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PublicFormat.SubjectPublicKeyInfo
        ))
    print(f"'{PUBLIC_KEY_FILE}' oluşturuldu.")
    
    return private_key

def load_private_key():
    """Özel anahtarı dosyadan yükler, yoksa oluşturur."""
    if not os.path.exists(PRIVATE_KEY_FILE):
        print("Anahtar dosyaları bulunamadı, yenileri oluşturuluyor...")
        return generate_and_save_keys()
    else:
        with open(PRIVATE_KEY_FILE, "rb") as f:
            return serialization.load_pem_private_key(f.read(), password=None)

# --- Token Yönetimi Fonksiyonları ---
def load_tokens():
    """Aktif token listesini JSON dosyasından yükler."""
    if not os.path.exists(TOKENS_FILE):
        return []
    try:
        with open(TOKENS_FILE, "r") as f:
            return json.load(f)
    except json.JSONDecodeError:
        return []

def save_tokens(tokens):
    """Aktif token listesini JSON dosyasına kaydeder."""
    with open(TOKENS_FILE, "w") as f:
        json.dump(tokens, f, indent=2)

# --- HTML Arayüz Şablonu ---
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8">
    <title>Token Yönetim Paneli</title>
    <style>
        body { font-family: sans-serif; margin: 2em; background-color: #f4f4f9; color: #333; }
        h1, h2 { color: #444; }
        .container { max-width: 800px; margin: auto; background: white; padding: 2em; border-radius: 8px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
        .token { border: 1px solid #ddd; padding: 1em; margin-bottom: 1em; border-radius: 5px; background-color: #fafafa; }
        .token p { word-break: break-all; }
        code { background: #eee; padding: 2px 5px; border-radius: 3px; }
        input[type='text'] { padding: 8px; width: 300px; border: 1px solid #ccc; border-radius: 4px; }
        button { padding: 10px 15px; border: none; background-color: #007bff; color: white; border-radius: 4px; cursor: pointer; }
        button:hover { background-color: #0056b3; }
    </style>
</head>
<body>
    <div class="container">
        <h1>Token Yönetim Paneli</h1>
        
        <h2>Yeni Token Oluştur</h2>
        <form action="/generate" method="post">
            <label for="subject">Kullanıcı/İstemci Adı (örn: n8n_kullanicisi):</label><br><br>
            <input type="text" id="subject" name="subject" required>
            <button type="submit">Token Oluştur</button>
        </form>
        
        <h2>Aktif Token'lar</h2>
        {% for token_info in tokens %}
            <div class="token">
                <p><strong>Kullanıcı:</strong> {{ token_info.subject }}</p>
                <p><strong>Token:</strong> <code>{{ token_info.token }}</code></p>
                <form action="/revoke" method="post" style="display:inline;">
                    <input type="hidden" name="token_to_revoke" value="{{ token_info.token }}">
                    <button type="submit" style="background-color:#dc3545;">İptal Et</button>
                </form>
            </div>
        {% else %}
            <p>Aktif token bulunmuyor.</p>
        {% endfor %}
    </div>
</body>
</html>
"""

# --- Web Rotaları (URL'ler) ---
@app.route("/")
def index():
    """Ana paneli ve aktif tokenları gösterir."""
    tokens = load_tokens()
    return render_template_string(HTML_TEMPLATE, tokens=tokens)

@app.route("/generate", methods=["POST"])
def generate_token_route():
    """Verilen kullanıcı adı için yeni bir JWT oluşturur."""
    subject = request.form.get("subject")
    if not subject:
        return "Kullanıcı adı gerekli", 400
    
    private_key = load_private_key()
    
    # Token oluşturma
    token = jwt.encode(
        {
            "iss": ISSUER_URL,
            "sub": subject,
            "aud": AUDIENCE,
            "exp": datetime.utcnow() + timedelta(days=365) # 1 yıl geçerli
        },
        private_key,
        algorithm="RS256"
    )

    # Token'ı kaydet
    tokens = load_tokens()
    tokens.append({"subject": subject, "token": token})
    save_tokens(tokens)
    
    return index()

@app.route("/revoke", methods=["POST"])
def revoke_token_route():
    """Bir token'ı aktif listeden kaldırarak iptal eder."""
    token_to_revoke = request.form.get("token_to_revoke")
    tokens = load_tokens()
    tokens = [t for t in tokens if t.get("token") != token_to_revoke]
    save_tokens(tokens)
    
    return index()

# --- Ana Çalıştırma Bloğu ---
if __name__ == "__main__":
    # Sunucuyu başlatmadan önce anahtarların var olduğundan emin ol
    load_private_key()
    # Flask sunucusunu 8050 portunda çalıştır
    app.run(host="0.0.0.0", port=8050, debug=True)
