# app.py v3.5 - Correção final do decorador de autenticação
import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time
from functools import wraps

load_dotenv()
app = Flask(__name__)
CORS(app) # Mantendo o CORS aberto para garantir que não é o problema

url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

# --- DECORADOR DE AUTENTICAÇÃO (VERSÃO CORRIGIDA E MAIS ROBUSTA) ---
def auth_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith("Bearer "):
            return jsonify({"error": "Token de autenticação não fornecido ou mal formatado"}), 401
        try:
            jwt_token = auth_header.split(" ")[1]
            user_session = supabase.auth.get_user(jwt_token)
            user = user_session.user
            if not user: return jsonify({"error": "Token inválido ou expirado"}), 401
            
            # --- AQUI ESTÁ A MUDANÇA PRINCIPAL ---
            # Em vez de usar .single(), que pode ser muito restritivo,
            # vamos buscar a lista de perfis e verificar o resultado.
            profile_response = supabase.table('profiles').select('business_id').eq('id', user.id).execute()
            profiles = profile_response.data
            
            # Verificamos explicitamente se encontrámos exatamente um perfil
            if not profiles or len(profiles) != 1:
                error_message = f"Perfil não encontrado ou duplicado para o usuário {user.id}. Perfis encontrados: {len(profiles)}"
                return jsonify({"error": "Falha de consistência de dados do perfil", "details": error_message}), 403
            
            # Se tudo estiver correto, pegamos o business_id do primeiro (e único) perfil
            kwargs['business_id'] = profiles[0]['business_id']
            # --- FIM DA MUDANÇA ---

        except Exception as e:
            return jsonify({"error": "Erro interno na autenticação", "details": str(e)}), 500
        return f(*args, **kwargs)
    return decorated_function

# --- (O RESTO DO CÓDIGO CONTINUA EXATAMENTE IGUAL) ---
@app.route("/")
def index(): return "Bem-vindo à API da plataforma Fluxo!"
@app.route("/api/health")
def health_check(): return jsonify({"status": "ok"})
@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        supabase.rpc('handle_new_user', {'user_id': data.get('user_id'),'full_name': data.get('full_name'),'business_name': data.get('business_name')}).execute()
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200
    except Exception as e: return jsonify({"error": str(e)}), 400
# ... (todas as outras rotas) ...
@app.route("/api/services", methods=['GET'])
@auth_required
def get_services(business_id):
    response = supabase.table('services').select('*').eq('business_id', business_id).order('name').execute()
    return jsonify(response.data), 200
@app.route("/api/services", methods=['POST'])
@auth_required
def create_service(business_id):
    data = request.get_json()
    response = supabase.table('services').insert({'name': data.get('name'),'price': data.get('price'),'duration_minutes': data.get('duration_minutes'),'business_id': business_id}).execute()
    return jsonify(response.data[0]), 201
# (etc...)

if __name__ == '__main__':
    app.run(debug=True)