from flask import Blueprint, request, session, jsonify
from datetime import datetime
from models import db, Expense, User, ExpenseStatus
from currency import fill_base_amount
from approval_engine import build_approval_chain
from auth import get_current_user

expenses_bp = Blueprint("expenses", __name__, url_prefix="/expenses")


# ─────────────────────────────────────────────────────────────────────────────
#  WHAT THIS FILE DOES
# ─────────────────────────────────────────────────────────────────────────────
#
#  POST /expenses/submit        → Employee submits a new expense
#  GET  /expenses/my            → Employee views their own expense history
#  GET  /expenses/<id>          → Anyone views a single expense detail
#  GET  /expenses/all           → Admin views ALL expenses in the company
#  POST /expenses/upload-receipt → Upload receipt image (for OCR)
#
# ─────────────────────────────────────────────────────────────────────────────


# ─── POST /expenses/submit ────────────────────────────────────────────────────

@expenses_bp.route("/submit", methods=["POST"])
def submit_expense():
    """
    Employee submits a new expense claim.

    What happens step by step:
        1. Validate the request data
        2. Create the Expense object
        3. Convert amount to company base currency (currency.py)
        4. Save to database
        5. Build the approval chain (approval_engine.py)
           → creates ApprovalStep rows for this expense

    Request body (JSON):
    {
        "amount":      50.0,
        "currency":    "USD",
        "category":    "Travel",
        "description": "Taxi to airport",
        "date":        "2024-01-15"
    }

    Response:
    {
        "message":    "Expense submitted successfully",
        "expense_id": 7,
        "status":     "pending",
        "amount_in_base": 4175.0,
        "base_currency":  "INR"
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    data = request.get_json()

    # ── Validate required fields ──────────────────────────────────────────────
    required = ["amount", "currency", "category", "date"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"'{field}' is required"}), 400

    # ── Parse the date string → Python date object ────────────────────────────
    try:
        expense_date = datetime.strptime(data["date"], "%Y-%m-%d").date()
    except ValueError:
        return jsonify({"error": "Date must be in YYYY-MM-DD format"}), 400

    # ── Validate amount is a positive number ─────────────────────────────────
    try:
        amount = float(data["amount"])
        if amount <= 0:
            raise ValueError
    except (ValueError, TypeError):
        return jsonify({"error": "Amount must be a positive number"}), 400

    # ── Create the Expense object ─────────────────────────────────────────────
    expense = Expense(
        user_id     = user.id,
        amount      = amount,
        currency    = data["currency"].upper(),
        category    = data["category"],
        description = data.get("description", ""),
        date        = expense_date,
        status      = ExpenseStatus.PENDING
    )
    db.session.add(expense)
    db.session.flush()  # flush so expense.id is available

    # ── Convert to company base currency (currency.py) ────────────────────────
    company_currency = user.company.currency_code
    success = fill_base_amount(expense, company_currency)

    if not success:
        db.session.rollback()
        return jsonify({
            "error": "Currency conversion failed. Please try again or check the currency code."
        }), 500

    db.session.commit()

    # ── Build the approval chain (approval_engine.py) ─────────────────────────
    # This reads the ApprovalRule and creates ApprovalStep rows
    build_approval_chain(expense)

    return jsonify({
        "message":        "Expense submitted successfully",
        "expense_id":     expense.id,
        "status":         expense.status,
        "amount_in_base": expense.amount_in_base,
        "base_currency":  company_currency
    }), 201


# ─── GET /expenses/my ─────────────────────────────────────────────────────────

@expenses_bp.route("/my", methods=["GET"])
def my_expenses():
    """
    Employee views their own expense history.
    Supports optional status filter: ?status=approved

    Response:
    [
        {
            "id":             7,
            "amount":         50.0,
            "currency":       "USD",
            "amount_in_base": 4175.0,
            "base_currency":  "INR",
            "category":       "Travel",
            "description":    "Taxi to airport",
            "date":           "2024-01-15",
            "status":         "pending",
            "submitted_on":   "2024-01-15T10:30:00",
            "current_approver": "Priya (Finance)"  ← who needs to approve next
        },
        ...
    ]
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    # Optional filter by status: /expenses/my?status=approved
    status_filter = request.args.get("status")

    query = Expense.query.filter_by(user_id=user.id)

    if status_filter and status_filter in ExpenseStatus.ALL:
        query = query.filter_by(status=status_filter)

    # Newest first
    expenses = query.order_by(Expense.created_at.desc()).all()

    result = []
    for exp in expenses:
        # Find who needs to approve next
        current_step     = exp.current_step
        current_approver = current_step.approver.name if current_step else None

        result.append({
            "id":               exp.id,
            "amount":           exp.amount,
            "currency":         exp.currency,
            "amount_in_base":   exp.amount_in_base,
            "base_currency":    user.company.currency_code,
            "category":         exp.category,
            "description":      exp.description,
            "date":             str(exp.date),
            "status":           exp.status,
            "submitted_on":     exp.created_at.isoformat(),
            "current_approver": current_approver
        })

    return jsonify(result), 200


# ─── GET /expenses/<id> ───────────────────────────────────────────────────────

