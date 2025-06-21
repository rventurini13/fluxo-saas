import os
import requests
import json
import re
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# Carrega variáveis de ambiente
load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()

# Evolution API URLs (configurar no .env)
EVOLUTION_BASE_URL = os.getenv("EVOLUTION_BASE_URL", "").strip()
EVOLUTION_API_KEY = os.getenv("EVOLUTION_API_KEY", "").strip()

if not all([SUPABASE_URL, SUPABASE_KEY, SUPABASE_SERVICE_KEY]):
    raise RuntimeError("Variáveis de ambiente do Supabase não configuradas.")

# Inicializa Flask + Supabase
app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_prefix=1)
app.url_map.strict_slashes = False

CORS(app,
     origins=["https://fluxo-plataforma-de-agendamento-automatizado.lovable.app"],
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     allow_headers=["Content-Type", "Authorization"],
     supports_credentials=True)

supabase = create_client(SUPABASE_URL, SUPABASE_SERVICE_KEY)

# ------------------
# Decorador de Auth
# ------------------

def auth_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return jsonify({"error": "Token ausente ou mal formatado"}), 401

        token = auth.split(" ")[1]

        try:
            user_resp = supabase.auth.get_user(token)
            user = user_resp.user

            if not user:
                return jsonify({"error": "Token inválido"}), 401

            prof = supabase.table("profiles") \
                .select("business_id") \
                .eq("id", user.id) \
                .single() \
                .execute().data

            if not prof:
                return jsonify({"error": "Perfil não encontrado"}), 403

            kwargs["business_id"] = prof["business_id"]

        except Exception as e:
            return jsonify({"error": "Falha na autenticação", "details": str(e)}), 500

        return fn(*args, **kwargs)

    return wrapper

# ------------------
# Helpers
# ------------------

def format_service(s):
    if "duration_minutes" in s:
        s["duration"] = s.pop("duration_minutes")
    return s

# ------------------
# Validação de Horário de Funcionamento
# ------------------

def validate_business_hours(business_id, start_time_str):
    """
    Valida se o horário está dentro do funcionamento do negócio
    """
    try:
        from pytz import timezone
        
        start_time = datetime.fromisoformat(start_time_str)
        
        tz_row = supabase.table("businesses") \
            .select("timezone") \
            .eq("id", business_id) \
            .single() \
            .execute().data
        
        tz_name = tz_row.get("timezone") or "America/Sao_Paulo"
        local_tz = timezone(tz_name)
        
        if start_time.tzinfo is None:
            start_time = local_tz.localize(start_time)
        else:
            start_time = start_time.astimezone(local_tz)
        
        weekday = start_time.weekday()
        weekday_names = {
            0: "monday", 1: "tuesday", 2: "wednesday",
            3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"
        }
        
        day_name = weekday_names[weekday]
        
        business_hours = supabase.table("business_hours") \
            .select("start_time, end_time, is_open") \
            .eq("business_id", business_id) \
            .eq("day_of_week", day_name) \
            .single() \
            .execute().data
        
        if not business_hours:
            return False, f"Horário de funcionamento não configurado para {day_name}"
        
        if not business_hours.get("is_open", False):
            day_names_pt = {
                "monday": "segunda-feira", "tuesday": "terça-feira",
                "wednesday": "quarta-feira", "thursday": "quinta-feira",
                "friday": "sexta-feira", "saturday": "sábado", "sunday": "domingo"
            }
            return False, f"Estabelecimento fechado às {day_names_pt[day_name]}s"
        
        if not business_hours.get("start_time") or not business_hours.get("end_time"):
            return False, f"Horário de funcionamento não definido"
        
        appointment_time = start_time.time()
        
        start_business_str = str(business_hours["start_time"])
        end_business_str = str(business_hours["end_time"])
        
        if len(start_business_str) > 5:
            start_business = datetime.strptime(start_business_str[:5], "%H:%M").time()
        else:
            start_business = datetime.strptime(start_business_str, "%H:%M").time()
            
        if len(end_business_str) > 5:
            end_business = datetime.strptime(end_business_str[:5], "%H:%M").time()
        else:
            end_business = datetime.strptime(end_business_str, "%H:%M").time()
        
        if appointment_time < start_business:
            return False, f"Horário muito cedo. Funcionamento inicia às {start_business.strftime('%H:%M')}"
        
        if appointment_time >= end_business:
            return False, f"Horário muito tarde. Funcionamento encerra às {end_business.strftime('%H:%M')}"
        
        return True, "Horário válido"
        
    except Exception as e:
        return False, f"Erro ao validar horário: {str(e)}"

# ------------------
# Rotas Públicas
# ------------------

@app.route("/", methods=["GET"])
def index():
    return "API Fluxo v29.0 -- OK"

@app.route("/api/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"})

@app.route("/api/on-signup", methods=["POST"])
def on_signup():
    data = request.get_json(force=True)
    try:
        supabase.rpc(
            "handle_new_user",
            {
                "user_id": data["user_id"],
                "full_name": data["full_name"],
                "business_name": data["business_name"]
            }
        ).execute()
        return jsonify({"message": "Usuário e negócio criados"}), 200
    except Exception as e:
        return jsonify({"error": str(e)}), 400

# ------------------
# Dashboard Stats
# ------------------

