import os
from flask import Flask
from config import Config
from models import db
 
 
def create_app(config_class=Config):
    app = Flask(__name__)
 
    app.config.from_object(config_class)
 
    # ── Override with environment variables if set (for Render deployment) ────
    if os.environ.get("SECRET_KEY"):
        app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
 
    if os.environ.get("DATABASE_URL"):
        db_url = os.environ.get("DATABASE_URL")
        # Render gives postgres:// but SQLAlchemy needs postgresql://
        if db_url.startswith("postgres://"):
            db_url = db_url.replace("postgres://", "postgresql://", 1)
        app.config["SQLALCHEMY_DATABASE_URI"] = db_url
 
    db.init_app(app)
 
    with app.app_context():
        db.create_all()
 
    from auth import auth_bp
    from expenses import expenses_bp
    from approvals import approvals_bp
    from admin import admin_bp
 
    app.register_blueprint(auth_bp)
    app.register_blueprint(expenses_bp)
    app.register_blueprint(approvals_bp)
    app.register_blueprint(admin_bp)
 
    from flask import render_template
 
    @app.route("/")
    def home():
        return render_template("index.html")
 
    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify
        return jsonify({"error": "Resource not found"}), 404
 
    return app
 
 
if __name__ == "__main__":
    app = create_app()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)