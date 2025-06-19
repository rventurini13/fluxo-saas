# app.py v28.0
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# --- Carrega variáveis de ambiente ---
load_dotenv()
app = Flask(__name__)

# --- Configuração de CORS e Proxy ---
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
CORS(app,
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"],
     methods=["GET","POST","PUT","DELETE","OPTIONS"],
     allow_headers=["Content-Type","Authorization"],
     supports_credentials=True)

# --- Inicialização do Supabase ---
SUPABASE_URL = os.getenv("SUPABASE_URL","").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY","").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY","").strip()
if not all([SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY]):
    raise ValueError("ERRO CRÍTICO: Variáveis de ambiente do Supabase não encontradas.")
supabase_admin: Client = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# --- Decorador de autenticação ---
def auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        auth_header = request.headers.get('Authorization','')
        if not auth_header.startswith('Bearer '):
            return jsonify({'error':'Token não fornecido ou mal formatado'}),401
        token = auth_header.split()[1]
        try:
            user = supabase_admin.auth.get_user(token).user
            if not user:
                return jsonify({'error':'Token inválido ou expirado'}),401
            profile = supabase_admin.table('profiles') \
                .select('business_id') \
                .eq('id',user.id) \
                .single() \
                .execute().data
            if not profile:
                return jsonify({'error':'Perfil de usuário não encontrado'}),403
            kwargs['business_id'] = profile['business_id']
        except Exception as e:
            return jsonify({'error':'Erro interno na autenticação','details':str(e)}),500
        return f(*args,**kwargs)
    return wrapper

# --- Auxiliar para formatar serviços ---
def format_service_response(s):
    if s and 'duration_minutes' in s:
        s['duration'] = s.pop('duration_minutes')
    return s

# --- Rotas públicas ---
@app.route("/api/health", methods=['GET'])
def health_check():
    return jsonify({'status':'ok'}),200

@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json(force=True)
    try:
        supabase_admin.rpc('handle_new_user',{
            'user_id': data.get('user_id'),
            'full_name': data.get('full_name'),
            'business_name': data.get('business_name')
        }).execute()
        return jsonify({'message':'Usuário e negócio criados com sucesso!'}),200
    except Exception as e:
        return jsonify({'error':str(e)}),400

# --- Stats Dashboard ---
@app.route("/api/dashboard/stats", methods=['GET'])
@auth_required
def get_dashboard_stats(business_id):
    try:
        today = datetime.now().strftime('%Y-%m-%d')
        tomorrow = (datetime.now()+timedelta(days=1)).strftime('%Y-%m-%d')
        count_today = supabase_admin.table('appointments') \
            .select('id',count='exact') \
            .eq('business_id',business_id) \
            .gte('start_time',today) \
            .lt('start_time',tomorrow) \
            .execute().count
        stats = {
            'appointmentsToday': count_today or 0,
            'revenueToday':0.0,
            'revenueMonth':0.0,
            'newClientsMonth':0,
            'appointmentsLast7Days':[],
            'revenueLast4Weeks':[],
            'topServices':[],
            'upcomingAppointments':[]
        }
        return jsonify(stats),200
    except Exception as e:
        return jsonify({'error':'Erro ao buscar estatísticas','details':str(e)}),500

# --- Agendamentos Disponíveis ---
@app.route("/api/available-professionals", methods=['GET'])
@auth_required
def available_professionals(business_id):
    service_id = request.args.get('service_id')
    start_time = request.args.get('start_time')
    if not service_id or not start_time:
        return jsonify({'error':'Parâmetros service_id e start_time são obrigatórios'}),400
    try:
        # buscar duração do serviço
        svc = supabase_admin.table('services') \
            .select('duration_minutes') \
            .eq('id',service_id) \
            .single() \
            .execute().data
        if not svc:
            return jsonify({'error':'Serviço não encontrado'}),404
        duration = timedelta(minutes=svc['duration_minutes'])
        st = datetime.fromisoformat(start_time)
        en = st + duration
        # profissionais que atendem ao serviço
        profs = supabase_admin.table('professional_services') \
            .select('professional_id, professionals(name)') \
            .eq('service_id',service_id) \
            .execute().data
        pids = [p['professional_id'] for p in profs]
        # agendamentos conflitantes
        busy = supabase_admin.table('appointments') \
            .select('professional_id') \
            .eq('business_id',business_id) \
            .in_('professional_id',pids) \
            .gte('start_time',st.isoformat()) \
            .lt('end_time',en.isoformat()) \
            .execute().data
        busy_ids = {b['professional_id'] for b in busy}
        # filtra disponíveis
        available = [
            {'id':p['professional_id'], 'name':p['professionals']['name']}
            for p in profs if p['professional_id'] not in busy_ids
        ]
        return jsonify(available),200
    except Exception as e:
        return jsonify({'error':'Erro ao buscar profissionais disponíveis','details':str(e)}),500

# --- Rotas de Agendamentos ---
@app.route("/api/appointments", methods=['GET'])
@auth_required
def list_appointments(business_id):
    try:
        resp = supabase_admin.table('appointments') \
            .select(
                '*, '
                'service:services(name) as service, '
                'professional:professionals(name) as professional'
            ) \
            .eq('business_id',business_id) \
            .order('start_time',desc=False) \
            .execute()
        return jsonify(resp.data),200
    except Exception as e:
        return jsonify({'error':'Erro ao buscar agendamentos','details':str(e)}),500

@app.route("/api/appointments", methods=['POST'])
@auth_required
def create_appointment(business_id):
    data = request.get_json(force=True)
    required = ['professional_id','service_id','client_name','client_phone','start_time']
    if not all(f in data for f in required):
        return jsonify({'error':'Campos obrigatórios em falta'}),400
    try:
        svc = supabase_admin.table('services') \
            .select('duration_minutes') \
            .eq('id',data['service_id']) \
            .single() \
            .execute().data
        if not svc:
            return jsonify({'error':'Serviço não encontrado'}),404
        st = datetime.fromisoformat(data['start_time'])
        en = st + timedelta(minutes=svc['duration_minutes'])
        ins = supabase_admin.table('appointments').insert({
            'business_id':business_id,
            'service_id':data['service_id'],
            'professional_id':data['professional_id'],
            'client_name':data['client_name'],
            'client_phone':data['client_phone'],
            'start_time':st.isoformat(),
            'end_time':en.isoformat()
        }).execute()
        return jsonify(ins.data[0]),201
    except Exception as e:
        return jsonify({'error':'Erro ao criar agendamento','details':str(e)}),500

# --- Serviços ---
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    resp = supabase_admin.table('services').select('*').eq('business_id',business_id).order('name').execute()
    return jsonify([format_service_response(s) for s in resp.data]),200
# ... restante das rotas de services e professionals permanece igual ao v15.2 ...

if __name__ == '__main__':
    app.run()
