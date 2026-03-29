import os

class Config:
    # Secret key used by Flask to sign session cookies
    # In production, set this as an environment variable — never hardcode it
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-in-prod")

    # Path to the SQLite database file
    # sqlite:///  means "create the file in the project root folder"
    # reimbursement.db is the filename that will appear on disk
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL", "sqlite:///reimbursement.db"
    )

    # Disable modification tracking — not needed and wastes memory
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Allow larger file uploads for receipt images (16 MB)
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
