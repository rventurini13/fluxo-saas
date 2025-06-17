import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False
CORS(app, 
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], 
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True
)

url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "): return jsonify({"error": "Token não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user = supabase.auth.get_user(jwt_token).user
            if not user: return jsonify({"error": "Token inválido ou expirado"}), 401
            profile_response = supabase.table('profiles').select('business_id').eq('id', user.id).execute()
            profiles = profile_response.data
            if not profiles or len(profiles) != 1:
                error_message = f"Perfil não encontrado ou duplicado. Encontrados: {len(profiles)}"
                return jsonify({"error": "Falha de consistência de dados do perfil", "details": error_message}), 403
            kwargs['business_id'] = profiles[0]['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

@app.route("/")
def index(): return "API do Fluxo v5.3"

@app.route("/api/health")
def health_check(): return jsonify({"status": "ok"})

@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        supabase.rpc('handle_new_user', {'user_id': data.get('user_id'),'full_name': data.get('full_name'),'business_name': data.get('business_name')}).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    response = supabase.table('services').select('*').eq('business_id', business_id).order('name').execute()
    return jsonify(response.data), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json()
    try:
        response = supabase.table('services').insert({
            'name': data.get('name'),
            'price': data.get('price'),
            'duration_minutes': data.get('duration'), # CORREÇÃO APLICADA
            'business_id': business_id
        }).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": "Erro ao criar serviço no backend", "details": str(e)}), 500

# (O resto das rotas)
# ...

if __name__ == '__main__':
    app.run()