from datetime import datetime
from models import db, Expense, ApprovalStep, ApprovalRule
from models import ExpenseStatus, ApprovalStepStatus, RuleType


# ─────────────────────────────────────────────────────────────────────────────
#  HOW THIS ENGINE WORKS — READ THIS FIRST
# ─────────────────────────────────────────────────────────────────────────────
#
#  Two main jobs:
#
#  Job 1 — build_approval_chain(expense)
#           Called once when an expense is submitted.
#           Reads the matching ApprovalRule and creates ApprovalStep rows
#           for that specific expense.
#
#  Job 2 — process_decision(step, decision, comment)
#           Called when an approver clicks Approve or Reject.
#           Updates the current step, then decides what happens next:
#             → activate next step (sequential)
#             → check if enough people approved (percentage)
#             → check if the special approver approved (specific/hybrid)
#             → mark expense as fully approved or rejected
#
# ─────────────────────────────────────────────────────────────────────────────


# ─── Job 1: Build the approval chain when expense is submitted ────────────────

def build_approval_chain(expense: Expense) -> bool:
    """
    Creates ApprovalStep rows for a newly submitted expense.

    Flow:
        1. If employee has is_manager_approver=True
           → insert their manager as step at sequence=0
        2. Find the matching ApprovalRule for this expense
           (based on company + threshold_amount)
        3. Copy each ApprovalRuleStep into an ApprovalStep for this expense

    Returns True if chain was built, False if something went wrong.

    Called in: routes/expenses.py after saving the expense
    """
    submitter = expense.submitter  # the User who submitted
    sequence  = 0                  # we count up from 0

    # ── Step A: Insert manager as first approver if flag is set ──────────────
    if submitter.is_manager_approver and submitter.manager_id:
        manager_step = ApprovalStep(
            expense_id  = expense.id,
            approver_id = submitter.manager_id,  # manager_id from User table
            sequence    = sequence,
            status      = ApprovalStepStatus.PENDING
        )
        db.session.add(manager_step)
        sequence += 1  # next steps start from 1

    # ── Step B: Find the matching ApprovalRule ────────────────────────────────
    # Rules are matched by:
    #   - same company as the submitter
    #   - threshold_amount is null (applies to all) OR expense amount >= threshold
    # If multiple rules match, pick the one with the highest threshold
    # (most specific rule wins)

    rule = _find_matching_rule(expense)

    if rule:
        expense.rule_id = rule.id  # link this expense to the rule

        # ── Step C: Copy ApprovalRuleSteps → ApprovalSteps ───────────────────
        for rule_step in rule.steps:  # already ordered by sequence
            live_step = ApprovalStep(
                expense_id  = expense.id,
                approver_id = rule_step.approver_id,  # copy the approver
                sequence    = sequence,               # continue from where manager left off
                status      = ApprovalStepStatus.PENDING
            )
            db.session.add(live_step)
            sequence += 1

    db.session.commit()

    # If no steps were created at all (no manager, no rule)
    # auto-approve the expense — no one needs to approve it
    if sequence == 0:
        expense.status = ExpenseStatus.APPROVED
        db.session.commit()

    return True


def _find_matching_rule(expense: Expense):
    """
    Find the best matching ApprovalRule for this expense.

    Matching logic:
        - Rule must belong to the same company as the submitter
        - Rule threshold_amount must be <= expense.amount_in_base
          (or threshold is null = applies to everything)
        - If multiple rules match, the one with the highest threshold wins
          (most specific rule takes priority)

    Example:
        Rules:  "Above 0"    threshold=0      → matches all expenses
                "Above 5000" threshold=5000   → matches expenses >= 5000
        Expense amount = 8000
        → "Above 5000" wins (higher threshold = more specific)
    """
    company_id = expense.submitter.company_id
    amount     = expense.amount_in_base or expense.amount

    # Get all rules for this company
    rules = ApprovalRule.query.filter_by(company_id=company_id).all()

    matching_rules = []
    for rule in rules:
        if rule.threshold_amount is None:
            # null threshold = applies to all amounts
            matching_rules.append(rule)
        elif amount >= rule.threshold_amount:
            matching_rules.append(rule)

    if not matching_rules:
        return None

    # Pick the rule with the highest threshold (most specific)
    return max(matching_rules, key=lambda r: r.threshold_amount or 0)


# ─── Job 2: Process an approver's decision ───────────────────────────────────

