import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix # Importamos o ProxyFix

load_dotenv()
app = Flask(__name__)

# --- NOVAS CONFIGURAÇÕES DE PRODUÇÃO ---

# 1. Aplicamos o ProxyFix para que o Flask entenda os cabeçalhos
#    enviados pelo proxy da Railway (como X-Forwarded-For, etc.)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)

# 2. Configuração CORS explícita e robusta
CORS(app, 
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], 
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True
)
# --- FIM DAS NOVAS CONFIGURAÇÕES ---

url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

# ... (Todo o resto do seu código, decorador e rotas, continua exatamente igual) ...
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # ... (lógica do decorador)
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "): return jsonify({"error": "Token não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user_session = supabase.auth.get_user(jwt_token)
            user = user_session.user
            if not user: return jsonify({"error": "Token inválido ou expirado"}), 401
            profile_response = supabase.table('profiles').select('business_id').eq('id', user.id).execute()
            profiles = profile_response.data
            if not profiles or len(profiles) != 1:
                error_message = f"Perfil não encontrado ou duplicado para o usuário {user.id}. Perfis encontrados: {len(profiles)}"
                return jsonify({"error": "Falha de consistência de dados do perfil", "details": error_message}), 403
            kwargs['business_id'] = profiles[0]['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function
# ... (todas as suas rotas aqui) ...

if __name__ == '__main__':
    # Gunicorn irá lidar com host e porta em produção via Procfile
    app.run()