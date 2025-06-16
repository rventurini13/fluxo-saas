# app.py v.MVP 1.2 - Com endpoint de signup
import os
from flask import Flask, jsonify, request
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta, time

load_dotenv()
app = Flask(__name__)

url: str = os.environ.get("SUPABASE_URL").strip()
key: str = os.environ.get("SUPABASE_KEY").strip()
supabase: Client = create_client(url, key)

business_id_logado = "c3335c7d-a513-4718-a562-e494b2d5a58d"

# ... (todas as outras rotas que já fizemos) ...
@app.route("/")
def index():
    return "Bem-vindo à API da plataforma Fluxo!"
@app.route("/api/health")
def health_check():
    return jsonify({"status": "ok","message": "API do Fluxo está no ar!"})
@app.route("/api/services", methods=['POST'])
def create_service():
    data = request.get_json()
    try:
        response = supabase.table('services').insert({'name': data.get('name'),'price': data.get('price'),'duration_minutes': data.get('duration_minutes'),'business_id': business_id_logado}).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/services", methods=['GET'])
def get_services():
    try:
        response = supabase.table('services').select('*').eq('business_id', business_id_logado).execute()
        return jsonify(response.data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/services/<service_id>", methods=['DELETE'])
def delete_service(service_id):
    try:
        response = supabase.table('services').delete().eq('id', service_id).execute()
        if len(response.data) == 0:
            return jsonify({"error": "Serviço não encontrado"}), 404
        return jsonify({"message": f"Serviço {service_id} apagado com sucesso"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/professionals", methods=['POST'])
def create_professional():
    data = request.get_json()
    try:
        response = supabase.table('professionals').insert({'name': data.get('name'),'business_id': business_id_logado}).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/professionals", methods=['GET'])
def get_professionals():
    try:
        response = supabase.table('professionals').select('*, services(*)').eq('business_id', business_id_logado).execute()
        return jsonify(response.data), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/professionals/<professional_id>", methods=['DELETE'])
def delete_professional(professional_id):
    try:
        response = supabase.table('professionals').delete().eq('id', professional_id).execute()
        if len(response.data) == 0:
            return jsonify({"error": "Profissional não encontrado"}), 404
        return jsonify({"message": f"Profissional {professional_id} apagado com sucesso"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/professionals/<professional_id>/services", methods=['POST'])
def add_service_to_professional(professional_id):
    data = request.get_json()
    service_id = data.get('service_id')
    if not service_id:
        return jsonify({"error": "O ID do serviço (service_id) é obrigatório"}), 400
    try:
        response = supabase.table('professional_services').insert({'professional_id': professional_id,'service_id': service_id}).execute()
        return jsonify(response.data[0]), 201
    except Exception as e:
        if 'duplicate key value violates unique constraint' in str(e):
            return jsonify({"error": "Este serviço já está associado a este profissional"}), 409
        return jsonify({"error": str(e)}), 400
@app.route("/api/professionals/<professional_id>/services/<service_id>", methods=['DELETE'])
def remove_service_from_professional(professional_id, service_id):
    try:
        response = supabase.table('professional_services').delete().match({'professional_id': professional_id,'service_id': service_id}).execute()
        if len(response.data) == 0:
            return jsonify({"error": "Associação não encontrada"}), 404
        return jsonify({"message": "Associação removida com sucesso"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400
@app.route("/api/schedule/availability", methods=['POST'])
def get_availability():
    data = request.get_json()
    professional_id = data.get('professional_id')
    service_id = data.get('service_id')
    date_str = data.get('date')
    try:
        service_response = supabase.table('services').select('duration_minutes').eq('id', service_id).single().execute()
        service = service_response.data
        business_response = supabase.table('businesses').select('opening_time, closing_time').eq('id', business_id_logado).single().execute()
        business = business_response.data
        next_day_str = (datetime.strptime(date_str, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')
        appointments_response = supabase.table('appointments').select('start_time, end_time').eq('professional_id', professional_id).gte('start_time', date_str).lt('start_time', next_day_str).execute()
        appointments = appointments_response.data
        duration = timedelta(minutes=service['duration_minutes'])
        opening_time = datetime.strptime(business['opening_time'], '%H:%M:%S').time()
        closing_time = datetime.strptime(business['closing_time'], '%H:%M:%S').time()
        booked_slots = [(datetime.fromisoformat(apt['start_time']), datetime.fromisoformat(apt['end_time'])) for apt in appointments]
        available_slots = []
        potential_slot_start = datetime.combine(datetime.strptime(date_str, '%Y-%m-%d'), opening_time)
        while (potential_slot_start + duration).time() <= closing_time:
            potential_slot_end = potential_slot_start + duration
            is_available = True
            for booked_start, booked_end in booked_slots:
                if max(potential_slot_start, booked_start) < min(potential_slot_end, booked_end):
                    is_available = False
                    break
            if is_available:
                available_slots.append(potential_slot_start.strftime('%H:%M'))
            potential_slot_start += timedelta(minutes=30)
        return jsonify({"available_slots": available_slots}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# --- NOVO ENDPOINT PARA FINALIZAR O CADASTRO ---
@app.route("/api/on-signup", methods=['POST'])
def on_supabase_signup():
    data = request.get_json()
    try:
        # Chama a função 'handle_new_user' que criamos no Supabase
        # passando os argumentos que ela espera
        supabase.rpc('handle_new_user', {
            'user_id': data.get('user_id'),
            'full_name': data.get('full_name'),
            'business_name': data.get('business_name')
        }).execute()
        
        return jsonify({"message": "Usuário e negócio criados com sucesso!"}), 200 # Mudei para 200 OK
        
    except Exception as e:
        # Se ocorrer um erro, o Supabase desfaz a criação do usuário automaticamente
        # ou podemos adicionar uma lógica para apagar o usuário aqui se necessário
        return jsonify({"error": str(e)}), 400

if __name__ == '__main__':
    app.run(debug=True)