@expenses_bp.route("/<int:expense_id>", methods=["GET"])
def get_expense(expense_id):
    """
    View a single expense with its full approval chain.
    Employee can only view their own. Manager/Admin can view any.

    Response:
    {
        "id":             7,
        "amount":         50.0,
        "currency":       "USD",
        "amount_in_base": 4175.0,
        "category":       "Travel",
        "description":    "Taxi to airport",
        "date":           "2024-01-15",
        "status":         "approved",
        "submitted_by":   "John",
        "approval_chain": [
            {
                "sequence":  0,
                "approver":  "Priya",
                "status":    "approved",
                "comment":   "Looks good",
                "acted_at":  "2024-01-16T09:00:00"
            },
            ...
        ]
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({"error": "Expense not found"}), 404

    # ── Permission check ──────────────────────────────────────────────────────
    # Employee can only see their own expenses
    # Manager can see their subordinates' expenses + their own
    # Admin can see everything in the company
    if not _can_view_expense(user, expense):
        return jsonify({"error": "Access denied"}), 403

    # ── Build approval chain summary ──────────────────────────────────────────
    chain = []
    for step in expense.approval_steps:
        chain.append({
            "sequence": step.sequence,
            "approver": step.approver.name,
            "status":   step.status,
            "comment":  step.comment,
            "acted_at": step.acted_at.isoformat() if step.acted_at else None
        })

    return jsonify({
        "id":             expense.id,
        "amount":         expense.amount,
        "currency":       expense.currency,
        "amount_in_base": expense.amount_in_base,
        "base_currency":  user.company.currency_code,
        "category":       expense.category,
        "description":    expense.description,
        "date":           str(expense.date),
        "status":         expense.status,
        "submitted_by":   expense.submitter.name,
        "submitted_on":   expense.created_at.isoformat(),
        "approval_chain": chain
    }), 200


# ─── GET /expenses/all ────────────────────────────────────────────────────────

@expenses_bp.route("/all", methods=["GET"])
def all_expenses():
    """
    Admin only — view ALL expenses in the company.
    Supports optional filter: ?status=pending

    Response: same format as /expenses/my but for all employees
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    if not user.is_admin:
        return jsonify({"error": "Admin access required"}), 403

    status_filter = request.args.get("status")

    # Get all expenses for the company
    query = Expense.query.join(User).filter(
        User.company_id == user.company_id
    )

    if status_filter and status_filter in ExpenseStatus.ALL:
        query = query.filter(Expense.status == status_filter)

    expenses = query.order_by(Expense.created_at.desc()).all()

    result = []
    for exp in expenses:
        current_step     = exp.current_step
        current_approver = current_step.approver.name if current_step else None

        result.append({
            "id":               exp.id,
            "submitted_by":     exp.submitter.name,
            "amount":           exp.amount,
            "currency":         exp.currency,
            "amount_in_base":   exp.amount_in_base,
            "base_currency":    user.company.currency_code,
            "category":         exp.category,
            "description":      exp.description,
            "date":             str(exp.date),
            "status":           exp.status,
            "submitted_on":     exp.created_at.isoformat(),
            "current_approver": current_approver
        })

    return jsonify(result), 200


# ─── POST /expenses/upload-receipt ────────────────────────────────────────────

@expenses_bp.route("/upload-receipt", methods=["POST"])
def upload_receipt():
    """
    Upload a receipt image for an expense.
    The file path is saved to expense.receipt_path.
    OCR processing (if implemented) would run here to auto-fill fields.

    Request: multipart/form-data
        file:       the image file
        expense_id: which expense this receipt belongs to

    Response:
    {
        "message":      "Receipt uploaded",
        "receipt_path": "uploads/receipts/expense_7_receipt.jpg"
    }
    """
    import os
    from werkzeug.utils import secure_filename

    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    expense_id = request.form.get("expense_id")
    file       = request.files.get("file")

    if not expense_id or not file:
        return jsonify({"error": "expense_id and file are required"}), 400

    expense = Expense.query.get(expense_id)
    if not expense or expense.user_id != user.id:
        return jsonify({"error": "Expense not found or access denied"}), 404

    # ── Save the file ─────────────────────────────────────────────────────────
    upload_folder  = "uploads/receipts"
    os.makedirs(upload_folder, exist_ok=True)

    filename     = secure_filename(f"expense_{expense_id}_{file.filename}")
    receipt_path = os.path.join(upload_folder, filename)
    file.save(receipt_path)

    # ── Save path to expense ──────────────────────────────────────────────────
    expense.receipt_path = receipt_path
    db.session.commit()

    return jsonify({
        "message":      "Receipt uploaded",
        "receipt_path": receipt_path
    }), 200


# ─── Internal helper ──────────────────────────────────────────────────────────

def _can_view_expense(user: User, expense: Expense) -> bool:
    """
    Permission check for viewing an expense.
    - Admin: can view any expense in their company
    - Manager: can view their own + their subordinates' expenses
    - Employee: can only view their own expenses
    """
    if user.is_admin:
        # Admin can view anything in their company
        return expense.submitter.company_id == user.company_id

    if user.is_manager:
        # Manager can view their own + subordinates'
        subordinate_ids = [s.id for s in user.subordinates]
        return expense.user_id == user.id or expense.user_id in subordinate_ids

    # Employee can only view their own
    return expense.user_id == user.id
