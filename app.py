from flask import Flask
from config import Config
from extensions import get_conn
import db_helpers as dbh
import os

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")
    app.config.from_object(Config)

    # initialize DB if missing
    db_path = app.config["DB_PATH"]
    if not os.path.exists(db_path):
        dbh.init_db_manual(db_path)

    # register blueprints
    from blueprints.auth import bp as auth_bp
    from blueprints.registros import bp as registros_bp
    from blueprints.offices import bp as offices_bp
    from blueprints.admin import bp as admin_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(registros_bp)
    app.register_blueprint(offices_bp)
    app.register_blueprint(admin_bp)

    # helper for templates: hashcolor filter
    def hashcolor_filter(s):
        # simple stable hash -> hex like earlier
        h = 0
        if not s:
            return "#888888"
        for ch in s:
            h = ord(ch) + ((h << 5) - h)
        color = "#"
        for i in range(3):
            color += ("%02x" % ((h >> (i * 8)) & 0xFF))
        return color
    app.jinja_env.filters['hashcolor'] = hashcolor_filter

    return app

if __name__ == "__main__":
    app = create_app()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