@app.route("/api/dashboard/stats", methods=["GET"])
@auth_required
def dashboard_stats(business_id):
    try:
        from pytz import timezone

        tz_row = supabase.table("businesses") \
            .select("timezone") \
            .eq("id", business_id) \
            .single() \
            .execute().data

        tz_name = tz_row.get("timezone") or "America/Sao_Paulo"
        local_tz = timezone(tz_name)

        date_str = request.args.get("date")

        if date_str:
            selected_local = local_tz.localize(datetime.strptime(date_str, "%Y-%m-%d"))
        else:
            selected_local = datetime.now(local_tz)

        start_of_day = selected_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day = start_of_day + timedelta(days=1)

        now_local = datetime.now(local_tz)
        start_of_month = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        services = supabase.table("services") \
            .select("id, name, price") \
            .eq("business_id", business_id) \
            .execute().data or []

        price_map = {s["id"]: s.get("price", 0.0) for s in services}
        service_map = {s["id"]: s.get("name", "") for s in services}

        appts_today = supabase.table("appointments") \
            .select("""
                id,
                customer_name,
                start_time,
                service_id,
                service:services(name),
                professional:professionals(name)
            """) \
            .eq("business_id", business_id) \
            .gte("start_time", start_of_day.isoformat()) \
            .lt("start_time", end_of_day.isoformat()) \
            .execute().data

        revenue_today = sum(price_map.get(a["service_id"], 0) for a in appts_today)

        appts_month = supabase.table("appointments") \
            .select("service_id") \
            .eq("business_id", business_id) \
            .gte("start_time", start_of_month.isoformat()) \
            .execute().data

        revenue_month = sum(price_map.get(a["service_id"], 0) for a in appts_month)

        old_clients = supabase.table("appointments") \
            .select("customer_phone") \
            .eq("business_id", business_id) \
            .lt("start_time", start_of_month.isoformat()) \
            .execute().data

        old_phones = {c["customer_phone"] for c in old_clients if c.get("customer_phone")}

        this_month = supabase.table("appointments") \
            .select("customer_phone") \
            .eq("business_id", business_id) \
            .gte("start_time", start_of_month.isoformat()) \
            .execute().data

        new_phones = {
            c["customer_phone"] for c in this_month
            if c.get("customer_phone") and c["customer_phone"] not in old_phones
        }

        new_clients = len(new_phones)

        appts_7d = []

        for i in range(6, -1, -1):
            day = now_local - timedelta(days=i)
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end = start + timedelta(days=1)

            count = supabase.table("appointments") \
                .select("id") \
                .eq("business_id", business_id) \
                .gte("start_time", start.isoformat()) \
                .lt("start_time", end.isoformat()) \
                .execute().data

            appts_7d.append({"date": start.date().isoformat(), "count": len(count)})

        revenue_4w = []

        for w in range(4):
            start = (now_local - timedelta(weeks=w)).replace(hour=0, minute=0, second=0, microsecond=0)
            start -= timedelta(days=start.weekday())
            end = start + timedelta(days=7)

            appts = supabase.table("appointments") \
                .select("service_id") \
                .eq("business_id", business_id) \
                .gte("start_time", start.isoformat()) \
                .lt("start_time", end.isoformat()) \
                .execute().data

            total = sum(price_map.get(a["service_id"], 0) for a in appts)

            revenue_4w.append({
                "weekLabel": f"{start.strftime('%d/%m')} -- {end.strftime('%d/%m')}",
                "revenue": total
            })

        svc_counter = {}

        for a in appts_month:
            sid = a["service_id"]
            svc_counter[sid] = svc_counter.get(sid, 0) + 1

        top = sorted(svc_counter.items(), key=lambda x: x[1], reverse=True)[:5]

        top_services = [
            {"serviceName": service_map.get(sid, "Desconhecido"), "count": count}
            for sid, count in top
        ]

        upcoming = []

        if selected_local.date() >= now_local.date():
            upcoming = sorted(appts_today, key=lambda x: x["start_time"])

        return jsonify({
            "appointmentsToday": len(appts_today),
            "revenueToday": revenue_today,
            "revenueMonth": revenue_month,
            "newClientsMonth": new_clients,
            "appointmentsLast7Days": appts_7d,
            "revenueLast4Weeks": revenue_4w,
            "topServices": top_services,
            "upcomingAppointments": upcoming
        }), 200

    except Exception as e:
        return jsonify({
            "error": "Falha ao calcular estatísticas",
            "details": str(e)
        }), 500

# ------------------
# Serviços CRUD
# ------------------

@app.route("/api/services", methods=["GET"])
@auth_required
def list_services(business_id):
    resp = supabase.table("services") \
        .select("*") \
        .eq("business_id", business_id) \
        .order("name") \
        .execute()
    return jsonify([format_service(s) for s in resp.data]), 200

@app.route("/api/services", methods=["POST"])
@auth_required
def create_service(business_id):
    req = request.get_json(force=True)
    name = req.get("name")
    price = req.get("price")
    duration = req.get("duration") or req.get("duration_minutes")

    if not all([name, price, duration]):
        return jsonify({"error": "name, price e duration são obrigatórios"}), 400

    try:
        rec = {
            "name": name,
            "price": float(price),
            "duration_minutes": int(duration),
            "business_id": business_id
        }
        r = supabase.table("services").insert(rec).execute().data[0]
        return jsonify(format_service(r)), 201
    except Exception as e:
        return jsonify({"error": "Falha ao criar serviço", "details": str(e)}), 500

@app.route("/api/services/<sid>", methods=["PUT"])
@auth_required
def update_service(sid, business_id):
    req = request.get_json(force=True)
    name = req.get("name")
    price = req.get("price")
    duration = req.get("duration") or req.get("duration_minutes")

    if not all([name, price, duration]):
        return jsonify({"error": "name, price e duration são obrigatórios"}), 400

    try:
        rec = {
            "name": name,
            "price": float(price),
            "duration_minutes": int(duration)
        }
        r = supabase.table("services") \
            .update(rec) \
            .eq("id", sid) \
            .eq("business_id", business_id) \
            .execute().data

        if not r:
            return jsonify({"error": "Serviço não encontrado"}), 404
        return jsonify(format_service(r[0])), 200
    except Exception as e:
        return jsonify({"error": "Falha ao atualizar", "details": str(e)}), 500

