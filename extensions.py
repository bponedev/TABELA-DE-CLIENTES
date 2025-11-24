# helpers to import in blueprints
from flask import current_app
import sqlite3

def get_conn():
    path = current_app.config.get("DB_PATH")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn
