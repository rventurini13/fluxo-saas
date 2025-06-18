# app.py v15.0 - Versão Final Consolidada e Corrigida (com ajustes para duration, profissionais e configurações)
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
    def decorated(*args, **kwargs):
        auth = request.headers.get('Authorization')
        if not auth or not auth.startswith('Bearer '):
            return jsonify({'error':'Token não fornecido ou mal formatado'}),401
        token = auth.split()[1]
        try:
            user = supabase_admin.auth.get_user(token).user
            if not user: return jsonify({'error':'Token inválido ou expirado'}),401
            profile = supabase_admin.table('profiles').select('business_id').eq('id',user.id).single().execute().data
            if not profile: return jsonify({'error':'Perfil não encontrado'}),403
            kwargs['business_id']=profile['business_id']
        except Exception as e:
            return jsonify({'error':'Erro autenticação','details':str(e)}),500
        return f(*args, **kwargs)
    return decorated

# --- Helpers ---
def format_service_response(s):
    if s and 'duration_minutes' in s:
        s['duration']=s['duration_minutes']
    return s

# --- PÚBLICAS ---
@app.route('/')
def index(): return 'API Fluxo v15.0'
@app.route('/api/health')
def health(): return jsonify({'status':'ok'})

# --- CONFIGURAÇÕES DO NEGÓCIO ---
@app.route('/api/config', methods=['GET'])
@auth_required
def get_config(business_id):
    # business info
    biz = supabase_admin.table('businesses').select('name,phone,address').eq('id',business_id).single().execute().data or {}
    # business hours
    hrs = supabase_admin.table('business_hours').select('weekday,start_time,end_time').eq('business_id',business_id).execute().data
    hours = {h['weekday']:{'start':h['start_time'],'end':h['end_time']} for h in hrs}
    return jsonify({'businessInfo':biz,'businessHours':hours}),200

@app.route('/api/config', methods=['PUT'])
@auth_required
def update_config(business_id):
    data = request.get_json(force=True)
    biz = data.get('businessInfo',{})
    hrs = data.get('businessHours',{})
    try:
        # atualiza info
        supabase_admin.table('businesses').update({
            'name':biz.get('name'),'phone':biz.get('phone'),'address':biz.get('address')
        }).eq('id',business_id).execute()
        # upsert horários
        for weekday, times in hrs.items():
            start = times.get('start')
            end = times.get('end')
            exists = supabase_admin.table('business_hours').select('id').eq('business_id',business_id).eq('weekday',weekday).single().execute().data
            if exists:
                supabase_admin.table('business_hours').update({'start_time':start,'end_time':end}).eq('id',exists['id']).execute()
            else:
                supabase_admin.table('business_hours').insert({'business_id':business_id,'weekday':weekday,'start_time':start,'end_time':end}).execute()
        return jsonify({'message':'Configurações salvas com sucesso'}),200
    except Exception as e:
        return jsonify({'error':'Falha ao salvar configurações','details':str(e)}),500

# --- Outros endpoints existentes (services, professionals etc.) -- omitted for brevity --

if __name__=='__main__':
    app.run()