@app.route("/api/services/<sid>", methods=["DELETE"])
@auth_required
def delete_service(sid, business_id):
    r = supabase.table("services") \
        .delete() \
        .eq("id", sid) \
        .eq("business_id", business_id) \
        .execute().data

    if not r:
        return jsonify({"error": "Serviço não encontrado"}), 404
    return jsonify({"message": "Serviço removido"}), 200

# ------------------
# Profissionais CRUD
# ------------------

@app.route("/api/professionals", methods=["GET"])
@auth_required
def list_professionals(business_id):
    resp = supabase.table("professionals") \
        .select("*, services(*)") \
        .eq("business_id", business_id) \
        .order("name") \
        .execute()
    return jsonify(resp.data), 200

@app.route("/api/professionals", methods=["POST"])
@auth_required
def create_professional(business_id):
    req = request.get_json(force=True)
    name = req.get("name")

    if not name:
        return jsonify({"error": "name é obrigatório"}), 400

    try:
        r = supabase.table("professionals") \
            .insert({"name": name, "business_id": business_id}) \
            .execute().data[0]
        return jsonify({**r, "services": []}), 201
    except Exception as e:
        return jsonify({"error": "Falha ao criar profissional", "details": str(e)}), 500

@app.route("/api/professionals/<pid>", methods=["DELETE"])
@auth_required
def delete_professional(pid, business_id):
    r = supabase.table("professionals") \
        .delete() \
        .eq("id", pid) \
        .eq("business_id", business_id) \
        .execute().data

    if not r:
        return jsonify({"error": "Profissional não encontrado"}), 404
    return jsonify({"message": "Profissional removido"}), 200

@app.route("/api/professionals/<pid>/services", methods=["POST"])
@auth_required
def add_prof_service(pid, business_id):
    sid = request.get_json(force=True).get("service_id")
    if not sid:
        return jsonify({"error": "service_id é obrigatório"}), 400

    try:
        r = supabase.table("professional_services") \
            .insert({"professional_id": pid, "service_id": sid}) \
            .execute().data[0]
        return jsonify(r), 201
    except Exception as e:
        return jsonify({"error": "Falha ao associar", "details": str(e)}), 500

@app.route("/api/professionals/<pid>/services/<sid>", methods=["DELETE"])
@auth_required
def remove_prof_service(pid, sid, business_id):
    r = supabase.table("professional_services") \
        .delete() \
        .match({"professional_id": pid, "service_id": sid}) \
        .execute().data

    if not r:
        return jsonify({"error": "Associação não encontrada"}), 404
    return jsonify({"message": "Associação removida"}), 200

@app.route("/api/professionals/<pid>", methods=["PUT"])
@auth_required
def update_professional(pid, business_id):
    req = request.get_json(force=True)
    name = req.get("name")

    if not name:
        return jsonify({"error": "name é obrigatório"}), 400

    try:
        r = supabase.table("professionals") \
            .update({"name": name}) \
            .eq("id", pid) \
            .eq("business_id", business_id) \
            .execute().data

        if not r:
            return jsonify({"error": "Profissional não encontrado"}), 404
        return jsonify(r[0]), 200
    except Exception as e:
        return jsonify({"error": "Falha ao atualizar profissional", "details": str(e)}), 500

# ------------------
# Agenda / Agendamentos
# ------------------

@app.route("/api/appointments", methods=["GET"])
@auth_required
def get_appointments(business_id):
    try:
        r = supabase.table("appointments") \
            .select("""
                id,
                customer_name,
                customer_phone,
                service_id,
                professional_id,
                start_time,
                end_time,
                service:services(name),
                professional:professionals(name)
            """) \
            .eq("business_id", business_id) \
            .execute().data
        return jsonify(r), 200
    except Exception as e:
        return jsonify({"error": "Falha ao buscar agendamentos", "details": str(e)}), 500

@app.route("/api/appointments/<aid>", methods=["GET"])
@auth_required
def get_appointment_by_id(aid, business_id):
    try:
        result = supabase.table("appointments") \
            .select("""
                id,
                customer_name,
                customer_phone,
                service_id,
                professional_id,
                start_time,
                end_time,
                service:services(name),
                professional:professionals(name)
            """) \
            .eq("id", aid) \
            .eq("business_id", business_id) \
            .single() \
            .execute()

        if result.data is None:
            return jsonify({"error": "Agendamento não encontrado"}), 404
        return jsonify(result.data), 200
    except Exception as e:
        return jsonify({"error": "Erro ao buscar agendamento", "details": str(e)}), 500

@app.route("/api/appointments", methods=["POST"])
@auth_required
def create_appointment(business_id):
    data = request.get_json(force=True)
    required = ["professional_id", "service_id", "customer_name", "customer_phone", "start_time"]

    if not all(k in data for k in required):
        return jsonify({"error": "Campos obrigatórios faltando"}), 400

    try:
        is_valid, error_msg = validate_business_hours(business_id, data["start_time"])
        if not is_valid:
            return jsonify({"error": error_msg}), 400

        svc = supabase.table("services") \
            .select("duration_minutes") \
            .eq("id", data["service_id"]) \
            .single() \
            .execute().data

        if not svc:
            return jsonify({"error": "Serviço não existe"}), 404

        start = datetime.fromisoformat(data["start_time"])
        end = start + timedelta(minutes=svc["duration_minutes"])

        rec = {
            "professional_id": data["professional_id"],
            "service_id": data["service_id"],
            "business_id": business_id,
            "customer_name": data["customer_name"],
            "customer_phone": data["customer_phone"],
            "start_time": start.isoformat(),
            "end_time": end.isoformat()
        }

        appt = supabase.table("appointments").insert(rec).execute().data[0]
        return jsonify(appt), 201
    except Exception as e:
        return jsonify({"error": "Falha ao criar agendamento", "details": str(e)}), 500

