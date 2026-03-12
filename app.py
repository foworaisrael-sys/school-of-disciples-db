from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, Response
from flask_login import LoginManager, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Student, Attendance, Payment, AcademicSession, Module
from config import Config
from datetime import date, datetime
from flask import send_file
from fpdf import FPDF
from io import BytesIO, StringIO
import os
import re
import csv
import sys

app = Flask(__name__)
app.config.from_object(Config)
db.init_app(app)

# Context processor to make date and datetime available in all templates
@app.context_processor
def utility_processor():
    return dict(date=date, datetime=datetime)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Please log in to access this page.'
login_manager.login_message_category = 'warning'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Create tables & default admin (run once)
def init_database():
    """Initialize database with tables and default data"""
    try:
        db.create_all()
        print("Database tables created successfully")
        
        # Use environment variable for admin password, fallback only for development
        admin_password = os.environ.get('ADMIN_PASSWORD', 'sod2026admin')
        if not User.query.filter_by(username='admin').first():
            admin = User(
                username='admin',
                password_hash=generate_password_hash(admin_password)
            )
            db.session.add(admin)
            db.session.commit()
            print(f"Default admin created: username=admin, password={admin_password}")
        
        # Create default academic session if none exists
        if not AcademicSession.query.first():
            current_year = date.today().year
            next_year = current_year + 1
            default_session = AcademicSession(
                name=f"{current_year}/{next_year}",
                start_date=date(current_year, 9, 1),
                end_date=date(next_year, 8, 31),
                is_active=True
            )
            db.session.add(default_session)
            db.session.commit()
            print(f"Created default academic session: {default_session.name}")
            
            # Create default modules for the session (1-10)
            for i in range(1, 11):
                module = Module(
                    module_number=i,
                    name=f"Module {i}",
                    session_id=default_session.id
                )
                db.session.add(module)
            db.session.commit()
            print("Created default modules 1-10")
    except Exception as e:
        print(f"Error initializing database: {e}", file=sys.stderr)

# Initialize database within app context
with app.app_context():
    init_database()

def is_valid_matric(matric):
    """Validate matric number format: SOD + 4 digits year + 5 digits number"""
    if not matric:
        return False
    return bool(re.match(r'^SOD\d{4}\d{5}$', matric))

def is_valid_phone(phone):
    """Validate phone number (simple validation)"""
    if not phone:
        return False
    # Remove common phone number characters
    cleaned = re.sub(r'[\s\-\(\)]', '', phone)
    # Check if it's mostly digits and has reasonable length
    return cleaned.isdigit() and 10 <= len(cleaned) <= 15

def find_student_by_identifier(identifier):
    """Find student by either matric_no or phone"""
    identifier = identifier.strip().upper()
    
    # Try to find by matric_no first
    student = Student.query.filter_by(matric_no=identifier).first()
    if student:
        return student
    
    # Try to find by phone (with various formats)
    # Remove common separators for comparison
    clean_identifier = re.sub(r'[\s\-\(\)]', '', identifier)
    students = Student.query.all()
    for s in students:
        if s.phone:
            clean_phone = re.sub(r'[\s\-\(\)]', '', s.phone)
            if clean_phone == clean_identifier:
                return s
    
    return None

def handle_database_operation(operation, success_message, error_message):
    """Helper function to handle database operations with error handling"""
    try:
        operation()
        db.session.commit()
        flash(success_message, 'success')
        return True
    except Exception as e:
        db.session.rollback()
        flash(f'{error_message}: {str(e)}', 'danger')
        return False

def get_active_session():
    """Get the currently active academic session"""
    return AcademicSession.query.filter_by(is_active=True).first()

def get_session_modules(session_id=None):
    """Get modules for a session"""
    if not session_id:
        session = get_active_session()
        if session:
            session_id = session.id
        else:
            return []
    
    return Module.query.filter_by(session_id=session_id).order_by(Module.module_number).all()

@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    
    if request.method == 'POST':
        username = request.form['username'].strip()
        password = request.form['password']
        
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash(f'Welcome back, {username}!', 'success')
            return redirect(url_for('dashboard'))
        flash('Invalid username or password', 'danger')
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out successfully', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    active_session = get_active_session()
    
    # Get statistics for dashboard
    total_students = Student.query.count()
    if active_session:
        session_students = Student.query.filter_by(session_id=active_session.id).count()
    else:
        session_students = 0
    
    today_attendance = Attendance.query.filter_by(date=date.today()).count()
    recent_payments = Payment.query.order_by(Payment.date_paid.desc()).limit(5).all()
    
    # Get attendance summary for today
    attendance_summary = {
        'present': Attendance.query.filter_by(date=date.today(), status='Present').count(),
        'late': Attendance.query.filter_by(date=date.today(), status='Late').count(),
        'absent': Attendance.query.filter_by(date=date.today(), status='Absent').count()
    }
    
    return render_template('dashboard.html', 
                         total_students=total_students,
                         session_students=session_students,
                         today_attendance=today_attendance,
                         recent_payments=recent_payments,
                         attendance_summary=attendance_summary,
                         active_session=active_session)

@app.route('/sessions', methods=['GET', 'POST'])
@login_required
def manage_sessions():
    """Manage academic sessions"""
    if request.method == 'POST':
        name = request.form['name'].strip()
        start_date = datetime.strptime(request.form['start_date'], '%Y-%m-%d').date()
        end_date = datetime.strptime(request.form['end_date'], '%Y-%m-%d').date()
        is_active = 'is_active' in request.form
        
        # If this session is set as active, deactivate all others
        if is_active:
            AcademicSession.query.update({AcademicSession.is_active: False})
        
        session = AcademicSession(
            name=name,
            start_date=start_date,
            end_date=end_date,
            is_active=is_active
        )
        
        def add_session():
            db.session.add(session)
            db.session.flush()  # Get the session ID
            
            # Create default modules for the session (1-10)
            for i in range(1, 11):
                module = Module(
                    module_number=i,
                    name=f"Module {i}",
                    session_id=session.id
                )
                db.session.add(module)
        
        if handle_database_operation(add_session, 
                                   f'Academic session {name} created successfully with modules 1-10',
                                   'Failed to create session'):
            return redirect(url_for('manage_sessions'))
    
    sessions = AcademicSession.query.order_by(AcademicSession.created_at.desc()).all()
    return render_template('sessions.html', sessions=sessions)

@app.route('/session/<int:session_id>/activate')
@login_required
def activate_session(session_id):
    """Activate a specific academic session"""
    session = AcademicSession.query.get_or_404(session_id)
    
    # Deactivate all sessions
    AcademicSession.query.update({AcademicSession.is_active: False})
    
    # Activate the selected session
    session.is_active = True
    db.session.commit()
    
    flash(f'Academic session {session.name} is now active', 'success')
    return redirect(url_for('manage_sessions'))

@app.route('/register_student', methods=['GET', 'POST'])
@login_required
def register_student():
    active_session = get_active_session()
    
    if request.method == 'POST':
        matric_no = request.form.get('matric_no', '').strip().upper()
        phone = request.form.get('phone', '').strip()
        first_name = request.form['first_name'].strip().title()
        last_name = request.form['last_name'].strip().title()
        email = request.form.get('email', '').strip()
        
        # Validate that at least one identifier is provided
        if not matric_no and not phone:
            flash('Please provide either Matric Number or Phone Number', 'danger')
            return redirect(url_for('register_student'))
        
        # Validate matric if provided
        if matric_no and not is_valid_matric(matric_no):
            flash('Invalid matric format. Use format: SOD202620949', 'danger')
            return redirect(url_for('register_student'))
        
        # Validate phone if provided
        if phone and not is_valid_phone(phone):
            flash('Invalid phone number format', 'danger')
            return redirect(url_for('register_student'))
        
        # Check if student already exists
        if matric_no and Student.query.filter_by(matric_no=matric_no).first():
            flash('Student with this matric number already exists', 'warning')
            return redirect(url_for('register_student'))
        
        if phone:
            # Clean phone for checking
            clean_phone = re.sub(r'[\s\-\(\)]', '', phone)
            existing = Student.query.all()
            for s in existing:
                if s.phone and re.sub(r'[\s\-\(\)]', '', s.phone) == clean_phone:
                    flash('Student with this phone number already exists', 'warning')
                    return redirect(url_for('register_student'))
        
        # Get session_id from form or use active session
        session_id = request.form.get('session_id')
        if not session_id and active_session:
            session_id = active_session.id
        
        student = Student(
            matric_no=matric_no if matric_no else None,
            phone=phone if phone else None,
            first_name=first_name,
            last_name=last_name,
            email=email,
            session_id=session_id
        )
        
        def add_student():
            db.session.add(student)
        
        id_display = matric_no or phone
        if handle_database_operation(add_student, 
                                   f'Student {first_name} {last_name} registered successfully with ID: {id_display}', 
                                   'Failed to register student'):
            return redirect(url_for('list_students'))
    
    # Get all sessions for dropdown
    sessions = AcademicSession.query.all()
    return render_template('register_student.html', 
                         sessions=sessions, 
                         active_session=active_session)

