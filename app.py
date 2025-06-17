# app.py v5.1 - Com log de diagnóstico de rotas
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix
import logging # Importamos a biblioteca de logging

load_dotenv()
app = Flask(__name__)

# --- CONFIGURAÇÃO DE PRODUÇÃO ---
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False
CORS(app, 
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app", "http://localhost:3000"], # Adicionei localhost para testes futuros
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True
)

url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

# (O decorador de autenticação continua aqui, sem alterações)
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # ... (código do decorador)
        return f(*args, **kwargs)
    return decorated_function

# --- TODAS AS NOSSAS ROTAS ---
@app.route("/")
def index(): return "API do Fluxo v5.1"

@app.route("/api/health")
def health_check(): return jsonify({"status": "ok"})

@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    # ... (código da função)
    return jsonify({"message": "OK"}), 200

@app.route("/api/services", methods=['GET', 'POST'])
@auth_required
def handle_services(business_id):
    if request.method == 'GET':
        response = supabase.table('services').select('*').eq('business_id', business_id).order('name').execute()
        return jsonify(response.data), 200
    elif request.method == 'POST':
        data = request.get_json()
        response = supabase.table('services').insert({'name': data.get('name'),'price': data.get('price'),'duration_minutes': data.get('duration_minutes'),'business_id': business_id}).execute()
        return jsonify(response.data[0]), 201

# (As outras rotas continuam aqui... simplifiquei a visualização)

# --- BLOCO DE DEBUG PARA LISTAR ROTAS ---
# Este código será executado assim que a aplicação iniciar na Railway
with app.app_context():
    regras = []
    for r in app.url_map.iter_rules():
        # Adicionamos uma verificação para não listar rotas estáticas internas do Flask
        if "static" not in r.endpoint:
            regras.append(f"{r.rule} -> MÉTODOS: {','.join(r.methods)}")
    
    # Usamos o logger do gunicorn para garantir que a mensagem apareça
    gunicorn_logger = logging.getLogger('gunicorn.error')
    gunicorn_logger.warning("--- MAPA DE ROTAS REGISTRADAS ---")
    for regra in sorted(regras): # Ordenamos para facilitar a leitura
        gunicorn_logger.warning(regra)
    gunicorn_logger.warning("---------------------------------")
# --- FIM DO BLOCO DE DEBUG ---


if __name__ == '__main__':
    app.run()