@app.route("/api/appointments/<aid>", methods=["PUT"])
@auth_required
def update_appointment(aid, business_id):
    data = request.get_json(force=True)
    required = ["professional_id", "service_id", "customer_name", "customer_phone", "start_time"]

    if not all(k in data for k in required):
        return jsonify({"error": "Campos obrigatórios faltando"}), 400

    try:
        is_valid, error_msg = validate_business_hours(business_id, data["start_time"])
        if not is_valid:
            return jsonify({"error": error_msg}), 400

        svc = supabase.table("services") \
            .select("duration_minutes") \
            .eq("id", data["service_id"]) \
            .single() \
            .execute().data

        if not svc:
            return jsonify({"error": "Serviço não existe"}), 404

        start = datetime.fromisoformat(data["start_time"])
        end = start + timedelta(minutes=svc["duration_minutes"])

        updated = supabase.table("appointments") \
            .update({
                "professional_id": data["professional_id"],
                "service_id": data["service_id"],
                "customer_name": data["customer_name"],
                "customer_phone": data["customer_phone"],
                "start_time": start.isoformat(),
                "end_time": end.isoformat()
            }) \
            .eq("id", aid) \
            .eq("business_id", business_id) \
            .execute().data

        if not updated:
            return jsonify({"error": "Agendamento não encontrado"}), 404
        return jsonify(updated[0]), 200
    except Exception as e:
        return jsonify({"error": "Falha ao atualizar agendamento", "details": str(e)}), 500

@app.route("/api/appointments/<aid>", methods=["DELETE"])
@auth_required
def delete_appointment(aid, business_id):
    try:
        deleted = supabase.table("appointments") \
            .delete() \
            .eq("id", aid) \
            .eq("business_id", business_id) \
            .execute().data

        if not deleted:
            return jsonify({"error": "Agendamento não encontrado"}), 404
        return jsonify({"message": "Agendamento removido com sucesso"}), 200
    except Exception as e:
        return jsonify({"error": "Erro ao deletar agendamento", "details": str(e)}), 500

@app.route("/api/available-professionals", methods=["GET"])
@auth_required
def available_professionals(business_id):
    svc_id = request.args.get("service_id")
    start_str = request.args.get("start_time")
    appt_id = request.args.get("appointment_id")

    if not svc_id or not start_str:
        return jsonify({"error": "service_id e start_time obrigatórios"}), 400

    try:
        is_valid, error_msg = validate_business_hours(business_id, start_str)
        if not is_valid:
            return jsonify({"error": error_msg, "available_professionals": []}), 200

        start = datetime.fromisoformat(start_str)

        svc = supabase.table("services") \
            .select("duration_minutes") \
            .eq("id", svc_id) \
            .single() \
            .execute().data

        if not svc:
            return jsonify({"error": "Serviço não existe"}), 404

        end = start + timedelta(minutes=svc["duration_minutes"])

        link = supabase.table("professional_services") \
            .select("professional_id") \
            .eq("service_id", svc_id) \
            .execute().data

        prof_ids = [l["professional_id"] for l in link]

        busy = supabase.table("appointments") \
            .select("id, professional_id") \
            .eq("business_id", business_id) \
            .lt("start_time", end.isoformat()) \
            .gt("end_time", start.isoformat()) \
            .execute().data

        if appt_id:
            busy = [b for b in busy if str(b["id"]) != str(appt_id)]

        busy_ids = {b["professional_id"] for b in busy}

        pros = supabase.table("professionals") \
            .select("id,name") \
            .eq("business_id", business_id) \
            .in_("id", prof_ids) \
            .execute().data

        free = [p for p in pros if p["id"] not in busy_ids]
        return jsonify(free), 200
    except Exception as e:
        return jsonify({"error": "Falha ao buscar disponíveis", "details": str(e)}), 500

# ------------------
# Horários de Funcionamento
# ------------------

@app.route("/api/business-hours", methods=["GET"])
@auth_required
def get_business_hours(business_id):
    try:
        hours = supabase.table("business_hours") \
            .select("*") \
            .eq("business_id", business_id) \
            .order("CASE day_of_week " + 
                   "WHEN 'monday' THEN 1 " +
                   "WHEN 'tuesday' THEN 2 " +
                   "WHEN 'wednesday' THEN 3 " +
                   "WHEN 'thursday' THEN 4 " +
                   "WHEN 'friday' THEN 5 " +
                   "WHEN 'saturday' THEN 6 " +
                   "WHEN 'sunday' THEN 7 END") \
            .execute()
        return jsonify(hours.data), 200
    except Exception as e:
        return jsonify({"error": "Falha ao buscar horários", "details": str(e)}), 500

@app.route("/api/business-hours/validate", methods=["POST"])
@auth_required
def validate_appointment_time(business_id):
    data = request.get_json(force=True)
    start_time = data.get("start_time")
    
    if not start_time:
        return jsonify({"error": "start_time é obrigatório"}), 400
    
    try:
        is_valid, message = validate_business_hours(business_id, start_time)
        return jsonify({
            "is_valid": is_valid,
            "message": message
        }), 200
    except Exception as e:
        return jsonify({"error": "Falha na validação", "details": str(e)}), 500

