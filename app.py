from flask import Flask
from config import Config
from models import db


def create_app():
    app = Flask(__name__)

    # Step 1 — load config (SECRET_KEY, DATABASE_URI, etc.)
    app.config.from_object(Config)

    # Step 2 — connect the db engine to this Flask app
    db.init_app(app)

    # Step 3 — create all tables if they don't exist yet
    # This reads every class in models.py that extends db.Model
    # and runs CREATE TABLE on the .db file automatically
    with app.app_context():
        db.create_all()
        print("✅ Database tables created successfully!")

    # Step 4 — register route blueprints
    # Uncomment these one by one as you build each route file
    # from routes.auth import auth_bp
    # from routes.expenses import expenses_bp
    # from routes.approvals import approvals_bp
    # from routes.admin import admin_bp

    # app.register_blueprint(auth_bp)
    # app.register_blueprint(expenses_bp)
    # app.register_blueprint(approvals_bp)
    # app.register_blueprint(admin_bp)

    return app


# Entry point — run with: python app.py
if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)
