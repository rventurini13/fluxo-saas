# app.py v15.0 - Versão Final Consolidada e Corrigida (com ajuste de duration)
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
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

# --- INICIALIZAÇÃO DAS VARIÁVEIS DE AMBIENTE ---
url_from_env = os.environ.get("SUPABASE_URL")
key_from_env = os.environ.get("SUPABASE_KEY")
service_key_from_env = os.environ.get("SUPABASE_SERVICE_KEY")

if not all([url_from_env, key_from_env, service_key_from_env]):
    raise ValueError("ERRO CRÍTICO: Variáveis de ambiente do Supabase não encontradas.")

url: str = url_from_env.strip()
key: str = key_from_env.strip()
service_key: str = service_key_from_env.strip()

supabase_admin: Client = create_client(url, service_key)

# --- DECORADOR DE AUTENTICAÇÃO ---
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user = supabase_admin.auth.get_user(jwt_token).user
            if not user:
                return jsonify({"error": "Token inválido ou expirado"}), 401

            profile_response = supabase_admin \
                .table('profiles') \
                .select('business_id') \
                .eq('id', user.id) \
                .single() \
                .execute()

            profile = profile_response.data
            if not profile:
                return jsonify({"error": "Perfil de usuário não encontrado"}), 403

            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500

        return f(*args, **kwargs)
    return decorated_function

# --- FUNÇÃO AUXILIAR PARA FORMATAR RESPOSTA DE SERVIÇO ---
def format_service_response(service):
    """Converte 'duration_minutes' para 'duration' para consistência com o front-end."""
    if service and 'duration_minutes' in service:
        service['duration'] = service.pop('duration_minutes')
    return service

# --- ROTAS PÚBLICAS ---
@app.route("/")
def index():
    return "API do Fluxo v15.0 - Final"

@app.route("/api/health", methods=['GET'])
def health_check():
    return jsonify({"status": "ok"})

@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json(force=True)
    try:
        supabase_admin.rpc(
            'handle_new_user',
            {
                'user_id': data.get('user_id'),
                'full_name': data.get('full_name'),
                'business_name': data.get('business_name')
            }
        ).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- ROTAS PROTEGIDAS ---
@app.route("/api/dashboard/stats", methods=['GET'])
@auth_required
def get_dashboard_stats(business_id):
    try:
        today_start = datetime.now().strftime('%Y-%m-%d')
        next_day_start = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')

        appointments_today_count = supabase_admin \
            .table('appointments') \
            .select('id', count='exact') \
            .eq('business_id', business_id) \
            .gte('start_time', today_start) \
            .lt('start_time', next_day_start) \
            .execute().count

        stats = {
            "appointmentsToday": appointments_today_count or 0,
            "revenueToday": 0.0,
            "revenueMonth": 0.0,
            "newClientsMonth": 0,
            "appointmentsLast7Days": [],
            "revenueLast4Weeks": [],
            "topServices": [],
            "upcomingAppointments": []
        }
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": "Erro ao buscar estatísticas", "details": str(e)}), 500

@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    response = supabase_admin \
        .table('services') \
        .select('*') \
        .eq('business_id', business_id) \
        .order('name') \
        .execute()

    formatted_data = [format_service_response(s) for s in response.data]
    return jsonify(formatted_data), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json(force=True)

    # Tenta 'duration' ou 'duration_minutes'
    raw_duration = data.get('duration') or data.get('duration_minutes')
    if raw_duration is None:
        return jsonify({"error": "O campo 'duration' ou 'duration_minutes' é obrigatório"}), 400

    try:
        duration = int(raw_duration)
        price    = float(data.get('price'))
        name     = data.get('name')
    except (TypeError, ValueError):
        return jsonify({"error": "Campos 'duration' e 'price' devem ser numéricos"}), 400

    try:
        response = supabase_admin.table('services').insert({
            'name': name,
            'price': price,
            'duration_minutes': duration,
            'business_id': business_id
        }).execute()
        return jsonify(format_service_response(response.data[0])), 201
    except Exception as e:
        return jsonify({"error": "Erro ao criar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['PUT'])
@auth_required
def update_service(service_id, business_id):
    data = request.get_json(force=True)

    raw_duration = data.get('duration') or data.get('duration_minutes')
    if raw_duration is None:
        return jsonify({"error": "O campo 'duration' ou 'duration_minutes' é obrigatório"}), 400

    try:
        duration = int(raw_duration)
        price    = float(data.get('price'))
        name     = data.get('name')
    except (TypeError, ValueError):
        return jsonify({"error": "Campos 'duration' e 'price' devem ser numéricos"}), 400

    try:
        resp = supabase_admin \
            .table('services') \
            .update({
                'name': name,
                'price': price,
                'duration_minutes': duration
            }) \
            .eq('id', service_id) \
            .eq('business_id', business_id) \
            .execute()

        if not resp.data:
            return jsonify({"error": "Serviço não encontrado ou não pertence a este negócio"}), 404

        return jsonify(format_service_response(resp.data[0])), 200
    except Exception as e:
        return jsonify({"error": "Erro ao atualizar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    response = supabase_admin \
        .table('services') \
        .delete() \
        .eq('id', service_id) \
        .eq('business_id', business_id) \
        .execute()

    if not response.data:
        return jsonify({"error": "Serviço não encontrado"}), 404

    return jsonify({"message": "Serviço apagado com sucesso"}), 200

@app.route("/api/professionals", methods=['GET'])
@auth_required
def get_professionals(business_id):
    response = supabase_admin \
        .table('professionals') \
        .select('*, services(*)') \
        .eq('business_id', business_id) \
        .order('name') \
        .execute()
    return jsonify(response.data), 200

@app.route("/api/professionals", methods=['POST'])
@auth_required
def create_professional(business_id):
    data = request.get_json(force=True)
    try:
        response = supabase_admin.table('professionals').insert({
            'name': data.get('name'),
            'business_id': business_id
        }).execute()
        new_professional = response.data[0]
        new_professional['services'] = []
        return jsonify(new_professional), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/professionals/<professional_id>", methods=['DELETE'])
@auth_required
def delete_professional(professional_id, business_id):
    response = supabase_admin \
        .table('professionals') \
        .delete() \
        .eq('id', professional_id) \
        .eq('business_id', business_id) \
        .execute()
    if not response.data:
        return jsonify({"error": "Profissional não encontrado"}), 404
    return jsonify({"message": "Profissional apagado com sucesso"}), 200

@app.route("/api/professionals/<professional_id>/services", methods=['POST'])
@auth_required
def add_service_to_professional(professional_id, business_id):
    data = request.get_json(force=True)
    service_id = data.get('service_id')
    try:
        response = supabase_admin \
            .table('professional_services') \
            .insert({
                'professional_id': professional_id,
                'service_id': service_id
            }).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/professionals/<professional_id>/services/<service_id>", methods=['DELETE'])
@auth_required
def remove_service_from_professional(professional_id, service_id, business_id):
    response = supabase_admin \
        .table('professional_services') \
        .delete() \
        .match({
            'professional_id': professional_id,
            'service_id': service_id
        }).execute()
    if not response.data:
        return jsonify({"error": "Associação não encontrada"}), 404
    return jsonify({"message": "Associação removida com sucesso"}), 200

if __name__ == '__main__':
    app.run()