# ------------------
# WhatsApp Functions
# ------------------

def get_conversation_state(business_id, phone_number):
    """Busca estado atual da conversa"""
    try:
        conv = supabase.table("whatsapp_conversations") \
            .select("*") \
            .eq("business_id", business_id) \
            .eq("phone_number", phone_number) \
            .order("created_at", desc=True) \
            .limit(1) \
            .execute()
        
        if conv.data:
            return conv.data[0]
        return None
    except:
        return None

def update_conversation_state(business_id, phone_number, **kwargs):
    """Atualiza estado da conversa"""
    try:
        existing = get_conversation_state(business_id, phone_number)
        
        if existing:
            supabase.table("whatsapp_conversations") \
                .update(kwargs) \
                .eq("id", existing["id"]) \
                .execute()
        else:
            data = {
                "business_id": business_id,
                "phone_number": phone_number,
                **kwargs
            }
            supabase.table("whatsapp_conversations") \
                .insert(data) \
                .execute()
    except Exception as e:
        print(f"Erro ao atualizar conversa: {e}")

def send_whatsapp_message(instance_name, phone_number, message):
    """Envia mensagem via Evolution API"""
    try:
        if not EVOLUTION_BASE_URL or not EVOLUTION_API_KEY:
            print("Evolution API não configurada")
            return False
            
        url = f"{EVOLUTION_BASE_URL}/message/sendText/{instance_name}"
        headers = {
            "Content-Type": "application/json",
            "apikey": EVOLUTION_API_KEY
        }
        
        payload = {
            "number": phone_number,
            "text": message
        }
        
        response = requests.post(url, json=payload, headers=headers)
        return response.status_code == 200
        
    except Exception as e:
        print(f"Erro ao enviar mensagem: {e}")
        return False

def get_flow_message(business_id, step):
    """Busca mensagem do fluxo configurado"""
    try:
        default_messages = {
            "welcome": """Olá! 👋 Bem-vindo à {{nome_do_negocio}}!

Sou seu assistente virtual e estou aqui para ajudar você a agendar seu horário.

Para começar, preciso do seu nome:""",
            
            "ask_service": """Perfeito, {{nome_do_cliente}}! 😊

Agora me diga, qual serviço você gostaria de agendar?

{{lista_de_servicos}}

Digite o número do serviço desejado:""",
            
            "ask_date": """Ótima escolha! {{servico_selecionado}} 💪

Agora vamos escolher a data. Temos disponibilidade nos seguintes dias:

{{datas_disponiveis}}

Digite o número do dia desejado:""",
            
            "ask_time": """Perfeito! Agora vamos escolher o horário.

Para {{data_selecionada}} temos os seguintes horários disponíveis:

{{horarios_disponiveis}}

Digite o número do horário desejado:""",
            
            "ask_professional": """Ótimo! Para {{data_selecionada}} às {{horario_selecionado}} temos:

{{lista_de_profissionais}}

Digite o número do profissional ou 'TANTO FAZ':""",
            
            "confirm": """Perfeito, {{nome_do_cliente}}! ✅

Vou confirmar seus dados:

**📋 Resumo do Agendamento:**
• Serviço: {{servico_selecionado}}
• Profissional: {{profissional_selecionado}}
• Data: {{data_selecionada}}
• Horário: {{horario_selecionado}}
• Valor: {{valor_do_servico}}

Tudo correto? Digite **SIM** para confirmar ou **NÃO** para alterar.""",
            
            "confirmed": """🎉 **Agendamento Confirmado!**

Seu horário foi agendado com sucesso, {{nome_do_cliente}}!

📱 Você receberá uma confirmação por SMS
⏰ Lembre-se: chegue 5 minutos antes
📍 Endereço: {{endereco_do_negocio}}

Em caso de dúvidas, entre em contato: {{telefone_do_negocio}}

Obrigado pela preferência! 😊"""
        }
        
        return default_messages.get(step, "Mensagem não encontrada")
        
    except Exception as e:
        print(f"Erro ao buscar mensagem do fluxo: {e}")
        return "Erro interno"

