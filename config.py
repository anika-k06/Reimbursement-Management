import os
 

# ─── Base config — shared by all environments ─────────────────────────────────
 
class Config:
    """
    Central configuration for the Reimbursement Management System.
 
    All values are read from environment variables first.
    Sensible development defaults are provided where safe.
 
    In production, set these environment variables on the server — never
    commit real secrets to source control.
 
    Quick reference — what each setting does:
        SECRET_KEY              → Flask signs session cookies with this; must be
                                  long, random, and secret in production
        SQLALCHEMY_DATABASE_URI → Where the database lives (SQLite for dev,
                                  PostgreSQL/MySQL for production)
        SQLALCHEMY_TRACK_MODIFICATIONS → SQLAlchemy internal flag; False saves memory
        MAX_CONTENT_LENGTH      → Hard cap on request body size (receipt uploads)
        SESSION_COOKIE_*        → Harden the session cookie for production
        JSON_SORT_KEYS          → Keep JSON response key order predictable
    """
 
    # ── Security ──────────────────────────────────────────────────────────────
    # In production set:  export SECRET_KEY="<random 64-char string>"
    # Generate one with:  python -c "import secrets; print(secrets.token_hex(32))"
    SECRET_KEY: str = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")
 
    # ── Database ──────────────────────────────────────────────────────────────
    # SQLite for local development — zero setup required, file appears in project root.
    # For production switch to PostgreSQL:
    #   export DATABASE_URL="postgresql://user:password@host:5432/reimbursement"
    SQLALCHEMY_DATABASE_URI: str = os.environ.get(
        "DATABASE_URL",
        "sqlite:///reimbursement.db"
    )
 
    # Disables Flask-SQLAlchemy's event system — we don't use it and it
    # adds unnecessary overhead on every db.session operation.
    SQLALCHEMY_TRACK_MODIFICATIONS: bool = False
 
    # ── File uploads ──────────────────────────────────────────────────────────
    # Limits the size of incoming request bodies.
    # Receipt images are the largest payload — 16 MB is generous but bounded.
    # Flask raises a 413 Request Entity Too Large if this is exceeded.
    MAX_CONTENT_LENGTH: int = 16 * 1024 * 1024   # 16 MB
 
    # Folder where uploaded receipt images are stored on disk.
    # expenses.py uses this when saving files via werkzeug's secure_filename.
    UPLOAD_FOLDER: str = os.environ.get("UPLOAD_FOLDER", "uploads/receipts")
 
    # ── Session cookie settings ───────────────────────────────────────────────
    # HttpOnly: JavaScript cannot read the cookie (prevents XSS theft)
    SESSION_COOKIE_HTTPONLY: bool = True
    # SameSite=Lax: cookie is not sent on cross-site POST requests (CSRF protection)
    SESSION_COOKIE_SAMESITE: str = "Lax"
    # Secure=True in production: cookie only sent over HTTPS
    # Set to True when deploying behind HTTPS; False for local HTTP dev
    SESSION_COOKIE_SECURE: bool = os.environ.get("FLASK_ENV") == "production"
 
    # ── JSON behaviour ────────────────────────────────────────────────────────
    # Keep JSON response keys in insertion order (easier to read in dev tools)
    JSON_SORT_KEYS: bool = False
 
 
# ─── Environment-specific subclasses ─────────────────────────────────────────
# Pass these to create_app() in app.py when needed:
#     app = create_app(DevelopmentConfig)
#     app = create_app(ProductionConfig)
#     app = create_app(TestingConfig)
 
class DevelopmentConfig(Config):
    """
    Local development — verbose errors, auto-reload, no HTTPS required.
    This is the default when you run python app.py directly.
    """
    DEBUG: bool = True
    SQLALCHEMY_ECHO: bool = True    # print every SQL statement to the console
 
 
class TestingConfig(Config):
    """
    Used by pytest / CI.
    In-memory SQLite database — created fresh for each test run and discarded.
    TESTING=True suppresses Flask's error-catching so exceptions propagate
    to the test runner.
    """
    TESTING: bool = True
    SQLALCHEMY_DATABASE_URI: str = "sqlite:///:memory:"
    WTF_CSRF_ENABLED: bool = False  # disable CSRF checks in tests if added later
 
 
class ProductionConfig(Config):
    """
    Production server settings.
    Requires DATABASE_URL and SECRET_KEY to be set as real environment variables.
    Will raise at startup if they are missing or still set to dev defaults.
    """
    DEBUG: bool = False
    SESSION_COOKIE_SECURE: bool = True   # force HTTPS-only cookies
 
    def __init__(self):
        # Hard fail at startup if someone forgot to set production secrets
        if not os.environ.get("SECRET_KEY"):
            raise RuntimeError(
                "SECRET_KEY environment variable must be set in production. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if not os.environ.get("DATABASE_URL"):
            raise RuntimeError(
                "DATABASE_URL environment variable must be set in production. "
                "Example: postgresql://user:password@host:5432/reimbursement"
            )
 