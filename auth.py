from flask import Blueprint, request, session, jsonify
from models import db, User, Company, Role
from currency import get_all_countries_currencies

auth_bp = Blueprint("auth", __name__, url_prefix="/auth")


# ─────────────────────────────────────────────────────────────────────────────
#  WHAT THIS FILE DOES
# ─────────────────────────────────────────────────────────────────────────────
#
#  POST /auth/signup  → First user signs up → Company + Admin created together
#  POST /auth/login   → Any user logs in → user_id saved in session
#  POST /auth/logout  → Clear session
#  GET  /auth/me      → Return current logged-in user info
#  GET  /auth/countries → Return all countries + currencies for signup dropdown
#
# ─────────────────────────────────────────────────────────────────────────────


# ─── Helper: get current logged-in user from session ─────────────────────────

def get_current_user():
    """
    Reads user_id from the Flask session and returns the User object.
    Returns None if no one is logged in.

    Every protected route calls this at the top:
        user = get_current_user()
        if not user:
            return jsonify({"error": "Login required"}), 401
    """
    user_id = session.get("user_id")
    if not user_id:
        return None
    return User.query.get(user_id)


# ─── GET /auth/countries ──────────────────────────────────────────────────────

@auth_bp.route("/countries", methods=["GET"])
def countries():
    """
    Returns all countries and their currencies.
    Called on the signup page to populate the country dropdown.

    Response:
    [
        { "country": "India", "currency_code": "INR", "currency_name": "Indian Rupee" },
        { "country": "United States", "currency_code": "USD", "currency_name": "US Dollar" },
        ...
    ]
    """
    data = get_all_countries_currencies()
    return jsonify(data), 200


# ─── POST /auth/signup ────────────────────────────────────────────────────────

@auth_bp.route("/signup", methods=["POST"])
def signup():
    """
    First-time signup — creates a Company AND an Admin user together.

    This is called only ONCE per company (when the admin registers).
    After this, the admin creates other employees/managers from the admin dashboard.

    Request body (JSON):
    {
        "company_name":  "Acme Corp",
        "country":       "India",
        "currency_code": "INR",
        "name":          "Raj Admin",
        "email":         "raj@acme.com",
        "password":      "secret123"
    }

    Response (success):
    {
        "message": "Company and admin created successfully",
        "user_id": 1,
        "role":    "admin"
    }
    """
    data = request.get_json()

    # ── Validate required fields ──────────────────────────────────────────────
    required = ["company_name", "country", "currency_code", "name", "email", "password"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400

    # ── Check email is not already taken ──────────────────────────────────────
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    # ── Create the Company ────────────────────────────────────────────────────
    company = Company(
        name          = data["company_name"],
        country       = data["country"],
        currency_code = data["currency_code"].upper()
    )
    db.session.add(company)
    db.session.flush()  # flush so company.id is available before commit

    # ── Create the Admin User ─────────────────────────────────────────────────
    admin = User(
        company_id = company.id,
        name       = data["name"],
        email      = data["email"].lower().strip(),
        role       = Role.ADMIN
    )
    admin.set_password(data["password"])  # hashes the password
    db.session.add(admin)
    db.session.commit()

    # ── Log the admin in immediately after signup ─────────────────────────────
    session["user_id"]   = admin.id
    session["role"]      = admin.role
    session["company_id"] = company.id

    return jsonify({
        "message":    "Company and admin created successfully",
        "user_id":    admin.id,
        "role":       admin.role,
        "company_id": company.id
    }), 201


# ─── POST /auth/login ─────────────────────────────────────────────────────────

@auth_bp.route("/login", methods=["POST"])
def login():
    """
    Log in any user (admin, manager, employee) with email + password.

    Request body (JSON):
    {
        "email":    "raj@acme.com",
        "password": "secret123"
    }

    Response (success):
    {
        "message":    "Login successful",
        "user_id":    1,
        "role":       "admin",
        "company_id": 1
    }

    The frontend uses the "role" field to redirect to the correct dashboard:
        admin    → dashboard_admin.html
        manager  → dashboard_manager.html
        employee → dashboard_employee.html
    """
    data = request.get_json()

    email    = data.get("email", "").lower().strip()
    password = data.get("password", "")

    if not email or not password:
        return jsonify({"error": "Email and password are required"}), 400

    # ── Find user by email ────────────────────────────────────────────────────
    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        # Same error message for both cases — don't reveal which one failed
        return jsonify({"error": "Invalid email or password"}), 401

    # ── Save to session ───────────────────────────────────────────────────────
    session["user_id"]    = user.id
    session["role"]       = user.role
    session["company_id"] = user.company_id

    return jsonify({
        "message":    "Login successful",
        "user_id":    user.id,
        "role":       user.role,
        "name":       user.name,
        "company_id": user.company_id
    }), 200


# ─── POST /auth/logout ────────────────────────────────────────────────────────

@auth_bp.route("/logout", methods=["POST"])
def logout():
    """
    Clear the session — logs out the current user.
    """
    session.clear()
    return jsonify({"message": "Logged out successfully"}), 200


# ─── GET /auth/me ─────────────────────────────────────────────────────────────

@auth_bp.route("/me", methods=["GET"])
def me():
    """
    Returns the currently logged-in user's info.
    Called by the frontend on page load to check who is logged in
    and render the correct dashboard.

    Response:
    {
        "user_id":    1,
        "name":       "Raj Admin",
        "email":      "raj@acme.com",
        "role":       "admin",
        "company_id": 1,
        "company":    "Acme Corp",
        "currency":   "INR"
    }
    """
    user = get_current_user()

    if not user:
        return jsonify({"error": "Not logged in"}), 401

    return jsonify({
        "user_id":    user.id,
        "name":       user.name,
        "email":      user.email,
        "role":       user.role,
        "company_id": user.company_id,
        "company":    user.company.name,
        "currency":   user.company.currency_code
    }), 200
