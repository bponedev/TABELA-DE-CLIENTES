from flask import Blueprint, render_template, request, redirect, url_for, flash, session, current_app
from extensions import get_conn
from werkzeug.security import check_password_hash
from functools import wraps

bp = Blueprint("auth", __name__)

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("auth.login", next=request.path))
        # validate active
        conn = get_conn()
        row = conn.execute("SELECT id, role, active FROM users WHERE id=?", (session["user_id"],)).fetchone()
        conn.close()
        if not row or row["active"] != 1:
            session.clear()
            flash("Sessão inválida.", "error")
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    wrapper.__name__ = f.__name__
    return wrapper

def require_roles(*roles):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("auth.login"))
            conn = get_conn()
            row = conn.execute("SELECT role FROM users WHERE id=?", (session["user_id"],)).fetchone()
            conn.close()
            if not row:
                session.clear()
                return redirect(url_for("auth.login"))
            role = row["role"]
            if role not in roles and role != "ADMIN":
                flash("Sem permissão.", "error")
                return redirect(url_for("registros.index"))
            return f(*args, **kwargs)
        wrapper.__name__ = f.__name__
        return wrapper
    return decorator

@bp.app_context_processor
def inject_user():
    user = None
    if "user_id" in session:
        conn = get_conn()
        row = conn.execute("SELECT id, username, full_name, role, active FROM users WHERE id=?", (session["user_id"],)).fetchone()
        conn.close()
        if row:
            user = {"id": row["id"], "username": row["username"], "full_name": row["full_name"], "role": row["role"], "active": row["active"]}
    return {"current_user": user}

@bp.route("/login", methods=["GET", "POST"])
def login():
    next_page = request.args.get("next") or url_for("registros.index")
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        conn = get_conn()
        row = conn.execute("SELECT id, password_hash, active FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if not row or row["active"] != 1:
            flash("Usuário inválido ou inativo.", "error")
            return render_template("login.html")
        if not check_password_hash(row["password_hash"], password):
            flash("Usuário ou senha incorretos.", "error")
            return render_template("login.html")
        session["user_id"] = row["id"]
        flash("Login efetuado.", "success")
        return redirect(next_page)
    return render_template("login.html")

@bp.route("/logout")
def logout():
    session.clear()
    flash("Desconectado.", "info")
    return redirect(url_for("auth.login"))