def replace_placeholders(message, business_id, conversation_state=None):
    """Substitui placeholders nas mensagens"""
    try:
        business = supabase.table("businesses") \
            .select("name, phone, address") \
            .eq("id", business_id) \
            .single() \
            .execute().data
        
        if business:
            message = message.replace("{{nome_do_negocio}}", business.get("name", ""))
            message = message.replace("{{telefone_do_negocio}}", business.get("phone", ""))
            message = message.replace("{{endereco_do_negocio}}", business.get("address", ""))
        
        if conversation_state and conversation_state.get("customer_name"):
            message = message.replace("{{nome_do_cliente}}", conversation_state["customer_name"])
        
        if "{{lista_de_servicos}}" in message:
            services = supabase.table("services") \
                .select("id, name, price") \
                .eq("business_id", business_id) \
                .order("name") \
                .execute().data
            
            if services:
                services_list = "\n".join([
                    f"{i+1} - {s['name']} (R$ {s['price']:.2f})"
                    for i, s in enumerate(services)
                ])
                message = message.replace("{{lista_de_servicos}}", services_list)
        
        if conversation_state and conversation_state.get("selected_service_id"):
            service = supabase.table("services") \
                .select("name, price") \
                .eq("id", conversation_state["selected_service_id"]) \
                .single() \
                .execute().data
            
            if service:
                message = message.replace("{{servico_selecionado}}", service["name"])
                message = message.replace("{{valor_do_servico}}", f"R$ {service['price']:.2f}")
        
        if "{{datas_disponiveis}}" in message:
            dates_list = generate_available_dates(business_id)
            message = message.replace("{{datas_disponiveis}}", dates_list)
        
        if conversation_state and conversation_state.get("selected_date"):
            date_obj = datetime.strptime(conversation_state["selected_date"], "%Y-%m-%d")
            date_formatted = date_obj.strftime("%d/%m/%Y")
            message = message.replace("{{data_selecionada}}", date_formatted)
        
        if "{{horarios_disponiveis}}" in message and conversation_state:
            if conversation_state.get("selected_service_id") and conversation_state.get("selected_date"):
                times_list = generate_available_times(
                    business_id, 
                    conversation_state["selected_service_id"],
                    conversation_state["selected_date"]
                )
                message = message.replace("{{horarios_disponiveis}}", times_list)
        
        if conversation_state and conversation_state.get("selected_time"):
            message = message.replace("{{horario_selecionado}}", conversation_state["selected_time"])
        
        if "{{lista_de_profissionais}}" in message and conversation_state:
            if all([conversation_state.get("selected_service_id"), 
                   conversation_state.get("selected_date"),
                   conversation_state.get("selected_time")]):
                
                start_time = f"{conversation_state['selected_date']}T{conversation_state['selected_time']}:00"
                professionals_list = generate_available_professionals(
                    business_id,
                    conversation_state["selected_service_id"], 
                    start_time
                )
                message = message.replace("{{lista_de_profissionais}}", professionals_list)
        
        if conversation_state and conversation_state.get("selected_professional_id"):
            professional = supabase.table("professionals") \
                .select("name") \
                .eq("id", conversation_state["selected_professional_id"]) \
                .single() \
                .execute().data
            
            if professional:
                message = message.replace("{{profissional_selecionado}}", professional["name"])
        
        return message
        
    except Exception as e:
        print(f"Erro ao substituir placeholders: {e}")
        return message

def generate_available_dates(business_id, days_ahead=7):
    """Gera lista de datas disponíveis"""
    try:
        from pytz import timezone
        
        tz_row = supabase.table("businesses") \
            .select("timezone") \
            .eq("id", business_id) \
            .single() \
            .execute().data
        
        tz_name = tz_row.get("timezone") or "America/Sao_Paulo"
        local_tz = timezone(tz_name)
        now = datetime.now(local_tz)
        
        available_dates = []
        for i in range(days_ahead):
            check_date = now + timedelta(days=i)
            weekday = check_date.weekday()
            
            weekday_names = {
                0: "monday", 1: "tuesday", 2: "wednesday",
                3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"
            }
            
            day_name = weekday_names[weekday]
            
            business_hours = supabase.table("business_hours") \
                .select("is_open") \
                .eq("business_id", business_id) \
                .eq("day_of_week", day_name) \
                .single() \
                .execute().data
            
            if business_hours and business_hours.get("is_open"):
                date_str = check_date.strftime("%d/%m")
                weekday_pt = {
                    0: "Seg", 1: "Ter", 2: "Qua", 3: "Qui", 
                    4: "Sex", 5: "Sáb", 6: "Dom"
                }[weekday]
                
                available_dates.append(f"{len(available_dates)+1} - {weekday_pt} ({date_str})")
        
        return "\n".join(available_dates) if available_dates else "Nenhuma data disponível"
        
    except Exception as e:
        print(f"Erro ao gerar datas: {e}")
        return "Erro ao carregar datas disponíveis"

def generate_available_times(business_id, service_id, date_str):
    """Gera lista de horários disponíveis para uma data específica"""
    try:
        from pytz import timezone
        
        tz_row = supabase.table("businesses") \
            .select("timezone") \
            .eq("id", business_id) \
            .single() \
            .execute().data
        
        tz_name = tz_row.get("timezone") or "America/Sao_Paulo"
        local_tz = timezone(tz_name)
        
        check_date = datetime.strptime(date_str, "%Y-%m-%d")
        weekday = check_date.weekday()
        
        weekday_names = {
            0: "monday", 1: "tuesday", 2: "wednesday",
            3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"
        }
        
        day_name = weekday_names[weekday]
        
        business_hours = supabase.table("business_hours") \
            .select("start_time, end_time, is_open") \
            .eq("business_id", business_id) \
            .eq("day_of_week", day_name) \
            .single() \
            .execute().data
        
        if not business_hours or not business_hours.get("is_open"):
            return "Não há horários disponíveis nesta data"
        
        service = supabase.table("services") \
            .select("duration_minutes") \
            .eq("id", service_id) \
            .single() \
            .execute().data
        
        if not service:
            return "Serviço não encontrado"
        
        start_time_str = str(business_hours["start_time"])
        end_time_str = str(business_hours["end_time"])
        
        if len(start_time_str) > 5:
            start_time = datetime.strptime(start_time_str[:5], "%H:%M").time()
        else:
            start_time = datetime.strptime(start_time_str, "%H:%M").time()
            
        if len(end_time_str) > 5:
            end_time = datetime.strptime(end_time_str[:5], "%H:%M").time()
        else:
            end_time = datetime.strptime(end_time_str, "%H:%M").time()
        
        available_times = []
        current_time = datetime.combine(check_date.date(), start_time)
        end_datetime = datetime.combine(check_date.date(), end_time)
        
        slot_interval = 30
        service_duration = service["duration_minutes"]
        
        while current_time + timedelta(minutes=service_duration) <= end_datetime:
            time_str = current_time.strftime("%H:%M")
            
            start_time_iso = f"{date_str}T{time_str}:00"
            
            professional_services = supabase.table("professional_services") \
                .select("professional_id") \
                .eq("service_id", service_id) \
                .execute().data
            
            prof_ids = [ps["professional_id"] for ps in professional_services]
            
            if prof_ids:
                end_time_iso = f"{date_str}T{(current_time + timedelta(minutes=service_duration)).strftime('%H:%M')}:00"
                
                busy = supabase.table("appointments") \
                    .select("professional_id") \
                    .eq("business_id", business_id) \
                    .lt("start_time", end_time_iso) \
                    .gt("end_time", start_time_iso) \
                    .execute().data
                
                busy_ids = {b["professional_id"] for b in busy}
                available_prof_ids = [pid for pid in prof_ids if pid not in busy_ids]
                
                if available_prof_ids:
                    available_times.append(f"{len(available_times)+1} - {time_str}")
            
            current_time += timedelta(minutes=slot_interval)
        
        return "\n".join(available_times) if available_times else "Nenhum horário disponível"
        
    except Exception as e:
        print(f"Erro ao gerar horários: {e}")
        return "Erro ao carregar horários disponíveis"

