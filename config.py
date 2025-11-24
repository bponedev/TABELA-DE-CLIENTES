import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "database.db")

class Config:
    SECRET_KEY = os.environ.get("FLASK_SECRET", "troque_para_uma_chave_secreta")
    DB_PATH = DB_PATH