@app.route('/edit_student/<int:student_id>', methods=['GET', 'POST'])
@login_required
def edit_student(student_id):
    """Edit student information"""
    student = Student.query.get_or_404(student_id)
    active_session = get_active_session()
    
    if request.method == 'POST':
        matric_no = request.form.get('matric_no', '').strip().upper()
        phone = request.form.get('phone', '').strip()
        first_name = request.form['first_name'].strip().title()
        last_name = request.form['last_name'].strip().title()
        email = request.form.get('email', '').strip()
        
        # Validate that at least one identifier is provided
        if not matric_no and not phone:
            flash('Please provide either Matric Number or Phone Number', 'danger')
            return redirect(url_for('edit_student', student_id=student.id))
        
        # Validate matric if provided
        if matric_no and not is_valid_matric(matric_no):
            flash('Invalid matric format. Use format: SOD202620949', 'danger')
            return redirect(url_for('edit_student', student_id=student.id))
        
        # Validate phone if provided
        if phone and not is_valid_phone(phone):
            flash('Invalid phone number format', 'danger')
            return redirect(url_for('edit_student', student_id=student.id))
        
        # Check if matric number already exists (if changed)
        if matric_no and matric_no != student.matric_no:
            existing = Student.query.filter_by(matric_no=matric_no).first()
            if existing:
                flash('Student with this matric number already exists', 'warning')
                return redirect(url_for('edit_student', student_id=student.id))
        
        # Check if phone already exists (if changed)
        if phone and phone != student.phone:
            clean_phone = re.sub(r'[\s\-\(\)]', '', phone)
            existing = Student.query.all()
            for s in existing:
                if s.id != student.id and s.phone and re.sub(r'[\s\-\(\)]', '', s.phone) == clean_phone:
                    flash('Student with this phone number already exists', 'warning')
                    return redirect(url_for('edit_student', student_id=student.id))
        
        # Update student information
        student.matric_no = matric_no if matric_no else None
        student.phone = phone if phone else None
        student.first_name = first_name
        student.last_name = last_name
        student.email = email
        student.session_id = request.form.get('session_id') or student.session_id
        
        def update_student():
            db.session.commit()
        
        if handle_database_operation(update_student, 
                                   f'Student {first_name} {last_name} updated successfully', 
                                   'Failed to update student'):
            return redirect(url_for('view_details', student_id=student.id))
    
    # Get all sessions for dropdown
    sessions = AcademicSession.query.all()
    return render_template('edit_student.html', 
                         student=student, 
                         sessions=sessions, 
                         active_session=active_session)

