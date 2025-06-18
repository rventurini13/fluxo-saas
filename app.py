# app.py v10.1 - Arquitetura Final com "Dois Clientes" e RLS
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
app = Flask(__name__)

# Configurações de Produção
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False
CORS(app, origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization"], supports_credentials=True)

# --- INICIALIZAÇÃO DOS DOIS CLIENTES ---
url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
service_key: str = os.environ.get("SUPABASE_SERVICE_KEY").strip()

# Cliente principal, usado para requisições no contexto de um usuário
supabase: Client = create_client(url, key)
# Cliente administrativo, que bypassa o RLS para tarefas específicas
supabase_admin: Client = create_client(url, service_key)

# --- DECORADOR DE AUTENTICAÇÃO ATUALIZADO ---
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "): return jsonify({"error": "Token não fornecido"}), 401
        
        # Injeta o token do usuário no cliente Supabase para esta requisição
        jwt_token = auth_header.split(" ")[1]
        supabase.postgrest.auth(jwt_token)
        
        # A validação é implícita. Se o token for inválido, a próxima chamada falhará.
        # As regras RLS no Supabase farão o filtro de dados.
        return f(*args, **kwargs)
    return decorated_function

# --- ROTAS PÚBLICAS ---
@app.route("/")
def index(): return "API do Fluxo v10.1 - Final"
@app.route("/api/health", methods=['GET'])
def health_check(): return jsonify({"status": "ok"})

@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        # Usamos o cliente administrativo para chamar a função que cria o business e o profile
        supabase_admin.rpc('handle_new_user', {'user_id': data.get('user_id'),'full_name': data.get('full_name'),'business_name': data.get('business_name')}).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 400

# --- ROTAS PROTEGIDAS ---
# Note que as funções já não recebem 'business_id', pois o RLS filtra isso na base de dados
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services():
    response = supabase.table('services').select('*').order('name').execute()
    return jsonify(response.data), 200

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service():
    # Precisamos de obter o business_id para o INSERT.
    # A forma mais segura é chamar uma função no Supabase que nos retorne o business_id do usuário atual.
    user_id = supabase.auth.get_user().user.id
    profile = supabase.table('profiles').select('business_id').eq('id', user_id).single().execute().data
    if not profile: return jsonify({"error": "Perfil não encontrado"}), 403
    
    data = request.get_json()
    response = supabase.table('services').insert({
        'name': data.get('name'),
        'price': float(data.get('price')),
        'duration_minutes': int(data.get('duration')),
        'business_id': profile['business_id']
    }).execute()
    return jsonify(response.data[0]), 201

# (E assim por diante para as outras rotas...)

if __name__ == '__main__':
    app.run()