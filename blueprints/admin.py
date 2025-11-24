from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import get_conn
from werkzeug.security import generate_password_hash
from datetime import datetime
from blueprints.auth import login_required, require_roles

bp = Blueprint("admin", __name__, url_prefix="/admin")

@bp.route("/users")
@login_required
@require_roles("ADMIN")
def users():
    conn = get_conn()
    rows = conn.execute("SELECT id, username, full_name, role, active, created_at FROM users ORDER BY id DESC").fetchall()
    users = []
    for r in rows:
        u_offs = conn.execute("SELECT office_key FROM user_offices WHERE user_id=?", (r["id"],)).fetchall()
        users.append({"id": r["id"], "username": r["username"], "full_name": r["full_name"], "role": r["role"], "active": r["active"], "created_at": r["created_at"], "offices": [x["office_key"] for x in u_offs]})
    conn.close()
    return render_template("admin_users.html", users=users)

@bp.route("/users/create", methods=["GET","POST"])
@login_required
@require_roles("ADMIN")
def create_user():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        full_name = request.form.get("full_name", "").strip()
        password = request.form.get("password", "")
        role = request.form.get("role", "OPERADOR")
        offices_sel = request.form.getlist("offices")
        if not username or not password:
            flash("Username e senha são obrigatórios.", "error")
            return redirect(url_for("admin.create_user"))
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
            return redirect(url_for("admin.users"))
        except Exception as e:
            conn.rollback()
            flash("Erro: " + str(e), "error")
            return redirect(url_for("admin.create_user"))
        finally:
            conn.close()
    # GET
    conn = get_conn()
    offrows = conn.execute("SELECT office_key, display_name FROM offices ORDER BY display_name").fetchall()
    conn.close()
    offices = [{"key": r["office_key"], "display": r["display_name"]} for r in offrows]
    return render_template("admin_users_create.html", offices=offices)

@bp.route("/users/edit/<int:user_id>", methods=["GET","POST"])
@login_required
@require_roles("ADMIN")
def edit_user(user_id):
    conn = get_conn()
    c = conn.cursor()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        role = request.form.get("role", "OPERADOR")
        active = 1 if request.form.get("active", "0") in ("1","true","on") else 0
        try:
            c.execute("UPDATE users SET full_name=?, role=?, active=? WHERE id=?", (full_name, role, active, user_id))
            conn.commit()
            flash("Usuário atualizado.", "success")
        except Exception as e:
            conn.rollback()
            flash("Erro: " + str(e), "error")
        finally:
            conn.close()
        return redirect(url_for("admin.users"))
    c.execute("SELECT id, username, full_name, role, active FROM users WHERE id=?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        flash("Usuário não encontrado.", "error")
        return redirect(url_for("admin.users"))
    user = {"id": row["id"], "username": row["username"], "full_name": row["full_name"], "role": row["role"], "active": row["active"]}
    conn = get_conn()
    offrows = conn.execute("SELECT office_key, display_name FROM offices ORDER BY display_name").fetchall()
    conn.close()
    offices = [{"key": r["office_key"], "display": r["display_name"]} for r in offrows]
    user_offs = []
    conn = get_conn()
    rows = conn.execute("SELECT office_key FROM user_offices WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    user_offs = [r["office_key"] for r in rows]
    return render_template("admin_users_edit.html", user=user, offices=offices, user_offs=user_offs)

@bp.route("/users/offices/<int:user_id>", methods=["GET","POST"])
@login_required
@require_roles("ADMIN")
def user_offices(user_id):
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
            flash("Erro: "+str(e), "error")
        finally:
            conn.close()
        return redirect(url_for("admin.users"))
    conn = get_conn()
    offrows = conn.execute("SELECT office_key, display_name FROM offices ORDER BY display_name").fetchall()
    offs = [{"key": r["office_key"], "display": r["display_name"]} for r in offrows]
    rows = conn.execute("SELECT office_key FROM user_offices WHERE user_id=?", (user_id,)).fetchall()
    conn.close()
    assigned = [r["office_key"] for r in rows]
    return render_template("admin_users_offices.html", offices=offs, assigned=assigned, user={"id": user_id})
