from flask import Blueprint, render_template, request, redirect, url_for, flash, session, send_file
from extensions import get_conn
import db_helpers as dbh
from datetime import datetime
import io, csv
from reportlab.pdfgen import canvas
from functools import wraps
from blueprints.auth import login_required, require_roles

bp = Blueprint("registros", __name__)

@bp.route("/")
@login_required
def index():
    offices = list_offices_local()
    return render_template("index.html", offices=offices)

def list_offices_local():
    conn = get_conn()
    rows = conn.execute("SELECT office_key, display_name FROM offices ORDER BY display_name").fetchall()
    conn.close()
    return [{"key": r["office_key"], "display": r["display_name"]} for r in rows]

@bp.route("/submit", methods=["POST"])
@login_required
def submit():
    try:
        nome = request.form.get("nome", "").strip()
        cpf = request.form.get("cpf", "").strip()
        # desk owner: field name may be 'escritorio' or 'escritorio_dono' depending on template; prefer dono
        escritorio_raw = request.form.get("escritorio_dono") or request.form.get("escritorio") or "CENTRAL"
        dono_key = dbh.normalize_office_key(escritorio_raw)
        dono_display = escritorio_raw.upper()
        # register office
        conn = get_conn()
        conn.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (dono_key, dono_display))
        tipo_acao = request.form.get("tipo_acao", "")
        data_fechamento = request.form.get("data_fechamento", "")
        pendencias = request.form.get("pendencias", "")
        numero_processo = request.form.get("numero_processo", "")
        data_protocolo = request.form.get("data_protocolo", "")
        observacoes = request.form.get("observacoes", "")
        captador = request.form.get("captador", "")
        now = datetime.utcnow().isoformat()
        c = conn.cursor()
        c.execute("""
            INSERT INTO registros (nome, cpf, escritorio_dono, escritorio_dono_chave, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        """, (nome, cpf, dono_display, dono_key, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, now))
        registro_id = c.lastrowid

        # tags (free text, comma separated) -> create tag rows and pivot
        raw_tags = request.form.get("tags", "")
        tags = [t.strip().upper() for t in raw_tags.split(",") if t.strip()]
        for t in tags:
            c.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t,))
            tid = c.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()["id"]
            c.execute("INSERT OR IGNORE INTO registro_tags (registro_id, tag_id) VALUES (?,?)", (registro_id, tid))

        # offices linked: name list from form (checkboxes or multiselect)
        offices_linked = request.form.getlist("offices_linked") or request.form.getlist("offices")
        for ok in offices_linked:
            key = dbh.normalize_office_key(ok)
            conn.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (key, ok.upper()))
            conn.execute("INSERT OR IGNORE INTO registro_offices (registro_id, office_key) VALUES (?,?)", (registro_id, key))

        conn.commit()
        conn.close()
        flash("Registro salvo!", "success")
        return redirect(url_for("registros.table", office=dono_key))
    except Exception as e:
        flash("Erro ao salvar: " + str(e), "error")
        return redirect(url_for("registros.index"))

@bp.route("/table")
@login_required
def table():
    office = request.args.get("office", "CENTRAL")
    filter_tag = request.args.get("tag")
    conn = get_conn()
    rows = []
    if office.upper() == "ALL":
        rows = conn.execute("SELECT * FROM registros ORDER BY id DESC").fetchall()
    else:
        key = dbh.normalize_office_key(office)
        rows = conn.execute("SELECT * FROM registros WHERE escritorio_dono_chave = ? ORDER BY id DESC", (key,)).fetchall()
    registros = []
    for r in rows:
        # tags
        tags = conn.execute("SELECT t.name FROM tags t JOIN registro_tags rt ON rt.tag_id=t.id WHERE rt.registro_id=?", (r["id"],)).fetchall()
        tags = [t["name"] for t in tags]
        if filter_tag and filter_tag.strip().upper() not in tags:
            continue
        # linked offices
        offs = conn.execute("SELECT office_key FROM registro_offices WHERE registro_id=?", (r["id"],)).fetchall()
        registros.append({"data": r, "tags": tags, "offices": [o["office_key"] for o in offs]})
    conn.close()
    offices = list_offices_local()
    return render_template("table.html", registros=registros, offices=offices, office=office, filter_tag=filter_tag)