@app.route('/attendance', methods=['GET', 'POST'])
@login_required
def attendance():
    active_session = get_active_session()
    modules = get_session_modules(active_session.id if active_session else None)
    
    if request.method == 'POST':
        identifier = request.form['identifier'].strip().upper()
        module_id = request.form.get('module_id')
        
        if not module_id:
            flash('Please select a module', 'danger')
            return redirect(url_for('attendance'))
        
        # Find student by identifier (matric or phone)
        student = find_student_by_identifier(identifier)
        
        if not student:
            flash('Student not found. Please check the matric number or phone number.', 'danger')
            return redirect(url_for('attendance'))
        
        # Check if attendance already recorded today for this module
        existing = Attendance.query.filter_by(
            student_id=student.id, 
            module_id=module_id,
            date=date.today()
        ).first()
        
        if existing:
            module = Module.query.get(module_id)
            flash(f'Attendance already recorded today for {student.full_name} in Module {module.module_number} as "{existing.status}"', 'warning')
        else:
            # Get session_id from student or use active session
            session_id = student.session_id or (active_session.id if active_session else None)
            
            att = Attendance(
                student_id=student.id,
                module_id=module_id,
                status=request.form['status'],
                session_id=session_id
            )
            
            def add_attendance():
                db.session.add(att)
            
            module = Module.query.get(module_id)
            if handle_database_operation(add_attendance,
                                       f'Attendance recorded for {student.full_name} in Module {module.module_number} as {request.form["status"]}',
                                       'Failed to record attendance'):
                return redirect(url_for('list_attendance'))
    
    # Get recent students for quick selection
    recent_students = Student.query.order_by(Student.registered_on.desc()).limit(10).all()
    return render_template('attendance.html', 
                         recent_students=recent_students,
                         modules=modules,
                         active_session=active_session)

@app.route('/payment', methods=['GET', 'POST'])
@login_required
def payment():
    active_session = get_active_session()
    
    if request.method == 'POST':
        identifier = request.form['identifier'].strip().upper()
        
        # Find student by identifier
        student = find_student_by_identifier(identifier)
        
        if not student:
            flash('Student not found', 'danger')
            return redirect(url_for('payment'))
        
        try:
            amount = float(request.form['amount'])
            if amount <= 0:
                flash('Amount must be greater than 0', 'danger')
                return redirect(url_for('payment'))
        except ValueError:
            flash('Invalid amount', 'danger')
            return redirect(url_for('payment'))
        
        # Get session_id from student or use active session
        session_id = student.session_id or (active_session.id if active_session else None)
        
        pay = Payment(
            student_id=student.id,
            payment_type=request.form['payment_type'].strip().title(),
            amount=amount,
            status=request.form['status'],
            session_id=session_id,
            notes=request.form.get('notes', '').strip()
        )
        
        def add_payment():
            db.session.add(pay)
        
        if handle_database_operation(add_payment,
                                   f'Payment of ₦{amount:,.2f} recorded for {student.full_name}',
                                   'Failed to record payment'):
            return redirect(url_for('view_details', student_id=student.id))
    
    # Get recent students for quick selection
    recent_students = Student.query.order_by(Student.registered_on.desc()).limit(10).all()
    return render_template('payment.html', recent_students=recent_students)

@app.route('/student/<int:student_id>')
@login_required
def view_student(student_id):
    """View student by ID"""
    student = Student.query.get(student_id)
    if not student:
        flash('Student not found', 'danger')
        return redirect(url_for('list_students'))
    return redirect(url_for('view_details', student_id=student_id))

@app.route('/view/<int:student_id>')
@login_required
def view_details(student_id):
    student = Student.query.get_or_404(student_id)
    
    # Get today's attendance across all modules
    today_attendances = Attendance.query.filter_by(
        student_id=student.id, 
        date=date.today()
    ).all()
    
    # Get attendance history with module info
    attendance_history = Attendance.query.filter_by(
        student_id=student.id
    ).order_by(Attendance.date.desc(), Attendance.time.desc()).all()
    
    payments = Payment.query.filter_by(student_id=student.id).order_by(Payment.date_paid.desc()).all()
    
    # Calculate total payments
    total_paid = sum(p.amount for p in payments if p.status == 'Paid')
    
    return render_template('view_student.html', 
                         student=student, 
                         today_attendances=today_attendances,
                         attendance_history=attendance_history,
                         payments=payments,
                         total_paid=total_paid)

@app.route('/list_students')
@login_required
def list_students():
    page = request.args.get('page', 1, type=int)
    per_page = 20
    search = request.args.get('search', '').strip()
    session_filter = request.args.get('session', 'all')
    
    # Base query
    query = Student.query
    
    # Apply session filter
    if session_filter != 'all':
        query = query.filter_by(session_id=int(session_filter))
    
    # Apply search filter
    if search:
        query = query.filter(
            (Student.matric_no.contains(search.upper())) |
            (Student.phone.contains(search)) |
            (Student.first_name.contains(search.title())) |
            (Student.last_name.contains(search.title()))
        )
    
    students = query.order_by(Student.id.desc()).paginate(page=page, per_page=per_page, error_out=False)
    
    # Get all sessions for filter dropdown
    sessions = AcademicSession.query.all()
    
    return render_template('list_students.html', 
                         students=students, 
                         search=search,
                         sessions=sessions,
                         selected_session=session_filter,
                         page=page)

