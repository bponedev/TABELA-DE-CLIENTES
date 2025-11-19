import os
import sqlite3
import re
import io
import csv
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, session, send_file
)
from werkzeug.security import generate_password_hash, check_password_hash
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import letter


# ===============================================================
# CONFIG
# ===============================================================

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET", "troque_para_uma_chave_secreta_segura")


# ===============================================================
# DATABASE
# ===============================================================

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    c = conn.cursor()

    # registros principais
    c.execute("""
        CREATE TABLE IF NOT EXISTS registros (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            cpf TEXT,
            escritorio_dono TEXT,
            escritorio_dono_chave TEXT,
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

    # registros excluídos
    c.execute("""
        CREATE TABLE IF NOT EXISTS excluidos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            nome TEXT,
            cpf TEXT,
            escritorio_dono TEXT,
            escritorio_dono_chave TEXT,
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

    # escritórios
    c.execute("""
        CREATE TABLE IF NOT EXISTS offices (
            office_key TEXT PRIMARY KEY,
            display_name TEXT
        )
    """)

    # pivot registro_escritorios_vinculados
    c.execute("""
        CREATE TABLE IF NOT EXISTS registro_offices (
            registro_id INTEGER,
            office_key TEXT,
            PRIMARY KEY (registro_id, office_key)
        )
    """)

    # tags
    c.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    # pivot registro_tags
    c.execute("""
        CREATE TABLE IF NOT EXISTS registro_tags (
            registro_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY (registro_id, tag_id)
        )
    """)

    # users
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

    # usuários vinculados a escritórios
    c.execute("""
        CREATE TABLE IF NOT EXISTS user_offices (
            user_id INTEGER,
            office_key TEXT,
            PRIMARY KEY (user_id, office_key)
        )
    """)

    # Central sempre existe
    c.execute("""
        INSERT OR IGNORE INTO offices (office_key, display_name)
        VALUES ('CENTRAL', 'CENTRAL')
    """)

    # Admin padrão
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        c.execute("""
            INSERT INTO users (username, full_name, password_hash, role, active, created_at)
            VALUES (?,?,?,?,?,?)
        """, (
            "admin",
            "Administrador",
            generate_password_hash("admin"),
            "ADMIN",
            1,
            datetime.utcnow().isoformat()
        ))

    conn.commit()
    conn.close()


init_db()


# ===============================================================
# AUX FUNCTIONS
# ===============================================================

def normalize_office_key(name):
    if not name:
        return "CENTRAL"
    s = name.strip().upper()
    s = s.replace(" ", "_")
    s = re.sub(r"[^A-Z0-9_]", "", s)
    return s


def register_office(office_key, display_name):
    conn = get_conn()
    conn.execute("""
        INSERT OR IGNORE INTO offices (office_key, display_name)
        VALUES (?,?)
    """, (office_key, display_name.upper()))
    conn.commit()
    conn.close()


def list_offices():
    conn = get_conn()
    rows = conn.execute("SELECT office_key, display_name FROM offices ORDER BY display_name").fetchall()
    conn.close()
    return [{"key": r["office_key"], "display": r["display_name"]} for r in rows]


def get_office_display(key):
    conn = get_conn()
    row = conn.execute("SELECT display_name FROM offices WHERE office_key=?", (key,)).fetchone()
    conn.close()
    return row["display_name"] if row else key


# TAGS -----------------------------------------------------------

def ensure_tag(name):
    name = name.strip().upper()
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (name,))
    row = conn.execute("SELECT id FROM tags WHERE name=?", (name,)).fetchone()
    conn.commit()
    conn.close()
    return row["id"]


def get_tags_for_registro(registro_id):
    conn = get_conn()
    rows = conn.execute("""
        SELECT t.name FROM tags t 
        JOIN registro_tags rt ON t.id = rt.tag_id
        WHERE rt.registro_id=?
    """, (registro_id,)).fetchall()
    conn.close()
    return [r["name"] for r in rows]


# AUTH -----------------------------------------------------------

