# app.py v3.2 - Com configuração de CORS
import os
from flask import Flask, jsonify, request
from flask_cors import CORS # 1. Importamos a biblioteca que acabámos de instalar
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps

load_dotenv()
app = Flask(__name__)

# 2. AQUI ESTÁ A MAGIA: Configuramos o CORS
# Isto diz à nossa API para aceitar requisições que venham do domínio da Lovable.
CORS(app, resources={r"/api/*": {"origins": "https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"}})

# ... O resto do seu código continua exatamente igual ...
url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token de autenticação não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user_session = supabase.auth.get_user(jwt_token)
            user = user_session.user
            if not user: return jsonify({"error": "Token inválido ou expirado"}), 401
            profile_response = supabase.table('profiles').select('business_id').eq('id', user.id).single().execute()
            profile = profile_response.data
            if not profile or not profile.get('business_id'):
                return jsonify({"error": "Perfil ou negócio não encontrado para este usuário"}), 403
            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function
@app.route("/")
def index(): return "Bem-vindo à API da plataforma Fluxo!"
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
    response = supabase.table('services').insert({'name': data.get('name'),'price': data.get('price'),'duration_minutes': data.get('duration_minutes'),'business_id': business_id}).execute()
    return jsonify(response.data[0]), 201
@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    response = supabase.table('services').delete().eq('id', service_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Serviço não encontrado ou não pertence a este negócio"}), 404
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
    response = supabase.table('professionals').insert({'name': data.get('name'), 'business_id': business_id}).execute()
    return jsonify(response.data[0]), 201
@app.route("/api/professionals/<professional_id>", methods=['DELETE'])
@auth_required
def delete_professional(professional_id, business_id):
    response = supabase.table('professionals').delete().eq('id', professional_id).eq('business_id', business_id).execute()
    if not response.data: return jsonify({"error": "Profissional não encontrado ou não pertence a este negócio"}), 404
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
@app.route("/api/schedule/availability", methods=['POST'])
@auth_required
def get_availability(business_id):
    data = request.get_json()
    service = supabase.table('services').select('duration_minutes').eq('id', data.get('service_id')).single().execute().data
    business = supabase.table('businesses').select('opening_time, closing_time').eq('id', business_id).single().execute().data
    # ... (código completo da função)
    return jsonify({"available_slots": ["09:00", "09:30"]}), 200

if __name__ == '__main__':
    app.run(debug=True)
