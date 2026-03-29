import os
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
import requests
from werkzeug.utils import secure_filename
from models import db, User, Company, Expense, ApprovalRule, ExpenseApprovalStep
import math

app = Flask(__name__)
app.config['SECRET_KEY'] = 'my_super_secret_college_project_key'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///app.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['UPLOAD_FOLDER'] = 'static/uploads'

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    if request.method == 'POST':
        user = User.query.filter_by(username=request.form.get('username')).first()
        if user and bcrypt.check_password_hash(user.password_hash, request.form.get('password')):
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if current_user.is_authenticated: return redirect(url_for('dashboard'))
    if request.method == 'POST':
        c_name = request.form.get('company_name')
        b_curr = request.form.get('base_currency')
        uname = request.form.get('username')
        pwd = request.form.get('password')
        if User.query.filter_by(username=uname).first():
            flash('Username exists!', 'danger')
            return redirect(url_for('signup'))
        new_company = Company(name=c_name, base_currency=b_curr)
        db.session.add(new_company)
        db.session.commit()
        db.session.add(User(username=uname, password_hash=bcrypt.generate_password_hash(pwd).decode('utf-8'), role='Admin', company_id=new_company.id))
        db.session.commit()
        flash('Admin created!', 'success')
        return redirect(url_for('login'))
    return render_template('signup.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/')
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role in ['Admin', 'CTO']:
        expenses = Expense.query.join(User).filter(User.company_id == current_user.company_id).all()
        return render_template('dashboard_admin.html', expenses=expenses)
    elif current_user.role in ['Manager', 'Finance']:
        subordinate_ids = [sub.id for sub in current_user.subordinates]
        team_expenses = Expense.query.filter(Expense.employee_id.in_(subordinate_ids)).all() if subordinate_ids else []
        
        # Pending Step 0 means direct manager approval needed
        pending_mgr = Expense.query.filter(Expense.employee_id.in_(subordinate_ids), Expense.status == 'Pending', Expense.current_approval_step == 0).all()
        
        # Look for expenses waiting at a rule step that requires THIS user's role
        # Join ApprovalRule where step == expense.current_approval_step and role == current_user.role
        company_rules_for_me = ApprovalRule.query.filter_by(company_id=current_user.company_id, approver_role=current_user.role).all()
        my_rule_steps = [r.sequence_step for r in company_rules_for_me]
        
        pending_role_expenses = Expense.query.join(User).filter(
            User.company_id == current_user.company_id,
            Expense.status == 'Pending',
            Expense.current_approval_step.in_(my_rule_steps)
        ).all()
        
        # Merge lists and ensure we haven't already approved it!
        my_past_approvals = [step.expense_id for step in ExpenseApprovalStep.query.filter_by(approver_id=current_user.id).all()]
        
        # Filter out ones I already approved this step for
        all_pending = []
        for e in set(pending_mgr + pending_role_expenses):
            if e.id not in my_past_approvals:
                all_pending.append(e)

        return render_template('dashboard_manager.html', pending_expenses=all_pending, all_team_expenses=team_expenses)
    else:
        my_expenses = Expense.query.filter_by(employee_id=current_user.id).all()
        return render_template('dashboard_employee.html', expenses=my_expenses)

@app.route('/manage_users', methods=['GET', 'POST'])
@login_required
def manage_users():
    if current_user.role != 'Admin': return "Unauthorized", 403
    if request.method == 'POST':
        manager_id = request.form.get('manager_id')
        db.session.add(User(
            username=request.form.get('username'),
            password_hash=bcrypt.generate_password_hash(request.form.get('password')).decode('utf-8'),
            role=request.form.get('role'),
            company_id=current_user.company_id,
            manager_id=manager_id if manager_id else None
        ))
        db.session.commit()
        flash('User created!', 'success')
        return redirect(url_for('manage_users'))
    users = User.query.filter_by(company_id=current_user.company_id).all()
    mgrs = [u for u in users if u.role in ['Admin', 'Manager', 'CTO', 'Finance']]
    return render_template('manage_users.html', users=users, managers=mgrs)

@app.route('/manage_workflow', methods=['GET', 'POST'])
@login_required
def manage_workflow():
    if current_user.role != 'Admin': return "Unauthorized", 403
    if request.method == 'POST':
        db.session.add(ApprovalRule(
            company_id=current_user.company_id,
            sequence_step=int(request.form.get('sequence_step')),
            approver_role=request.form.get('approver_role'),
            percentage_required=int(request.form.get('percentage_required', 0))
        ))
        db.session.commit()
        flash('Rule added!', 'success')
        return redirect(url_for('manage_workflow'))
    rules = ApprovalRule.query.filter_by(company_id=current_user.company_id).order_by(ApprovalRule.sequence_step).all()
    return render_template('manage_workflow.html', rules=rules)

