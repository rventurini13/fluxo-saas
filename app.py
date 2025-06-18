# app.py v9.0 - Arquitetura Final com Dois Clientes Supabase
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()
app = Flask(__name__)

app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False
CORS(app, origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization"], supports_credentials=True)

# --- INICIALIZAÇÃO DOS DOIS CLIENTES ---
url: str = os.environ.get("SUPABASE_URL").strip()
# A chave pública para operações no contexto de um usuário
key: str = os.environ.get("SUPABASE_KEY").strip() 
# A chave de serviço para operações administrativas
service_key: str = os.environ.get("SUPABASE_SERVICE_KEY").strip() # Crie esta variável na Railway!

# Cliente principal, usado para requisições de usuários
supabase: Client = create_client(url, key)
# Cliente administrativo, que bypassa o RLS
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
        
        # A validação do token é implícita. Se for inválido, a próxima chamada falhará.
        return f(*args, **kwargs)
    return decorated_function


# --- ROTA DE SIGNUP USA O CLIENTE ADMIN ---
@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        # Usamos o cliente administrativo para chamar a função de criação
        supabase_admin.rpc('handle_new_user', {'user_id': data.get('user_id'),'full_name': data.get('full_name'),'business_name': data.get('business_name')}).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 400

# --- ROTAS PROTEGIDAS USAM O CLIENTE DE USUÁRIO NORMAL ---
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services():
    # O RLS do Supabase fará o filtro automaticamente baseado no token injetado
    response = supabase.table('services').select('*').order('name').execute()
    return jsonify(response.data), 200

# (E assim por diante para todas as outras rotas... a lógica delas fica muito mais simples)
# ...

if __name__ == '__main__':
    app.run()