@bp.route("/edit")
@login_required
def edit():
    rid = request.args.get("id")
    conn = get_conn()
    row = conn.execute("SELECT * FROM registros WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        flash("Registro não encontrado.", "error")
        return redirect(url_for("registros.index"))
    tags_rows = conn.execute("SELECT t.name FROM tags t JOIN registro_tags rt ON rt.tag_id=t.id WHERE rt.registro_id=?", (rid,)).fetchall()
    tags = [t["name"] for t in tags_rows]
    linked = conn.execute("SELECT office_key FROM registro_offices WHERE registro_id=?", (rid,)).fetchall()
    linked_keys = [l["office_key"] for l in linked]
    offices = list_offices_local()
    conn.close()
    return render_template("edit.html", cliente=row, tags=tags, offices_linked=linked_keys, offices=offices)

@bp.route("/update", methods=["POST"])
@login_required
def update():
    rid = request.form.get("id")
    dono_raw = request.form.get("escritorio_dono") or request.form.get("escritorio") or ""
    dono_key = dbh.normalize_office_key(dono_raw)
    dono_display = dono_raw.upper() if dono_raw else dbh.normalize_office_key(dono_raw)
    conn = get_conn()
    conn.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (dono_key, dono_display))
    # update main
    conn.execute("""
        UPDATE registros SET nome=?, cpf=?, escritorio_dono=?, escritorio_dono_chave=?, tipo_acao=?, data_fechamento=?, pendencias=?, numero_processo=?, data_protocolo=?, observacoes=?, captador=?
        WHERE id=?
    """, (
        request.form.get("nome"),
        request.form.get("cpf"),
        dono_display,
        dono_key,
        request.form.get("tipo_acao"),
        request.form.get("data_fechamento"),
        request.form.get("pendencias"),
        request.form.get("numero_processo"),
        request.form.get("data_protocolo"),
        request.form.get("observacoes"),
        request.form.get("captador"),
        rid
    ))
    # tags
    conn.execute("DELETE FROM registro_tags WHERE registro_id=?", (rid,))
    raw_tags = request.form.get("tags", "")
    tags = [t.strip().upper() for t in raw_tags.split(",") if t.strip()]
    for t in tags:
        conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (t,))
        tid = conn.execute("SELECT id FROM tags WHERE name=?", (t,)).fetchone()["id"]
        conn.execute("INSERT OR IGNORE INTO registro_tags (registro_id, tag_id) VALUES (?,?)", (rid, tid))
    # linked offices
    conn.execute("DELETE FROM registro_offices WHERE registro_id=?", (rid,))
    offices_linked = request.form.getlist("offices_linked") or request.form.getlist("offices")
    for ok in offices_linked:
        key = dbh.normalize_office_key(ok)
        conn.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (key, ok.upper()))
        conn.execute("INSERT OR IGNORE INTO registro_offices (registro_id, office_key) VALUES (?,?)", (rid, key))
    conn.commit()
    conn.close()
    flash("Registro atualizado!", "success")
    return redirect(url_for("registros.table", office=dono_key))

@bp.route("/delete", methods=["POST"])
@login_required
def delete():
    rid = request.form.get("id")
    office = request.form.get("office", "CENTRAL")
    conn = get_conn()
    row = conn.execute("SELECT * FROM registros WHERE id=?", (rid,)).fetchone()
    if not row:
        conn.close()
        flash("Registro não encontrado.", "error")
        return redirect(url_for("registros.table", office=office))
    conn.execute("""
        INSERT INTO excluidos (nome, cpf, escritorio_origem, escritorio_origem_chave, tipo_acao, data_fechamento, pendencias, numero_processo, data_protocolo, observacoes, captador, created_at, data_exclusao)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (row["nome"], row["cpf"], row["escritorio_dono"], row["escritorio_dono_chave"], row["tipo_acao"], row["data_fechamento"], row["pendencias"], row["numero_processo"], row["data_protocolo"], row["observacoes"], row["captador"], row["created_at"], datetime.utcnow().isoformat()))
    conn.execute("DELETE FROM registros WHERE id=?", (rid,))
    conn.commit()
    conn.close()
    flash("Registro excluído.", "success")
    return redirect(url_for("registros.table", office=office))

@bp.route("/export/csv")
@login_required
def export_csv():
    office = request.args.get("office", "CENTRAL")
    conn = get_conn()
    if office.upper() == "ALL":
        rows = conn.execute("SELECT * FROM registros").fetchall()
    else:
        key = dbh.normalize_office_key(office)
        rows = conn.execute("SELECT * FROM registros WHERE escritorio_dono_chave=?", (key,)).fetchall()
    conn.close()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=';')
    writer.writerow(['ID','Nome','CPF','Escritório Dono','Tipo Ação','Data Fechamento','Pendências','Nº Processo','Data Protocolo','Observações','Captador'])
    for r in rows:
        writer.writerow([r['id'], r['nome'], r['cpf'], r['escritorio_dono'], r['tipo_acao'], r['data_fechamento'], r['pendencias'], r['numero_processo'], r['data_protocolo'], r['observacoes'], r['captador']])
    mem = io.BytesIO(output.getvalue().encode('utf-8'))
    return send_file(mem, as_attachment=True, download_name=f"registros_{office}.csv", mimetype="text/csv")

@bp.route("/export/pdf")
@login_required
def export_pdf():
    office = request.args.get("office", "CENTRAL")
    conn = get_conn()
    if office.upper() == "ALL":
        rows = conn.execute("SELECT * FROM registros").fetchall()
    else:
        key = dbh.normalize_office_key(office)
        rows = conn.execute("SELECT * FROM registros WHERE escritorio_dono_chave=?", (key,)).fetchall()
    conn.close()
    buffer = io.BytesIO()
    p = canvas.Canvas(buffer, pagesize=canvas._pagesize)
    width, height = canvas._pagesize
    p.setFont("Helvetica-Bold", 14)
    p.drawString(40, height - 50, f"Registros - Escritório {office}")
    y = height - 80
    p.setFont("Helvetica", 10)
    for r in rows:
        if y < 80:
            p.showPage()
            y = height - 80
            p.setFont("Helvetica", 10)
        p.drawString(40, y, f"{r['id']} — {r['nome']} | {r['cpf']} | {r['escritorio_dono']} | {r['tipo_acao']}")
        y -= 14
    p.save()
    buffer.seek(0)
    return send_file(buffer, as_attachment=True, download_name=f"registros_{office}.pdf", mimetype="application/pdf")
