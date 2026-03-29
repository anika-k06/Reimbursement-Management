from flask import Blueprint, request, jsonify
from models import db, ApprovalStep, Expense, ApprovalStepStatus, ExpenseStatus
from approval_engine import process_decision, get_pending_steps_for_approver
from auth import get_current_user

approvals_bp = Blueprint("approvals", __name__, url_prefix="/approvals")


# ─────────────────────────────────────────────────────────────────────────────
#  WHAT THIS FILE DOES
# ─────────────────────────────────────────────────────────────────────────────
#
#  GET  /approvals/pending          → Manager sees their pending approval queue
#  POST /approvals/decide/<step_id> → Manager approves or rejects a step
#  GET  /approvals/history          → Manager sees all past decisions they made
#  POST /approvals/override/<id>    → Admin overrides any expense decision
#
# ─────────────────────────────────────────────────────────────────────────────


# ─── GET /approvals/pending ───────────────────────────────────────────────────

@approvals_bp.route("/pending", methods=["GET"])
def pending_approvals():
    """
    Returns all expenses currently waiting for THIS approver to act on.

    Called by: dashboard_manager.html to show the pending queue

    Uses get_pending_steps_for_approver() from approval_engine.py which:
        - finds all ApprovalSteps assigned to this user
        - filters to only the CURRENT active step per expense
          (so an approver doesn't see step 2 until step 1 is done)

    Response:
    [
        {
            "step_id":        3,
            "expense_id":     7,
            "submitted_by":   "John",
            "amount_in_base": 4175.0,
            "base_currency":  "INR",
            "category":       "Travel",
            "description":    "Taxi to airport",
            "date":           "2024-01-15",
            "submitted_on":   "2024-01-15T10:30:00",
            "sequence":       1,
            "rule_name":      "Above 5000"
        },
        ...
    ]
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    # Only managers and admins can approve
    if user.is_employee:
        return jsonify({"error": "Access denied — approvers only"}), 403

    # Get all steps waiting for this approver (from approval_engine.py)
    pending_steps = get_pending_steps_for_approver(user.id)

    result = []
    for step in pending_steps:
        expense = step.expense
        result.append({
            "step_id":        step.id,
            "expense_id":     expense.id,
            "submitted_by":   expense.submitter.name,
            "amount":         expense.amount,
            "currency":       expense.currency,
            "amount_in_base": expense.amount_in_base,
            "base_currency":  user.company.currency_code,
            "category":       expense.category,
            "description":    expense.description,
            "date":           str(expense.date),
            "submitted_on":   expense.created_at.isoformat(),
            "sequence":       step.sequence,
            "rule_name":      expense.rule.name if expense.rule else "No rule"
        })

    return jsonify(result), 200


# ─── POST /approvals/decide/<step_id> ────────────────────────────────────────

@approvals_bp.route("/decide/<int:step_id>", methods=["POST"])
def decide(step_id):
    """
    Manager/approver clicks Approve or Reject on an expense.

    This calls process_decision() from approval_engine.py which:
        - marks this step as approved/rejected
        - if rejected → marks entire expense as rejected
        - if approved → checks rule_type and either:
            → activates next step (sequential)
            → checks percentage condition
            → checks specific approver override
            → marks expense fully approved if all conditions met

    Request body (JSON):
    {
        "decision": "approved",   ← or "rejected"
        "comment":  "Looks good"  ← optional note
    }

    Response:
    {
        "message":        "Approved — moved to next approver: Rahul",
        "expense_status": "pending",   ← or "approved" / "rejected"
        "expense_id":     7
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    if user.is_employee:
        return jsonify({"error": "Access denied — approvers only"}), 403

    # ── Get the step ──────────────────────────────────────────────────────────
    step = ApprovalStep.query.get(step_id)
    if not step:
        return jsonify({"error": "Approval step not found"}), 404

    # ── Make sure this step belongs to this approver ──────────────────────────
    if step.approver_id != user.id:
        return jsonify({"error": "This step is not assigned to you"}), 403

    # ── Make sure step is still pending ───────────────────────────────────────
    if step.status != ApprovalStepStatus.PENDING:
        return jsonify({"error": f"This step is already {step.status}"}), 400

    # ── Make sure the expense is still pending ────────────────────────────────
    if step.expense.status != ExpenseStatus.PENDING:
        return jsonify({
            "error": f"Expense is already {step.expense.status}"
        }), 400

    # ── Validate decision ─────────────────────────────────────────────────────
    data     = request.get_json()
    decision = data.get("decision", "").lower()
    comment  = data.get("comment", "")

    if decision not in [ApprovalStepStatus.APPROVED, ApprovalStepStatus.REJECTED]:
        return jsonify({"error": "Decision must be 'approved' or 'rejected'"}), 400

    # ── Process the decision (approval_engine.py handles all the logic) ───────
    result = process_decision(step, decision, comment)

    return jsonify({
        "message":        result["message"],
        "expense_status": result["status"],
        "expense_id":     step.expense_id
    }), 200


# ─── GET /approvals/history ───────────────────────────────────────────────────

@approvals_bp.route("/history", methods=["GET"])
def approval_history():
    """
    Returns all past decisions made by the current approver.
    Shows approved + rejected steps with comments and timestamps.

    Response:
    [
        {
            "step_id":      3,
            "expense_id":   7,
            "submitted_by": "John",
            "amount_in_base": 4175.0,
            "category":     "Travel",
            "your_decision": "approved",
            "your_comment":  "Looks good",
            "decided_on":   "2024-01-16T09:00:00",
            "final_status": "approved"   ← expense's overall status
        },
        ...
    ]
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    if user.is_employee:
        return jsonify({"error": "Access denied"}), 403

    # Get all steps this user has already acted on (not pending)
    acted_steps = ApprovalStep.query.filter(
        ApprovalStep.approver_id == user.id,
        ApprovalStep.status != ApprovalStepStatus.PENDING
    ).order_by(ApprovalStep.acted_at.desc()).all()

    result = []
    for step in acted_steps:
        expense = step.expense
        result.append({
            "step_id":        step.id,
            "expense_id":     expense.id,
            "submitted_by":   expense.submitter.name,
            "amount_in_base": expense.amount_in_base,
            "base_currency":  user.company.currency_code,
            "category":       expense.category,
            "description":    expense.description,
            "your_decision":  step.status,
            "your_comment":   step.comment,
            "decided_on":     step.acted_at.isoformat() if step.acted_at else None,
            "final_status":   expense.status
        })

    return jsonify(result), 200


# ─── POST /approvals/override/<expense_id> ───────────────────────────────────

@approvals_bp.route("/override/<int:expense_id>", methods=["POST"])
def admin_override(expense_id):
    """
    Admin only — forcefully approve or reject any expense,
    bypassing the normal approval chain.

    Use case: Admin needs to override a stuck approval,
    or manually resolve an edge case.

    Request body (JSON):
    {
        "decision": "approved",   ← or "rejected"
        "comment":  "Override by admin — urgent reimbursement"
    }

    Response:
    {
        "message":    "Expense overridden — marked as approved",
        "expense_id": 7
    }
    """
    user = get_current_user()
    if not user:
        return jsonify({"error": "Login required"}), 401

    if not user.is_admin:
        return jsonify({"error": "Admin access required"}), 403

    expense = Expense.query.get(expense_id)
    if not expense:
        return jsonify({"error": "Expense not found"}), 404

    # Make sure expense belongs to this admin's company
    if expense.submitter.company_id != user.company_id:
        return jsonify({"error": "Access denied"}), 403

    data     = request.get_json()
    decision = data.get("decision", "").lower()
    comment  = data.get("comment", "Admin override")

    if decision not in [ExpenseStatus.APPROVED, ExpenseStatus.REJECTED]:
        return jsonify({"error": "Decision must be 'approved' or 'rejected'"}), 400

    # ── Force the expense status ──────────────────────────────────────────────
    expense.status = decision

    # ── Mark all pending steps as skipped (set comment to show override) ──────
    for step in expense.approval_steps:
        if step.status == ApprovalStepStatus.PENDING:
            step.status   = decision
            step.comment  = f"[Admin override] {comment}"
            step.acted_at = __import__('datetime').datetime.utcnow()

    db.session.commit()

    return jsonify({
        "message":    f"Expense overridden — marked as {decision}",
        "expense_id": expense_id
    }), 200
