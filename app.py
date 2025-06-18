# app.py v12.2 - Adiciona funcionalidade de UPDATE (PUT) para serviços
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
app = Flask(__name__)

# --- CONFIGURAÇÃO DE PRODUÇÃO ---
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
service_key: str = os.environ.get("SUPABASE_SERVICE_KEY").strip()

# Cliente administrativo, que tem permissões para chamar a função de signup
supabase_admin: Client = create_client(url, service_key)

def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "): return jsonify({"error": "Token não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user = supabase_admin.auth.get_user(jwt_token).user
            if not user: return jsonify({"error": "Token inválido ou expirado"}), 401
            
            # Usando o cliente admin para buscar o perfil, já que ele bypassa o RLS
            profile_response = supabase_admin.table('profiles').select('business_id').eq('id', user.id).single().execute()
            profile = profile_response.data
            if not profile: return jsonify({"error": "Perfil de usuário não encontrado"}), 403
            
            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

# --- ROTAS PÚBLICAS ---
@app.route("/")
def index(): return "API do Fluxo v12.2 - Final"

# --- ROTAS DE SERVIÇOS ---
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    response = supabase_admin.table('services').select('*').eq('business_id', business_id).order('name').execute()
    return jsonify(response.data), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json()
    response = supabase_admin.table('services').insert({'name': data.get('name'),'price': float(data.get('price')),'duration_minutes': int(data.get('duration')),'business_id': business_id}).execute()
    return jsonify(response.data[0]), 201

# --- NOVA ROTA DE UPDATE (PUT) ADICIONADA AQUI ---
@app.route("/api/services/<service_id>", methods=['PUT'])
@auth_required
def update_service(service_id, business_id):
    data = request.get_json()
    try:
        response = supabase_admin.table('services').update({
            'name': data.get('name'),
            'price': float(data.get('price')),
            'duration_minutes': int(data.get('duration'))
        }).eq('id', service_id).eq('business_id', business_id).execute()

        if not response.data:
            return jsonify({"error": "Serviço não encontrado ou não pertence a este negócio"}), 404
        
        return jsonify(response.data[0]), 200
    except Exception as e:
        return jsonify({"error": "Erro ao atualizar serviço", "details": str(e)}), 500
# --- FIM DA NOVA ROTA ---

@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    response = supabase_admin.table('services').delete().eq('id', service_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify({"message": "Serviço apagado com sucesso"}), 200

# (O resto das suas rotas de profissionais, etc., continua aqui como no arquivo que você enviou)
# ...

if __name__ == '__main__':
    app.run()