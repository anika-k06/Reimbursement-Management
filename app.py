from flask import Flask
from config import Config
from models import db
 
 
def create_app(config_class=Config):
    """
    Application factory — creates and configures the Flask app.
 
    Using a factory function (instead of a global app object) means:
      - We can create multiple app instances for testing
      - Config can be swapped at creation time (e.g. TestConfig)
      - Blueprint imports are deferred, avoiding circular imports
 
    Usage:
        # Normal startup (python app.py)
        app = create_app()
 
        # Testing — pass a different config class
        app = create_app(TestConfig)
    """
    app = Flask(__name__)
 
    # ── Step 1: Load config (SECRET_KEY, DATABASE_URI, etc.) ─────────────────
    app.config.from_object(config_class)
 
    # ── Step 2: Connect the SQLAlchemy engine to this Flask app ──────────────
    # db is defined in models.py as db = SQLAlchemy()
    # init_app() binds it to this specific app instance
    db.init_app(app)
 
    # ── Step 3: Create all database tables ───────────────────────────────────
    # Reads every class in models.py that extends db.Model and runs
    # CREATE TABLE IF NOT EXISTS on the .db file automatically.
    # In production, use Flask-Migrate (Alembic) instead of create_all()
    # so that schema changes are tracked and applied incrementally.
    with app.app_context():
        db.create_all()
        print("✅ Database tables created (or already exist).")
 
    # ── Step 4: Register route blueprints ────────────────────────────────────
    # Each blueprint is defined in its own file and handles a logical group
    # of routes. Import here (inside the factory) to avoid circular imports
    # since each route file imports from models.py and auth.py.
 
    from auth import auth_bp
    from expenses import expenses_bp
    from approvals import approvals_bp
    from admin import admin_bp
 
    app.register_blueprint(auth_bp)       # /auth/*
    app.register_blueprint(expenses_bp)   # /expenses/*
    app.register_blueprint(approvals_bp)  # /approvals/*
    app.register_blueprint(admin_bp)      # /admin/*
 
    # ── Step 5: Register global error handlers ────────────────────────────────
    # Return consistent JSON error responses instead of Flask's default HTML
    # error pages — important for an API that the frontend consumes via fetch().
 
    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify
        return jsonify({"error": "Resource not found"}), 404
 
    @app.errorhandler(405)
    def method_not_allowed(e):
        from flask import jsonify
        return jsonify({"error": "Method not allowed"}), 405
 
    @app.errorhandler(500)
    def internal_error(e):
        from flask import jsonify
        db.session.rollback()   # roll back any broken transaction
        return jsonify({"error": "Internal server error"}), 500
 
    return app
 
 
# ── Entry point — run with: python app.py ─────────────────────────────────────
# When deployed (gunicorn, waitress, etc.), the WSGI server imports create_app()
# directly and never executes this block.
 
if __name__ == "__main__":
    app = create_app()
 
    # debug=True enables:
    #   - Auto-reload when source files change
    #   - Interactive debugger in the browser on unhandled exceptions
    # NEVER set debug=True in production
    app.run(debug=True)
 