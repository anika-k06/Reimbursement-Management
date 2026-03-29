from datetime import datetime
from flask_sqlalchemy import SQLAlchemy
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ─── Enums (stored as strings for portability) ───────────────────────────────

class Role:
    ADMIN    = "admin"
    MANAGER  = "manager"
    EMPLOYEE = "employee"
    ALL      = [ADMIN, MANAGER, EMPLOYEE]


class ExpenseStatus:
    PENDING   = "pending"
    APPROVED  = "approved"
    REJECTED  = "rejected"
    ALL       = [PENDING, APPROVED, REJECTED]


class ApprovalStepStatus:
    PENDING  = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    ALL      = [PENDING, APPROVED, REJECTED]


class RuleType:
    """
    sequential  – approvers work in order; all must approve
    percentage  – X% of approvers must approve (conditional)
    specific    – if a specific approver approves, auto-approved (conditional)
    hybrid      – percentage OR specific approver (conditional)
    """
    SEQUENTIAL = "sequential"
    PERCENTAGE = "percentage"
    SPECIFIC   = "specific"
    HYBRID     = "hybrid"
    ALL        = [SEQUENTIAL, PERCENTAGE, SPECIFIC, HYBRID]


# ─── Models ──────────────────────────────────────────────────────────────────

class Company(db.Model):
    """
    Created automatically when the first user signs up.
    Stores the company's base currency (set from the country selected at signup).
    """
    __tablename__ = "companies"

    id            = db.Column(db.Integer, primary_key=True)
    name          = db.Column(db.String(120), nullable=False)
    currency_code = db.Column(db.String(10), nullable=False)   # e.g. "INR", "USD"
    country       = db.Column(db.String(80), nullable=False)
    created_at    = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    users    = db.relationship("User",         back_populates="company", lazy="dynamic")
    rules    = db.relationship("ApprovalRule", back_populates="company", lazy="dynamic")

    def __repr__(self):
        return f"<Company {self.name} ({self.currency_code})>"


class User(db.Model):
    """
    Covers all three roles: admin, manager, employee.
    A user belongs to exactly one company.

    is_manager_approver:
        When True, the employee's direct manager is inserted as the FIRST
        approval step before any rule-defined steps run.
    """
    __tablename__ = "users"

    id                  = db.Column(db.Integer, primary_key=True)
    company_id          = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)
    manager_id          = db.Column(db.Integer, db.ForeignKey("users.id"),     nullable=True)

    name                = db.Column(db.String(100), nullable=False)
    email               = db.Column(db.String(150), unique=True, nullable=False)
    password_hash       = db.Column(db.String(256), nullable=False)
    role                = db.Column(db.String(20),  nullable=False, default=Role.EMPLOYEE)
    is_manager_approver = db.Column(db.Boolean, default=False)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    company      = db.relationship("Company", back_populates="users")
    manager      = db.relationship("User", remote_side="User.id", backref="subordinates")
    expenses     = db.relationship("Expense",      back_populates="submitter", lazy="dynamic")
    approval_steps = db.relationship(
        "ApprovalStep", back_populates="approver",
        foreign_keys="ApprovalStep.approver_id", lazy="dynamic"
    )

    # ── Auth helpers ──────────────────────────────────────────────────────────
    def set_password(self, password: str):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # ── Role helpers ──────────────────────────────────────────────────────────
    @property
    def is_admin(self):    return self.role == Role.ADMIN
    @property
    def is_manager(self):  return self.role == Role.MANAGER
    @property
    def is_employee(self): return self.role == Role.EMPLOYEE

    def __repr__(self):
        return f"<User {self.email} [{self.role}]>"


class Expense(db.Model):
    """
    An expense claim submitted by an employee.

    amount          – value in the currency the employee chose (e.g. USD)
    currency        – ISO code the employee submitted in (e.g. "USD")
    amount_in_base  – converted value in the company's currency (set on submit)
    rule_id         – which ApprovalRule governs this expense (can be null if
                      no rule matches; admin may override)
    status          – overall status driven by approval_engine.py
    receipt_path    – local path to the uploaded / OCR-processed receipt file
    """
    __tablename__ = "expenses"

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey("users.id"),          nullable=False)
    rule_id        = db.Column(db.Integer, db.ForeignKey("approval_rules.id"), nullable=True)

    amount         = db.Column(db.Float,   nullable=False)
    currency       = db.Column(db.String(10), nullable=False)
    amount_in_base = db.Column(db.Float,   nullable=True)   # filled by currency.py on save
    category       = db.Column(db.String(80), nullable=False)
    description    = db.Column(db.Text,    nullable=True)
    date           = db.Column(db.Date,    nullable=False)
    status         = db.Column(db.String(20), nullable=False, default=ExpenseStatus.PENDING)
    receipt_path   = db.Column(db.String(300), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    submitter      = db.relationship("User",         back_populates="expenses")
    rule           = db.relationship("ApprovalRule", back_populates="expenses")
    approval_steps = db.relationship(
        "ApprovalStep", back_populates="expense",
        order_by="ApprovalStep.sequence", cascade="all, delete-orphan", lazy="select"
    )

    # ── Helpers ───────────────────────────────────────────────────────────────
    @property
    def current_step(self):
        """Return the first pending ApprovalStep, or None if all done."""
        return next(
            (s for s in self.approval_steps if s.status == ApprovalStepStatus.PENDING),
            None
        )

    def __repr__(self):
        return f"<Expense #{self.id} {self.amount}{self.currency} [{self.status}]>"


class ApprovalStep(db.Model):
    """
    One node in the sequential approval chain for a single expense.

    Generated by approval_engine.py when the expense is submitted.
    The engine activates steps one at a time (sequence order).

    sequence    – 0 = manager step (if is_manager_approver), then 1, 2, 3…
    status      – pending / approved / rejected
    comment     – approver's note on approve/reject
    acted_at    – timestamp of the decision
    """
    __tablename__ = "approval_steps"

    id          = db.Column(db.Integer, primary_key=True)
    expense_id  = db.Column(db.Integer, db.ForeignKey("expenses.id"), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"),    nullable=False)

    sequence    = db.Column(db.Integer, nullable=False, default=0)
    status      = db.Column(db.String(20), nullable=False, default=ApprovalStepStatus.PENDING)
    comment     = db.Column(db.Text,    nullable=True)
    acted_at    = db.Column(db.DateTime, nullable=True)

    # Relationships
    expense  = db.relationship("Expense", back_populates="approval_steps")
    approver = db.relationship(
        "User", back_populates="approval_steps",
        foreign_keys=[approver_id]
    )

    def __repr__(self):
        return f"<ApprovalStep expense={self.expense_id} seq={self.sequence} [{self.status}]>"


class ApprovalRule(db.Model):
    """
    Company-level rule that defines WHO approves expenses and HOW.

    rule_type               – sequential | percentage | specific | hybrid
    threshold_amount        – expenses above this amount use this rule (in base currency)
    percentage_required     – used for 'percentage' and 'hybrid' types (0–100)
    specific_approver_override – for 'specific'/'hybrid': if the special approver
                               approves, the whole expense is immediately approved.

    Steps (ApprovalRuleStep) define the ordered list of approvers.
    """
    __tablename__ = "approval_rules"

    id                        = db.Column(db.Integer, primary_key=True)
    company_id                = db.Column(db.Integer, db.ForeignKey("companies.id"), nullable=False)

    name                      = db.Column(db.String(100), nullable=False)
    rule_type                 = db.Column(db.String(20),  nullable=False, default=RuleType.SEQUENTIAL)
    threshold_amount          = db.Column(db.Float, nullable=True)   # null = applies to all amounts
    percentage_required       = db.Column(db.Float, nullable=True)   # e.g. 60.0 for "60%"
    specific_approver_override = db.Column(db.Boolean, default=False)
    created_at                = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    company  = db.relationship("Company",          back_populates="rules")
    steps    = db.relationship(
        "ApprovalRuleStep", back_populates="rule",
        order_by="ApprovalRuleStep.sequence", cascade="all, delete-orphan", lazy="select"
    )
    expenses = db.relationship("Expense", back_populates="rule", lazy="dynamic")

    def __repr__(self):
        return f"<ApprovalRule '{self.name}' [{self.rule_type}]>"


class ApprovalRuleStep(db.Model):
    """
    A single approver slot in an ApprovalRule.
    sequence defines the order (0-indexed).

    At expense-submission time, approval_engine.py copies these into
    concrete ApprovalStep rows for that expense.
    """
    __tablename__ = "approval_rule_steps"

    id          = db.Column(db.Integer, primary_key=True)
    rule_id     = db.Column(db.Integer, db.ForeignKey("approval_rules.id"), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey("users.id"),          nullable=False)
    sequence    = db.Column(db.Integer, nullable=False, default=0)

    # Relationships
    rule     = db.relationship("ApprovalRule", back_populates="steps")
    approver = db.relationship("User")

    def __repr__(self):
        return f"<ApprovalRuleStep rule={self.rule_id} seq={self.sequence} approver={self.approver_id}>"
