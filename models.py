from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import date, datetime

db = SQLAlchemy()

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    
    def __repr__(self):
        return f'<User {self.username}>'

class AcademicSession(db.Model):
    """Model for academic sessions"""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False, unique=True)  # e.g., "2025/2026"
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Relationships
    students = db.relationship('Student', back_populates='session', lazy=True)
    modules = db.relationship('Module', back_populates='session', lazy=True, cascade='all, delete-orphan')
    
    def __repr__(self):
        return f'<Session {self.name}>'

class Module(db.Model):
    """Model for class modules (1-10)"""
    id = db.Column(db.Integer, primary_key=True)
    module_number = db.Column(db.Integer, nullable=False)  # 1-10
    name = db.Column(db.String(100), nullable=True)  # Optional module name
    session_id = db.Column(db.Integer, db.ForeignKey('academic_session.id'), nullable=False)
    
    # Relationships
    session = db.relationship('AcademicSession', back_populates='modules')
    attendances = db.relationship('Attendance', back_populates='module', lazy=True, cascade='all, delete-orphan')
    
    __table_args__ = (db.UniqueConstraint('module_number', 'session_id', name='unique_module_per_session'),)
    
    def __repr__(self):
        return f'<Module {self.module_number}: {self.name or f"Module {self.module_number}"}>'

class Student(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    matric_no = db.Column(db.String(20), unique=True, nullable=True)
    phone = db.Column(db.String(30), unique=True, nullable=True)
    first_name = db.Column(db.String(100), nullable=False)
    last_name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120))
    registered_on = db.Column(db.Date, nullable=False, default=date.today)
    session_id = db.Column(db.Integer, db.ForeignKey('academic_session.id'), nullable=True)
    
    # Relationships
    session = db.relationship('AcademicSession', back_populates='students')
    attendances = db.relationship('Attendance', back_populates='student', lazy=True, cascade='all, delete-orphan')
    payments = db.relationship('Payment', back_populates='student', lazy=True, cascade='all, delete-orphan')
    
    @property
    def full_name(self):
        return f"{self.first_name} {self.last_name}"
    
    @property
    def identifier(self):
        """Return either matric_no or phone as identifier"""
        return self.matric_no or self.phone
    
    @property
    def display_id(self):
        """Display format for student ID"""
        if self.matric_no:
            return f"Matric: {self.matric_no}"
        elif self.phone:
            return f"Phone: {self.phone}"
        return "No ID"
    
    @property
    def total_paid(self):
        return sum(p.amount for p in self.payments if p.status == 'Paid')
    
    @property
    def attendance_count(self):
        return len(self.attendances)
    
    def __repr__(self):
        return f'<Student {self.identifier}: {self.full_name}>'

class Attendance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    module_id = db.Column(db.Integer, db.ForeignKey('module.id'), nullable=False)
    date = db.Column(db.Date, nullable=False, default=date.today)
    time = db.Column(db.Time, nullable=False, default=lambda: datetime.now().time())
    status = db.Column(db.String(20), nullable=False)  # Present, Absent, Late
    session_id = db.Column(db.Integer, db.ForeignKey('academic_session.id'), nullable=True)
    
    __table_args__ = (db.UniqueConstraint('student_id', 'module_id', 'date', name='unique_attendance_per_day_module'),)
    
    # Relationships
    student = db.relationship('Student', back_populates='attendances')
    module = db.relationship('Module', back_populates='attendances')
    session = db.relationship('AcademicSession')
    
    @property
    def matric_no(self):
        return self.student.matric_no if self.student else None
    
    @property
    def phone(self):
        return self.student.phone if self.student else None
    
    def __repr__(self):
        return f'<Attendance {self.student.identifier if self.student else "Unknown"} Module {self.module.module_number if self.module else "?"}: {self.status}>'

class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    student_id = db.Column(db.Integer, db.ForeignKey('student.id', ondelete='CASCADE'), nullable=False)
    payment_type = db.Column(db.String(100), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    date_paid = db.Column(db.Date, nullable=False, default=date.today)
    status = db.Column(db.String(20), nullable=False)  # Paid, Pending
    session_id = db.Column(db.Integer, db.ForeignKey('academic_session.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    
    # Relationships
    student = db.relationship('Student', back_populates='payments')
    session = db.relationship('AcademicSession')
    
    @property
    def matric_no(self):
        return self.student.matric_no if self.student else None
    
    def __repr__(self):
        return f'<Payment {self.student.identifier if self.student else "Unknown"}: ₦{self.amount}>'