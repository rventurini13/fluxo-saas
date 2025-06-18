# app.py v9.2 - Com diagnóstico de variáveis de ambiente
import os
import json # Usaremos para imprimir as variáveis de forma legível
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

load_dotenv()

# --- BLOCO DE DIAGNÓSTICO DE AMBIENTE ---
# Este código será executado assim que a aplicação iniciar na Railway
print("--- INICIANDO DIAGNÓSTICO DE VARIÁVEIS DE AMBIENTE ---")
# Imprime um dicionário de todas as variáveis de ambiente para depuração
print(json.dumps(dict(os.environ), indent=2))
print("--- FIM DO DIAGNÓSTICO ---")
# --- FIM DO BLOCO DE DIAGNÓSTICO ---


app = Flask(__name__)

# Configurações de Produção
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False
CORS(app, origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"], methods=["GET", "POST", "DELETE", "OPTIONS"], allow_headers=["Content-Type", "Authorization"], supports_credentials=True)

# Inicialização Segura das Variáveis
url_from_env = os.environ.get("SUPABASE_URL")
key_from_env = os.environ.get("SUPABASE_KEY")
service_key_from_env = os.environ.get("SUPABASE_SERVICE_KEY")

if not all([url_from_env, key_from_env, service_key_from_env]):
    raise ValueError("ERRO CRÍTICO: Uma ou mais variáveis de ambiente do Supabase não foram encontradas.")

url: str = url_from_env.strip()
key: str = key_from_env.strip()
service_key: str = service_key_from_env.strip()

# Clientes Supabase
supabase: Client = create_client(url, key)
supabase_admin: Client = create_client(url, service_key)

# (O resto do seu código, com o decorador e as rotas, continua aqui)
# ...

if __name__ == '__main__':
    app.run()