@app.route('/delete_rule/<int:rule_id>', methods=['POST'])
@login_required
def delete_rule(rule_id):
    if current_user.role != 'Admin': return "Unauthorized", 403
    rule = ApprovalRule.query.get(rule_id)
    if rule:
        db.session.delete(rule)
        db.session.commit()
        flash('Rule deleted', 'success')
    return redirect(url_for('manage_workflow'))

@app.route('/submit_expense', methods=['GET', 'POST'])
@login_required
def submit_expense():
    if request.method == 'POST':
        amount = float(request.form.get('amount'))
        currency = request.form.get('currency')
        base_curr = current_user.company.base_currency
        amt_base = amount
        if currency != base_curr:
            try:
                resp = requests.get(f"https://api.exchangerate-api.com/v4/latest/{currency}")
                amt_base = amount * resp.json().get("rates", {}).get(base_curr, 1)
            except: pass
        receipt = request.files.get('receipt')
        r_path = ""
        if receipt and receipt.filename:
            r_path = os.path.join(app.config['UPLOAD_FOLDER'], secure_filename(receipt.filename))
            receipt.save(r_path)
            
        # Is step 0 required? Yes if there's a manager_id. Else skip to 1
        start_step = 0 if current_user.manager_id else 1
        
        # But wait, what if there are no rules for step 1?
        # That check happens during approvals. A new expense is just Pending at start_step.
        exp = Expense(employee_id=current_user.id, amount_submitted=amount, currency_submitted=currency, amount_base=amt_base, category=request.form.get('category'), description=request.form.get('description'), receipt_image_path=r_path, status='Pending', current_approval_step=start_step)
        
        # If starting at step 1 but NO rules exist, auto-approve
        if start_step == 1:
            if ApprovalRule.query.filter_by(company_id=current_user.company_id).count() == 0:
                exp.status = 'Approved'
                
        db.session.add(exp)
        db.session.commit()
        flash('Submitted!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('submit_expense.html', base_curr=current_user.company.base_currency)

@app.route('/mock_ocr', methods=['POST'])
@login_required
def mock_ocr():
    return jsonify({"amount": 42.50, "currency": "USD", "category": "Food", "description": "Team lunch at Burger King"})

def check_step_completion(expense):
    # Check if the current step is fully satisfied
    rule = ApprovalRule.query.filter_by(sequence_step=expense.current_approval_step, company_id=expense.employee.company_id).first()
    if not rule:
        # Invalid step, means we passed all rules
        expense.status = 'Approved'
        return
        
    if rule.percentage_required > 0:
        role_count = User.query.filter_by(role=rule.approver_role, company_id=expense.employee.company_id).count()
        required = math.ceil(role_count * (rule.percentage_required / 100))
        
        # Count approvals for this expense by users of this role
        approvals = ExpenseApprovalStep.query.join(User).filter(ExpenseApprovalStep.expense_id==expense.id, User.role==rule.approver_role, ExpenseApprovalStep.status=='Approved').count()
        if approvals >= required:
            expense.current_approval_step += 1
            check_further(expense)
    else:
        # Just 1 approval needed
        expense.current_approval_step += 1
        check_further(expense)

def check_further(expense):
    # check if the new step exists, if not, Approved
    max_step = db.session.query(db.func.max(ApprovalRule.sequence_step)).filter_by(company_id=expense.employee.company_id).scalar()
    if not max_step or expense.current_approval_step > max_step:
        expense.status = 'Approved'

@app.route('/approve/<int:expense_id>/<action>', methods=['POST'])
@login_required
def approve_expense(expense_id, action):
    expense = Expense.query.get_or_404(expense_id)
    
    # CTO / Admin Override
    if current_user.role in ['Admin', 'CTO'] and request.form.get('force_override'):
        expense.status = 'Approved' if action == 'approve' else 'Rejected'
        db.session.add(ExpenseApprovalStep(expense_id=expense.id, approver_id=current_user.id, status=expense.status))
        db.session.commit()
        flash(f'Expense overriden to {expense.status}', 'success')
        return redirect(url_for('dashboard'))
        
    if action == 'reject':
        expense.status = 'Rejected'
        db.session.add(ExpenseApprovalStep(expense_id=expense.id, approver_id=current_user.id, status='Rejected'))
        db.session.commit()
        flash('Expense rejected.', 'success')
        return redirect(url_for('dashboard'))
        
    # Standard Approval
    if expense.current_approval_step == 0:
        # Manager step
        if current_user.id == expense.employee.manager_id:
            db.session.add(ExpenseApprovalStep(expense_id=expense.id, approver_id=current_user.id, status='Approved'))
            expense.current_approval_step += 1
            check_further(expense)
    else:
        # Check rule
        rule = ApprovalRule.query.filter_by(sequence_step=expense.current_approval_step, company_id=current_user.company_id).first()
        if rule and current_user.role == rule.approver_role:
            db.session.add(ExpenseApprovalStep(expense_id=expense.id, approver_id=current_user.id, status='Approved'))
            check_step_completion(expense)
            
    db.session.commit()
    flash('Approved successfully.', 'success')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    with app.app_context(): db.create_all()
    app.run(debug=True, port=5000)