def get_user(uid):
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    conn.close()
    return row


def get_user_offices(uid):
    conn = get_conn()
    rows = conn.execute("SELECT office_key FROM user_offices WHERE user_id=?", (uid,)).fetchall()
    conn.close()
    return [r["office_key"] for r in rows]


def login_required(f):
    @wraps(f)
    def wrap(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login", next=request.path))

        user = get_user(session["user_id"])
        if not user or user["active"] != 1:
            session.clear()
            return redirect(url_for("login"))

        return f(*args, **kwargs)
    return wrap


def require_roles(*roles):
    def decorator(f):
        @wraps(f)
        def wrap(*args, **kwargs):
            user = get_user(session["user_id"])
            if user["role"] not in roles and user["role"] != "ADMIN":
                flash("Sem permissão.", "error")
                return redirect(url_for("index"))
            return f(*args, **kwargs)
        return wrap
    return decorator


@app.context_processor
def inject_user():
    if "user_id" in session:
        return {"current_user": get_user(session["user_id"])}
    return {"current_user": None}


# ===============================================================
# LOGIN / LOGOUT
# ===============================================================

@app.route("/login", methods=["GET", "POST"])
def login():
    next_page = request.args.get("next", url_for("index"))

    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]

        conn = get_conn()
        row = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()

        if not row or not check_password_hash(row["password_hash"], password):
            flash("Usuário ou senha inválidos.", "error")
            return render_template("login.html")

        session["user_id"] = row["id"]
        return redirect(next_page)

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ===============================================================
# INDEX
# ===============================================================

@app.route("/")
@login_required
def index():
    return render_template("index.html", offices=list_offices())


# ===============================================================
# CRIAR REGISTRO
# ===============================================================

@app.route("/submit", methods=["POST"])
@login_required
def submit():
    nome = request.form.get("nome")
    cpf = request.form.get("cpf")

    dono_display = request.form.get("escritorio_dono")
    dono_key = normalize_office_key(dono_display)
    register_office(dono_key, dono_display)

    tipo_acao = request.form.get("tipo_acao")
    data_fechamento = request.form.get("data_fechamento")
    pendencias = request.form.get("pendencias")
    numero_processo = request.form.get("numero_processo")
    data_protocolo = request.form.get("data_protocolo")
    observacoes = request.form.get("observacoes")
    captador = request.form.get("captador")

    raw_tags = request.form.get("tags", "")
    tags_list = [t.strip() for t in raw_tags.split(",") if t.strip()]

    offices_linked = request.form.getlist("offices_linked")

    conn = get_conn()
    conn.execute("""
        INSERT INTO registros (
            nome, cpf, escritorio_dono, escritorio_dono_chave,
            tipo_acao, data_fechamento, pendencias, numero_processo,
            data_protocolo, observacoes, captador, created_at
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        nome, cpf, dono_display.upper(), dono_key, tipo_acao,
        data_fechamento, pendencias, numero_processo,
        data_protocolo, observacoes, captador,
        datetime.utcnow().isoformat()
    ))

    registro_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

    for t in tags_list:
        tid = ensure_tag(t)
        conn.execute("INSERT INTO registro_tags (registro_id, tag_id) VALUES (?,?)", (registro_id, tid))

    for ok in offices_linked:
        key = normalize_office_key(ok)
        register_office(key, ok)
        conn.execute("""
            INSERT OR IGNORE INTO registro_offices (registro_id, office_key)
            VALUES (?,?)
        """, (registro_id, key))

    conn.commit()
    conn.close()

    flash("Registro criado!", "success")
    return redirect(url_for("table", office=dono_key))


# ===============================================================
# TABELA PRINCIPAL
# ===============================================================

@app.route("/table")
@login_required
def table():
    office = request.args.get("office", "CENTRAL").upper()
    filter_tag = request.args.get("tag")

    conn = get_conn()

    if office == "ALL":
        rows = conn.execute("SELECT * FROM registros ORDER BY id DESC").fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM registros WHERE escritorio_dono_chave=? ORDER BY id DESC
        """, (office,)).fetchall()

    registros = []
    for r in rows:
        tags = get_tags_for_registro(r["id"])

        if filter_tag and filter_tag.upper() not in tags:
            continue

        offs = conn.execute("""
            SELECT office_key FROM registro_offices WHERE registro_id=?
        """, (r["id"],)).fetchall()

        registros.append({
            "data": r,
            "tags": tags,
            "offices": [o["office_key"] for o in offs]
        })

    conn.close()

    return render_template(
        "table.html",
        registros=registros,
        offices=list_offices(),
        office=office,
        filter_tag=filter_tag
    )


