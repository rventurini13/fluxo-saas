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
        from pytz import timezone

        # --- Time-zone do negócio
        tz_row = supabase.table("businesses") \
            .select("timezone") \
            .eq("id", business_id) \
            .single() \
            .execute().data
        tz_name  = tz_row.get("timezone") or "America/Sao_Paulo"
        local_tz = timezone(tz_name)

        # --- Data selecionada (query param ?date=YYYY-MM-DD) ou hoje
        date_str = request.args.get("date")
        if date_str:
            selected_local = local_tz.localize(datetime.strptime(date_str, "%Y-%m-%d"))
        else:
            selected_local = datetime.now(local_tz)

        start_of_day = selected_local.replace(hour=0, minute=0, second=0, microsecond=0)
        end_of_day   = start_of_day + timedelta(days=1)

        now_local      = datetime.now(local_tz)
        start_of_month = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # ------------------------------------------------------------------
        # Carrega **uma única vez** os serviços do negócio
        # ------------------------------------------------------------------
        services = supabase.table("services") \
            .select("id, name, price") \
            .eq("business_id", business_id) \
            .execute().data or []

        price_map   = {s["id"]: s.get("price", 0.0) for s in services}
        service_map = {s["id"]: s.get("name", "")   for s in services}

        # ------------------------------------------------------------------
        # Agendamentos do dia selecionado
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Agendamentos do mês corrente
        # ------------------------------------------------------------------
        appts_month = supabase.table("appointments") \
            .select("service_id") \
            .eq("business_id", business_id) \
            .gte("start_time", start_of_month.isoformat()) \
            .execute().data
        revenue_month = sum(price_map.get(a["service_id"], 0) for a in appts_month)

        # ------------------------------------------------------------------
        # Novos clientes no mês
        # ------------------------------------------------------------------
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

        # ------------------------------------------------------------------
        # Últimos 7 dias (contagem de agendamentos)
        # ------------------------------------------------------------------
        appts_7d = []
        for i in range(6, -1, -1):
            day   = now_local - timedelta(days=i)
            start = day.replace(hour=0, minute=0, second=0, microsecond=0)
            end   = start + timedelta(days=1)

            count = supabase.table("appointments") \
                .select("id") \
                .eq("business_id", business_id) \
                .gte("start_time", start.isoformat()) \
                .lt("start_time",  end.isoformat()) \
                .execute().data
            appts_7d.append({"date": start.date().isoformat(), "count": len(count)})

        # ------------------------------------------------------------------
        # Faturamento das últimas 4 semanas
        # ------------------------------------------------------------------
        revenue_4w = []
        for w in range(4):
            start = (now_local - timedelta(weeks=w)).replace(hour=0, minute=0, second=0, microsecond=0)
            start -= timedelta(days=start.weekday())  # segunda-feira da semana
            end    = start + timedelta(days=7)

            appts = supabase.table("appointments") \
                .select("service_id") \
                .eq("business_id", business_id) \
                .gte("start_time", start.isoformat()) \
                .lt("start_time",  end.isoformat()) \
                .execute().data
            total = sum(price_map.get(a["service_id"], 0) for a in appts)

            revenue_4w.append({
                "weekLabel": f"{start.strftime('%d/%m')} – {end.strftime('%d/%m')}",
                "revenue":   total
            })

        # ------------------------------------------------------------------
        # Top serviços do mês   ✅ FOI MOVIDO PARA ANTES DO RETURN
        # ------------------------------------------------------------------
        svc_counter = {}
        for a in appts_month:
            sid = a["service_id"]
            svc_counter[sid] = svc_counter.get(sid, 0) + 1

        top = sorted(svc_counter.items(), key=lambda x: x[1], reverse=True)[:5]
        top_services = [
            {"serviceName": service_map.get(sid, "Desconhecido"), "count": count}
            for sid, count in top
        ]

        # ------------------------------------------------------------------
        # Próximos agendamentos (apenas se data ≥ hoje)
        # ------------------------------------------------------------------
        upcoming = []
        if selected_local.date() >= now_local.date():
            upcoming = sorted(appts_today, key=lambda x: x["start_time"])

        # ------------------------------------------------------------------
        # Resposta JSON unificada
        # ------------------------------------------------------------------
        return jsonify({
            "appointmentsToday":   len(appts_today),
            "revenueToday":        revenue_today,
            "revenueMonth":        revenue_month,
            "newClientsMonth":     new_clients,
            "appointmentsLast7Days": appts_7d,
            "revenueLast4Weeks":     revenue_4w,
            "topServices":           top_services,
            "upcomingAppointments":  upcoming
        }), 200

    except Exception as e:
        return jsonify({
            "error":   "Falha ao calcular estatísticas",
            "details": str(e)
        }), 500

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

# -------------------
# Agenda / Agendamentos
# -------------------

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
    svc_id        = request.args.get("service_id")
    start_str     = request.args.get("start_time")
    appt_id       = request.args.get("appointment_id")  # opcional: usado na edição

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
                       .select("id, professional_id") \
                       .eq("business_id", business_id) \
                       .lt("start_time", end.isoformat()) \
                       .gt("end_time",   start.isoformat()) \
                       .execute().data

        # Exclui o próprio agendamento da checagem de conflitos

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

# -------------------
if __name__ == "__main__":
    app.run(debug=True)