def generate_available_professionals(business_id, service_id, start_time_iso):
    """Gera lista de profissionais disponíveis"""
    try:
        start_time = datetime.fromisoformat(start_time_iso)
        
        service = supabase.table("services") \
            .select("duration_minutes") \
            .eq("id", service_id) \
            .single() \
            .execute().data
        
        if not service:
            return "Serviço não encontrado"
        
        end_time = start_time + timedelta(minutes=service["duration_minutes"])
        
        professional_services = supabase.table("professional_services") \
            .select("professional_id") \
            .eq("service_id", service_id) \
            .execute().data
        
        prof_ids = [ps["professional_id"] for ps in professional_services]
        
        if not prof_ids:
            return "Nenhum profissional habilitado para este serviço"
        
        busy = supabase.table("appointments") \
            .select("professional_id") \
            .eq("business_id", business_id) \
            .lt("start_time", end_time.isoformat()) \
            .gt("end_time", start_time.isoformat()) \
            .execute().data
        
        busy_ids = {b["professional_id"] for b in busy}
        
        available_professionals = supabase.table("professionals") \
            .select("id, name") \
            .eq("business_id", business_id) \
            .in_("id", prof_ids) \
            .execute().data
        
        free_professionals = [p for p in available_professionals if p["id"] not in busy_ids]
        
        if len(free_professionals) == 1:
            return f"Profissional disponível: {free_professionals[0]['name']}"
        elif len(free_professionals) > 1:
            professionals_list = "\n".join([
                f"{i+1} - {p['name']}"
                for i, p in enumerate(free_professionals)
            ])
            return professionals_list
        else:
            return "Nenhum profissional disponível neste horário"
            
    except Exception as e:
        print(f"Erro ao gerar profissionais: {e}")
        return "Erro ao carregar profissionais disponíveis"

def process_whatsapp_message(business_id, phone_number, message_text, instance_name):
    """Processa mensagem recebida e retorna resposta"""
    try:
        message_text = message_text.strip()
        conversation = get_conversation_state(business_id, phone_number)
        
        if not conversation:
            update_conversation_state(
                business_id, phone_number,
                current_step="waiting_name",
                customer_name=None
            )
            
            welcome_msg = get_flow_message(business_id, "welcome")
            response = replace_placeholders(welcome_msg, business_id)
            return response
        
        current_step = conversation.get("current_step", "waiting_name")
        
        if current_step == "waiting_name":
            update_conversation_state(
                business_id, phone_number,
                current_step="waiting_service",
                customer_name=message_text
            )
            
            service_msg = get_flow_message(business_id, "ask_service")
            conversation["customer_name"] = message_text
            response = replace_placeholders(service_msg, business_id, conversation)
            return response
        
        elif current_step == "waiting_service":
            try:
                service_index = int(message_text) - 1
                services = supabase.table("services") \
                    .select("id, name") \
                    .eq("business_id", business_id) \
                    .order("name") \
                    .execute().data
                
                if 0 <= service_index < len(services):
                    selected_service = services[service_index]
                    
                    update_conversation_state(
                        business_id, phone_number,
                        current_step="waiting_date",
                        selected_service_id=selected_service["id"]
                    )
                    
                    date_msg = get_flow_message(business_id, "ask_date")
                    conversation["selected_service_id"] = selected_service["id"]
                    response = replace_placeholders(date_msg, business_id, conversation)
                    return response
                else:
                    return "Número inválido. Por favor, escolha um serviço da lista digitando o número correspondente."
                    
            except ValueError:
                return "Por favor, digite apenas o número do serviço desejado."
        
        elif current_step == "waiting_date":
            try:
                date_index = int(message_text) - 1
                
                from pytz import timezone
                tz_row = supabase.table("businesses") \
                    .select("timezone") \
                    .eq("id", business_id) \
                    .single() \
                    .execute().data
                
                tz_name = tz_row.get("timezone") or "America/Sao_Paulo"
                local_tz = timezone(tz_name)
                now = datetime.now(local_tz)
                
                available_dates = []
                for i in range(7):
                    check_date = now + timedelta(days=i)
                    weekday = check_date.weekday()
                    
                    weekday_names = {
                        0: "monday", 1: "tuesday", 2: "wednesday",
                        3: "thursday", 4: "friday", 5: "saturday", 6: "sunday"
                    }
                    
                    day_name = weekday_names[weekday]
                    
                    business_hours = supabase.table("business_hours") \
                        .select("is_open") \
                        .eq("business_id", business_id) \
                        .eq("day_of_week", day_name) \
                        .single() \
                        .execute().data
                    
                    if business_hours and business_hours.get("is_open"):
                        available_dates.append(check_date.strftime("%Y-%m-%d"))
                
                if 0 <= date_index < len(available_dates):
                    selected_date = available_dates[date_index]
                    
                    update_conversation_state(
                        business_id, phone_number,
                        current_step="waiting_time",
                        selected_date=selected_date
                    )
                    
                    time_msg = get_flow_message(business_id, "ask_time")
                    conversation["selected_date"] = selected_date
                    response = replace_placeholders(time_msg, business_id, conversation)
                    return response
                else:
                    return "Data inválida. Por favor, escolha uma data da lista digitando o número correspondente."
                    
            except ValueError:
                return "Por favor, digite apenas o número da data desejada."
        
        else:
            supabase.table("whatsapp_conversations") \
                .delete() \
                .eq("business_id", business_id) \
                .eq("phone_number", phone_number) \
                .execute()
            
            welcome_msg = get_flow_message(business_id, "welcome")
            response = replace_placeholders(welcome_msg, business_id)
            return response
        
    except Exception as e:
        print(f"Erro ao processar mensagem: {e}")
        return "Ops! Ocorreu um erro. Para fazer um agendamento, digite seu nome:"

