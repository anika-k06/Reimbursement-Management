from flask import Blueprint, request, jsonify
from models import db, User, Company, ApprovalRule, ApprovalRuleStep, Role, RuleType
from auth import get_current_user

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


# ─────────────────────────────────────────────────────────────────────────────
#  WHAT THIS FILE DOES
# ─────────────────────────────────────────────────────────────────────────────
#
#  USER MANAGEMENT
#  POST /admin/users/create          → Admin creates employee or manager
#  GET  /admin/users                 → Admin views all users in company
#  PUT  /admin/users/<id>/role       → Admin changes a user's role
#  PUT  /admin/users/<id>/manager    → Admin assigns a manager to an employee
#
#  APPROVAL RULES
#  POST /admin/rules/create          → Admin creates an approval rule
#  GET  /admin/rules                 → Admin views all rules
#  PUT  /admin/rules/<id>            → Admin edits a rule
#  DELETE /admin/rules/<id>          → Admin deletes a rule
#
# ─────────────────────────────────────────────────────────────────────────────


# ─── Helper: admin-only guard ─────────────────────────────────────────────────

def admin_only():
    """
    Returns (user, None) if logged in as admin.
    Returns (None, error_response) if not.

    Usage in every route:
        user, err = admin_only()
        if err: return err
    """
    user = get_current_user()
    if not user:
        return None, (jsonify({"error": "Login required"}), 401)
    if not user.is_admin:
        return None, (jsonify({"error": "Admin access required"}), 403)
    return user, None


# ═════════════════════════════════════════════════════════════════════════════
#  USER MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

# ─── POST /admin/users/create ─────────────────────────────────────────────────

