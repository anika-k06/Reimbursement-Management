# 💸 Reimbursement Management System

A Flask web app that automates employee expense reimbursement with multi-level approval workflows. Built in 8 hours by a team of 4.

---

## 🎯 Problem Statement

Companies struggle with manual reimbursement processes — slow approvals, no transparency, and error-prone currency conversions. This system solves that with a structured, role-based approval platform.

---

## ✅ Features

- **Employees** — Submit expenses in any currency, track approval status in real time
- **Managers** — View pending approval queue, approve/reject with comments
- **Admins** — Manage users, configure approval rules, override any expense

---

## 🧠 Approval Engine

Supports 4 rule types:

| Rule Type | Behaviour |
|-----------|-----------|
| **Sequential** | Approvers act in order. All must approve. |
| **Percentage** | X% of approvers must approve. |
| **Specific** | One designated approver's approval auto-approves the expense. |
| **Hybrid** | Specific approver OR percentage threshold — whichever comes first. |

Optionally, an employee's direct manager can be set as a **Step 0 pre-approver** before the main chain runs.

---

## 🛠️ Tech Stack

`Python` · `Flask` · `SQLite / SQLAlchemy` · `ExchangeRate API` · `REST Countries API` · `HTML / CSS / JS`

---

## 🚀 Getting Started

```bash
pip install -r requirements.txt
python app.py
```

Open `http://localhost:5000`, sign up to create your company + admin account, then set up users and approval rules from the admin dashboard.

---

## 🔌 API Overview

| Prefix | What it handles |
|--------|----------------|
| `/auth` | Signup, login, logout, current user |
| `/expenses` | Submit, view, and upload receipts |
| `/approvals` | Approve/reject steps, admin override |
| `/admin` | User management, approval rule config |

---

## 🗂️ Project Structure

```
├── app.py                  # Flask app entry point
├── config.py               # Config and environment settings
├── models.py               # Database models
├── auth.py                 # Auth routes
├── expenses.py             # Expense routes
├── approvals.py            # Approval routes
├── admin.py                # Admin routes
├── approval_engine.py      # Core approval state machine
├── currency.py             # Currency conversion helpers
├── templates
  ├── index.html            # Frontend
└── requirements.txt
```

---

## ⚙️ Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `SECRET_KEY` | `dev-secret-change-in-prod` | Flask session signing key |
| `DATABASE_URL` | `sqlite:///reimbursement.db` | Database URI |
| `FLASK_ENV` | — | Set to `production` for secure cookies |