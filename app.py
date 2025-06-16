import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps # Importamos wraps para criar nosso decorador

load_dotenv()
app = Flask(__name__)

url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

# --- DECORADOR DE AUTENTICAÇÃO ---
# Esta função é a nossa "segurança de porta". Ela será executada antes de cada rota que protegermos.
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Pega o token do cabeçalho da requisição
        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"error": "Token de autenticação não fornecido"}), 401
        
        try:
            # O token vem no formato "Bearer <token>", então separamos o token
            jwt_token = auth_header.split(" ")[1]
            # O Supabase valida o token e nos retorna os dados do usuário
            user_data = supabase.auth.get_user(jwt_token).user
            
            if not user_data:
                return jsonify({"error": "Token inválido ou expirado"}), 401
            
            # Buscamos o business_id do usuário na nossa tabela de perfis
            profile = supabase.table('profiles').select('business_id').eq('id', user_data.id).single().execute().data
            if not profile or not profile.get('business_id'):
                return jsonify({"error": "Perfil ou negócio não encontrado para este usuário"}), 404
            
            # Passamos o business_id para a função da rota
            kwargs['business_id'] = profile['business_id']

        except Exception as e:
            return jsonify({"error": "Erro na autenticação", "details": str(e)}), 401
            
        return f(*args, **kwargs)
    return decorated_function

# --- ROTAS DA API (AGORA PROTEGIDAS) ---

@app.route("/")
def index():
    return "Bem-vindo à API da plataforma Fluxo!"

@app.route("/api/health")
def health_check():
    return jsonify({"status": "ok","message": "API do Fluxo está no ar!"})

# Note o @auth_required antes da definição da rota
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id): # Recebe o business_id do decorador
    try:
        response = supabase.table('services').select('*').eq('business_id', business_id).execute()
        return jsonify(response.data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json()
    try:
        response = supabase.table('services').insert({
            'name': data.get('name'),
            'price': data.get('price'),
            'duration_minutes': data.get('duration_minutes'),
            'business_id': business_id # Usa o business_id do usuário logado
        }).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ... (O mesmo padrão @auth_required deve ser aplicado a TODAS as outras rotas que manipulam dados) ...
# Por simplicidade, atualizei apenas as de serviço, mas o conceito é o mesmo para as outras.

@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        supabase.rpc('handle_new_user', {
            'user_id': data.get('user_id'),
            'full_name': data.get('full_name'),
            'business_name': data.get('business_name')
        }).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)
