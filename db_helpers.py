# initialization and basic helpers that are shared
import os
import re
from datetime import datetime
from werkzeug.security import generate_password_hash
from .extensions import get_conn
from flask import current_app

def init_db_manual(db_path):
    # legacy support if called directly
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()

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

    c.execute("""
        CREATE TABLE IF NOT EXISTS offices (
            office_key TEXT PRIMARY KEY,
            display_name TEXT
        )
    """)

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

    c.execute("""
        CREATE TABLE IF NOT EXISTS tags (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS registro_tags (
            registro_id INTEGER,
            tag_id INTEGER,
            PRIMARY KEY(registro_id, tag_id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS registro_offices (
            registro_id INTEGER,
            office_key TEXT,
            PRIMARY KEY(registro_id, office_key)
        )
    """)

    conn.commit()

    # ensure CENTRAL
    c.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", ("CENTRAL", "CENTRAL"))

    # default admin
    c.execute("SELECT COUNT(*) FROM users")
    if c.fetchone()[0] == 0:
        now = datetime.utcnow().isoformat()
        c.execute("INSERT INTO users (username, full_name, password_hash, role, active, created_at) VALUES (?,?,?,?,?,?)",
                  ("admin", "Administrador Padrão", generate_password_hash("admin"), "ADMIN", 1, now))
    conn.commit()
    conn.close()

# Utilities used in blueprints (normalized key / register office / tags)
def normalize_office_key(name):
    if not name:
        return "CENTRAL"
    s = name.strip().upper()
    s = s.replace(" ", "_")
    s = re.sub(r"[^A-Z0-9_]", "", s)
    return s or "CENTRAL"

def register_office_conn(conn, office_key, display_name=None):
    if not display_name:
        display_name = office_key.replace("_", " ")
    conn.execute("INSERT OR IGNORE INTO offices (office_key, display_name) VALUES (?,?)", (office_key, display_name.upper()))

def ensure_tag_conn(conn, name):
    n = name.strip().upper()
    conn.execute("INSERT OR IGNORE INTO tags (name) VALUES (?)", (n,))
    row = conn.execute("SELECT id FROM tags WHERE name=?", (n,)).fetchone()
    return row["id"]
