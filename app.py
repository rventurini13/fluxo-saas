# app.py v7.2 - Correção final para criar serviços
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

# Configurações de Produção
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
                return jsonify({"error": "Falha de consistência de dados do perfil"}), 403
            kwargs['business_id'] = profiles[0]['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

# --- Rota create_service CORRIGIDA ---
@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json()
    try:
        # A linha 'business_id': business_id estava em falta e foi adicionada
        response = supabase.table('services').insert({
            'name': data.get('name'),
            'price': float(data.get('price')), # Garante que o preço é um número
            'duration_minutes': int(data.get('duration')), # Garante que a duração é um número
            'business_id': business_id # A CORREÇÃO CRÍTICA ESTÁ AQUI
        }).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": "Erro ao criar serviço no backend", "details": str(e)}), 500

# (Todo o resto do código continua igual, aqui está ele completo para não haver erros)
@app.route("/")
def index(): return "API do Fluxo v7.2 - Final"
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
@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    response = supabase.table('services').delete().eq('id', service_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify({"message": "Serviço apagado com sucesso"}), 200
@app.route("/api/professionals", methods=['GET'])
@auth_required
def get_professionals(business_id):
    response = supabase.table('professionals').select('*, services(*)').eq('business_id', business_id).order('name').execute()
    return jsonify(response.data), 200
@app.route("/api/professionals", methods=['POST'])
@auth_required
def create_professional(business_id):
    data = request.get_json()
    try:
        response = supabase.table('professionals').insert({'name': data.get('name'), 'business_id': business_id}).execute()
        new_professional = response.data[0]
        new_professional['services'] = []
        return jsonify(new_professional), 201
    except Exception as e: return jsonify({"error": str(e)}), 500
@app.route("/api/professionals/<professional_id>", methods=['DELETE'])
@auth_required
def delete_professional(professional_id, business_id):
    response = supabase.table('professionals').delete().eq('id', professional_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Profissional não encontrado"}), 404
    return jsonify({"message": "Profissional apagado com sucesso"}), 200
@app.route("/api/professionals/<professional_id>/services", methods=['POST'])
@auth_required
def add_service_to_professional(professional_id, business_id):
    data = request.get_json()
    response = supabase.table('professional_services').insert({'professional_id': professional_id, 'service_id': data.get('service_id')}).execute()
    return jsonify(response.data[0]), 201
@app.route("/api/professionals/<professional_id>/services/<service_id>", methods=['DELETE'])
@auth_required
def remove_service_from_professional(professional_id, service_id, business_id):
    response = supabase.table('professional_services').delete().match({'professional_id': professional_id, 'service_id': service_id}).execute()
    if not response.data: return jsonify({"error": "Associação não encontrada"}), 404
    return jsonify({"message": "Associação removida com sucesso"}), 200

if __name__ == '__main__':
    app.run()