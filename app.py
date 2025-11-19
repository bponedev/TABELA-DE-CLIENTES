# app.py
import os
import io
import csv
import sqlite3
import re
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter

# -------------------------
# Config
# -------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET", "troque_para_uma_chave_secreta")

# -------------------------
# DB helpers
# -------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    # we will keep row access by index in many templates, so default row factory is fine
    return conn

def init_db():
    conn = get_conn()
    c = conn.cursor()

    # main records table (single table with escritório field)
    c.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            cpf TEXT,
            escritorio_chave TEXT,
            escritorio_nome TEXT,
            tipo_acao TEXT,
            data_fechamento TEXT,
            pendencias TEXT,
            numero_processo TEXT,
            data_protocolo TEXT,
            observacoes TEXT,
            captador TEXT,
            created_at TEXT
        )
    """)

    # excluidos table
    c.execute("""
        CREATE TABLE IF NOT EXISTS excluidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            cpf TEXT,
            escritorio_origem TEXT,
            escritorio_origem_chave TEXT,
            tipo_acao TEXT,
            data_fechamento TEXT,
            pendencias TEXT,
            numero_processo TEXT,
            data_protocolo TEXT,
            observacoes TEXT,
            captador TEXT,
            created_at TEXT,
            data_exclusao TEXT
        )
    """)

    # offices metadata
    c.execute("""
        CREATE TABLE IF NOT EXISTS offices (
            office_key TEXT PRIMARY KEY,
            display_name TEXT
        )
    """)

    # users and user_offices
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            full_name TEXT,
            password_hash TEXT,
            role TEXT,
            active INTEGER DEFAULT 1,
            created_at TEXT
        )
    """)
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_offices (
            user_id INTEGER,
            office_key TEXT,
            PRIMARY KEY(user_id, office_key)
        )
    """)

    conn.commit()

    # ensure CENTRAL office exists
    c.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", ("CENTRAL", "CENTRAL"))
    conn.commit()

    # ensure default admin exists
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        now = datetime.utcnow().isoformat()
        pw_hash = generate_password_hash("admin")
        c.execute("INSERT INTO users (username, full_name, password_hash, role, active, created_at) VALUES (?,?,?,?,?,?)",
                  ("admin", "Administrador Padrão", pw_hash, "ADMIN", 1, now))
        conn.commit()

    conn.close()

# initialize
init_db()

# -------------------------
# Utilities
# -------------------------
def normalize_office_key(name: str) -> str:
    if not name:
        return "CENTRAL"
    s = name.strip().upper()
    s = s.replace(" ", "_")
    s = re.sub(r'[^A-Z0-9_]', '', s)
    return s or "CENTRAL"

def register_office(office_key: str, display_name: str = None):
    if not office_key:
        office_key = "CENTRAL"
    if not display_name:
        display_name = office_key.replace("_", " ").upper()
    else:
        display_name = display_name.upper()
    
    conn = get_conn()
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (office_key, display_name))
    conn.commit()
    conn.close()

def list_offices():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT office_key, display_name FROM offices ORDER BY display_name")
    rows = c.fetchall()
    conn.close()
    out = []
    for r in rows:
        out.append({"key": r[0], "display": r[1]})
    # ensure CENTRAL exists
    if not any(o["key"] == "CENTRAL" for o in out):
        out.insert(0, {"key": "CENTRAL", "display": "CENTRAL"})
        register_office("CENTRAL", "CENTRAL")
    return out

def get_office_display(key: str):
    if not key:
        return "CENTRAL"
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT display_name FROM offices WHERE office_key=?", (key,))
    row = c.fetchone()
    conn.close()
    if row:
        return row[0]
    return key.replace("_", " ").upper()

# -------------------------
# Auth / permissions
# -------------------------
def get_user_by_username(username):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, full_name, password_hash, role, active FROM users WHERE username=?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "full_name": row[2], "password_hash": row[3], "role": row[4], "active": row[5]}

def get_user_by_id(uid):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, full_name, role, active FROM users WHERE id=?", (uid,))
    row = c.fetchone()
    conn.close()
    if not row:
        return None
    return {"id": row[0], "username": row[1], "full_name": row[2], "role": row[3], "active": row[4]}

def get_user_offices(user_id):
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT office_key FROM user_offices WHERE user_id=?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return [r[0] for r in rows]

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))
        user = get_user_by_id(session["user_id"])
        if not user or user["active"] != 1:
            session.pop("user_id", None)
            flash("Sessão inválida. Faça login novamente.", "error")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    decorated.__name__ = f.__name__
    return decorated

def require_roles(*roles):
    def wrapper(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            user = get_user_by_id(session["user_id"])
            if not user:
                session.pop("user_id", None)
                return redirect(url_for("login"))
            if user["role"] not in roles and user["role"] != "ADMIN":
                flash("Permissão negada.", "error")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        decorated.__name__ = f.__name__
        return decorated
    return wrapper

# expose current_user to templates
@app.context_processor
def inject_user():
    user = None
    if "user_id" in session:
        user = get_user_by_id(session["user_id"])
    return {"current_user": user}

# -------------------------
# Auth routes
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    next_page = request.args.get("next") or url_for("index")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        u = get_user_by_username(username)
        if not u or not u["active"]:
            flash("Usuário inválido ou inativo.", "error")
            return render_template("login.html")
        if check_password_hash(u["password_hash"], password):
            session["user_id"] = u["id"]
            flash("Login efetuado.", "success")
            return redirect(next_page)
        else:
            flash("Usuário ou senha incorretos.", "error")
            return render_template("login.html")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.pop("user_id", None)
    flash("Desconectado.", "info")
    return redirect(url_for("login"))

# -------------------------
# Index / create record
# -------------------------
@app.route("/")
@login_required
def index():
    offices = list_offices()
    return render_template("index.html", offices=offices)

@app.route("/submit", methods=["POST"])
@login_required
def submit():
    try:
        nome = request.form.get("nome", "").strip()
        cpf = request.form.get("cpf", "").strip()
        escritorio_input = request.form.get("escritorio", "CENTRAL").strip()
        
        # Lógica simplificada para encontrar o office_key
        offices = list_offices()
        office_key = "CENTRAL"
        display_name = "CENTRAL"
        
        # Procura o escritório pelo display name
        for office in offices:
            if office["display"] == escritorio_input:
                office_key = office["key"]
                display_name = office["display"]
                break
        else:
            # Se não encontrou, usa o input normalizado
            office_key = normalize_office_key(escritorio_input)
            display_name = escritorio_input.upper() if escritorio_input else "CENTRAL"
            register_office(office_key, display_name)

        tipo_acao = request.form.get("tipo_acao", "")
        data_fechamento = request.form.get("data_fechamento", "")
        pendencias = request.form.get("pendencias", "")
        numero_processo = request.form.get("numero_processo", "")
        data_protocolo = request.form.get("data_protocolo", "")
        observacoes = request.form.get("observacoes", "")
        captador = request.form.get("captador", "NÃO PAGO")

        now = datetime.utcnow().isoformat()
        
        conn = get_conn()
        c = conn.cursor()
        c.execute("""
            INSERT INTO registros (nome, cpf, escritorio_chave, escritorio_nome, tipo_acao, data_fechamento, pendencias,
                                  numero_processo, data_protocolo, observacoes, captador, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (nome, cpf, f"office_{office_key}", display_name, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, now))
        conn.commit()
        conn.close()
        
        flash("Registro salvo com sucesso.", "success")
        return redirect(url_for("table", office=office_key))
    
    except Exception as e:
        flash(f"Erro ao salvar registro: {str(e)}", "error")
        return redirect(url_for("index"))

