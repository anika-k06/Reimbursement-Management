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

    app.config.from_object(config_class)

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

    # ✅ ADD THIS PART HERE
    from flask import render_template

    @app.route('/')
    def home():
        return render_template('index.html')

    # existing error handlers...
    @app.errorhandler(404)
    def not_found(e):
        from flask import jsonify
        return jsonify({"error": "Resource not found"}), 404

    return app

 
if __name__ == "__main__":
    app = create_app()
 
    # debug=True enables:
    #   - Auto-reload when source files change
    #   - Interactive debugger in the browser on unhandled exceptions
    # NEVER set debug=True in production
    app.run(debug=True)