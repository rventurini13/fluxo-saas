# app.py v28.1

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

# --- VARIÁVEIS DE AMBIENTE SUPABASE ---
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

# --- AUXILIAR FORMATAÇÃO SERVIÇOS ---
def format_service_response(service):
    """Converte 'duration_minutes' para 'duration'."""
    if service and 'duration_minutes' in service:
        service['duration'] = service.pop('duration_minutes')
    return service

# --- ROTAS PÚBLICAS ---
@app.route("/")
def index():
    return "API do Fluxo v16.0"

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

# --- DASHBOARD ---
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
            .execute().count or 0

        stats = {
            "appointmentsToday": appointments_today_count,
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

# --- SERVIÇOS ---
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    resp = supabase_admin \
        .table('services') \
        .select('*') \
        .eq('business_id', business_id) \
        .order('name') \
        .execute()
    return jsonify([format_service_response(s) for s in resp.data]), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json(force=True)
    raw_duration = data.get('duration') or data.get('duration_minutes')
    if raw_duration is None:
        return jsonify({"error": "O campo 'duration' ou 'duration_minutes' é obrigatório"}), 400
    try:
        duration = int(raw_duration)
        price = float(data.get('price'))
        name = data.get('name')
    except:
        return jsonify({"error": "Campos 'duration' e 'price' devem ser numéricos"}), 400
    try:
        resp = supabase_admin.table('services').insert({
            'name': name,
            'price': price,
            'duration_minutes': duration,
            'business_id': business_id
        }).execute()
        return jsonify(format_service_response(resp.data[0])), 201
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
        price = float(data.get('price'))
        name = data.get('name')
    except:
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
            return jsonify({"error": "Serviço não encontrado"}), 404
        return jsonify(format_service_response(resp.data[0])), 200
    except Exception as e:
        return jsonify({"error": "Erro ao atualizar serviço", "details": str(e)}), 500

@app.route("/api/services/<service_id>", methods=['DELETE'])
@auth_required
def delete_service(service_id, business_id):
    resp = supabase_admin \
        .table('services') \
        .delete() \
        .eq('id', service_id) \
        .eq('business_id', business_id) \
        .execute()
    if not resp.data:
        return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify({"message": "Serviço apagado com sucesso"}), 200

# --- PROFISSIONAIS ---
@app.route("/api/professionals", methods=['GET'])
@auth_required
def get_professionals(business_id):
    resp = supabase_admin \
        .table('professionals') \
        .select('*, services(*)') \
        .eq('business_id', business_id) \
        .order('name') \
        .execute()
    return jsonify(resp.data), 200

@app.route("/api/professionals", methods=['POST'])
@auth_required
def create_professional(business_id):
    data = request.get_json(force=True)
    try:
        resp = supabase_admin.table('professionals').insert({
            'name': data.get('name'),
            'business_id': business_id
        }).execute()
        newp = resp.data[0]
        newp['services'] = []
        return jsonify(newp), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/api/professionals/<pid>", methods=['DELETE'])
@auth_required
def delete_professional(pid, business_id):
    resp = supabase_admin \
        .table('professionals') \
        .delete() \
        .eq('id', pid) \
        .eq('business_id', business_id) \
        .execute()
    if not resp.data:
        return jsonify({"error": "Profissional não encontrado"}), 404
    return jsonify({"message": "Profissional apagado"}), 200

@app.route("/api/professionals/<pid>/services", methods=['POST'])
@auth_required
def add_service_to_professional(pid, business_id):
    data = request.get_json(force=True)
    sid = data.get('service_id')
    try:
        resp = supabase_admin \
            .table('professional_services') \
            .insert({'professional_id': pid, 'service_id': sid}) \
            .execute()
        return jsonify(resp.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/professionals/<pid>/services/<sid>", methods=['DELETE'])
@auth_required
def remove_service_from_professional(pid, sid, business_id):
    resp = supabase_admin \
        .table('professional_services') \
        .delete() \
        .match({'professional_id': pid, 'service_id': sid}) \
        .execute()
    if not resp.data:
        return jsonify({"error": "Associação não encontrada"}), 404
    return jsonify({"message": "Associação removida"}), 200

# --- AGENDAMENTOS (CALENDÁRIO) ---
@app.route("/api/appointments", methods=['GET'])
@auth_required
def get_appointments(business_id):
    try:
        resp = supabase_admin \
            .table('appointments') \
            .select('*, service:services(name), professional:professionals(name)') \
            .eq('business_id', business_id) \
            .execute()
        return jsonify(resp.data), 200
    except Exception as e:
        return jsonify({"error": "Erro ao buscar agendamentos", "details": str(e)}), 500

@app.route("/api/appointments", methods=['POST'])
@auth_required
def create_appointment(business_id):
    data = request.get_json(force=True)
    required = ['professional_id', 'service_id', 'customer_name', 'customer_phone', 'start_time']
    if not all(f in data for f in required):
        return jsonify({"error": "Campos obrigatórios em falta"}), 400

    try:
        # pega duração do serviço
        svc = supabase_admin \
            .table('services') \
            .select('duration_minutes') \
            .eq('id', data['service_id']) \
            .single() \
            .execute().data
        if not svc:
            return jsonify({"error": "Serviço não encontrado"}), 404

        start = datetime.fromisoformat(data['start_time'])
        end = start + timedelta(minutes=svc['duration_minutes'])

        resp = supabase_admin \
            .table('appointments') \
            .insert({
                'professional_id': data['professional_id'],
                'service_id': data['service_id'],
                'business_id': business_id,
                'customer_name': data['customer_name'],
                'customer_phone': data['customer_phone'],
                'start_time': start.isoformat(),
                'end_time': end.isoformat()
            }).execute()
        return jsonify(resp.data[0]), 201

    except Exception as e:
        return jsonify({"error": "Erro ao criar agendamento", "details": str(e)}), 500

@app.route("/api/available-professionals", methods=['GET'])
@auth_required
def available_professionals(business_id):
    service_id = request.args.get('service_id')
    start_time_str = request.args.get('start_time')
    if not service_id or not start_time_str:
        return jsonify({"error": "Parâmetros service_id e start_time são obrigatórios"}), 400

    try:
        # duração do serviço
        svc = supabase_admin \
            .table('services') \
            .select('duration_minutes') \
            .eq('id', service_id) \
            .single() \
            .execute().data
        duration = svc['duration_minutes']
        start = datetime.fromisoformat(start_time_str)
        end = start + timedelta(minutes=duration)

        # quem faz esse serviço?
        link = supabase_admin \
            .table('professional_services') \
            .select('professional_id') \
            .eq('service_id', service_id) \
            .execute().data
        prof_ids = [r['professional_id'] for r in link]

        # filtra conflitos: A.start < end AND A.end > start
        busy = supabase_admin \
            .table('appointments') \
            .select('professional_id') \
            .eq('business_id', business_id) \
            .lt('start_time', end.isoformat()) \
            .gt('end_time', start.isoformat()) \
            .execute().data
        busy_ids = {b['professional_id'] for b in busy}

        # busca dados dos profissionais livres
        pros = supabase_admin \
            .table('professionals') \
            .select('id, name') \
            .eq('business_id', business_id) \
            .in_('id', prof_ids) \
            .execute().data

        free = [p for p in pros if p['id'] not in busy_ids]
        return jsonify(free), 200

    except Exception as e:
        return jsonify({"error": "Erro ao buscar profissionais disponíveis", "details": str(e)}), 500

if __name__ == '__main__':
    app.run()