# ===============================================================
# EDITAR
# ===============================================================

@app.route("/edit")
@login_required
def edit():
    rid = request.args.get("id")

    conn = get_conn()
    row = conn.execute("SELECT * FROM registros WHERE id=?", (rid,)).fetchone()

    if not row:
        flash("Registro não encontrado.", "error")
        conn.close()
        return redirect(url_for("index"))

    tags = get_tags_for_registro(rid)

    offices_linked = conn.execute("""
        SELECT office_key FROM registro_offices WHERE registro_id=?
    """, (rid,)).fetchall()

    conn.close()

    return render_template(
        "edit.html",
        cliente=row,
        tags=tags,
        offices_linked=[o["office_key"] for o in offices_linked],
        offices=list_offices()
    )


@app.route("/update", methods=["POST"])
@login_required
def update():
    rid = request.form.get("id")

    dono_display = request.form.get("escritorio_dono")
    dono_key = normalize_office_key(dono_display)
    register_office(dono_key, dono_display)

    nome = request.form.get("nome")
    cpf = request.form.get("cpf")
    tipo_acao = request.form.get("tipo_acao")
    data_fechamento = request.form.get("data_fechamento")
    pendencias = request.form.get("pendencias")
    numero_processo = request.form.get("numero_processo")
    data_protocolo = request.form.get("data_protocolo")
    observacoes = request.form.get("observacoes")
    captador = request.form.get("captador")

    raw_tags = request.form.get("tags", "")
    tags_list = [t.strip().upper() for t in raw_tags.split(",") if t.strip()]

    offices_linked = request.form.getlist("offices_linked")

    conn = get_conn()
    conn.execute("""
        UPDATE registros SET
            nome=?, cpf=?, escritorio_dono=?, escritorio_dono_chave=?,
            tipo_acao=?, data_fechamento=?, pendencias=?,
            numero_processo=?, data_protocolo=?, observacoes=?, captador=?
        WHERE id=?
    """, (
        nome, cpf, dono_display.upper(), dono_key, tipo_acao,
        data_fechamento, pendencias, numero_processo, data_protocolo,
        observacoes, captador, rid
    ))

    conn.execute("DELETE FROM registro_tags WHERE registro_id=?", (rid,))
    for t in tags_list:
        tid = ensure_tag(t)
        conn.execute("INSERT INTO registro_tags (registro_id, tag_id) VALUES (?,?)", (rid, tid))

    conn.execute("DELETE FROM registro_offices WHERE registro_id=?", (rid,))
    for ok in offices_linked:
        key = normalize_office_key(ok)
        register_office(key, ok)
        conn.execute("INSERT INTO registro_offices (registro_id, office_key) VALUES (?,?)", (rid, key))

    conn.commit()
    conn.close()

    flash("Registro atualizado!", "success")
    return redirect(url_for("table", office=dono_key))


# ===============================================================
# EXCLUIR
# ===============================================================

