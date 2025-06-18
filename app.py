# app.py v15.0 - Versão Final com todas as funcionalidades do MVP web
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

# --- CONFIGURAÇÃO DE PRODUÇÃO ---
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False
CORS(app, 
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], 
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True
)

# --- INICIALIZAÇÃO SEGURA ---
url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
service_key: str = os.environ.get("SUPABASE_SERVICE_KEY").strip()
supabase_admin: Client = create_client(url, service_key)

# --- DECORADOR DE AUTENTICAÇÃO ---
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "): return jsonify({"error": "Token não fornecido"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user = supabase_admin.auth.get_user(jwt_token).user
            if not user: return jsonify({"error": "Token inválido"}), 401
            profile = supabase_admin.table('profiles').select('business_id').eq('id', user.id).single().execute().data
            if not profile: return jsonify({"error": "Perfil não encontrado"}), 403
            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({"error": "Erro na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

# --- FUNÇÃO AUXILIAR ---
def format_service_response(service):
    if service and 'duration_minutes' in service:
        service['duration'] = service.pop('duration_minutes')
    return service

# --- ROTAS PÚBLICAS ---
@app.route("/")
def index(): return "API do Fluxo v15.0 - Final"
@app.route("/api/health", methods=['GET'])
def health_check(): return jsonify({"status": "ok"})
@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        supabase_admin.rpc('handle_new_user', {'user_id': data.get('user_id'),'full_name': data.get('full_name'),'business_name': data.get('business_name')}).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 400

# --- ROTAS DE SERVIÇOS ---
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    response = supabase_admin.table('services').select('*').eq('business_id', business_id).order('name').execute()
    formatted_data = [format_service_response(s) for s in response.data]
    return jsonify(formatted_data), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json()
    try:
        response = supabase_admin.table('services').insert({'name': data.get('name'),'price': float(data.get('price')),'duration_minutes': int(data.get('duration')),'business_id': business_id}).execute()
        return jsonify(format_service_response(response.data[0])), 201
    except Exception as e: return jsonify({"error": "Erro ao criar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['PUT'])
@auth_required
def update_service(service_id, business_id):
    data = request.get_json()
    try:
        response = supabase_admin.table('services').update({'name': data.get('name'),'price': float(data.get('price')),'duration_minutes': int(data.get('duration'))}).eq('id', service_id).eq('business_id', business_id).execute()
        if not response.data: return jsonify({"error": "Serviço não encontrado"}), 404
        return jsonify(format_service_response(response.data[0])), 200
    except Exception as e: return jsonify({"error": "Erro ao atualizar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    response = supabase_admin.table('services').delete().eq('id', service_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify({"message": "Serviço apagado com sucesso"}), 200

# --- ROTAS DE PROFISSIONAIS ---
@app.route("/api/professionals", methods=['GET'])
@auth_required
def get_professionals(business_id):
    response = supabase_admin.table('professionals').select('*, services:services(*)').eq('business_id', business_id).order('name').execute()
    # Renomeia a chave 'services' para consistência, se necessário, ou ajusta o front-end
    for prof in response.data:
        for serv in prof.get('services', []):
            format_service_response(serv)
    return jsonify(response.data), 200

@app.route("/api/professionals", methods=['POST'])
@auth_required
def create_professional(business_id):
    data = request.get_json()
    try:
        # Passo 1: Criar o profissional
        prof_response = supabase_admin.table('professionals').insert({
            'name': data.get('name'), 
            'business_id': business_id
        }).execute()
        new_professional_id = prof_response.data[0]['id']

        # Passo 2: Verificar e associar os serviços enviados
        service_ids = data.get('service_ids', [])
        if service_ids:
            associations_to_insert = [
                {'professional_id': new_professional_id, 'service_id': s_id}
                for s_id in service_ids
            ]
            supabase_admin.table('professional_services').insert(associations_to_insert).execute()
        
        # Passo 3: Retornar o profissional completo, já com os serviços associados
        final_professional_response = supabase_admin.table('professionals').select('*, services(*)').eq('id', new_professional_id).single().execute()
        
        return jsonify(final_professional_response.data), 201
    except Exception as e:
        return jsonify({"error": "Erro ao criar profissional", "details": str(e)}), 500

@app.route("/api/professionals/<professional_id>", methods=['DELETE'])
@auth_required
def delete_professional(professional_id, business_id):
    response = supabase_admin.table('professionals').delete().eq('id', professional_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Profissional não encontrado"}), 404
    return jsonify({"message": "Profissional apagado com sucesso"}), 200

@app.route("/api/professionals/<professional_id>/services", methods=['POST'])
@auth_required
def add_service_to_professional(professional_id, business_id):
    data = request.get_json()
    service_id = data.get('service_id')
    try:
        response = supabase_admin.table('professional_services').insert({'professional_id': professional_id, 'service_id': service_id}).execute()
        return jsonify(response.data[0]), 201
    except Exception as e: return jsonify({"error": str(e)}), 400

@app.route("/api/professionals/<professional_id>/services/<service_id>", methods=['DELETE'])
@auth_required
def remove_service_from_professional(professional_id, service_id, business_id):
    response = supabase_admin.table('professional_services').delete().match({'professional_id': professional_id, 'service_id': service_id}).execute()
    if not response.data: return jsonify({"error": "Associação não encontrada"}), 404
    return jsonify({"message": "Associação removida com sucesso"}), 200

if __name__ == '__main__':
    app.run()