# ------------------
# WhatsApp Routes
# ------------------

@app.route("/api/whatsapp/webhook", methods=["POST"])
def whatsapp_webhook():
    """Webhook para receber mensagens do WhatsApp via Evolution API"""
    try:
        data = request.get_json(force=True)
        
        print(f"Webhook recebido: {json.dumps(data, indent=2)}")
        
        if data.get("event") == "messages.upsert":
            message_data = data.get("data", {})
            
            if message_data.get("fromMe"):
                return jsonify({"status": "ignored - sent by me"}), 200
            
            phone_number = message_data.get("key", {}).get("remoteJid", "").replace("@s.whatsapp.net", "")
            message_text = message_data.get("message", {}).get("conversation", "")
            instance_name = data.get("instance", "")
            
            if not message_text:
                msg_obj = message_data.get("message", {})
                if "extendedTextMessage" in msg_obj:
                    message_text = msg_obj["extendedTextMessage"].get("text", "")
                elif "imageMessage" in msg_obj:
                    message_text = msg_obj["imageMessage"].get("caption", "")
            
            if not phone_number or not message_text:
                return jsonify({"status": "ignored - invalid message"}), 200
            
            business_id = instance_name
            
            try:
                business = supabase.table("businesses") \
                    .select("id") \
                    .eq("whatsapp_instance", instance_name) \
                    .single() \
                    .execute().data
                
                if business:
                    business_id = business["id"]
            except:
                pass
            
            response_text = process_whatsapp_message(business_id, phone_number, message_text, instance_name)
            
            if response_text:
                send_whatsapp_message(instance_name, phone_number, response_text)
            
            return jsonify({"status": "processed"}), 200
        
        return jsonify({"status": "ignored - not a message"}), 200
        
    except Exception as e:
        print(f"Erro no webhook: {e}")
        return jsonify({"error": str(e)}), 500

@app.route("/api/whatsapp/connect", methods=["POST"])
@auth_required
def connect_whatsapp(business_id):
    """Conecta instância do WhatsApp para o negócio"""
    try:
        if not EVOLUTION_BASE_URL or not EVOLUTION_API_KEY:
            return jsonify({"error": "Evolution API não configurada no servidor"}), 500
        
        instance_name = f"business_{business_id}"
        
        url = f"{EVOLUTION_BASE_URL}/instance/create"
        headers = {
            "Content-Type": "application/json",
            "apikey": EVOLUTION_API_KEY
        }
        
        payload = {
            "instanceName": instance_name,
            "token": EVOLUTION_API_KEY,
            "qrcode": True,
            "webhook": f"{request.host_url}api/whatsapp/webhook"
        }
        
        response = requests.post(url, json=payload, headers=headers)
        
        if response.status_code == 201:
            result = response.json()
            
            supabase.table("businesses") \
                .update({
                    "whatsapp_instance": instance_name,
                    "whatsapp_status": "connecting"
                }) \
                .eq("id", business_id) \
                .execute()
            
            return jsonify({
                "message": "Instância criada com sucesso",
                "instance": instance_name,
                "qr_code": result.get("qrcode", {}).get("code", "")
            }), 200
        else:
            return jsonify({"error": f"Erro ao criar instância: {response.text}"}), 400
            
    except Exception as e:
        return jsonify({"error": f"Erro ao conectar WhatsApp: {str(e)}"}), 500

@app.route("/api/whatsapp/status", methods=["GET"])
@auth_required
def whatsapp_status(business_id):
    """Verifica status da conexão WhatsApp"""
    try:
        business = supabase.table("businesses") \
            .select("whatsapp_instance, whatsapp_status") \
            .eq("id", business_id) \
            .single() \
            .execute().data
        
        if not business or not business.get("whatsapp_instance"):
            return jsonify({
                "connected": False,
                "status": "not_configured"
            }), 200
        
        return jsonify({
            "connected": business.get("whatsapp_status") == "connected",
            "status": business.get("whatsapp_status", "disconnected"),
            "instance": business["whatsapp_instance"]
        }), 200
            
    except Exception as e:
        return jsonify({
            "connected": False,
            "status": "error",
            "error": str(e)
        }), 200

# ------------------
if __name__ == "__main__":
    app.run(debug=True)