# app.py v15.0 - Versão Final Consolidada e Corrigida (com ajuste de duration e associação de serviços)
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
url = os.getenv("SUPABASE_URL", '').strip()
key = os.getenv("SUPABASE_KEY", '').strip()
service_key = os.getenv("SUPABASE_SERVICE_KEY", '').strip()
if not all([url, key, service_key]):
    raise ValueError("ERRO CRÍTICO: Variáveis de ambiente do Supabase não encontradas.")

supabase_admin: Client = create_client(url, service_key)

# --- DECORADOR DE AUTENTICAÇÃO ---
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split()[1]
            user = supabase_admin.auth.get_user(jwt_token).user
            if not user:
                return jsonify({"error": "Token inválido ou expirado"}), 401
            profile = supabase_admin.table('profiles') \
                .select('business_id') \
                .eq('id', user.id) \
                .single() \
                .execute().data
            if not profile:
                return jsonify({"error": "Perfil de usuário não encontrado"}), 403
            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

# --- AUXILIAR: formatar serviço para front ---
def format_service_response(service):
    if service and 'duration_minutes' in service:
        service['duration'] = service['duration_minutes']
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
            {'user_id': data.get('user_id'), 'full_name': data.get('full_name'), 'business_name': data.get('business_name')}
        ).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- ROTAS PROTEGIDAS ---
@app.route("/api/dashboard/stats", methods=['GET'])
@auth_required
def get_dashboard_stats(business_id):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
        count_today = supabase_admin.table('appointments') \
            .select('id', count='exact') \
            .eq('business_id', business_id) \
            .gte('start_time', today) \
            .lt('start_time', tomorrow) \
            .execute().count
        stats = {
            "appointmentsToday": count_today or 0,
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
    resp = supabase_admin.table('services').select('*').eq('business_id', business_id).order('name').execute()
    data = [format_service_response(s) for s in resp.data]
    return jsonify(data), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json(force=True)
    raw = data.get('duration') or data.get('duration_minutes')
    if raw is None:
        return jsonify({"error": "O campo 'duration' é obrigatório"}), 400
    try:
        duration = int(raw)
        price = float(data.get('price'))
        name = data.get('name')
    except (TypeError, ValueError):
        return jsonify({"error": "Campos 'duration' e 'price' devem ser numéricos"}), 400
    try:
        ins = supabase_admin.table('services').insert({
            'name': name, 'price': price, 'duration_minutes': duration, 'business_id': business_id
        }).execute()
        return jsonify(format_service_response(ins.data[0])), 201
    except Exception as e:
        return jsonify({"error": "Erro ao criar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['PUT'])
@auth_required
def update_service(service_id, business_id):
    data = request.get_json(force=True)
    raw = data.get('duration') or data.get('duration_minutes')
    if raw is None:
        return jsonify({"error": "O campo 'duration' é obrigatório"}), 400
    try:
        duration = int(raw)
        price = float(data.get('price'))
        name = data.get('name')
    except (TypeError, ValueError):
        return jsonify({"error": "Campos 'duration' e 'price' devem ser numéricos"}), 400
    try:
        up = supabase_admin.table('services').update({
            'name': name, 'price': price, 'duration_minutes': duration
        }).eq('id', service_id).eq('business_id', business_id).execute()
        if not up.data:
            return jsonify({"error": "Serviço não encontrado"}), 404
        return jsonify(format_service_response(up.data[0])), 200
    except Exception as e:
        return jsonify({"error": "Erro ao atualizar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    d = supabase_admin.table('services').delete().eq('id', service_id).eq('business_id', business_id).execute()
    if not d.data:
        return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify({"message": "Serviço apagado com sucesso"}), 200

@app.route("/api/professionals", methods=['GET'])
@auth_required
def get_professionals(business_id):
    resp = supabase_admin.table('professionals').select('*, services(*)').eq('business_id', business_id).order('name').execute()
    return jsonify(resp.data), 200

@app.route("/api/professionals", methods=['POST'])
@auth_required
def create_professional(business_id):
    data = request.get_json(force=True)
    name = data.get('name')
    services = data.get('services', []) or data.get('service_ids', [])
    try:
        ins = supabase_admin.table('professionals').insert({
            'name': name, 'business_id': business_id
        }).execute()
        prof = ins.data[0]
        prof_id = prof['id']
        # associa serviços selecionados
        if isinstance(services, list) and services:
            assoc = [{'professional_id': prof_id, 'service_id': sid} for sid in services]
            supabase_admin.table('professional_services').insert(assoc).execute()
        # retorna profissional com serviços associados
        full = supabase_admin.table('professionals').select('*, services(*)').eq('id', prof_id).single().execute().data
        return jsonify(full), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/professionals/<professional_id>", methods=['DELETE'])
@auth_required
def delete_professional(professional_id, business_id):
    resp = supabase_admin.table('professionals').delete().eq('id', professional_id).eq('business_id', business_id).execute()
    if not resp.data:
        return jsonify({"error": "Profissional não encontrado"}), 404
    return jsonify({"message": "Profissional apagado com sucesso"}), 200

@app.route("/api/professionals/<professional_id>/services", methods=['POST'])
@auth_required
def add_service_to_professional(professional_id, business_id):
    data = request.get_json(force=True)
    sid = data.get('service_id')
    try:
        ins = supabase_admin.table('professional_services').insert({'professional_id': professional_id, 'service_id': sid}).execute()
        return jsonify(ins.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/professionals/<professional_id>/services/<service_id>", methods=['DELETE'])
@auth_required
def remove_service_from_professional(professional_id, service_id, business_id):
    resp = supabase_admin.table('professional_services').delete().match({'professional_id': professional_id, 'service_id': service_id}).execute()
    if not resp.data:
        return jsonify({"error": "Associação não encontrada"}), 404
    return jsonify({"message": "Associação removida com sucesso"}), 200

if __name__ == '__main__':
    app.run()