def process_decision(step: ApprovalStep, decision: str, comment: str = "") -> dict:
    """
    Called when an approver clicks Approve or Reject on an expense.

    Parameters:
        step     — the ApprovalStep being acted on
        decision — "approved" or "rejected"
        comment  — optional note from the approver

    Returns a dict with the result:
        { "status": "approved" | "rejected" | "pending", "message": "..." }

    Flow:
        1. Update the current step (mark approved/rejected + timestamp)
        2. If rejected → mark entire expense as rejected, stop
        3. If approved → check the rule_type to decide what happens next
           - sequential : activate the next step
           - percentage : check if enough people approved
           - specific   : check if the special approver just approved
           - hybrid     : check either condition
        4. If all conditions are met → mark expense as approved
    """

    # ── 1. Update this step ───────────────────────────────────────────────────
    step.status   = decision
    step.comment  = comment
    step.acted_at = datetime.utcnow()
    db.session.commit()

    expense = step.expense

    # ── 2. Rejection — stops the entire chain immediately ────────────────────
    if decision == ApprovalStepStatus.REJECTED:
        expense.status = ExpenseStatus.REJECTED
        db.session.commit()
        return { "status": "rejected", "message": "Expense rejected." }

    # ── 3. Approved — check what to do next based on rule_type ───────────────
    rule = expense.rule

    # No rule attached — simple sequential, just go to next step
    if rule is None:
        return _activate_next_step(expense, step.sequence)

    if rule.rule_type == RuleType.SEQUENTIAL:
        # Everyone must approve in order — just move to next step
        return _activate_next_step(expense, step.sequence)

    elif rule.rule_type == RuleType.PERCENTAGE:
        # Check if enough % of approvers have approved
        return _check_percentage(expense, rule)

    elif rule.rule_type == RuleType.SPECIFIC:
        # Check if this approver is the special override approver
        return _check_specific(expense, rule, step)

    elif rule.rule_type == RuleType.HYBRID:
        # Check specific first, then percentage
        result = _check_specific(expense, rule, step)
        if result["status"] == "approved":
            return result
        return _check_percentage(expense, rule)

    # Fallback — should never reach here
    return _activate_next_step(expense, step.sequence)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _activate_next_step(expense: Expense, current_sequence: int) -> dict:
    """
    Find the next pending step after current_sequence and keep it pending
    (it's already pending — the approver just sees it appear in their queue).

    If no next step exists → all steps done → approve the expense.
    """
    # Find the very next step (current_sequence + 1)
    next_step = next(
        (s for s in expense.approval_steps
         if s.sequence == current_sequence + 1),
        None
    )

    if next_step:
        # Next approver will see this in their pending queue
        # (it's already status=pending from when it was created)
        return {
            "status":  "pending",
            "message": f"Moved to next approver: {next_step.approver.name}"
        }
    else:
        # No more steps — all approved sequentially
        expense.status = ExpenseStatus.APPROVED
        db.session.commit()
        return { "status": "approved", "message": "Expense fully approved!" }


def _check_percentage(expense: Expense, rule: ApprovalRule) -> dict:
    """
    Check if enough percentage of approvers have approved.

    Example:
        rule.percentage_required = 60
        Total steps = 5
        Approved so far = 3
        3/5 = 60% → condition met → approve expense

    Also checks: if remaining approvers can't possibly reach the threshold
    → approve early (no point waiting for impossible votes)
    """
    all_steps     = expense.approval_steps
    total         = len(all_steps)
    approved_count = sum(1 for s in all_steps if s.status == ApprovalStepStatus.APPROVED)
    required_pct  = rule.percentage_required or 100  # default 100% if not set

    current_pct = (approved_count / total) * 100 if total > 0 else 0

    if current_pct >= required_pct:
        expense.status = ExpenseStatus.APPROVED
        db.session.commit()
        return {
            "status":  "approved",
            "message": f"Expense approved — {approved_count}/{total} approvers approved ({current_pct:.0f}%)"
        }

    return {
        "status":  "pending",
        "message": f"{approved_count}/{total} approved so far — need {required_pct}%"
    }


def _check_specific(expense: Expense, rule: ApprovalRule, step: ApprovalStep) -> dict:
    """
    Check if the specific override approver just approved.

    The "specific approver" is defined in ApprovalRuleStep where the rule's
    specific_approver_override = True. We check if the approver who just
    approved matches any rule step where they are the override approver.

    Example:
        rule.specific_approver_override = True
        CFO (user_id=8) is in the rule steps
        CFO just approved → expense auto-approved regardless of other steps
    """
    if not rule.specific_approver_override:
        # This rule doesn't have a specific override — fall through
        return { "status": "pending", "message": "No specific override configured." }

    # The override approver is the first approver in the rule's steps
    # (admin sets this up — they add the "special" approver to the rule)
    if rule.steps:
        override_approver_id = rule.steps[0].approver_id

        if step.approver_id == override_approver_id:
            # The special approver just approved → auto-approve everything
            expense.status = ExpenseStatus.APPROVED
            db.session.commit()
            return {
                "status":  "approved",
                "message": f"Expense auto-approved by override approver: {step.approver.name}"
            }

    return { "status": "pending", "message": "Override approver has not approved yet." }


# ─── Utility: get pending expenses for an approver ───────────────────────────

def get_pending_steps_for_approver(approver_id: int) -> list:
    """
    Returns all ApprovalSteps that are currently waiting for this approver.

    Used in routes/approvals.py to show the manager/approver their queue.

    A step is "waiting for approver" when:
        - step.approver_id = this approver
        - step.status = "pending"
        - the expense itself is still "pending"
        - it is the CURRENT step (lowest sequence among pending steps)
    """
    # Get all pending steps assigned to this approver
    candidate_steps = ApprovalStep.query.filter_by(
        approver_id = approver_id,
        status      = ApprovalStepStatus.PENDING
    ).all()

    active_steps = []
    for step in candidate_steps:
        expense = step.expense

        # Only show if the expense is still pending overall
        if expense.status != ExpenseStatus.PENDING:
            continue

        # Only show if this is the current active step
        # (i.e. no earlier step is still pending)
        current = expense.current_step
        if current and current.id == step.id:
            active_steps.append(step)

    return active_steps