@app.route("/delete", methods=["POST"])
@login_required
def delete():
    rid = request.form.get("id")

    conn = get_conn()
    row = conn.execute("SELECT * FROM registros WHERE id=?", (rid,)).fetchone()

    if not row:
        flash("Registro não encontrado.", "error")
        conn.close()
        return redirect(url_for("index"))

    conn.execute("""
        INSERT INTO excluidos (
            nome, cpf, escritorio_dono, escritorio_dono_chave,
            tipo_acao, data_fechamento, pendencias,
            numero_processo, data_protocolo, observacoes,
            captador, created_at, data_exclusao
        )
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        row["nome"], row["cpf"],
        row["escritorio_dono"], row["escritorio_dono_chave"],
        row["tipo_acao"], row["data_fechamento"], row["pendencias"],
        row["numero_processo"], row["data_protocolo"], row["observacoes"],
        row["captador"], row["created_at"],
        datetime.utcnow().isoformat()
    ))

    conn.execute("DELETE FROM registros WHERE id=?", (rid,))
    conn.commit()
    conn.close()

    flash("Registro excluído.", "success")
    return redirect(url_for("table"))


# ===============================================================
# EXCLUÍDOS — LISTAR
# ===============================================================

@app.route("/excluidos")
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def excluidos():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM excluidos ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("excluidos.html", rows=rows)


# ===============================================================
# RESTAURAR
# ===============================================================

@app.route("/restore", methods=["POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def restore():
    rid = request.form.get("id")

    conn = get_conn()
    row = conn.execute("SELECT * FROM excluidos WHERE id=?", (rid,)).fetchone()

    if not row:
        flash("Registro não encontrado.", "error")
        conn.close()
        return redirect(url_for("excluidos"))

    conn.execute("""
        INSERT INTO registros (
            nome, cpf, escritorio_dono, escritorio_dono_chave,
            tipo_acao, data_fechamento, pendencias,
            numero_processo, data_protocolo, observacoes,
            captador, created_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        row["nome"], row["cpf"],
        row["escritorio_dono"], row["escritorio_dono_chave"],
        row["tipo_acao"], row["data_fechamento"], row["pendencias"],
        row["numero_processo"], row["data_protocolo"], row["observacoes"],
        row["captador"], row["created_at"]
    ))

    conn.execute("DELETE FROM excluidos WHERE id=?", (rid,))
    conn.commit()
    conn.close()

    flash("Registro restaurado!", "success")
    return redirect(url_for("excluidos"))


# ===============================================================
# EXCLUIR DEFINITIVO
# ===============================================================

@app.route("/delete_forever", methods=["POST"])
@login_required
@require_roles("ADMIN")
def delete_forever():
    rid = request.form.get("id")
    conn = get_conn()
    conn.execute("DELETE FROM excluidos WHERE id=?", (rid,))
    conn.commit()
    conn.close()

    flash("Registro excluído permanentemente!", "success")
    return redirect(url_for("excluidos"))


# ===============================================================
# OFFICES — LISTAR
# ===============================================================

@app.route("/offices")
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def offices_page():
    return render_template("offices.html", offices=list_offices())


# ===============================================================
# OFFICES — CRIAR
# ===============================================================

