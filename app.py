import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
from functools import wraps
from werkzeug.middleware.proxy_fix import ProxyFix

# Carrega variáveis de ambiente
load_dotenv()
SUPABASE_URL         = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY         = os.getenv("SUPABASE_KEY", "").strip()
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY", "").strip()
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

# -------------------
# Decorador de Auth
# -------------------
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

# -------------------
# Helpers
# -------------------
def format_service(s):
    if "duration_minutes" in s:
        s["duration"] = s.pop("duration_minutes")
    return s

# -------------------
# Rotas Públicas
# -------------------
@app.route("/", methods=["GET"])
def index():
    return "API Fluxo v28.2 – OK"

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

# -------------------
# Dashboard Stats
# -------------------
@app.route("/api/dashboard/stats", methods=["GET"])
@auth_required
def dashboard_stats(business_id):
    try:
        today = datetime.now().date()
        tomorrow = today + timedelta(days=1)
        count_today = supabase.table("appointments") \
                              .select("id", count="exact") \
                              .eq("business_id", business_id) \
                              .gte("start_time", today.isoformat()) \
                              .lt("start_time", tomorrow.isoformat()) \
                              .execute().count or 0
        stats = {
            "appointmentsToday": count_today,
            "revenueToday": 0.0,
            "revenueMonth": 0.0,
            "newClientsMonth": 0,
            "appointmentsLast7Days": [],
            "revenueLast4Weeks": [],
            "topServices": [],
            "upcomingAppointments": []
        }
        return jsonify(stats), 200
    except Exception as e:
        return jsonify({"error": "Falha ao buscar stats", "details": str(e)}), 500

# -------------------
# Serviços CRUD
# -------------------
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

# -------------------
# Profissionais CRUD
# -------------------
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

# -------------------
# Agenda / Agendamentos
# -------------------
@app.route("/api/appointments", methods=["GET"])
@auth_required
def get_appointments(business_id):
    try:
        r = supabase.table("appointments") \
                   .select("*, service:services(name), professional:professionals(name)") \
                   .eq("business_id", business_id) \
                   .execute().data
        return jsonify(r), 200
    except Exception as e:
        return jsonify({"error": "Falha ao buscar agendamentos", "details": str(e)}), 500

@app.route("/api/appointments", methods=["POST"])
@auth_required
def create_appointment(business_id):
    data = request.get_json(force=True)
    required = ["professional_id", "service_id",
                "customer_name", "customer_phone", "start_time"]
    if not all(k in data for k in required):
        return jsonify({"error": "Campos obrigatórios faltando"}), 400
    try:
        svc = supabase.table("services") \
                      .select("duration_minutes") \
                      .eq("id", data["service_id"]) \
                      .single() \
                      .execute().data
        if not svc:
            return jsonify({"error": "Serviço não existe"}), 404
        start = datetime.fromisoformat(data["start_time"])
        end   = start + timedelta(minutes=svc["duration_minutes"])
        rec = {
            "professional_id": data["professional_id"],
            "service_id":      data["service_id"],
            "business_id":     business_id,
            "customer_name":   data["customer_name"],
            "customer_phone":  data["customer_phone"],
            "start_time":      start.isoformat(),
            "end_time":        end.isoformat()
        }
        appt = supabase.table("appointments").insert(rec).execute().data[0]
        return jsonify(appt), 201
    except Exception as e:
        return jsonify({"error": "Falha ao criar agendamento", "details": str(e)}), 500

# --- Rota para deletar um agendamento ---
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
    svc_id    = request.args.get("service_id")
    start_str = request.args.get("start_time")
    if not svc_id or not start_str:
        return jsonify({"error": "service_id e start_time obrigatórios"}), 400
    try:
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
                       .select("professional_id") \
                       .eq("business_id", business_id) \
                       .lt("start_time", end.isoformat()) \
                       .gt("end_time",   start.isoformat()) \
                       .execute().data
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

# -------------------
if __name__ == "__main__":
    app.run(debug=True)