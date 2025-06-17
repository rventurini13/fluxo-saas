# app.py v4.1 - Versão Final de Produção
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix # Garante que estamos a usar

load_dotenv()
app = Flask(__name__)

# --- CONFIGURAÇÕES DE PRODUÇÃO ---
# Aplica o ProxyFix para que o Flask entenda os cabeçalhos do proxy da Railway
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# Configuração CORS explícita e robusta
CORS(app, 
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], 
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True
)

# ... (o resto do código, como Supabase client e o decorador, continua o mesmo) ...
url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

def auth_required(f):
    # ... (código do decorador)
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "): return jsonify({"error": "Token não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user = supabase.auth.get_user(jwt_token).user
            if not user: return jsonify({"error": "Token inválido ou expirado"}), 401
            profile = supabase.table('profiles').select('business_id').eq('id', user.id).single().execute().data
            if not profile: return jsonify({"error": "Perfil não encontrado para este usuário"}), 403
            kwargs['business_id'] = profile['business_id']
        except Exception as e: return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

# ... (todas as suas rotas aqui, sem alterações na lógica delas) ...

if __name__ == '__main__':
    # Em produção, o Gunicorn lida com host e porta
    app.run()