@app.route('/delete_student/<int:student_id>', methods=['POST'])
@login_required
def delete_student(student_id):
    """Delete a student and all related records"""
    student = Student.query.get(student_id)
    
    if not student:
        flash('Student not found', 'danger')
        return redirect(url_for('list_students'))
    
    # Store student name for confirmation message
    student_name = student.full_name
    identifier = student.identifier
    
    try:
        # Delete the student (cascade will handle attendances and payments)
        db.session.delete(student)
        db.session.commit()
        flash(f'Student {student_name} ({identifier}) has been deleted successfully', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Failed to delete student: {str(e)}', 'danger')
    
    return redirect(url_for('list_students'))

@app.route('/export_students_csv')
@login_required
def export_students_csv():
    """Export students to CSV file"""
    session_filter = request.args.get('session', 'all')
    
    # Filter students by session if specified
    if session_filter != 'all':
        students = Student.query.filter_by(session_id=int(session_filter)).all()
        session = AcademicSession.query.get(int(session_filter))
        session_name = session.name if session else 'All'
    else:
        students = Student.query.all()
        session_name = 'All'
    
    # Create CSV data
    si = StringIO()
    cw = csv.writer(si)
    
    # Write headers
    cw.writerow(['ID', 'First Name', 'Last Name', 'Email', 'Phone', 'Matric No', 'Session', 'Total Payments', 'Attendance Count'])
    
    # Write data rows
    for s in students:
        cw.writerow([
            s.identifier,
            s.first_name,
            s.last_name,
            s.email or '',
            s.phone or '',
            s.matric_no or 'N/A',
            s.session.name if s.session else 'N/A',
            f"₦{s.total_paid:,.2f}",
            s.attendance_count
        ])
    
    output = si.getvalue()
    si.close()
    
    # Create response
    filename = f'students_{session_name}_{date.today().strftime("%Y%m%d")}.csv'
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/export_students_pdf')
@login_required
def export_students_pdf():
    session_filter = request.args.get('session', 'all')
    
    # Filter students by session if specified
    if session_filter != 'all':
        students = Student.query.filter_by(session_id=int(session_filter)).all()
        session = AcademicSession.query.get(int(session_filter))
        session_name = session.name if session else 'All'
    else:
        students = Student.query.all()
        session_name = 'All Sessions'
    
    try:
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", 'B', 16)
        
        # School Name
        pdf.cell(190, 10, "SCHOOL OF DISCIPLES", ln=1, align='C')
        pdf.set_font("Arial", 'B', 14)
        pdf.cell(190, 10, "Students Database", ln=1, align='C')
        pdf.set_font("Arial", size=10)
        pdf.cell(190, 10, f"Session: {session_name}", ln=1, align='C')
        pdf.cell(190, 10, f"Generated on {date.today().strftime('%d %B %Y')}", ln=1, align='C')
        pdf.ln(10)
        
        # Table headers
        pdf.set_font("Arial", 'B', 8)
        headers = ['ID', 'First Name', 'Last Name', 'Email', 'Phone', 'Session']
        col_widths = [25, 25, 25, 45, 35, 35]
        
        for i, header in enumerate(headers):
            pdf.cell(col_widths[i], 10, header, 1, 0, 'C')
        pdf.ln()
        
        # Data rows
        pdf.set_font("Arial", size=6)
        for s in students:
            student_id = s.identifier[:15] if s.identifier else 'N/A'
            email = (s.email[:20] + '...') if s.email and len(s.email) > 20 else (s.email or '')
            phone = s.phone or ''
            session_name_display = s.session.name if s.session else 'N/A'
            
            pdf.cell(col_widths[0], 10, student_id, 1)
            pdf.cell(col_widths[1], 10, s.first_name[:15], 1)
            pdf.cell(col_widths[2], 10, s.last_name[:15], 1)
            pdf.cell(col_widths[3], 10, email, 1)
            pdf.cell(col_widths[4], 10, phone, 1)
            pdf.cell(col_widths[5], 10, session_name_display[:15], 1)
            pdf.ln()
        
        output = BytesIO()
        pdf.output(output)
        output.seek(0)
        
    except Exception as e:
        flash(f'Error creating PDF file: {str(e)}', 'danger')
        return redirect(url_for('list_students'))
    
    filename = f'students_{session_name}_{date.today().strftime("%Y%m%d")}.pdf'
    return send_file(output, 
                    as_attachment=True, 
                    download_name=filename, 
                    mimetype='application/pdf')

@app.route('/list_attendance', methods=['GET', 'POST'])
@login_required
def list_attendance():
    # Handle date selection
    if request.method == 'POST':
        selected_date = request.form.get('selected_date')
    else:
        selected_date = request.args.get('date', date.today().isoformat())
    
    # Get module filter
    module_filter = request.args.get('module', 'all')
    session_filter = request.args.get('session', 'all')
    
    # Validate date
    try:
        selected_date_obj = datetime.strptime(selected_date, '%Y-%m-%d').date()
    except (ValueError, TypeError):
        flash('Invalid date format', 'danger')
        selected_date_obj = date.today()
        selected_date = selected_date_obj.isoformat()
    
    # Get students based on session filter
    if session_filter != 'all':
        all_students = Student.query.filter_by(session_id=int(session_filter)).all()
    else:
        all_students = Student.query.all()
    
    # Get modules for filter
    if session_filter != 'all':
        modules = Module.query.filter_by(session_id=int(session_filter)).order_by(Module.module_number).all()
    else:
        modules = Module.query.order_by(Module.module_number).all()
    
    # Get attendance for the selected date
    attendance_query = Attendance.query.filter_by(date=selected_date_obj)
    
    if module_filter != 'all':
        attendance_query = attendance_query.filter_by(module_id=int(module_filter))
    
    attendances = attendance_query.all()
    
    # Create a dict for quick lookup
    attendance_dict = {}
    for a in attendances:
        key = f"{a.student_id}_{a.module_id}"
        attendance_dict[key] = a
    
    # Build list with status
    student_attendance = []
    for student in all_students:
        for module in modules:
            key = f"{student.id}_{module.id}"
            att = attendance_dict.get(key)
            status = att.status if att else 'Absent'
            time_str = att.time.strftime('%H:%M:%S') if att else 'N/A'
            student_attendance.append({
                'student_id': student.id,
                'matric_no': student.matric_no,
                'phone': student.phone,
                'name': student.full_name,
                'module_number': module.module_number,
                'module_name': module.name,
                'status': status,
                'time': time_str,
                'session': student.session.name if student.session else 'N/A'
            })
    
    # Calculate statistics
    total_present = sum(1 for sa in student_attendance if sa['status'] == 'Present')
    total_absent = sum(1 for sa in student_attendance if sa['status'] == 'Absent')
    total_late = sum(1 for sa in student_attendance if sa['status'] == 'Late')
    
    # Get all sessions for filter
    sessions = AcademicSession.query.all()
    
    return render_template('list_attendance.html', 
                         student_attendance=student_attendance,
                         selected_date=selected_date,
                         today=date.today().isoformat(),
                         total_present=total_present,
                         total_absent=total_absent,
                         total_late=total_late,
                         total_students=len(all_students),
                         total_modules=len(modules),
                         sessions=sessions,
                         modules=modules,
                         selected_session=session_filter,
                         selected_module=module_filter)

@app.route('/attendance_report')
@login_required
def attendance_report():
    """Generate attendance report for date range"""
    start_date = request.args.get('start_date', date.today().replace(day=1).isoformat())
    end_date = request.args.get('end_date', date.today().isoformat())
    module_filter = request.args.get('module', 'all')
    session_filter = request.args.get('session', 'all')
    
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date range', 'danger')
        start = date.today().replace(day=1)
        end = date.today()
        start_date = start.isoformat()
        end_date = end.isoformat()
    
    # Base query
    query = db.session.query(
        Student.id.label('student_id'),
        Student.matric_no,
        Student.phone,
        Student.first_name,
        Student.last_name,
        Module.module_number,
        Module.name.label('module_name'),
        Attendance.date,
        Attendance.time,
        Attendance.status,
        AcademicSession.name.label('session_name')
    ).join(Attendance, Student.id == Attendance.student_id
    ).join(Module, Attendance.module_id == Module.id
    ).join(AcademicSession, Attendance.session_id == AcademicSession.id, isouter=True
    ).filter(Attendance.date.between(start, end))
    
    # Apply session filter
    if session_filter != 'all':
        query = query.filter(Attendance.session_id == int(session_filter))
    
    # Apply module filter
    if module_filter != 'all':
        query = query.filter(Attendance.module_id == int(module_filter))
    
    attendance_data = query.order_by(Attendance.date.desc(), Module.module_number, Attendance.time.desc()).all()
    
    # Get all sessions and modules for filters
    sessions = AcademicSession.query.all()
    modules = Module.query.order_by(Module.module_number).all()
    
    return render_template('attendance_report.html',
                         attendance_data=attendance_data,
                         start_date=start_date,
                         end_date=end_date,
                         sessions=sessions,
                         modules=modules,
                         selected_session=session_filter,
                         selected_module=module_filter)

@app.route('/export_attendance_report_csv')
@login_required
def export_attendance_report_csv():
    """Export attendance report to CSV"""
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')
    module_filter = request.args.get('module', 'all')
    session_filter = request.args.get('session', 'all')
    
    if not start_date or not end_date:
        flash('Please select date range', 'danger')
        return redirect(url_for('attendance_report'))
    
    try:
        start = datetime.strptime(start_date, '%Y-%m-%d').date()
        end = datetime.strptime(end_date, '%Y-%m-%d').date()
    except ValueError:
        flash('Invalid date format', 'danger')
        return redirect(url_for('attendance_report'))
    
    # Get attendance for date range
    query = db.session.query(
        Student.matric_no,
        Student.phone,
        Student.first_name,
        Student.last_name,
        Module.module_number,
        Module.name.label('module_name'),
        Attendance.date,
        Attendance.time,
        Attendance.status,
        AcademicSession.name.label('session_name')
    ).join(Attendance, Student.id == Attendance.student_id
    ).join(Module, Attendance.module_id == Module.id
    ).join(AcademicSession, Attendance.session_id == AcademicSession.id, isouter=True
    ).filter(Attendance.date.between(start, end))
    
    if session_filter != 'all':
        query = query.filter(Attendance.session_id == int(session_filter))
    
    if module_filter != 'all':
        query = query.filter(Attendance.module_id == int(module_filter))
    
    attendance_data = query.order_by(Attendance.date.desc(), Module.module_number).all()
    
    # Create CSV
    si = StringIO()
    cw = csv.writer(si)
    
    # Write headers
    cw.writerow(['Date', 'Module', 'Matric No', 'Phone', 'First Name', 'Last Name', 'Status', 'Time', 'Session'])
    
    # Write data rows
    for record in attendance_data:
        cw.writerow([
            record.date.strftime('%Y-%m-%d'),
            f"Module {record.module_number}",
            record.matric_no or 'N/A',
            record.phone or 'N/A',
            record.first_name,
            record.last_name,
            record.status,
            record.time.strftime('%H:%M:%S') if record.time else 'N/A',
            record.session_name or 'N/A'
        ])
    
    output = si.getvalue()
    si.close()
    
    filename = f'attendance_report_{start_date}_to_{end_date}.csv'
    
    return Response(
        output,
        mimetype='text/csv',
        headers={'Content-Disposition': f'attachment; filename={filename}'}
    )

@app.route('/get_student/<identifier>')
@login_required
def get_student(identifier):
    """API endpoint to get student details for AJAX calls"""
    student = find_student_by_identifier(identifier)
    if student:
        return jsonify({
            'found': True,
            'name': student.full_name,
            'id': student.id,
            'identifier': student.identifier
        })
    return jsonify({'found': False})

@app.errorhandler(404)
def not_found_error(error):
    flash('Page not found', 'warning')
    return redirect(url_for('dashboard'))

@app.errorhandler(500)
def internal_error(error):
    db.session.rollback()
    flash('An internal error occurred', 'danger')
    return redirect(url_for('dashboard'))

if __name__ == '__main__':
    app.run(debug=True)