@admin_bp.route("/users/create", methods=["POST"])
def create_user():
    """
    Admin creates a new employee or manager in their company.

    Request body (JSON):
    {
        "name":                 "John Doe",
        "email":                "john@acme.com",
        "password":             "temp123",
        "role":                 "employee",     ← or "manager"
        "manager_id":           9,              ← optional, assign manager
        "is_manager_approver":  true            ← optional, default false
    }

    Response:
    {
        "message": "User created successfully",
        "user_id": 20,
        "role":    "employee"
    }
    """
    user, err = admin_only()
    if err: return err

    data = request.get_json()

    # ── Validate required fields ──────────────────────────────────────────────
    required = ["name", "email", "password", "role"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400

    # ── Validate role ─────────────────────────────────────────────────────────
    role = data["role"].lower()
    if role not in [Role.EMPLOYEE, Role.MANAGER]:
        return jsonify({"error": "Role must be 'employee' or 'manager'"}), 400

    # ── Check email not already taken ─────────────────────────────────────────
    if User.query.filter_by(email=data["email"]).first():
        return jsonify({"error": "Email already registered"}), 409

    # ── Validate manager_id if provided ───────────────────────────────────────
    manager_id = data.get("manager_id")
    if manager_id:
        manager = User.query.get(manager_id)
        if not manager or manager.company_id != user.company_id:
            return jsonify({"error": "Manager not found in your company"}), 404

    # ── Create the user ───────────────────────────────────────────────────────
    new_user = User(
        company_id          = user.company_id,   # same company as admin
        name                = data["name"],
        email               = data["email"].lower().strip(),
        role                = role,
        manager_id          = manager_id,
        is_manager_approver = data.get("is_manager_approver", False)
    )
    new_user.set_password(data["password"])
    db.session.add(new_user)
    db.session.commit()

    return jsonify({
        "message": "User created successfully",
        "user_id": new_user.id,
        "role":    new_user.role
    }), 201


# ─── GET /admin/users ─────────────────────────────────────────────────────────

@admin_bp.route("/users", methods=["GET"])
def get_all_users():
    """
    Admin views all users in their company.
    Optional filter: ?role=employee or ?role=manager

    Response:
    [
        {
            "id":                   20,
            "name":                 "John Doe",
            "email":                "john@acme.com",
            "role":                 "employee",
            "manager":              "Priya",      ← manager's name or null
            "manager_id":           9,
            "is_manager_approver":  false
        },
        ...
    ]
    """
    user, err = admin_only()
    if err: return err

    role_filter = request.args.get("role")

    query = User.query.filter_by(company_id=user.company_id)

    if role_filter and role_filter in Role.ALL:
        query = query.filter_by(role=role_filter)

    users = query.order_by(User.name).all()

    result = []
    for u in users:
        result.append({
            "id":                  u.id,
            "name":                u.name,
            "email":               u.email,
            "role":                u.role,
            "manager":             u.manager.name if u.manager else None,
            "manager_id":          u.manager_id,
            "is_manager_approver": u.is_manager_approver
        })

    return jsonify(result), 200


# ─── PUT /admin/users/<id>/role ───────────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>/role", methods=["PUT"])
def change_role(user_id):
    """
    Admin changes a user's role (employee ↔ manager).
    Cannot change another admin's role.

    Request body (JSON):
    {
        "role": "manager"   ← or "employee"
    }

    Response:
    {
        "message": "Role updated to manager",
        "user_id": 20
    }
    """
    admin, err = admin_only()
    if err: return err

    target = User.query.get(user_id)
    if not target or target.company_id != admin.company_id:
        return jsonify({"error": "User not found in your company"}), 404

    if target.is_admin:
        return jsonify({"error": "Cannot change another admin's role"}), 403

    data = request.get_json()
    new_role = data.get("role", "").lower()

    if new_role not in [Role.EMPLOYEE, Role.MANAGER]:
        return jsonify({"error": "Role must be 'employee' or 'manager'"}), 400

    target.role = new_role
    db.session.commit()

    return jsonify({
        "message": f"Role updated to {new_role}",
        "user_id": user_id
    }), 200


# ─── PUT /admin/users/<id>/manager ───────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>/manager", methods=["PUT"])
def assign_manager(user_id):
    """
    Admin assigns a manager to an employee.
    This sets the manager_id field on the User.

    Request body (JSON):
    {
        "manager_id":           9,      ← User id of the manager
        "is_manager_approver":  true    ← optional, should manager auto-approve?
    }

    Response:
    {
        "message":    "Manager assigned successfully",
        "employee":   "John",
        "manager":    "Priya"
    }
    """
    admin, err = admin_only()
    if err: return err

    employee = User.query.get(user_id)
    if not employee or employee.company_id != admin.company_id:
        return jsonify({"error": "User not found in your company"}), 404

    data       = request.get_json()
    manager_id = data.get("manager_id")

    if not manager_id:
        return jsonify({"error": "manager_id is required"}), 400

    manager = User.query.get(manager_id)
    if not manager or manager.company_id != admin.company_id:
        return jsonify({"error": "Manager not found in your company"}), 404

    # Prevent assigning someone as their own manager
    if manager.id == employee.id:
        return jsonify({"error": "A user cannot be their own manager"}), 400

    employee.manager_id = manager.id

    # Optionally update is_manager_approver flag
    if "is_manager_approver" in data:
        employee.is_manager_approver = bool(data["is_manager_approver"])

    db.session.commit()

    return jsonify({
        "message":  "Manager assigned successfully",
        "employee": employee.name,
        "manager":  manager.name
    }), 200


# ═════════════════════════════════════════════════════════════════════════════
#  APPROVAL RULES MANAGEMENT
# ═════════════════════════════════════════════════════════════════════════════

# ─── POST /admin/rules/create ─────────────────────────────────────────────────

@admin_bp.route("/rules/create", methods=["POST"])
def create_rule():
    """
    Admin creates an approval rule with an ordered list of approvers.

    Request body (JSON):
    {
        "name":                       "Above 5000",
        "rule_type":                  "sequential",
        "threshold_amount":           5000,
        "percentage_required":        null,
        "specific_approver_override": false,
        "approvers": [
            { "approver_id": 5, "sequence": 0 },   ← Priya (Finance)
            { "approver_id": 8, "sequence": 1 },   ← Rahul (CFO)
            { "approver_id": 2, "sequence": 2 }    ← Admin
        ]
    }

    For "percentage" rule_type, set percentage_required (e.g. 60).
    For "specific" rule_type, set specific_approver_override=true.
    For "hybrid", set both.

    Response:
    {
        "message": "Rule created successfully",
        "rule_id": 1
    }
    """
    user, err = admin_only()
    if err: return err

    data = request.get_json()

    # ── Validate required fields ──────────────────────────────────────────────
    if not data.get("name"):
        return jsonify({"error": "'name' is required"}), 400

    rule_type = data.get("rule_type", RuleType.SEQUENTIAL)
    if rule_type not in RuleType.ALL:
        return jsonify({"error": f"rule_type must be one of: {RuleType.ALL}"}), 400

    # ── Validate approvers list ───────────────────────────────────────────────
    approvers = data.get("approvers", [])
    if not approvers:
        return jsonify({"error": "At least one approver is required"}), 400

    # Make sure all approvers exist and belong to this company
    for item in approvers:
        approver = User.query.get(item.get("approver_id"))
        if not approver or approver.company_id != user.company_id:
            return jsonify({
                "error": f"Approver id={item.get('approver_id')} not found in your company"
            }), 404

    # ── Create the ApprovalRule ───────────────────────────────────────────────
    rule = ApprovalRule(
        company_id                = user.company_id,
        name                      = data["name"],
        rule_type                 = rule_type,
        threshold_amount          = data.get("threshold_amount"),
        percentage_required       = data.get("percentage_required"),
        specific_approver_override = data.get("specific_approver_override", False)
    )
    db.session.add(rule)
    db.session.flush()  # get rule.id before adding steps

    # ── Create the ApprovalRuleSteps (the ordered approver list) ─────────────
    for item in approvers:
        step = ApprovalRuleStep(
            rule_id     = rule.id,
            approver_id = item["approver_id"],
            sequence    = item["sequence"]
        )
        db.session.add(step)

    db.session.commit()

    return jsonify({
        "message": "Rule created successfully",
        "rule_id": rule.id
    }), 201


# ─── GET /admin/rules ─────────────────────────────────────────────────────────

@admin_bp.route("/rules", methods=["GET"])
def get_rules():
    """
    Admin views all approval rules for their company.

    Response:
    [
        {
            "id":                       1,
            "name":                     "Above 5000",
            "rule_type":                "sequential",
            "threshold_amount":         5000,
            "percentage_required":      null,
            "specific_approver_override": false,
            "approvers": [
                { "sequence": 0, "name": "Priya", "user_id": 5 },
                { "sequence": 1, "name": "Rahul", "user_id": 8 }
            ]
        },
        ...
    ]
    """
    user, err = admin_only()
    if err: return err

    rules = ApprovalRule.query.filter_by(company_id=user.company_id).all()

    result = []
    for rule in rules:
        approvers = [
            {
                "sequence": step.sequence,
                "name":     step.approver.name,
                "user_id":  step.approver_id
            }
            for step in rule.steps  # already ordered by sequence
        ]

        result.append({
            "id":                         rule.id,
            "name":                       rule.name,
            "rule_type":                  rule.rule_type,
            "threshold_amount":           rule.threshold_amount,
            "percentage_required":        rule.percentage_required,
            "specific_approver_override": rule.specific_approver_override,
            "approvers":                  approvers
        })

    return jsonify(result), 200


# ─── PUT /admin/rules/<id> ────────────────────────────────────────────────────

@admin_bp.route("/rules/<int:rule_id>", methods=["PUT"])
def update_rule(rule_id):
    """
    Admin edits an existing approval rule.
    Replaces the entire approver list if 'approvers' is provided.

    Request body (JSON) — send only fields you want to change:
    {
        "name":               "Updated Rule Name",
        "threshold_amount":   10000,
        "approvers": [
            { "approver_id": 5, "sequence": 0 },
            { "approver_id": 8, "sequence": 1 }
        ]
    }
    """
    user, err = admin_only()
    if err: return err

    rule = ApprovalRule.query.get(rule_id)
    if not rule or rule.company_id != user.company_id:
        return jsonify({"error": "Rule not found"}), 404

    data = request.get_json()

    # ── Update scalar fields if provided ─────────────────────────────────────
    if "name" in data:
        rule.name = data["name"]
    if "rule_type" in data:
        if data["rule_type"] not in RuleType.ALL:
            return jsonify({"error": f"Invalid rule_type"}), 400
        rule.rule_type = data["rule_type"]
    if "threshold_amount" in data:
        rule.threshold_amount = data["threshold_amount"]
    if "percentage_required" in data:
        rule.percentage_required = data["percentage_required"]
    if "specific_approver_override" in data:
        rule.specific_approver_override = data["specific_approver_override"]

    # ── Replace approvers list if provided ────────────────────────────────────
    if "approvers" in data:
        # Delete old steps (cascade handles this, but explicit is clearer)
        for old_step in rule.steps:
            db.session.delete(old_step)
        db.session.flush()

        # Add new steps
        for item in data["approvers"]:
            approver = User.query.get(item.get("approver_id"))
            if not approver or approver.company_id != user.company_id:
                db.session.rollback()
                return jsonify({"error": f"Approver id={item.get('approver_id')} not found"}), 404

            new_step = ApprovalRuleStep(
                rule_id     = rule.id,
                approver_id = item["approver_id"],
                sequence    = item["sequence"]
            )
            db.session.add(new_step)

    db.session.commit()

    return jsonify({"message": "Rule updated successfully", "rule_id": rule_id}), 200


# ─── DELETE /admin/rules/<id> ─────────────────────────────────────────────────

@admin_bp.route("/rules/<int:rule_id>", methods=["DELETE"])
def delete_rule(rule_id):
    """
    Admin deletes an approval rule.
    The rule's ApprovalRuleSteps are deleted automatically
    because of cascade="all, delete-orphan" in models.py.

    Note: existing expenses that already used this rule are NOT affected —
    their ApprovalStep rows still exist and work independently.
    """
    user, err = admin_only()
    if err: return err

    rule = ApprovalRule.query.get(rule_id)
    if not rule or rule.company_id != user.company_id:
        return jsonify({"error": "Rule not found"}), 404

    db.session.delete(rule)
    db.session.commit()

    return jsonify({"message": "Rule deleted successfully"}), 200