# -------------------------
# Table listing + filters + pagination
# -------------------------
@app.route("/table")
@login_required
def table():
    office_param = request.args.get("office", "CENTRAL")
    page = int(request.args.get("page", "1") or 1)
    per_page = int(request.args.get("per_page", "10") or 10)
    if per_page not in (10,20,50,100):
        per_page = 10
    filtro = request.args.get("filtro")
    valor = request.args.get("valor", "").strip()
    data_tipo = request.args.get("data_tipo")
    data_de = request.args.get("data_de")
    data_ate = request.args.get("data_ate")

    offices = list_offices()
    conn = get_conn()
    c = conn.cursor()

    rows = []
    total = 0
    if office_param == "ALL" or office_param == "ALL" or office_param.upper() == "ALL":
        # aggregate from registros
        where = []
        params = []
        if filtro and valor:
            if filtro == "nome":
                where.append("LOWER(nome) LIKE ?")
                params.append(f"%{valor.lower()}%")
            elif filtro == "cpf":
                where.append("cpf LIKE ?")
                params.append(f"%{valor}%")
            elif filtro == "id":
                try:
                    _id = int(valor)
                    where.append("id = ?")
                    params.append(_id)
                except:
                    where.append("1=0")
        if data_tipo in ("data_fechamento", "data_protocolo") and (data_de or data_ate):
            if data_de and data_ate:
                where.append(f"{data_tipo} BETWEEN ? AND ?")
                params.extend([data_de, data_ate])
            elif data_de:
                where.append(f"{data_tipo} >= ?")
                params.append(data_de)
            elif data_ate:
                where.append(f"{data_tipo} <= ?")
                params.append(data_ate)
        where_sql = "WHERE " + " AND ".join(where) if where else ""
        q = f"SELECT * FROM registros {where_sql} ORDER BY id DESC"
        c.execute(q, tuple(params))
        allrows = c.fetchall()
        total = len(allrows)
        start = (page-1)*per_page
        rows = allrows[start:start+per_page]
    else:
        office_key = normalize_office_key(office_param)
        # we store escritorio_chave as "office_<key>" in records; match either
        where = []
        params = []
        where.append("escritorio_chave = ?")
        params.append(f"office_{office_key}")
        if filtro and valor:
            if filtro == "nome":
                where.append("LOWER(nome) LIKE ?")
                params.append(f"%{valor.lower()}%")
            elif filtro == "cpf":
                where.append("cpf LIKE ?")
                params.append(f"%{valor}%")
            elif filtro == "id":
                try:
                    _id = int(valor)
                    where.append("id = ?")
                    params.append(_id)
                except:
                    where.append("1=0")
        if data_tipo in ("data_fechamento", "data_protocolo") and (data_de or data_ate):
            if data_de and data_ate:
                where.append(f"{data_tipo} BETWEEN ? AND ?")
                params.extend([data_de, data_ate])
            elif data_de:
                where.append(f"{data_tipo} >= ?")
                params.append(data_de)
            elif data_ate:
                where.append(f"{data_tipo} <= ?")
                params.append(data_ate)
        where_sql = "WHERE " + " AND ".join(where)
        count_q = f"SELECT COUNT(*) FROM registros {where_sql}"
        try:
            c.execute(count_q, tuple(params))
            total = c.fetchone()[0]
        except:
            total = 0
        total_pages = max(1, (total + per_page -1)//per_page)
        if page < 1: page = 1
        if page > total_pages: page = total_pages
        offset = (page-1)*per_page
        q = f"SELECT * FROM registros {where_sql} ORDER BY id DESC LIMIT ? OFFSET ?"
        c.execute(q, tuple(params + [per_page, offset]))
        rows = c.fetchall()

    conn.close()
    total_pages = max(1, (total + per_page -1)//per_page)
    return render_template("table.html",
                           rows=rows, office=office_param, offices=offices,
                           page=page, per_page=per_page, total=total, total_pages=total_pages,
                           filtro=filtro, valor=valor, data_tipo=data_tipo, data_de=data_de, data_ate=data_ate)

# -------------------------
# Edit / Update record
# -------------------------
@app.route("/edit")
@login_required
def edit():
    registro_id = request.args.get("id")
    office = request.args.get("office", "CENTRAL")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM registros WHERE id=?", (registro_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("Registro não encontrado.", "error")
        return redirect(url_for("table", office=office))
    cliente = {
        "id": row[0], "nome": row[1], "cpf": row[2], "escritorio_nome": row[4], "escritorio_chave": row[3],
        "tipo_acao": row[5], "data_fechamento": row[6], "pendencias": row[7], "numero_processo": row[8],
        "data_protocolo": row[9], "observacoes": row[10], "captador": row[11], "created_at": row[12]
    }
    offices = list_offices()
    return render_template("edit.html", cliente=cliente, office=office, offices=offices)

@app.route("/update", methods=["POST"])
@login_required
def update():
    registro_id = request.form.get("id")
    office_input = request.form.get("escritorio", "").strip()
    # try to map display to key
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT office_key FROM offices WHERE display_name = ?", (office_input.upper(),))
    found = c.fetchone()
    if found:
        office_key = found[0]
        display_name = get_office_display(office_key)
    else:
        office_key = normalize_office_key(office_input) if office_input else normalize_office_key(request.form.get("office","CENTRAL"))
        display_name = office_input.upper() or get_office_display(office_key)
        register_office(office_key, display_name)

    nome = request.form.get("nome")
    cpf = request.form.get("cpf")
    tipo_acao = request.form.get("tipo_acao")
    data_fechamento = request.form.get("data_fechamento")
    pendencias = request.form.get("pendencias")
    numero_processo = request.form.get("numero_processo")
    data_protocolo = request.form.get("data_protocolo")
    observacoes = request.form.get("observacoes")
    captador = request.form.get("captador")

    c.execute("""
        UPDATE registros SET nome=?, cpf=?, escritorio_chave=?, escritorio_nome=?, tipo_acao=?, data_fechamento=?, pendencias=?, numero_processo=?, data_protocolo=?, observacoes=?, captador=?
        WHERE id=?
    """, (nome, cpf, f"office_{office_key}", display_name, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, registro_id))
    conn.commit()
    conn.close()
    flash("Registro atualizado.", "success")
    return redirect(url_for("table", office=office_key))

# -------------------------
# Delete (move to excluidos) - single and batch
# -------------------------
@app.route("/delete", methods=["POST"])
@login_required
def delete():
    registro_id = request.form.get("id")
    office = request.form.get("office", "CENTRAL")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM registros WHERE id=?", (registro_id,))
    row = c.fetchone()
    if row:
        escritorio_nome = row[4] if row[4] else get_office_display(normalize_office_key(office))
        escritorio_chave = row[3] if row[3] else f"office_{normalize_office_key(office)}"
        c.execute("""
            INSERT INTO excluidos (nome, cpf, escritorio_origem, escritorio_origem_chave, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, created_at, data_exclusao)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (row[1], row[2], escritorio_nome, escritorio_chave, row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12], datetime.utcnow().isoformat()))
        c.execute("DELETE FROM registros WHERE id=?", (registro_id,))
        conn.commit()
        flash("Registro excluído.", "success")
    conn.close()
    return redirect(url_for("table", office=office))

@app.route("/delete_selected", methods=["POST"])
@login_required
def delete_selected():
    ids = request.form.getlist("ids")
    office = request.form.get("office", "CENTRAL")
    if not ids:
        flash("Nenhum registro selecionado.", "error")
        return redirect(url_for("table", office=office))
    conn = get_conn()
    c = conn.cursor()
    for registro_id in ids:
        c.execute("SELECT * FROM registros WHERE id=?", (registro_id,))
        row = c.fetchone()
        if not row:
            continue
        escritorio_nome = row[4] if row[4] else get_office_display(normalize_office_key(office))
        escritorio_chave = row[3] if row[3] else f"office_{normalize_office_key(office)}"
        c.execute("""
            INSERT INTO excluidos (nome, cpf, escritorio_origem, escritorio_origem_chave, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, created_at, data_exclusao)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (row[1], row[2], escritorio_nome, escritorio_chave, row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12], datetime.utcnow().isoformat()))
        c.execute("DELETE FROM registros WHERE id=?", (registro_id,))
    conn.commit()
    conn.close()
    flash("Registros excluídos.", "success")
    return redirect(url_for("table", office=office))

# -------------------------
# Excluidos / restore
# -------------------------
@app.route("/excluidos")
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def excluidos():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM excluidos ORDER BY id DESC")
    rows = c.fetchall()
    conn.close()
    offices = list_offices()
    return render_template("excluidos.html", rows=rows, offices=offices)

@app.route("/restore", methods=["POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def restore():
    registro_id = request.form.get("id")
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM excluidos WHERE id=?", (registro_id,))
    row = c.fetchone()
    if row:
        # derive office key from stored origem_chave or display
        origem_chave = row[4]
        origem_display = row[3]
        if origem_chave and origem_chave.startswith("office_"):
            office_key = origem_chave[len("office_"):].upper()
        else:
            office_key = normalize_office_key(origem_display)
        register_office(office_key, origem_display)
        c.execute("""
            INSERT INTO registros (nome, cpf, escritorio_chave, escritorio_nome, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (row[1], row[2], f"office_{office_key}", origem_display, row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12]))
        c.execute("DELETE FROM excluidos WHERE id=?", (registro_id,))
        conn.commit()
        flash("Registro restaurado.", "success")
    conn.close()
    return redirect(url_for("excluidos"))

@app.route("/restore_selected", methods=["POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def restore_selected():
    ids = request.form.getlist("ids")
    conn = get_conn()
    c = conn.cursor()
    for registro_id in ids:
        c.execute("SELECT * FROM excluidos WHERE id=?", (registro_id,))
        row = c.fetchone()
        if not row:
            continue
        origem_chave = row[4]
        origem_display = row[3]
        if origem_chave and origem_chave.startswith("office_"):
            office_key = origem_chave[len("office_"):].upper()
        else:
            office_key = normalize_office_key(origem_display)
        register_office(office_key, origem_display)
        c.execute("""
            INSERT INTO registros (nome, cpf, escritorio_chave, escritorio_nome, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (row[1], row[2], f"office_{office_key}", origem_display, row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12]))
        c.execute("DELETE FROM excluidos WHERE id=?", (registro_id,))
    conn.commit()
    conn.close()
    flash("Registros restaurados.", "success")
    return redirect(url_for("excluidos"))

# Permanent delete
@app.route("/delete_forever", methods=["POST"])
@login_required
@require_roles("ADMIN")
def delete_forever():
    registro_id = request.form.get("id")
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM excluidos WHERE id=?", (registro_id,))
    conn.commit()
    conn.close()
    flash("Registro excluído permanentemente.", "success")
    return redirect(url_for("excluidos"))

@app.route("/delete_forever_selected", methods=["POST"])
@login_required
@require_roles("ADMIN")
def delete_forever_selected():
    ids = request.form.getlist("ids")
    conn = get_conn()
    c = conn.cursor()
    for rid in ids:
        c.execute("DELETE FROM excluidos WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    flash("Registros excluídos permanentemente.", "success")
    return redirect(url_for("excluidos"))

# -------------------------
# Migrate (single & batch)
# -------------------------
@app.route("/migrate", methods=["POST"])
@login_required
def migrate():
    registro_id = request.form.get("id")
    office_current = request.form.get("office_current", "CENTRAL")
    office_target = request.form.get("office_target", "")
    if not office_target:
        flash("Destino inválido.", "error")
        return redirect(url_for("table", office=office_current))
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT * FROM registros WHERE id=?", (registro_id,))
    row = c.fetchone()
    if not row:
        flash("Registro não encontrado.", "error")
        conn.close()
        return redirect(url_for("table", office=office_current))
    target_key = normalize_office_key(office_target)
    target_display = office_target.upper()
    register_office(target_key, target_display)
    c.execute("""
        UPDATE registros SET escritorio_chave=?, escritorio_nome=? WHERE id=?
    """, (f"office_{target_key}", target_display, registro_id))
    conn.commit()
    conn.close()
    flash("Registro movido com sucesso.", "success")
    return redirect(url_for("table", office=target_key))

@app.route("/migrate_selected", methods=["POST"])
@login_required
def migrate_selected():
    ids = request.form.getlist("ids")
    office_current = request.form.get("office_current", "CENTRAL")
    office_target = request.form.get("office_target", "")
    if not ids or not office_target:
        flash("Nada selecionado ou destino inválido.", "error")
        return redirect(url_for("table", office=office_current))
    target_key = normalize_office_key(office_target)
    target_display = office_target.upper()
    register_office(target_key, target_display)
    conn = get_conn()
    c = conn.cursor()
    for registro_id in ids:
        c.execute("UPDATE registros SET escritorio_chave=?, escritorio_nome=? WHERE id=?", (f"office_{target_key}", target_display, registro_id))
    conn.commit()
    conn.close()
    flash("Registros movidos com sucesso.", "success")
    return redirect(url_for("table", office=target_key))

# -------------------------
# Offices management
# -------------------------
@app.route("/offices")
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def offices_page():
    offices = list_offices()
    return render_template("offices.html", offices=offices, offices_raw=offices)

@app.route("/offices/create", methods=["POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def offices_create():
    name = request.form.get("office_name", "").strip()
    if not name:
        flash("Nome inválido.", "error")
        return redirect(url_for("offices_page"))
    key = normalize_office_key(name)
    register_office(key, name.upper())
    flash("Escritório criado.", "success")
    return redirect(url_for("offices_page"))

@app.route("/office/edit/<office_key>", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def office_edit(office_key):
    office_key = normalize_office_key(office_key)
    if request.method == "POST":
        new_display = request.form.get("display_name", "").strip().upper()
        if not new_display:
            flash("Nome inválido.", "error")
            return redirect(url_for("office_edit", office_key=office_key))
        conn = get_conn()
        c = conn.cursor()
        c.execute("UPDATE offices SET display_name=? WHERE office_key=?", (new_display, office_key))
        conn.commit()
        conn.close()
        flash("Escritório atualizado.", "success")
        return redirect(url_for("offices_page"))
    # GET
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT office_key, display_name FROM offices WHERE office_key=?", (office_key,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("Escritório não encontrado.", "error")
        return redirect(url_for("offices_page"))
    office = {"key": row[0], "display": row[1]}
    return render_template("office_edit.html", office=office)

@app.route("/offices/delete", methods=["POST"])
@login_required
@require_roles("ADMIN")
def offices_delete():
    office_key = request.form.get("office_key")
    if not office_key or office_key == "CENTRAL":
        flash("Escritório inválido ou protegido.", "error")
        return redirect(url_for("offices_page"))
    conn = get_conn()
    c = conn.cursor()
    c.execute("DELETE FROM offices WHERE office_key=?", (office_key,))
    conn.commit()
    conn.close()
    flash("Escritório excluído.", "success")
    return redirect(url_for("offices_page"))

# -------------------------
# Users admin
# -------------------------
@app.route("/admin/users")
@login_required
@require_roles("ADMIN")
def admin_users():
    conn = get_conn()
    c = conn.cursor()
    c.execute("SELECT id, username, full_name, role, active, created_at FROM users ORDER BY id DESC")
    rows = c.fetchall()
    users = []
    for r in rows:
        uid = r[0]
        u_offs = get_user_offices(uid)
        users.append({"id": uid, "username": r[1], "full_name": r[2], "role": r[3], "active": r[4], "created_at": r[5], "offices": u_offs})
    conn.close()
    return render_template("admin_users.html", users=users)

@app.route("/admin/users/create", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN")
def admin_users_create():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "OPERADOR")
        offices_sel = request.form.getlist("offices")
        if not username or not password:
            flash("Username e senha são obrigatórios.", "error")
            return redirect(url_for("admin_users_create"))
        pw_hash = generate_password_hash(password)
        now = datetime.utcnow().isoformat()
        conn = get_conn()
        c = conn.cursor()
        try:
            c.execute("INSERT INTO users (username, full_name, password_hash, role, active, created_at) VALUES (?,?,?,?,?,?)",
                      (username, full_name, pw_hash, role, 1, now))
            uid = c.lastrowid
            for ok in offices_sel:
                c.execute("INSERT OR IGNORE INTO user_offices (user_id, office_key) VALUES (?,?)", (uid, ok))
            conn.commit()
            flash("Usuário criado.", "success")
            return redirect(url_for("admin_users"))
        except Exception as e:
            conn.rollback()
            flash("Erro ao criar usuário: " + str(e), "error")
            return redirect(url_for("admin_users_create"))
        finally:
            conn.close()
    offices = list_offices()
    return render_template("admin_users_create.html", offices=offices)

@app.route("/admin/users/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN")
def admin_users_edit(user_id):
    conn = get_conn()
    c = conn.cursor()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "OPERADOR")
        active = 1 if request.form.get("active", "0") in ("1", "true", "on") else 0
        try:
            c.execute("UPDATE users SET full_name=?, role=?, active=? WHERE id=?", (full_name, role, active, user_id))
            conn.commit()
            flash("Usuário atualizado.", "success")
        except Exception as e:
            conn.rollback()
            flash("Erro ao atualizar: " + str(e), "error")
        finally:
            conn.close()
        return redirect(url_for("admin_users"))
    c.execute("SELECT id, username, full_name, role, active FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_users"))
    user = {"id": row[0], "username": row[1], "full_name": row[2], "role": row[3], "active": row[4]}
    offices = list_offices()
    user_offs = get_user_offices(user_id)
    return render_template("admin_users_edit.html", user=user, offices=offices, user_offs=user_offs)

@app.route("/admin/users/offices/<int:user_id>", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN")
def admin_users_offices(user_id):
    if request.method == "POST":
        selected = request.form.getlist("offices")
        conn = get_conn()
        c = conn.cursor()
        try:
            c.execute("DELETE FROM user_offices WHERE user_id=?", (user_id,))
            for ok in selected:
                c.execute("INSERT INTO user_offices (user_id, office_key) VALUES (?,?)", (user_id, ok))
            conn.commit()
            flash("Escritórios atribuídos atualizados.", "success")
        except Exception as e:
            conn.rollback()
            flash("Erro ao atualizar escritórios: " + str(e), "error")
        finally:
            conn.close()
        return redirect(url_for("admin_users"))
    offices = list_offices()
    user_offs = get_user_offices(user_id)
    return render_template("admin_users_offices.html", offices=offices, user_offs=user_offs, user_id=user_id)

@app.route("/admin/users/reset_password/<int:user_id>", methods=["POST"])
@login_required
@require_roles("ADMIN")
def admin_users_reset_password(user_id):
    newpass = request.form.get("new_password", "").strip()
    if not newpass:
        flash("Senha nova obrigatória.", "error")
        return redirect(url_for("admin_users"))
    pw_hash = generate_password_hash(newpass)
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("UPDATE users SET password_hash=? WHERE id=?", (pw_hash, user_id))
        conn.commit()
        flash("Senha redefinida.", "success")
    except Exception as e:
        conn.rollback()
        flash("Erro ao redefinir senha: " + str(e), "error")
    finally:
        conn.close()
    return redirect(url_for("admin_users"))

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
@require_roles("ADMIN")
def admin_users_delete(user_id):
    conn = get_conn()
    c = conn.cursor()
    try:
        c.execute("DELETE FROM user_offices WHERE user_id=?", (user_id,))
        c.execute("DELETE FROM users WHERE id=?", (user_id,))
        conn.commit()
        flash("Usuário excluído.", "success")
    except Exception as e:
        conn.rollback()
        flash("Erro ao excluir usuário: " + str(e), "error")
    finally:
        conn.close()
    return redirect(url_for("admin_users"))

# -------------------------
# Export CSV / PDF
# -------------------------
@app.route("/export/csv")
@login_required
def export_csv():
    office = request.args.get("office", "CENTRAL")
    conn = get_conn()
    c = conn.cursor()
    rows = []
    if office.upper() == "ALL":
        c.execute("SELECT * FROM registros")
        rows = c.fetchall()
    else:
        key = normalize_office_key(office)
        c.execute("SELECT * FROM registros WHERE escritorio_chave=?", (f"office_{key}",))
        rows = c.fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["id","nome","cpf","escritorio_chave","escritorio_nome","tipo_acao","data_fechamento","pendencias","numero_processo","data_protocolo","observacoes","captador","created_at"])
    for r in rows:
        writer.writerow([str(x) for x in r])
    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(mem, as_attachment=True, download_name=f"{office}_export.csv", mimetype="text/csv")

@app.route("/export/pdf")
@login_required
def export_pdf():
    office = request.args.get("office", "CENTRAL")
    conn = get_conn()
    c = conn.cursor()
    rows = []
    if office.upper() == "ALL":
        c.execute("SELECT * FROM registros")
        rows = c.fetchall()
    else:
        key = normalize_office_key(office)
        c.execute("SELECT * FROM registros WHERE escritorio_chave=?", (f"office_{key}",))
        rows = c.fetchall()
    conn.close()
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    y = 750
    p.setFont("Helvetica-Bold", 12)
    p.drawString(40, y, f"Registros - Escritório {office}")
    y -= 24
    p.setFont("Helvetica", 10)
    for r in rows:
        line = " | ".join(str(x) for x in r[1:6])
        p.drawString(20, y, line)
        y -= 14
        if y < 60:
            p.showPage()
            y = 750
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"{office}_export.pdf", mimetype="application/pdf")

# -------------------------
# Error handler for debugging
# -------------------------
import traceback

@app.errorhandler(500)
def internal_error(error):
    return f"Erro 500: {str(error)}<br><br>Traceback:<br>{traceback.format_exc()}", 500

# -------------------------
# Run
# -------------------------
if __name__ == "__main__":
    # ensure DB/tables exist
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
