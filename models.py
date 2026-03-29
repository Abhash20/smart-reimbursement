from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime

db = SQLAlchemy()

class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    base_currency = db.Column(db.String(10), nullable=False, default="USD")
    
    # Settings for approvals
    is_manager_approver = db.Column(db.Boolean, default=True) # If true, manager must approve first before workflow triggers
    
    users = db.relationship('User', backref='company', lazy=True)
    approval_rules = db.relationship('ApprovalRule', backref='company', lazy=True)

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), nullable=False, unique=True)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # Roles: 'Admin', 'CTO', 'Finance', 'Manager', 'Employee'
    role = db.Column(db.String(20), nullable=False, default='Employee')
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=True)
    manager_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    
    # Manager relationship
    subordinates = db.relationship('User', backref=db.backref('manager', remote_side=[id]))
    expenses = db.relationship('Expense', backref='employee', foreign_keys='Expense.employee_id', lazy=True)

class Expense(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    employee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    
    amount_submitted = db.Column(db.Float, nullable=False)
    currency_submitted = db.Column(db.String(10), nullable=False)
    amount_base = db.Column(db.Float, nullable=False)
    
    category = db.Column(db.String(50), nullable=False)
    description = db.Column(db.String(200), nullable=True)
    date = db.Column(db.DateTime, default=datetime.utcnow)
    receipt_image_path = db.Column(db.String(200), nullable=True)
    
    # Overall Status: 'Pending', 'Approved', 'Rejected'
    status = db.Column(db.String(20), default='Pending')
    
    # Current step in approval process (0 = requires manager, 1 = requires step 1 rule, etc.)
    current_approval_step = db.Column(db.Integer, default=0)
    
    approvals = db.relationship('ExpenseApprovalStep', backref='expense', lazy=True, cascade="all, delete-orphan")

class ApprovalRule(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    company_id = db.Column(db.Integer, db.ForeignKey('company.id'), nullable=False)
    
    sequence_step = db.Column(db.Integer, nullable=False) # e.g. 1, 2, 3
    
    # The role that must approve this step (e.g. 'Finance', 'CTO', 'Manager')
    approver_role = db.Column(db.String(50), nullable=False)
    
    # Percentage rule (e.g. 60 means 60% of ALL people with this role must approve)
    # If 0, then any *one* person with the role can approve.
    percentage_required = db.Column(db.Integer, nullable=True, default=0)

class ExpenseApprovalStep(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    expense_id = db.Column(db.Integer, db.ForeignKey('expense.id'), nullable=False)
    approver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True) 
    
    # Status: 'Approved', 'Rejected'
    status = db.Column(db.String(20), default='Approved')
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