@app.route("/offices/create", methods=["POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def offices_create():
    name = request.form.get("office_name")
    key = normalize_office_key(name)
    register_office(key, name.upper())

    flash("Escritório criado.", "success")
    return redirect(url_for("offices_page"))


# ===============================================================
# OFFICE EDIT
# ===============================================================

@app.route("/office/edit/<office_key>", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def office_edit(office_key):
    office_key = normalize_office_key(office_key)

    if request.method == "POST":
        new_name = request.form.get("display_name").strip().upper()
        conn = get_conn()
        conn.execute("UPDATE offices SET display_name=? WHERE office_key=?", (new_name, office_key))
        conn.commit()
        conn.close()

        flash("Atualizado!", "success")
        return redirect(url_for("offices_page"))

    conn = get_conn()
    row = conn.execute("""
        SELECT office_key, display_name FROM offices WHERE office_key=?
    """, (office_key,)).fetchone()
    conn.close()

    if not row:
        flash("Escritório não existe.", "error")
        return redirect(url_for("offices_page"))

    return render_template("office_edit.html", office=row)


# ===============================================================
# OFFICE DELETE
# ===============================================================

@app.route("/offices/delete", methods=["POST"])
@login_required
@require_roles("ADMIN")
def offices_delete():
    key = request.form.get("office_key")

    if key == "CENTRAL":
        flash("CENTRAL não pode ser excluído.", "error")
        return redirect(url_for("offices_page"))

    conn = get_conn()
    conn.execute("DELETE FROM offices WHERE office_key=?", (key,))
    conn.commit()
    conn.close()

    flash("Escritório removido.", "success")
    return redirect(url_for("offices_page"))


# ===============================================================
# USERS — LISTAR
# ===============================================================

@app.route("/admin/users")
@login_required
@require_roles("ADMIN")
def admin_users():
    conn = get_conn()
    rows = conn.execute("""
        SELECT id, username, full_name, role, active, created_at
        FROM users ORDER BY id DESC
    """).fetchall()

    users = []
    for r in rows:
        offs = conn.execute("""
            SELECT office_key FROM user_offices WHERE user_id=?
        """, (r["id"],)).fetchall()

        users.append({
            "id": r["id"],
            "username": r["username"],
            "full_name": r["full_name"],
            "role": r["role"],
            "active": r["active"],
            "created_at": r["created_at"],
            "offices": [o["office_key"] for o in offs]
        })

    conn.close()
    return render_template("admin_users.html", users=users)


# ===============================================================
# USER CREATE
# ===============================================================

@app.route("/admin/users/create", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN")
def admin_users_create():
    if request.method == "POST":
        username = request.form.get("username").strip()
        full_name = request.form.get("full_name")
        password = request.form.get("password")
        role = request.form.get("role")
        offices_sel = request.form.getlist("offices")

        if not username or not password:
            flash("Username e senha obrigatórios.", "error")
            return redirect(url_for("admin_users_create"))

        conn = get_conn()

        try:
            conn.execute("""
                INSERT INTO users (username, full_name, password_hash, role, active, created_at)
                VALUES (?,?,?,?,?,?)
            """, (
                username, full_name,
                generate_password_hash(password),
                role, 1,
                datetime.utcnow().isoformat()
            ))

            uid = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            for ok in offices_sel:
                conn.execute("""
                    INSERT INTO user_offices (user_id, office_key) VALUES (?,?)
                """, (uid, ok))

            conn.commit()
            flash("Usuário criado.", "success")
            return redirect(url_for("admin_users"))

        except Exception as e:
            conn.rollback()
            flash(f"Erro: {e}", "error")

        finally:
            conn.close()

    return render_template("admin_users_create.html", offices=list_offices())


# ===============================================================
# USER EDIT
# ===============================================================

@app.route("/admin/users/edit/<int:user_id>", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN")
def admin_users_edit(user_id):
    conn = get_conn()

    if request.method == "POST":
        full_name = request.form.get("full_name")
        role = request.form.get("role")
        active = 1 if request.form.get("active") == "1" else 0

        conn.execute("""
            UPDATE users SET full_name=?, role=?, active=? WHERE id=?
        """, (full_name, role, active, user_id))

        conn.commit()
        conn.close()

        flash("Usuário atualizado.", "success")
        return redirect(url_for("admin_users"))

    user = conn.execute("SELECT * FROM users WHERE id=?", (user_id,)).fetchone()
    conn.close()

    if not user:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin_users"))

    return render_template("admin_users_edit.html", user=user)


# ===============================================================
# USER OFFICES
# ===============================================================

@app.route("/admin/users/offices/<int:user_id>", methods=["GET", "POST"])
@login_required
@require_roles("ADMIN")
def admin_users_offices(user_id):
    if request.method == "POST":
        offices_sel = request.form.getlist("offices")

        conn = get_conn()
        conn.execute("DELETE FROM user_offices WHERE user_id=?", (user_id,))

        for ok in offices_sel:
            conn.execute("""
                INSERT INTO user_offices (user_id, office_key)
                VALUES (?,?)
            """, (user_id, ok))

        conn.commit()
        conn.close()

        flash("Escritórios atribuídos!", "success")
        return redirect(url_for("admin_users"))

    offices = list_offices()
    user_offs = get_user_offices(user_id)

    return render_template("admin_users_offices.html",
                           offices=offices,
                           user_offs=user_offs,
                           user_id=user_id)


# ===============================================================
# RESET PASSWORD
# ===============================================================

@app.route("/admin/users/reset_password/<int:user_id>", methods=["POST"])
@login_required
@require_roles("ADMIN")
def admin_users_reset_password(user_id):
    new_password = request.form.get("new_password")

    if not new_password:
        flash("Senha não pode ser vazia.", "error")
        return redirect(url_for("admin_users"))

    conn = get_conn()
    conn.execute("UPDATE users SET password_hash=? WHERE id=?",
                 (generate_password_hash(new_password), user_id))
    conn.commit()
    conn.close()

    flash("Senha redefinida!", "success")
    return redirect(url_for("admin_users"))


# ===============================================================
# DELETE USER
# ===============================================================

@app.route("/admin/users/delete/<int:user_id>", methods=["POST"])
@login_required
@require_roles("ADMIN")
def admin_users_delete(user_id):
    conn = get_conn()
    conn.execute("DELETE FROM user_offices WHERE user_id=?", (user_id,))
    conn.execute("DELETE FROM users WHERE id=?", (user_id,))
    conn.commit()
    conn.close()

    flash("Usuário excluído!", "success")
    return redirect(url_for("admin_users"))


# ===============================================================
# EXPORT CSV
# ===============================================================

@app.route("/export/csv")
@login_required
def export_csv():
    office = request.args.get("office", "CENTRAL").upper()

    conn = get_conn()

    if office == "ALL":
        rows = conn.execute("SELECT * FROM registros").fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM registros WHERE escritorio_dono_chave=?
        """, (office,)).fetchall()

    conn.close()

    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")

    writer.writerow([
        "ID", "Nome", "CPF", "Escritório Dono",
        "Tipo Ação", "Data Fechamento", "Pendências",
        "Nº Processo", "Data Protocolo", "Observações", "Captador"
    ])

    for row in rows:
        writer.writerow([
            row["id"], row["nome"], row["cpf"],
            row["escritorio_dono"], row["tipo_acao"],
            row["data_fechamento"], row["pendencias"],
            row["numero_processo"], row["data_protocolo"],
            row["observacoes"], row["captador"]
        ])

    mem = io.BytesIO(output.getvalue().encode("utf-8"))
    return send_file(
        mem,
        as_attachment=True,
        download_name=f"registros_{office}.csv",
        mimetype="text/csv"
    )


# ===============================================================
# EXPORT PDF
# ===============================================================

@app.route("/export/pdf")
@login_required
def export_pdf():
    office = request.args.get("office", "CENTRAL").upper()

    conn = get_conn()

    if office == "ALL":
        rows = conn.execute("SELECT * FROM registros").fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM registros WHERE escritorio_dono_chave=?
        """, (office,)).fetchall()

    conn.close()

    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=letter)
    width, height = letter

    p.setFont("Helvetica-Bold", 16)
    p.drawString(100, height - 50, f"Relatório - Escritório Dono: {office}")

    y = height - 90
    p.setFont("Helvetica", 10)

    for row in rows:
        if y < 60:
            p.showPage()
            p.setFont("Helvetica", 10)
            y = height - 50

        p.drawString(50, y, f"ID: {row['id']} | Nome: {row['nome']} | CPF: {row['cpf']}")
        y -= 15
        p.drawString(50, y, f"Escritório Dono: {row['escritorio_dono']} | Tipo: {row['tipo_acao']}")
        y -= 15
        p.drawString(50, y, f"Fechamento: {row['data_fechamento']} | Captador: {row['captador']}")
        y -= 25

    p.save()
    buffer.seek(0)

    return send_file(
        buffer,
        as_attachment=True,
        download_name=f"registros_{office}.pdf",
        mimetype="application/pdf"
    )


# ===============================================================
# RUN
# ===============================================================

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5000)
