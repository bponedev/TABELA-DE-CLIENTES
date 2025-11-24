from flask import Blueprint, render_template, request, redirect, url_for, flash
from extensions import get_conn
import db_helpers as dbh
from blueprints.auth import login_required, require_roles

bp = Blueprint("offices", __name__, url_prefix="/offices")

@bp.route("/")
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def offices_page():
    conn = get_conn()
    rows = conn.execute("SELECT office_key, display_name FROM offices ORDER BY display_name").fetchall()
    conn.close()
    offices = [{"key": r["office_key"], "display": r["display_name"]} for r in rows]
    return render_template("offices.html", offices=offices)

@bp.route("/create", methods=["POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def create():
    name = request.form.get("office_name", "").strip()
    if not name:
        flash("Nome inválido.", "error")
        return redirect(url_for("offices.offices_page"))
    key = dbh.normalize_office_key(name)
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (key, name.upper()))
    conn.commit()
    conn.close()
    flash("Escritório criado.", "success")
    return redirect(url_for("offices.offices_page"))

@bp.route("/edit/<office_key>", methods=["GET","POST"])
@login_required
@require_roles("ADMIN", "SUPERVISOR")
def edit_office(office_key):
    office_key = dbh.normalize_office_key(office_key)
    conn = get_conn()
    if request.method == "POST":
        new_display = request.form.get("display_name", "").strip().upper()
        if not new_display:
            flash("Nome inválido.", "error")
            return redirect(url_for("offices.edit_office", office_key=office_key))
        conn.execute("UPDATE offices SET display_name=? WHERE office_key=?", (new_display, office_key))
        conn.commit()
        conn.close()
        flash("Escritório atualizado.", "success")
        return redirect(url_for("offices.offices_page"))
    row = conn.execute("SELECT office_key, display_name FROM offices WHERE office_key=?", (office_key,)).fetchone()
    conn.close()
    if not row:
        flash("Escritório não encontrado.", "error")
        return redirect(url_for("offices.offices_page"))
    office = {"key": row["office_key"], "display": row["display_name"]}
    return render_template("office_edit.html", office=office)

@bp.route("/delete", methods=["POST"])
@login_required
@require_roles("ADMIN")
def delete():
    office_key = request.form.get("office_key")
    if not office_key or office_key == "CENTRAL":
        flash("Escritório inválido/protegido.", "error")
        return redirect(url_for("offices.offices_page"))
    conn = get_conn()
    conn.execute("DELETE FROM offices WHERE office_key=?", (office_key,))
    conn.commit()
    conn.close()
    flash("Escritório excluído.", "success")
    return redirect(url_for("offices.offices_page"))
