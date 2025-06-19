# app.py v15.1 - Agenda improvements: create appointments and available professionals
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# --- Load environment ---
load_dotenv()
app = Flask(__name__)

# --- CORS & Proxy ---
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
CORS(app,
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"],
     methods=["GET","POST","PUT","DELETE","OPTIONS"],
     allow_headers=["Content-Type","Authorization"],
     supports_credentials=True)

# --- Supabase client ---
url = os.getenv("SUPABASE_URL","").strip()
key = os.getenv("SUPABASE_KEY","").strip()
service_key = os.getenv("SUPABASE_SERVICE_KEY","").strip()
if not all([url, key, service_key]):
    raise ValueError("Erro crítico: variáveis de ambiente não encontradas.")
supabase_admin: Client = create_client(url, service_key)

# --- Auth decorator ---
def auth_required(f):
    @wraps(f)
    def decorator(*args, **kwargs):
        auth = request.headers.get('Authorization', '')
        if not auth.startswith('Bearer '):
            return jsonify({'error':'Token não fornecido ou mal formatado'}),401
        token = auth.split()[1]
        try:
            user = supabase_admin.auth.get_user(token).user
            if not user: raise Exception("Invalid token")
            profile = supabase_admin.table('profiles').select('business_id').eq('id', user.id).single().execute().data
            if not profile: return jsonify({'error':'Perfil não encontrado'}),403
            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({'error':'Erro na autenticação','details':str(e)}),401
        return f(*args, **kwargs)
    return decorator

# --- Helper: format service ---
def format_service(s):
    if 'duration_minutes' in s:
        s['duration'] = s['duration_minutes']
    return s

# --- Public ---
@app.route("/api/health")
def health(): return jsonify({'status':'ok'})

# --- Dashboard Stats ---
@app.route("/api/dashboard/stats", methods=['GET'])
@auth_required
def get_dashboard_stats(business_id):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d')
        count_today = supabase_admin.table('appointments') \
            .select('id', count='exact') \
            .eq('business_id', business_id) \
            .gte('start_time', today) \
            .lt('start_time', tomorrow) \
            .execute().count
        stats = {
            'appointmentsToday': count_today or 0,
            'revenueToday': 0.0,
            'revenueMonth': 0.0,
            'newClientsMonth': 0,
            'appointmentsLast7Days': [],
            'revenueLast4Weeks': [],
            'topServices': [],
            'upcomingAppointments': []
        }
        return jsonify(stats),200
    except Exception as e:
        return jsonify({'error':'Erro ao buscar stats','details':str(e)}),500

# --- Services ---
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    resp = supabase_admin.table('services').select('*').eq('business_id', business_id).order('name').execute()
    return jsonify([format_service(s) for s in resp.data]),200

# --- Professionals ---
@app.route("/api/professionals", methods=['GET'])
@auth_required
def get_professionals(business_id):
    resp = supabase_admin.table('professionals').select('*, services(*)').eq('business_id', business_id).order('name').execute()
    return jsonify(resp.data),200

# --- Appointments: list ---
@app.route("/api/appointments", methods=['GET'])
@auth_required
def list_appointments(business_id):
    try:
        resp = supabase_admin.table('appointments').select('*').eq('business_id', business_id).order('start_time', desc=False).execute()
        return jsonify(resp.data),200
    except Exception as e:
        return jsonify({'error':'Erro ao buscar agendamentos','details':str(e)}),500

# --- Available professionals for service/time ---
@app.route("/api/available-professionals", methods=['GET'])
@auth_required
def available_professionals(business_id):
    service_id = request.args.get('service_id')
    start = request.args.get('start_time')  # ISO 8601
    if not service_id or not start:
        return jsonify({'error':'Parâmetros service_id e start_time são obrigatórios'}),400
    # fetch duration
    svc = supabase_admin.table('services').select('duration_minutes').eq('id', service_id).single().execute().data
    if not svc:
        return jsonify({'error':'Serviço não encontrado'}),404
    start_dt = datetime.fromisoformat(start)
    end_dt = start_dt + timedelta(minutes=svc['duration_minutes'])
    # professionals qualified
    quals = supabase_admin.table('professional_services').select('professional_id').eq('service_id', service_id).execute().data
    prof_ids = [q['professional_id'] for q in quals]
    # busy appointments overlapping
    busy = supabase_admin.table('appointments').select('professional_id') \
        .eq('business_id', business_id) \
        .in_('professional_id', prof_ids) \
        .lt('start_time', end_dt.isoformat()) \
        .gt('end_time', start_dt.isoformat()) \
        .execute().data
    busy_ids = {b['professional_id'] for b in busy}
    free_ids = [pid for pid in prof_ids if pid not in busy_ids]
    profs = supabase_admin.table('professionals').select('*').in_('id', free_ids).execute().data
    return jsonify(profs),200

# --- Appointments: create ---
@app.route("/api/appointments", methods=['POST'])
@auth_required
def create_appointment(business_id):
    data = request.get_json(force=True)
    service_id = data.get('service_id')
    professional_id = data.get('professional_id')
    start = data.get('start_time')
    if not all([service_id, professional_id, start]):
        return jsonify({'error':'service_id, professional_id e start_time são obrigatórios'}),400
    # duration
    svc = supabase_admin.table('services').select('duration_minutes').eq('id', service_id).single().execute().data
    if not svc:
        return jsonify({'error':'Serviço não encontrado'}),404
    start_dt = datetime.fromisoformat(start)
    end_dt = start_dt + timedelta(minutes=svc['duration_minutes'])
    try:
        ins = supabase_admin.table('appointments').insert({
            'business_id': business_id,
            'service_id': service_id,
            'professional_id': professional_id,
            'start_time': start_dt.isoformat(),
            'end_time': end_dt.isoformat()
        }).execute()
        return jsonify(ins.data[0]),201
    except Exception as e:
        return jsonify({'error':'Erro ao criar agendamento','details':str(e)}),500

if __name__ == '__main__':
    app.run()
