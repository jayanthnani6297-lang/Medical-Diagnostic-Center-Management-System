from flask import Flask, render_template, request, redirect, session, url_for, flash
from database import init_db
from ai_module import calculate_risk
from ai_module import interpret_results
from hash_module import generate_hash
from qr_module import generate_qr
from status_utils import StatusManager
from reference_utils import ReferenceChecker
import traceback
import sqlite3
import os
import json
import time
import bcrypt
from functools import wraps
import random
import sys
import secrets
import hmac
import hashlib
import requests
from datetime import datetime
import threading
from security_utils import security_manager
from decorators import role_required, admin_or_role_required
# ML imports
from ml_routes import ml_bp
from ml_models import ml_disease_model  # Changed from ml_manager
from notification_service import NotificationService

print(os.path.abspath("medical.db"))

# Test definitions mapping
TEST_DEFINITIONS = {
    "cbc": [
        "hemoglobin", "wbc", "rbc",
        "platelets", "hematocrit",
        "mcv", "mch", "mchc"
    ],
    "diabetes": [
        "fasting_glucose",
        "postprandial_glucose",
        "hba1c"
    ],
    "lipid": [
        "total_cholesterol",
        "hdl",
        "ldl",
        "triglycerides",
        "vldl",
        "cardiac_ratio"
    ],
    "bp": [
        "systolic",
        "diastolic",
        "pulse_rate"
    ],
    "bmi": [
        "height",
        "weight",
        "bmi"
    ]
}

# Default ranges for individual tests (when not part of a panel)
INDIVIDUAL_TEST_RANGES = {
    'fasting_glucose': (70, 200),
    'postprandial_glucose': (90, 250),
    'random_glucose': (70, 250),
    'hba1c': (4.0, 10.0),
    'total_cholesterol': (120, 320),
    'hdl': (25, 85),
    'ldl': (50, 220),
    'triglycerides': (50, 400),
    'tsh': (0.5, 10.0),
    't3': (70, 200),
    't4': (4, 12),
    'ft3': (2, 7),
    'ft4': (0.8, 2.5),
    'vitamin_d': (10, 100),
    'vitamin_b12': (150, 1000),
    'ferritin': (10, 300),
    'crp': (0.1, 10),
    'urine_routine': (0, 100),
    'urine_culture': (0, 100000),
    'microalbumin': (0, 300),
    'blood_culture': (0, 1),
}

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', os.urandom(24))

# Public URL for QR codes - CHANGE THIS TO YOUR ACTUAL URL
For local demo with ngrok: https://your-ngrok-url.ngrok.io
# For production: https://yourdomain.com
BASE_URL = os.environ.get('BASE_URL', 'http://localhost:5000') # Change this to your actual URL
print(f"✅ Using public URL: {BASE_URL}")
print(f"✅ QR codes will use this URL for secure report access")

# Report generation lock to prevent duplicates
report_generation_locks = {}

@app.template_filter('fromjson')
def fromjson_filter(value):
    try:
        return json.loads(value)
    except:
        return {}

init_db()

# Register Security Blueprint
try:
    from security_routes import security_bp
    app.register_blueprint(security_bp)
    print("✅ Security Dashboard registered at /security/dashboard")
except Exception as e:
    print(f"⚠️ Security Dashboard not available: {e}")

# Register ML Blueprint
try:
    app.register_blueprint(ml_bp)
    print("✅ ML Dashboard registered at /ml/dashboard")
except Exception as e:
    print(f"❌ Failed to register ML blueprint: {e}")

def create_notifications_table():
    """Create notifications table if it doesn't exist"""
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            patient_id INTEGER NOT NULL,
            recipient TEXT NOT NULL,
            type TEXT NOT NULL,
            subject TEXT,
            message TEXT NOT NULL,
            secure_link TEXT NOT NULL,
            token TEXT NOT NULL,
            status TEXT DEFAULT 'pending',
            sent_at TIMESTAMP,
            delivered_at TIMESTAMP,
            error_message TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (report_id) REFERENCES reports(report_id),
            FOREIGN KEY (patient_id) REFERENCES patients(patient_id)
        )
    """)
    conn.commit()
    conn.close()
    print("✅ Notifications table ready")

create_notifications_table()

# ===============================
# HELPER FUNCTIONS
# ===============================

def log_action(cursor, username, action, details):
    if cursor:
        try:
            role = session.get('role', 'unknown')
            cursor.execute("""
                INSERT INTO audit_logs (actor, role, action, details, ip_address)
                VALUES (?, ?, ?, ?, ?)
            """, (username, role, action, json.dumps(details), request.remote_addr))
        except sqlite3.ProgrammingError:
            # Cursor is closed, create a new connection
            conn = sqlite3.connect("medical.db", timeout=30)
            new_cursor = conn.cursor()
            role = session.get('role', 'unknown')
            new_cursor.execute("""
                INSERT INTO audit_logs (actor, role, action, details, ip_address)
                VALUES (?, ?, ?, ?, ?)
            """, (username, role, action, json.dumps(details), request.remote_addr))
            conn.commit()
            conn.close()

def update_sample_status(cursor, patient_test_id, status, note=""):
    StatusManager.update_status(patient_test_id, status, note, cursor)

def check_critical_values(patient_test_id):
    """Check for critical values and create alerts"""
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT parameter_name, parameter_value, flag, tr.patient_test_id, pt.patient_id
        FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE tr.patient_test_id = ? AND flag LIKE '%Critical%'
    """, (patient_test_id,))

    criticals = cursor.fetchall()

    for critical in criticals:
        # Insert into critical_alerts table
        cursor.execute("""
            INSERT INTO critical_alerts
            (patient_test_id, patient_id, test_name, test_value, critical_range)
            VALUES (?, ?, ?, ?, ?)
        """, (critical[3], critical[4], critical[0], critical[1], critical[2]))

        # Log the critical alert
        log_action(cursor, 'system', 'CRITICAL_ALERT', {
            'patient_test_id': critical[3],
            'parameter': critical[0],
            'value': critical[1],
            'flag': critical[2]
        })

    conn.commit()
    conn.close()
    return len(criticals) > 0

def generate_secure_token(report_id):
    """Generate a secure, one-time use token for report access"""
    # Create a random token
    token = secrets.token_urlsafe(32)
    
    # Create HMAC signature
    signature = hmac.new(
        key=app.secret_key.encode(),
        msg=f"{report_id}:{token}".encode(),
        digestmod=hashlib.sha256
    ).hexdigest()[:16]
    
    # Create access_tokens table if not exists
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS access_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER NOT NULL,
            token TEXT NOT NULL,
            signature TEXT NOT NULL,
            expires_at TIMESTAMP,
            used INTEGER DEFAULT 0,
            used_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    
    # Store in database (expires in 7 days)
    cursor.execute("""
        INSERT INTO access_tokens (report_id, token, signature, expires_at)
        VALUES (?, ?, ?, datetime('now', '+7 days'))
    """, (report_id, token, signature))
    conn.commit()
    conn.close()
    
    return f"{report_id}:{token}:{signature}"

def generate_final_report(patient_id):
    lock_key = f"report_{patient_id}"
    if lock_key not in report_generation_locks:
        report_generation_locks[lock_key] = threading.Lock()

    with report_generation_locks[lock_key]:
        conn = sqlite3.connect("medical.db", timeout=30)
        cursor = conn.cursor()

        # Check if report already exists
        cursor.execute("""
            SELECT report_id FROM reports
            WHERE patient_id = ?
            ORDER BY created_date DESC LIMIT 1
        """, (patient_id,))
        existing_report = cursor.fetchone()
        if existing_report:
            cursor.execute("""
                SELECT COUNT(*) FROM patient_tests
                WHERE patient_id = ? AND status NOT IN ('Completed', 'Verified')
            """, (patient_id,))
            pending = cursor.fetchone()[0]
            if pending == 0:
                conn.close()
                return existing_report[0], None, None

        # Fetch all test results for this patient
        cursor.execute("""
            SELECT tr.parameter_name, tr.parameter_value, tr.unit, tr.reference_range, tr.flag
            FROM test_results tr
            JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
            WHERE pt.patient_id = ?
            ORDER BY tr.parameter_name
        """, (patient_id,))
        all_results = cursor.fetchall()
        print(f"📊 Found {len(all_results)} test results for patient {patient_id}")

        # If no results, abort and alert
        if len(all_results) == 0:
            conn.close()
            flash(f"Cannot generate report: no test results found for patient {patient_id}.", "error")
            return None, None, None

        # Build results dictionary
        results_dict = {}
        for param_name, param_value, unit, ref_range, flag in all_results:
            results_dict[param_name] = param_value

        # Get interpretation and recommendation
        interpretation, recommendation = interpret_results(results_dict)

        # AUTO VALIDATION ENGINE
        auto_verified = True
        for status in interpretation.values():
            if "High" in status or "Critical" in status or "Stage" in status:
                auto_verified = False
                break

        if auto_verified:
            system_status = "Auto-Verified"
        else:
            system_status = "Doctor Review Required"

        # Calculate risk score
        risk_score = 0
        risk_level = "Incomplete Data"

        fasting = float(results_dict.get("fasting_glucose", 0))
        total_chol = float(results_dict.get("total_cholesterol", 0))
        systolic = float(results_dict.get("systolic", 0))
        diastolic = float(results_dict.get("diastolic", 0))
        bmi = float(results_dict.get("bmi", 0))

        if fasting > 0 or total_chol > 0 or systolic > 0 or bmi > 0:
            bp_string = f"{int(systolic)}/{int(diastolic)}" if systolic > 0 else "0/0"
            risk_score, risk_level = calculate_risk(
                sugar=fasting,
                cholesterol=total_chol,
                bp_string=bp_string,
                bmi=bmi
            )

        # Create report content for hash and signature
        report_content = f"{patient_id}-{json.dumps(results_dict)}-{risk_score}-{time.time()}"

        # Use chained hash for blockchain-style integrity
        report_hash = security_manager.create_chained_hash(report_content)

        # Generate digital signature
        digital_signature = security_manager.sign_report(report_content)

        # Insert report into database
        cursor.execute("""
            INSERT INTO reports
            (patient_id, overall_risk_score, risk_level, hash_value, digital_signature, interpretation, recommendation, diagnosis, ai_decision)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            patient_id,
            risk_score,
            risk_level,
            report_hash,
            digital_signature,
            json.dumps(interpretation),
            recommendation,
            system_status,
            json.dumps({"risk_score": risk_score, "risk_level": risk_level})
        ))

        report_id = cursor.lastrowid
        conn.commit()
        
        # ---- QR CODE & TOKEN GENERATION ----
        # Generate secure one-time token
        secure_token = generate_secure_token(report_id)
        
        # Create the full QR URL using BASE_URL
        qr_url = f"{BASE_URL}/secure_report/{secure_token}"
        
        # Add columns to reports table if they don't exist
        try:
            cursor.execute("ALTER TABLE reports ADD COLUMN qr_token TEXT")
        except:
            pass
        try:
            cursor.execute("ALTER TABLE reports ADD COLUMN qr_url TEXT")
        except:
            pass
        
        # Store the token URL in database for reference
        cursor.execute("""
            UPDATE reports SET qr_token = ?, qr_url = ?
            WHERE report_id = ?
        """, (secure_token, qr_url, report_id))
        
        conn.commit()

        # Generate QR code
        print(f"\n" + "="*60)
        print(f"📱 QR CODE GENERATED FOR PATIENT")
        print(f"📱 Scan this from ANYWHERE:")
        print(f"📱 URL: {qr_url}")
        print("="*60 + "\n")
        
        generate_qr(qr_url, f"report_{report_id}.png")
        
        # ---- SEND NOTIFICATION ----
        try:
            # Get patient contact info
            cursor.execute("""
                SELECT name, email, mobile, notification_preference
                FROM patients WHERE patient_id = ?
            """, (patient_id,))
            patient_info = cursor.fetchone()
            if patient_info:
                patient_name, email, mobile, pref = patient_info
                contact_info = {'email': email, 'mobile': mobile}
                # Only send if we have contact info
                if email or mobile:
                    NotificationService.send_report_notification(
                        report_id=report_id,
                        patient_id=patient_id,
                        patient_name=patient_name,
                        contact_info=contact_info,
                        preference=pref if pref else "email",
                        secure_link=qr_url,
                        token=secure_token
                    )
                else:
                    print(f"⚠️ No contact info for patient {patient_name}, skipping notification")
        except Exception as e:
            print(f"❌ Notification error: {e}")

        conn.close()
        print(f"✅ Report #{report_id} generated with secure token")

        return report_id, risk_score, risk_level

def machine_upload_internal(patient_id, test_type, results):
    """Internal function to handle machine upload results"""
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    # Get the pending test ID for this patient and test type
    cursor.execute("""
        SELECT patient_test_id
        FROM patient_tests
        WHERE patient_id = ? AND test_type = ? AND status != 'Verified'
        ORDER BY patient_test_id DESC LIMIT 1
    """, (patient_id, test_type))

    test_result = cursor.fetchone()

    if not test_result:
        conn.close()
        return {"error": "No pending test found"}, 404

    patient_test_id = test_result[0]

    # Update to Processing if still Collected
    cursor.execute("SELECT status FROM patient_tests WHERE patient_test_id = ?", (patient_test_id,))
    current_status = cursor.fetchone()[0]

    if current_status == 'Collected':
        StatusManager.update_status(patient_test_id, 'Processing', 'Machine upload started', cursor)

    # Get patient details for reference ranges
    cursor.execute("SELECT age, gender FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()
    patient_age = patient[0] if patient else 30
    patient_gender = patient[1] if patient else 'Both'

    # Insert machine parameters
    for key, value in results.items():
        ref_range = ReferenceChecker.get_reference_range(test_type, key, patient_age, patient_gender)
        flag = ReferenceChecker.check_value(value, ref_range) if ref_range else 'Unknown'

        ref_range_str = ''
        if ref_range:
            ref_range_str = f"{ref_range['normal_min']}-{ref_range['normal_max']} {ref_range['unit']}"

        cursor.execute("""
            INSERT INTO test_results
            (patient_test_id, parameter_name, parameter_value, unit, reference_range, flag, entered_by, entry_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            patient_test_id,
            key,
            str(value),
            ref_range['unit'] if ref_range else '',
            ref_range_str,
            flag,
            session.get('username', 'lab'),
            'Machine'
        ))

    # Mark test completed
    StatusManager.update_status(patient_test_id, 'Completed', 'Machine results uploaded', cursor)

    conn.commit()

    # Check for critical values across ALL tests for this patient
    cursor.execute("""
        SELECT COUNT(*) FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE pt.patient_id = ? AND tr.flag LIKE '%Critical%'
    """, (patient_id,))
    has_critical = cursor.fetchone()[0] > 0

    # Check if all tests completed
    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE patient_id = ? AND status != 'Completed' AND status != 'Verified'
    """, (patient_id,))

    pending = cursor.fetchone()[0]

    # Auto-verify if no critical values and all tests are done
    if not has_critical and pending == 0:
        # Update all tests to Verified
        cursor.execute("""
            UPDATE patient_tests
            SET status = 'Verified', verification_date = CURRENT_TIMESTAMP
            WHERE patient_id = ? AND status = 'Completed'
        """, (patient_id,))

        # Update the report verification status
        cursor.execute("""
            UPDATE reports
            SET verification_status = 'Verified',
                verified_date = CURRENT_TIMESTAMP,
                verified_by = 'AUTO_SYSTEM'
            WHERE patient_id = ? AND verification_status != 'Verified'
        """, (patient_id,))

        conn.commit()

    conn.close()

    if pending == 0:
        report_id, risk_score, risk_level = generate_final_report(patient_id)

        return {
            "message": "Machine Upload + Report Generated",
            "report_id": report_id,
            "risk_score": risk_score,
            "risk_level": risk_level
        }

    return {"message": "Machine Upload Successful. Waiting for other tests."}

# ===============================
# AUTHENTICATION ROUTES
# ===============================

@app.route("/")
def root():
    return redirect("/login")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = sqlite3.connect("medical.db", timeout=30)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT role, password, full_name FROM users
            WHERE username = ?
        """, (username,))

        result = cursor.fetchone()

        if result:
            role, stored_password, full_name = result
            try:
                if bcrypt.checkpw(password.encode('utf-8'), stored_password.encode('utf-8')):
                    session.clear()
                    session["username"] = username
                    session["role"] = role
                    session["full_name"] = full_name
                    session["last_activity"] = time.time()

                    # Log successful login
                    log_action(cursor, username, "login_success", {"role": role})
                    conn.commit()
                    conn.close()

                    if role == "receptionist":
                        return redirect("/reception_dashboard")
                    elif role == "collector":
                        return redirect("/collector_dashboard")
                    elif role == "technician":
                        return redirect("/technician_dashboard")
                    elif role == "doctor":
                        return redirect("/doctor_dashboard")
                    elif role == "admin":
                        return redirect("/admin_dashboard")
            except Exception as e:
                print(f"Login error: {e}")
                pass

        # Log failed login attempt
        try:
            log_action(cursor, username, "login_failed", {})
            conn.commit()
        except:
            new_conn = sqlite3.connect("medical.db", timeout=30)
            new_cursor = new_conn.cursor()
            log_action(new_cursor, username, "login_failed", {})
            new_conn.commit()
            new_conn.close()

        conn.close()
        flash("Invalid username or password", "error")
        return redirect(url_for('login'))

    return render_template("login.html")

@app.route("/logout")
def logout():
    log_action(None, session.get('username', 'unknown'), "logout", {})
    session.clear()
    return redirect("/login")

# ===============================
# DASHBOARD ROUTES
# ===============================

@app.route("/reception_dashboard")
@role_required("receptionist")
def reception_dashboard():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT patient_id, name, age, gender, contact, registered_date FROM patients ORDER BY registered_date DESC")
    patients = cursor.fetchall()

    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT COUNT(*) FROM patients WHERE date(registered_date) = date(?)", (today,))
    today_registrations = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE status IN ('Ordered', 'Collected', 'Processing')")
    pending_tests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE date(collection_date) = date(?)", (today,))
    scheduled_tests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reports WHERE date(created_date) = date(?)", (today,))
    completed_reports = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COALESCE(SUM(paid_amount), 0) FROM billing
        WHERE date(bill_date) = date(?)
    """, (today,))
    today_collection = cursor.fetchone()[0]

    cursor.execute("SELECT AVG(duration_minutes) FROM sample_tracking WHERE status = 'Completed'")
    avg_time_result = cursor.fetchone()[0]
    avg_processing_time = round(avg_time_result, 1) if avg_time_result else 0

    cursor.execute("SELECT COUNT(*) FROM patient_tests")
    total_tests = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE status IN ('Completed', 'Verified')")
    completed_tests = cursor.fetchone()[0]
    completion_rate = round((completed_tests / total_tests * 100), 1) if total_tests > 0 else 0

    cursor.execute("""
        SELECT p.name, GROUP_CONCAT(pt.test_type), pt.status, pt.collection_date,
               COALESCE(b.total_amount, 0) as amount
        FROM patients p
        JOIN patient_tests pt ON p.patient_id = pt.patient_id
        LEFT JOIN billing b ON p.patient_id = b.patient_id
        GROUP BY p.patient_id, pt.collection_date
        ORDER BY pt.collection_date DESC LIMIT 5
    """)
    recent = cursor.fetchall()
    recent_activities = []
    for r in recent:
        status_color = 'success' if r[2] == 'Completed' else 'warning' if r[2] == 'Processing' else 'info'
        recent_activities.append({
            'patient_name': r[0],
            'tests': r[1].split(',') if r[1] else [],
            'status': r[2],
            'status_color': status_color,
            'time': r[3] if r[3] else '',
            'amount': float(r[4]) if r[4] else 0
        })

    conn.close()

    return render_template("reception_dashboard.html",
                         patients=patients,
                         today_registrations=today_registrations,
                         pending_tests=pending_tests,
                         scheduled_tests=scheduled_tests,
                         completed_reports=completed_reports,
                         today_collection=today_collection,
                         avg_processing_time=avg_processing_time,
                         completion_rate=completion_rate,
                         recent_activities=recent_activities)

@app.route("/lab_dashboard")
@role_required("lab")
def lab_dashboard():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    today = datetime.now().strftime('%Y-%m-%d')

    status_colors = {
        'Collected': 'secondary',
        'Processing': 'info',
        'Completed': 'success',
        'Verified': 'primary'
    }

    # Pending Collection
    cursor.execute("""
        SELECT p.patient_id, p.name, p.age, p.gender,
               GROUP_CONCAT(pt.test_type) as tests,
               COUNT(pt.patient_test_id) as test_count,
               pt.priority
        FROM patients p
        JOIN patient_tests pt ON p.patient_id = pt.patient_id
        WHERE pt.status = 'Ordered'
        GROUP BY p.patient_id
        ORDER BY
            CASE pt.priority
                WHEN 'STAT' THEN 1
                WHEN 'Urgent' THEN 2
                ELSE 3
            END,
            pt.collection_date ASC
    """)

    pending_collection_raw = cursor.fetchall()
    pending_collection = []
    for p in pending_collection_raw:
        pending_collection.append({
            'id': p[0],
            'name': p[1],
            'age': p[2],
            'gender': p[3],
            'tests': p[4].split(',') if p[4] else [],
            'count': p[5],
            'priority': p[6]
        })

    # Processing Queue
    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type, pt.status,
               pt.sample_barcode, pt.collection_date,
               (SELECT COUNT(*) FROM test_results WHERE patient_test_id = pt.patient_test_id) as result_count
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status IN ('Collected', 'Processing')
        ORDER BY
            CASE pt.priority
                WHEN 'STAT' THEN 1
                WHEN 'Urgent' THEN 2
                ELSE 3
            END,
            pt.collection_date ASC
    """)

    processing_queue_raw = cursor.fetchall()
    processing_queue = []
    for q in processing_queue_raw:
        processing_queue.append({
            'test_id': q[0],
            'patient': q[1],
            'test_type': q[2],
            'status': q[3],
            'barcode': q[4] or 'Not labeled',
            'collection_date': q[5],
            'result_count': q[6],
            'status_color': status_colors.get(q[3], 'secondary')
        })

    # Completed today
    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE status = 'Completed' AND date(completion_date) = date(?)
    """, (today,))
    completed_today = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE status = 'Processing'")
    in_progress = cursor.fetchone()[0]

    # Recent activities
    cursor.execute("""
        SELECT p.name, pt.test_type, pt.status,
               COALESCE(pt.completion_date, pt.verification_date, pt.collection_date) as event_date,
               COALESCE(pt.verified_by, 'system') as technician
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status IN ('Completed', 'Verified')
        ORDER BY event_date DESC LIMIT 5
    """)
    recent_raw = cursor.fetchall()
    recent_activities = []
    for r in recent_raw:
        time_str = ''
        if r[3]:
            date_str = str(r[3])
            if ' ' in date_str:
                time_str = date_str.split(' ')[1][:5]
        recent_activities.append({
            'patient_name': r[0],
            'test': r[1],
            'status_color': 'success' if r[2] == 'Completed' else 'info',
            'time': time_str,
            'technician': r[4]
        })

    # Test distribution
    cursor.execute("""
        SELECT test_type, COUNT(*) as count
        FROM patient_tests
        WHERE status IN ('Collected', 'Processing', 'Completed')
        GROUP BY test_type
    """)
    dist_raw = cursor.fetchall()
    total = sum([d[1] for d in dist_raw]) or 1
    test_distribution = []
    test_names = {'cbc': 'CBC', 'diabetes': 'Diabetes', 'lipid': 'Lipid', 'bp': 'BP', 'bmi': 'BMI'}
    for d in dist_raw:
        test_distribution.append({
            'name': test_names.get(d[0], d[0].upper()),
            'count': d[1],
            'percentage': round((d[1] / total) * 100, 1)
        })

    cursor.execute("SELECT AVG(duration_minutes) FROM sample_tracking WHERE status = 'Completed'")
    avg_time_result = cursor.fetchone()[0]
    avg_processing_time = round(avg_time_result, 1) if avg_time_result else 0

    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE date(collection_date) = date(?)", (today,))
    tests_today = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM patient_tests")
    total_tests_all = cursor.fetchone()[0]
    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE status IN ('Completed', 'Verified')")
    completed_tests_all = cursor.fetchone()[0]
    completion_rate = round((completed_tests_all / total_tests_all * 100), 1) if total_tests_all > 0 else 0

    on_time_rate = 92

    conn.close()

    return render_template("lab_dashboard.html",
                         pending_collection=pending_collection,
                         processing_queue=processing_queue,
                         completed_today=completed_today,
                         in_progress=in_progress,
                         recent_activities=recent_activities,
                         test_distribution=test_distribution,
                         avg_processing_time=avg_processing_time,
                         tests_today=tests_today,
                         completion_rate=completion_rate,
                         on_time_rate=on_time_rate)

@app.route("/collect_sample/<int:patient_id>")
@role_required("collector")
def collect_sample(patient_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()

    cursor.execute("""
        SELECT patient_test_id, test_type, priority
        FROM patient_tests
        WHERE patient_id = ? AND status = 'Ordered'
    """, (patient_id,))
    tests = cursor.fetchall()

    conn.close()

    if not tests:
        flash("No pending tests to collect for this patient", "warning")
        return redirect(url_for('collector_dashboard'))

    return render_template("collection_form.html",
                         patient_id=patient_id,
                         patient_name=patient[0] if patient else "Unknown",
                         tests=tests)

@app.route("/record_collection/<int:patient_id>", methods=["POST"])
@role_required("collector")
def record_collection(patient_id):
    collector_name = request.form.get("collector_name", session.get('username', 'lab'))
    collection_time = request.form.get("collection_time")
    sample_type = request.form.get("sample_type")
    sample_barcode = request.form.get("sample_barcode")
    notes = request.form.get("notes", "")
    test_ids = request.form.getlist("test_ids")

    if not test_ids:
        flash("Please select at least one test to collect", "error")
        return redirect(url_for('collect_sample', patient_id=patient_id))

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    if not sample_barcode:
        sample_barcode = f"LAB{patient_id}{datetime.now().strftime('%Y%m%d%H%M%S')}"

    success_count = 0
    for test_id in test_ids:
        unique_barcode = f"LAB{patient_id}-{test_id}-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        cursor.execute("""
            UPDATE patient_tests
            SET status = 'Collected',
                collected_by = ?,
                collection_time = ?,
                sample_type = ?,
                sample_barcode = ?,
                notes = ?
            WHERE patient_test_id = ? AND patient_id = ?
        """, (collector_name, collection_time, sample_type, unique_barcode, notes, test_id, patient_id))

        if cursor.rowcount > 0:
            success_count += 1
            from status_utils import StatusManager
            StatusManager.update_status(int(test_id), 'Collected', f'Sample collected: {sample_type}', cursor)

    log_action(
        cursor,
        session.get("username", "collector"),
        "samples_collected",
        {"patient_id": patient_id, "test_count": success_count, "sample_type": sample_type}
    )

    conn.commit()
    conn.close()

    flash(f"✅ Successfully collected {success_count} samples", "success")
    return redirect(url_for('collector_dashboard'))

@app.route("/doctor_dashboard")
@role_required("doctor")
def doctor_dashboard():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    # Get ALL reports, not just pending
    cursor.execute("""
        SELECT r.report_id, p.name, r.overall_risk_score, r.diagnosis,
               CASE
                   WHEN r.overall_risk_score >= 70 THEN 'Critical'
                   WHEN r.overall_risk_score >= 40 THEN 'High'
                   WHEN r.overall_risk_score >= 20 THEN 'Moderate'
                   ELSE 'Low'
               END as risk_level,
               r.created_date,
               r.ai_decision
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        ORDER BY r.created_date DESC
        LIMIT 20
    """)

    reports_raw = cursor.fetchall()
    reports = []
    for r in reports_raw:
        ml_pred = None
        confidence = None
        if r[6]:
            try:
                ai_data = json.loads(r[6])
                ml_pred = ai_data.get('risk_level', 'N/A')
                confidence = ai_data.get('confidence', 85)
            except:
                ml_pred = 'N/A'
                confidence = 0
        reports.append((r[0], r[1], r[2], r[3], ml_pred, confidence))

    # Get pending reports count for stats
    cursor.execute("""
        SELECT COUNT(*) FROM reports
        WHERE diagnosis IS NULL OR diagnosis = '' OR diagnosis = 'Doctor Review Required'
    """)
    pending_count = cursor.fetchone()[0]

    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT COUNT(*) FROM reports
        WHERE diagnosis IS NOT NULL AND diagnosis != ''
        AND diagnosis != 'Doctor Review Required'
        AND date(verified_date) = date(?)
    """, (today,))
    diagnosed_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT r.verified_date, p.name, r.diagnosis, r.overall_risk_score
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.diagnosis IS NOT NULL AND r.diagnosis != ''
        AND r.diagnosis != 'Doctor Review Required'
        ORDER BY r.verified_date DESC LIMIT 5
    """)
    recent_raw = cursor.fetchall()
    recent_diagnoses = []
    for r in recent_raw:
        recent_diagnoses.append({
            'timestamp': r[0] if r[0] else '',
            'patient_name': r[1],
            'diagnosis': r[2][:50] + '...' if r[2] and len(r[2]) > 50 else r[2],
            'risk': r[3]
        })

    cursor.execute("SELECT COUNT(*) FROM reports")
    total_reports = cursor.fetchone()[0]

    conn.close()

    return render_template("doctor_dashboard.html",
                         reports=reports,
                         pending_count=pending_count,
                         diagnosed_count=diagnosed_count,
                         recent_diagnoses=recent_diagnoses,
                         total_reports=total_reports)

@app.route("/admin_dashboard")
@role_required("admin")
def admin_dashboard():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM patient_tests")
    total_tests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reports")
    total_reports = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reports WHERE overall_risk_score >= 40")
    high_risk = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("""
        SELECT status, COUNT(*) FROM patient_tests GROUP BY status
    """)
    status_counts_raw = cursor.fetchall()
    status_counts = {}
    for status in ['Collected', 'Processing', 'Completed', 'Verified']:
        status_counts[status] = 0
    for row in status_counts_raw:
        status_counts[row[0]] = row[1]

    cursor.execute("""
        SELECT timestamp, actor, action, details FROM audit_logs
        ORDER BY timestamp DESC LIMIT 10
    """)
    recent_logs = cursor.fetchall()

    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE date(collection_date) = date(?)", (today,))
    today_tests = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reports WHERE diagnosis IS NULL OR diagnosis = '' OR diagnosis = 'Doctor Review Required'")
    pending_reports = cursor.fetchone()[0]

    cursor.execute("""
        SELECT (COUNT(CASE WHEN status IN ('Completed', 'Verified') THEN 1 END) * 100.0 / COUNT(*))
        FROM patient_tests
    """)
    completion_rate_raw = cursor.fetchone()[0]
    completion_rate = round(completion_rate_raw, 1) if completion_rate_raw else 0

    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn.close()

    return render_template(
        "admin_dashboard.html",
        total_patients=total_patients,
        total_tests=total_tests,
        total_reports=total_reports,
        high_risk=high_risk,
        total_users=total_users,
        status_counts=status_counts,
        recent_logs=recent_logs,
        today_tests=today_tests,
        pending_reports=pending_reports,
        completion_rate=completion_rate,
        current_time=current_time
    )

@app.route("/admin/notifications")
@role_required("admin")
def admin_notifications():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT n.*, p.name as patient_name
        FROM notifications n
        JOIN patients p ON n.patient_id = p.patient_id
        ORDER BY n.created_at DESC
        LIMIT 100
    """)
    
    # Convert to list of dicts for template
    columns = [col[0] for col in cursor.description]
    notifications = []
    for row in cursor.fetchall():
        notif_dict = dict(zip(columns, row))
        notifications.append(notif_dict)
    
    conn.close()
    return render_template("notifications.html", notifications=notifications)

@app.route("/quality_control")
@role_required("admin")
def quality_control():
    return render_template("quality_control.html",
                         current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route("/admin/generate_missing_reports")
@role_required("admin")
def generate_missing_reports():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT DISTINCT pt.patient_id, p.name
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.patient_id NOT IN (SELECT DISTINCT patient_id FROM reports)
        GROUP BY pt.patient_id
        HAVING COUNT(CASE WHEN pt.status NOT IN ('Completed', 'Verified') THEN 1 END) = 0
    """)

    patients = cursor.fetchall()
    conn.close()

    if not patients:
        flash("No missing reports found. All patients have reports.", "info")
        return redirect(url_for('admin_dashboard'))

    generated = []
    for patient_id, patient_name in patients:
        try:
            report_id, risk_score, risk_level = generate_final_report(patient_id)
            generated.append(f"Patient {patient_name} - Report #{report_id}")
            print(f"✅ Generated report #{report_id} for {patient_name}")
        except Exception as e:
            print(f"❌ Error generating report for {patient_name}: {e}")

    flash(f"✅ Generated reports for: {', '.join(generated)}", "success")
    return redirect(url_for('admin_dashboard'))

@app.route("/automation_dashboard")
@role_required("admin")
def automation_dashboard():
    from auto_lab_processor import auto_lab

    stats = auto_lab.get_automation_stats()

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type, pt.status, pt.priority
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status IN ('Collected', 'Processing')
        ORDER BY
            CASE pt.priority
                WHEN 'STAT' THEN 1
                WHEN 'Urgent' THEN 2
                ELSE 3
            END,
            pt.collection_date
        LIMIT 20
    """)

    queue = []
    for test in cursor.fetchall():
        eta = random.randint(2, 15)
        queue.append({
            'id': test[0],
            'patient': test[1],
            'type': test[2],
            'status': test[3],
            'status_color': 'processing' if test[3] == 'Processing' else 'collected',
            'auto': True,
            'eta': f"{eta} min"
        })

    cursor.execute("""
        SELECT n.report_id, p.name, n.sent_at
        FROM notifications n
        JOIN patients p ON n.patient_id = p.patient_id
        ORDER BY n.sent_at DESC
        LIMIT 10
    """)

    notifications = []
    for notif in cursor.fetchall():
        notifications.append({
            'report_id': notif[0],
            'patient': notif[1],
            'time': notif[2]
        })

    conn.close()

    return render_template("automation_dashboard.html",
                         **stats,
                         queue=queue,
                         notifications=notifications)

# ===============================
# RECEPTION MODULE
# ===============================

@app.route("/onboard")
@role_required("receptionist")
def onboard():
    return render_template("onboard.html")

@app.route("/order_test/<int:patient_id>")
@role_required("receptionist")
def order_test(patient_id):
    """Show form to order additional tests for an existing patient"""
    return render_template("order_test.html", patient_id=patient_id)

@app.route("/order_test_submit/<int:patient_id>", methods=["POST"])
@role_required("receptionist")
def order_test_submit(patient_id):
    test_type = request.form.get("test_type")
    priority = request.form.get("priority", "Normal")
    notes = request.form.get("notes", "")
    amount_paid = float(request.form.get("amount_paid", 0))
    payment_mode = request.form.get("payment_mode", "cash")

    if not test_type:
        return "Test type required", 400

    from database import TEST_PRICES
    test_price = TEST_PRICES.get(test_type, 0)

    if amount_paid < test_price:
        return render_template("error.html",
                             error_code=400,
                             message=f"Amount paid (₹{amount_paid}) is less than test price (₹{test_price}). Please collect full payment.",
                             current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                             request_path=request.path,
                             request_method=request.method,
                             session=session), 400

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT name FROM patients WHERE patient_id = ?", (patient_id,))
    patient_name = cursor.fetchone()[0]

    cursor.execute("""
        INSERT INTO patient_tests (patient_id, test_type, status, priority, collection_date, notes)
        VALUES (?, ?, 'Ordered', ?, CURRENT_TIMESTAMP, ?)
    """, (patient_id, test_type, priority, notes))

    test_id = cursor.lastrowid

    receipt_number = f"RCP{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"

    cursor.execute("""
        INSERT INTO billing (patient_id, test_ids, total_amount, paid_amount, payment_mode, receipt_number, payment_status, bill_date)
        VALUES (?, ?, ?, ?, ?, ?, 'Paid', CURRENT_TIMESTAMP)
    """, (
        patient_id,
        test_type,
        test_price,
        amount_paid,
        payment_mode,
        receipt_number
    ))

    bill_id = cursor.lastrowid

    from status_utils import StatusManager
    StatusManager.update_status(test_id, 'Ordered', f'Additional test ordered: {test_type}', cursor)

    log_action(
        cursor,
        session.get("username", "reception"),
        "test_ordered",
        {"patient_id": patient_id, "test_type": test_type, "priority": priority, "amount": test_price, "bill_id": bill_id, "receipt": receipt_number}
    )

    conn.commit()
    conn.close()

    receipt_data = {
        'receipt_number': receipt_number,
        'date': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
        'patient_name': patient_name,
        'patient_id': patient_id,
        'test_type': test_type,
        'amount': test_price,
        'payment_mode': payment_mode,
        'collected_by': session.get('username', 'reception')
    }

    flash(f"✅ Test ordered successfully! Amount: ₹{test_price} | Receipt: {receipt_number}", "success")
    return render_template("order_receipt.html", receipt=receipt_data, patient_id=patient_id)

@app.route("/onboard_submit", methods=["POST"])
@role_required("receptionist")
def onboard_submit():
    name = request.form["name"]
    age = request.form["age"]
    gender = request.form["gender"]
    contact = request.form["contact"]
    email = request.form.get("email")
    mobile = request.form.get("mobile")
    notification_preference = request.form.get("notification_preference", "email")
    priority = request.form.get("priority", "Normal")
    payment_mode = request.form.get("payment_mode", "cash")
    amount_paid = float(request.form.get("amount_paid", 0))

    selected_tests = request.form.getlist("tests")

    app.logger.info(f"Received tests (raw): {selected_tests}")
    app.logger.info(f"Amount paid: {amount_paid}")
    app.logger.info(f"Mobile: {mobile}, Email: {email}, Preference: {notification_preference}")

    selected_tests = list(set(selected_tests))
    app.logger.info(f"Unique tests: {selected_tests}")

    if not selected_tests:
        return render_template("error.html",
                             error_code=400,
                             message="Please select at least one test!",
                             current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                             request_path=request.path,
                             request_method=request.method,
                             session=session), 400

    from database import TEST_PRICES
    total_amount = sum(TEST_PRICES.get(test, 0) for test in selected_tests)

    app.logger.info(f"Total amount: {total_amount}")

    if amount_paid < total_amount:
        error_msg = f"Amount paid (₹{amount_paid}) is less than total amount (₹{total_amount}). "
        error_msg += f"Selected tests: {', '.join(selected_tests)}"
        return render_template("error.html",
                             error_code=400,
                             message=error_msg,
                             current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                             request_path=request.path,
                             request_method=request.method,
                             session=session), 400

    max_retries = 3
    retry_count = 0

    while retry_count < max_retries:
        try:
            conn = sqlite3.connect("medical.db", timeout=30)
            cursor = conn.cursor()

            # Insert patient with all contact fields (including mobile and notification_preference)
            cursor.execute("""
                INSERT INTO patients (name, age, gender, contact, email, mobile, notification_preference)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (name, age, gender, contact, email, mobile, notification_preference))

            patient_id = cursor.lastrowid

            test_details = []
            for test in selected_tests:
                price = TEST_PRICES.get(test, 0)
                test_details.append((test, price))

            receipt_number = f"RCP{datetime.now().strftime('%Y%m%d%H%M%S')}{random.randint(100,999)}"

            cursor.execute("""
                INSERT INTO billing (patient_id, test_ids, total_amount, paid_amount, payment_mode, receipt_number)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (
                patient_id,
                ','.join(selected_tests),
                total_amount,
                amount_paid,
                payment_mode,
                receipt_number
            ))

            log_action(
                cursor,
                session.get("username", "reception"),
                "patient_registered",
                {
                    "patient_id": patient_id, 
                    "tests": selected_tests, 
                    "priority": priority, 
                    "amount": total_amount, 
                    "receipt": receipt_number,
                    "email": email,
                    "mobile": mobile,
                    "preference": notification_preference
                }
            )

            for test in selected_tests:
                cursor.execute("""
                    INSERT INTO patient_tests (patient_id, test_type, status, priority, collection_date)
                    VALUES (?, ?, 'Ordered', ?, CURRENT_TIMESTAMP)
                """, (patient_id, test, priority))

                test_id = cursor.lastrowid
                from status_utils import StatusManager
                StatusManager.update_status(test_id, 'Ordered', f'Patient {name} registered', cursor)

            conn.commit()
            conn.close()
            break

        except sqlite3.OperationalError as e:
            if "database is locked" in str(e) and retry_count < max_retries - 1:
                retry_count += 1
                time.sleep(1)
                continue
            else:
                return render_template("error.html",
                                     error_code=500,
                                     message="Database is busy. Please try again.",
                                     current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                     request_path=request.path,
                                     request_method=request.method,
                                     session=session), 500

    contact_display = email or mobile or "No contact provided"
    flash(f"✅ Patient {name} registered successfully! Report link will be sent via {notification_preference} to {contact_display}", "success")
    return redirect(url_for('patient_detail', patient_id=patient_id))

# ===============================
# LAB MODULE
# ===============================

@app.route("/simulate_machine/<int:patient_test_id>", methods=["POST"])
@role_required("technician")
def simulate_machine(patient_test_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT patient_id, test_type, status
        FROM patient_tests
        WHERE patient_test_id = ? AND status != 'Verified'
    """, (patient_test_id,))

    test = cursor.fetchone()
    if not test:
        conn.close()
        flash("Test not found or already verified", "error")
        return redirect(url_for('technician_dashboard'))

    patient_id, test_type, current_status = test

    if current_status == 'Collected':
        StatusManager.update_status(patient_test_id, 'Processing', 'Auto-started', cursor)
        conn.commit()

    test_type = test_type.lower()
    results = {}

    # Generate random results based on test type
    if test_type in TEST_DEFINITIONS:
        if test_type == "cbc":
            results = {
                "hemoglobin": round(random.uniform(11, 17), 1),
                "wbc": random.randint(4000, 11000),
                "rbc": round(random.uniform(4.0, 6.0), 1),
                "platelets": random.randint(150000, 450000),
                "hematocrit": round(random.uniform(36, 50), 1),
                "mcv": random.randint(80, 100),
                "mch": random.randint(27, 33),
                "mchc": random.randint(31, 36)
            }
        elif test_type == "diabetes":
            results = {
                "fasting_glucose": random.randint(70, 200),
                "postprandial_glucose": random.randint(90, 250),
                "hba1c": round(random.uniform(4.5, 9.5), 1)
            }
        elif test_type == "lipid":
            total = random.randint(150, 300)
            hdl = random.randint(30, 70)
            triglycerides = random.randint(100, 300)
            results = {
                "total_cholesterol": total,
                "hdl": hdl,
                "ldl": random.randint(80, 200),
                "triglycerides": triglycerides,
                "vldl": triglycerides // 5,
                "cardiac_ratio": round(total / hdl, 2)
            }
        elif test_type == "bp":
            results = {
                "systolic": random.randint(100, 180),
                "diastolic": random.randint(70, 110),
                "pulse_rate": random.randint(60, 110)
            }
        elif test_type == "bmi":
            height = round(random.uniform(1.5, 1.9), 2)
            weight = random.randint(50, 100)
            results = {
                "height": height,
                "weight": weight,
                "bmi": round(weight / (height * height), 1)
            }
    else:
        if test_type in INDIVIDUAL_TEST_RANGES:
            low, high = INDIVIDUAL_TEST_RANGES[test_type]
            if isinstance(low, float) or isinstance(high, float):
                value = round(random.uniform(low, high), 1)
            else:
                value = random.randint(low, high)
            results = {test_type: value}
        else:
            results = {test_type: random.randint(0, 100)}

    response = machine_upload_internal(patient_id, test_type, results)

    check_critical_values(patient_test_id)

    conn.close()

    flash(f"✅ Test {patient_test_id} processed successfully!", "success")
    return redirect(url_for('technician_dashboard'))

@app.route("/lab_patient/<int:patient_id>")
@role_required("technician")
def lab_patient(patient_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT patient_test_id, test_type, status, priority, collection_date,
               (SELECT COUNT(*) FROM test_results WHERE patient_test_id = pt.patient_test_id) as result_count,
               CASE WHEN notes LIKE '%MANUAL_ONLY%' THEN 1 ELSE 0 END as manual_flag
        FROM patient_tests pt
        WHERE patient_id = ? AND status != 'Verified'
        ORDER BY
            CASE priority
                WHEN 'STAT' THEN 1
                WHEN 'Urgent' THEN 2
                ELSE 3
            END,
            collection_date
    """, (patient_id,))

    tests = cursor.fetchall()

    cursor.execute("SELECT name FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()
    patient_name = patient[0] if patient else "Unknown"

    conn.close()

    return render_template("lab_patient.html",
                         tests=tests,
                         patient_id=patient_id,
                         patient_name=patient_name,
                         user_role=session.get('role'))

@app.route("/collector_dashboard")
@role_required("collector")
def collector_dashboard():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    today = datetime.now().strftime('%Y-%m-%d')

    cursor.execute("""
        SELECT p.patient_id, p.name, p.age, p.gender, p.contact,
               COUNT(pt.patient_test_id) as test_count,
               GROUP_CONCAT(pt.test_type) as tests,
               SUM(CASE WHEN pt.priority = 'STAT' THEN 1 ELSE 0 END) as stat_count,
               SUM(CASE WHEN pt.priority = 'Urgent' THEN 1 ELSE 0 END) as urgent_count
        FROM patients p
        JOIN patient_tests pt ON p.patient_id = pt.patient_id
        WHERE pt.status = 'Ordered'
        GROUP BY p.patient_id
        ORDER BY
            CASE
                WHEN SUM(CASE WHEN pt.priority = 'STAT' THEN 1 ELSE 0 END) > 0 THEN 1
                WHEN SUM(CASE WHEN pt.priority = 'Urgent' THEN 1 ELSE 0 END) > 0 THEN 2
                ELSE 3
            END,
            MAX(pt.collection_date) ASC
    """)

    pending_raw = cursor.fetchall()
    pending_collection = []
    for row in pending_raw:
        pending_collection.append({
            'patient_id': row[0],
            'name': row[1],
            'age': row[2],
            'gender': row[3],
            'contact': row[4],
            'test_count': row[5],
            'tests': row[6].split(',') if row[6] else [],
            'stat_count': row[7] or 0,
            'urgent_count': row[8] or 0
        })

    urgent_count = sum(p['urgent_count'] + p['stat_count'] for p in pending_collection)

    cursor.execute("""
        SELECT p.name, pt.test_type, pt.collected_by, pt.collection_time, pt.sample_barcode
        FROM patients p
        JOIN patient_tests pt ON p.patient_id = pt.patient_id
        WHERE pt.status = 'Collected' AND date(pt.collection_time) = date(?)
        ORDER BY pt.collection_time DESC
        LIMIT 10
    """, (today,))

    collected_raw = cursor.fetchall()
    collected_today = []
    for row in collected_raw:
        collected_today.append({
            'patient_name': row[0],
            'test_type': row[1],
            'collected_by': row[2],
            'collection_time': row[3],
            'barcode': row[4]
        })

    cursor.execute("SELECT COUNT(*) FROM patient_tests WHERE status = 'Ordered'")
    pending_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE status = 'Collected' AND date(collection_time) = date(?)
    """, (today,))
    collected_count = cursor.fetchone()[0]

    avg_collection_time = 0

    conn.close()

    return render_template("collector_dashboard.html",
                         pending_collection=pending_collection,
                         collected_today=collected_today,
                         pending_count=pending_count,
                         collected_count=collected_count,
                         urgent_count=urgent_count,
                         avg_collection_time=avg_collection_time)

@app.route("/technician_dashboard")
@role_required("technician")
def technician_dashboard():
    """Dashboard for lab technicians"""
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    today = datetime.now().strftime('%Y-%m-%d')

    # Samples ready for processing (status = 'Collected')
    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type, pt.priority,
               pt.sample_barcode, pt.collection_time,
               (SELECT COUNT(*) FROM test_results WHERE patient_test_id = pt.patient_test_id) as result_count
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status = 'Collected'
        ORDER BY
            CASE pt.priority
                WHEN 'STAT' THEN 1
                WHEN 'Urgent' THEN 2
                ELSE 3
            END,
            pt.collection_date ASC
    """)
    processing_queue = cursor.fetchall()

    # In‑progress tests (status = 'Processing')
    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type,
               pt.processing_start_date, pt.sample_barcode
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status = 'Processing'
        ORDER BY pt.processing_start_date DESC
    """)
    in_progress = cursor.fetchall()

    # Completed today – includes both Completed and Verified
    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE (status = 'Completed' OR status = 'Verified')
        AND date(COALESCE(completion_date, verification_date)) = date(?)
    """, (today,))
    completed_today = cursor.fetchone()[0]

    # Total completed/verified all time
    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE status IN ('Completed', 'Verified')
    """)
    total_completed = cursor.fetchone()[0]

    # Test counts by type for active tests
    cursor.execute("""
        SELECT test_type, COUNT(*) as count
        FROM patient_tests
        WHERE status IN ('Collected', 'Processing')
        GROUP BY test_type
    """)
    test_counts = cursor.fetchall()

    # History of processed tests (last 10)
    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type,
               COALESCE(pt.completion_date, pt.verification_date) as processed_date
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status IN ('Completed', 'Verified')
        ORDER BY processed_date DESC
        LIMIT 10
    """)
    completed_history = cursor.fetchall()

    conn.close()

    return render_template("technician_dashboard.html",
                         processing_queue=processing_queue,
                         in_progress=in_progress,
                         completed_today=completed_today,
                         total_completed=total_completed,
                         test_counts=test_counts,
                         completed_history=completed_history)

@app.route("/toggle_auto_process/<int:patient_test_id>", methods=["POST"])
@role_required("lab")
def toggle_auto_process(patient_test_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT notes FROM patient_tests WHERE patient_test_id = ?", (patient_test_id,))
    result = cursor.fetchone()

    if result:
        current_notes = result[0] or ''
        if 'MANUAL_ONLY' in current_notes:
            new_notes = current_notes.replace('MANUAL_ONLY', '').strip()
        else:
            new_notes = (current_notes + ' MANUAL_ONLY').strip()

        cursor.execute("UPDATE patient_tests SET notes = ? WHERE patient_test_id = ?",
                      (new_notes, patient_test_id))
        conn.commit()

    conn.close()
    return redirect(request.referrer or "/lab_dashboard")

@app.route("/disable_auto_process/<int:patient_test_id>", methods=["POST"])
@role_required("lab")
def disable_auto_process(patient_test_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        UPDATE patient_tests
        SET notes = 'MANUAL_ONLY'
        WHERE patient_test_id = ?
    """, (patient_test_id,))

    conn.commit()
    conn.close()

    return redirect(request.referrer or "/lab_patient")

@app.route("/enter_test/<int:patient_test_id>")
@role_required("technician")
def enter_test(patient_test_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT test_type, patient_id, status
        FROM patient_tests
        WHERE patient_test_id = ?
    """, (patient_test_id,))

    result = cursor.fetchone()

    if not result:
        conn.close()
        return "Test Not Found", 404

    test_type, patient_id, status = result

    cursor.execute("SELECT name FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()
    patient_name = patient[0] if patient else "Unknown"

    cursor.execute("""
        SELECT parameter_name, unit, normal_min, normal_max, critical_low, critical_high
        FROM test_reference_ranges
        WHERE test_type = ? AND gender_specific = 'Both'
        GROUP BY parameter_name
    """, (test_type,))

    reference_ranges = cursor.fetchall()

    cursor.execute("""
        SELECT parameter_name, parameter_value, flag
        FROM test_results
        WHERE patient_test_id = ?
    """, (patient_test_id,))

    test_results = cursor.fetchall()

    conn.close()

    return render_template(
        "enter_test.html",
        patient_test_id=patient_test_id,
        test_type=test_type,
        patient_id=patient_id,
        patient_name=patient_name,
        status=status,
        reference_ranges=reference_ranges,
        test_results=test_results
    )

@app.route("/submit_test/<int:patient_test_id>", methods=["POST"])
@role_required("technician")
def submit_test(patient_test_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT patient_id, status FROM patient_tests WHERE patient_test_id = ?",
        (patient_test_id,)
    )

    result = cursor.fetchone()

    if not result:
        conn.close()
        return "Invalid Test ID", 404

    patient_id, current_status = result

    if current_status == 'Collected':
        StatusManager.update_status(patient_test_id, 'Processing', 'Manual entry started', cursor)

    cursor.execute("SELECT age, gender FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()
    patient_age = patient[0] if patient else 30
    patient_gender = patient[1] if patient else 'Both'

    cursor.execute("SELECT test_type FROM patient_tests WHERE patient_test_id = ?", (patient_test_id,))
    test_type = cursor.fetchone()[0]

    has_critical = False
    for key in request.form:
        if request.form[key]:
            ref_range = ReferenceChecker.get_reference_range(test_type, key, patient_age, patient_gender)
            flag = ReferenceChecker.check_value(request.form[key], ref_range) if ref_range else 'Unknown'

            if flag and 'Critical' in flag:
                has_critical = True

            cursor.execute("""
                INSERT INTO test_results
                (patient_test_id, parameter_name, parameter_value, unit, reference_range, flag, entered_by, entry_method)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                patient_test_id,
                key,
                request.form[key],
                ref_range['unit'] if ref_range else '',
                f"{ref_range['normal_min']}-{ref_range['normal_max']}" if ref_range else '',
                flag,
                session.get('username', 'lab'),
                'Manual'
            ))

    StatusManager.update_status(patient_test_id, 'Completed', 'Manual results uploaded', cursor)
    conn.commit()

    if has_critical:
        check_critical_values(patient_test_id)

    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE patient_id = ? AND status != 'Completed' AND status != 'Verified'
    """, (patient_id,))

    pending_count = cursor.fetchone()[0]
    conn.close()

    if pending_count == 0:
        report_id, risk_score, risk_level = generate_final_report(patient_id)
        return redirect(url_for('patient_portal_report', report_id=report_id))

    return redirect(url_for('technician_dashboard'))

@app.route("/machine_upload", methods=["POST"])
@role_required("lab")
def machine_upload():
    data = request.json

    if not data:
        return {"error": "No JSON received"}, 400

    patient_test_id = data.get("patient_test_id")
    parameters = data.get("parameters")

    if not patient_test_id or not parameters:
        return {"error": "Missing patient_test_id or parameters"}, 400

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT patient_id, status FROM patient_tests WHERE patient_test_id = ?",
        (patient_test_id,)
    )
    result = cursor.fetchone()

    if not result:
        conn.close()
        return {"error": "Invalid Test ID"}, 404

    patient_id, current_status = result

    if current_status == 'Collected':
        StatusManager.update_status(patient_test_id, 'Processing', 'Machine upload started', cursor)

    cursor.execute("SELECT age, gender FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()
    patient_age = patient[0] if patient else 30
    patient_gender = patient[1] if patient else 'Both'

    cursor.execute("SELECT test_type FROM patient_tests WHERE patient_test_id = ?", (patient_test_id,))
    test_type = cursor.fetchone()[0]

    has_critical = False
    for key, value in parameters.items():
        ref_range = ReferenceChecker.get_reference_range(test_type, key, patient_age, patient_gender)
        flag = ReferenceChecker.check_value(value, ref_range) if ref_range else 'Unknown'

        if flag and 'Critical' in flag:
            has_critical = True

        cursor.execute("""
            INSERT INTO test_results
            (patient_test_id, parameter_name, parameter_value, unit, reference_range, flag, entered_by, entry_method)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            patient_test_id,
            key,
            str(value),
            ref_range['unit'] if ref_range else '',
            f"{ref_range['normal_min']}-{ref_range['normal_max']}" if ref_range else '',
            flag,
            session.get('username', 'lab'),
            'Machine'
        ))

    StatusManager.update_status(patient_test_id, 'Completed', 'Machine results uploaded', cursor)

    conn.commit()

    if has_critical:
        check_critical_values(patient_test_id)

    cursor.execute("""
        SELECT COUNT(*) FROM patient_tests
        WHERE patient_id = ? AND status != 'Completed' AND status != 'Verified'
    """, (patient_id,))

    pending = cursor.fetchone()[0]
    conn.close()

    if pending == 0:
        report_id, risk_score, risk_level = generate_final_report(patient_id)

        return {
            "message": "Machine Upload + Report Generated",
            "report_id": report_id,
            "risk_score": risk_score,
            "risk_level": risk_level
        }

    return {"message": "Machine Upload Successful. Waiting for other tests."}

@app.route("/lab_view_report/<int:report_id>")
@admin_or_role_required(["lab", "doctor", "admin"])
def lab_view_report(report_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.overall_risk_score, r.risk_level, r.hash_value, r.diagnosis, p.name,
               r.interpretation, r.recommendation, r.verification_status, r.created_date,
               r.verified_date, r.verified_by
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.report_id = ?
    """, (report_id,))

    report = cursor.fetchone()

    if not report:
        conn.close()
        return "Report Not Found", 404

    risk_score, risk_level, hash_value, diagnosis, patient_name, interpretation_json, recommendation, verification_status, created_date, verified_date, verified_by = report

    cursor.execute("""
        SELECT tr.parameter_name, tr.parameter_value, tr.unit, tr.reference_range, tr.flag
        FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE pt.patient_id = (SELECT patient_id FROM reports WHERE report_id = ?)
        ORDER BY tr.parameter_name
    """, (report_id,))

    test_results = cursor.fetchall()
    conn.close()

    qr_filename = f"report_{report_id}.png"
    qr_path = url_for('static', filename=qr_filename) if os.path.exists(os.path.join('static', qr_filename)) else None

    interpretation = json.loads(interpretation_json) if interpretation_json else {}

    return render_template(
        "lab_report_view.html",
        report_id=report_id,
        patient_name=patient_name,
        risk_score=risk_score,
        risk_level=risk_level,
        hash_value=hash_value,
        diagnosis=diagnosis,
        interpretation=interpretation,
        recommendation=recommendation,
        verification_status=verification_status,
        created_date=created_date,
        verified_date=verified_date,
        verified_by=verified_by,
        test_results=test_results,
        qr_path=qr_path
    )

# ===============================
# ADDITIONAL ROUTES FOR NAVIGATION
# ===============================

@app.route("/patients")
@admin_or_role_required(["receptionist", "doctor", "admin"])
def patients_list():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("SELECT patient_id, name, age, gender, contact, registered_date FROM patients ORDER BY registered_date DESC")
    patients = cursor.fetchall()
    conn.close()
    return render_template("patients_list.html", patients=patients)

@app.route("/patient/<int:patient_id>")
@admin_or_role_required(["receptionist", "doctor", "admin"])
def patient_detail(patient_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM patients WHERE patient_id = ?", (patient_id,))
    patient = cursor.fetchone()

    cursor.execute("""
        SELECT pt.patient_test_id, pt.test_type, pt.status, pt.priority, pt.collection_date,
               (SELECT COUNT(*) FROM test_results WHERE patient_test_id = pt.patient_test_id) as result_count
        FROM patient_tests pt
        WHERE pt.patient_id = ?
        ORDER BY pt.collection_date DESC
    """, (patient_id,))
    tests = cursor.fetchall()

    # Get latest billing record
    cursor.execute("""
        SELECT bill_id, receipt_number, total_amount, paid_amount, payment_mode, bill_date
        FROM billing
        WHERE patient_id = ?
        ORDER BY bill_date DESC
        LIMIT 1
    """, (patient_id,))
    latest_bill = cursor.fetchone()

    conn.close()

    if not patient:
        return "Patient not found", 404

    return render_template("patient_detail.html",
                         patient=patient,
                         tests=tests,
                         latest_bill=latest_bill)

@app.route("/lab_completed")
@admin_or_role_required(["technician", "lab", "doctor"])
def lab_completed():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type,
               COALESCE(pt.completion_date, pt.verification_date) as completed_date
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status IN ('Completed', 'Verified')
        ORDER BY completed_date DESC
    """)
    tests = cursor.fetchall()
    conn.close()
    return render_template("lab_completed.html", tests=tests)

@app.route("/lab_in_progress")
@role_required("technician")
def lab_in_progress():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type, pt.processing_start_date
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status = 'Processing'
        ORDER BY pt.processing_start_date DESC
    """)
    tests = cursor.fetchall()
    conn.close()
    return render_template("lab_in_progress.html", tests=tests)

@app.route("/lab_reports")
@admin_or_role_required(["technician", "lab", "doctor", "admin"])
def lab_reports():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.report_id, p.name, r.overall_risk_score, r.created_date
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        ORDER BY r.created_date DESC
        LIMIT 50
    """)
    reports = cursor.fetchall()
    conn.close()
    return render_template("lab_reports.html", reports=reports)

@app.route("/admin/users")
@role_required("admin")
def admin_users():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, username, role, full_name, email, created_date FROM users")
    users = cursor.fetchall()
    conn.close()
    return render_template("admin_users.html", users=users)

@app.route("/admin/settings")
@role_required("admin")
def admin_settings():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM patients")
    total_patients = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM reports")
    total_reports = cursor.fetchone()[0]

    db_size = os.path.getsize("medical.db") / (1024 * 1024)

    conn.close()

    return render_template("admin_settings.html",
                         total_users=total_users,
                         total_patients=total_patients,
                         total_reports=total_reports,
                         db_size=round(db_size, 2),
                         current_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'))

@app.route("/all_reports")
@role_required("doctor")
def all_reports():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.report_id, p.name, r.overall_risk_score, r.diagnosis, r.created_date
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        ORDER BY r.created_date DESC
        LIMIT 100
    """)
    reports = cursor.fetchall()
    conn.close()
    return render_template("all_reports.html", reports=reports)

# ===============================
# STATUS MANAGEMENT ROUTES
# ===============================

@app.route("/update_test_status/<int:patient_test_id>", methods=["POST"])
@role_required("technician")
def update_test_status(patient_test_id):
    new_status = request.form.get("status")
    note = request.form.get("note", "")

    if not new_status:
        return "Status required", 400

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    success, message = StatusManager.update_status(patient_test_id, new_status, note, cursor)

    if success:
        conn.commit()
        conn.close()
        return redirect(request.referrer or "/lab_dashboard")
    else:
        conn.close()
        return message, 400

@app.route("/test_timeline/<int:patient_test_id>")
@role_required("technician")
def test_timeline(patient_test_id):
    timeline = StatusManager.get_timeline(patient_test_id)

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT pt.test_type, p.name, pt.status, pt.priority, pt.collection_date
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.patient_test_id = ?
    """, (patient_test_id,))

    test_info = cursor.fetchone()

    cursor.execute("""
        SELECT COUNT(*) FROM test_results WHERE patient_test_id = ?
    """, (patient_test_id,))
    results_count = cursor.fetchone()[0]

    cursor.execute("SELECT patient_id FROM patient_tests WHERE patient_test_id = ?", (patient_test_id,))
    patient_result = cursor.fetchone()
    patient_id = patient_result[0] if patient_result else None

    conn.close()

    avg_time = StatusManager.calculate_avg_processing_time(test_info[0] if test_info else None)

    return render_template("test_timeline.html",
                         timeline=timeline,
                         test_info=test_info,
                         patient_test_id=patient_test_id,
                         patient_id=patient_id,
                         results_count=results_count,
                         avg_time=avg_time)

@app.route("/lab_status_dashboard")
@admin_or_role_required(["technician", "lab", "doctor", "admin", "collector"])
def lab_status_dashboard():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT pt.patient_test_id, p.name, pt.test_type, pt.status,
               pt.collection_date, pt.priority,
               (SELECT COUNT(*) FROM test_results WHERE patient_test_id = pt.patient_test_id) as result_count
        FROM patient_tests pt
        JOIN patients p ON pt.patient_id = p.patient_id
        WHERE pt.status IN ('Collected', 'Processing', 'Completed', 'Verified')
        ORDER BY
            CASE pt.priority
                WHEN 'STAT' THEN 1
                WHEN 'Urgent' THEN 2
                ELSE 3
            END,
            CASE pt.status
                WHEN 'Collected' THEN 1
                WHEN 'Processing' THEN 2
                WHEN 'Completed' THEN 3
                WHEN 'Verified' THEN 4
                ELSE 5
            END,
            pt.collection_date
    """)

    tests = cursor.fetchall()

    grouped_tests = {
        'Collected': [],
        'Processing': [],
        'Completed': [],
        'Verified': []
    }

    for test in tests:
        if test[3] in grouped_tests:
            grouped_tests[test[3]].append(test)

    summary = StatusManager.get_test_status_summary()

    avg_times = {}
    for test_type in ['cbc', 'diabetes', 'lipid', 'bp', 'bmi', 'lft', 'kft', 'thyroid']:
        avg_times[test_type] = StatusManager.calculate_avg_processing_time(test_type)

    conn.close()

    return render_template("lab_status_dashboard.html",
                         grouped_tests=grouped_tests,
                         summary=summary,
                         avg_times=avg_times)

# ===============================
# DOCTOR MODULE
# ===============================

@app.route("/add_diagnosis/<int:report_id>")
@role_required("doctor")
def add_diagnosis(report_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT p.name, r.overall_risk_score, r.interpretation, r.ai_decision, r.patient_id,
               r.recommendation
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.report_id = ?
    """, (report_id,))

    report_info = cursor.fetchone()

    if not report_info:
        conn.close()
        return "Report not found", 404

    patient_name, risk_score, interpretation_json, ai_decision_json, patient_id, recommendation = report_info

    cursor.execute("""
        SELECT tr.parameter_name, tr.parameter_value, tr.unit, tr.reference_range, tr.flag
        FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE pt.patient_id = ?
        ORDER BY tr.parameter_name
    """, (patient_id,))

    test_results = cursor.fetchall()

    formatted_results = []
    for test in test_results:
        formatted_results.append({
            'name': test[0].replace('_', ' ').title(),
            'value': test[1],
            'unit': test[2] or '',
            'range': test[3] or 'Standard',
            'flag': test[4] or 'Normal'
        })

    ml_prediction = None
    if ai_decision_json:
        try:
            ai_data = json.loads(ai_decision_json)
            ml_prediction = {
                'diagnosis': ai_data.get('risk_level', 'Unknown'),
                'confidence': ai_data.get('confidence', 85),
                'risk_score': ai_data.get('risk_score', risk_score)
            }
        except:
            ml_prediction = None

    conn.close()

    interpretation = json.loads(interpretation_json) if interpretation_json else {}

    return render_template("add_diagnosis.html",
                         report_id=report_id,
                         patient_name=patient_name,
                         risk_score=risk_score,
                         interpretation=interpretation,
                         recommendation=recommendation,
                         ml_prediction=ml_prediction,
                         test_results=formatted_results)

@app.route("/submit_diagnosis/<int:report_id>", methods=["POST"])
@role_required("doctor")
def submit_diagnosis(report_id):
    diagnosis = request.form["diagnosis"]
    doctor_override = request.form.get("override_reason", "")

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT diagnosis FROM reports WHERE report_id = ?", (report_id,))
    result = cursor.fetchone()
    current_diagnosis = result[0] if result else None

    cursor.execute("""
        UPDATE reports
        SET diagnosis = ?, doctor_override = ?, verified_date = CURRENT_TIMESTAMP, verified_by = ?
        WHERE report_id = ?
    """, (diagnosis, doctor_override, session.get('username'), report_id))

    cursor.execute("SELECT patient_id FROM reports WHERE report_id = ?", (report_id,))
    patient_result = cursor.fetchone()
    if patient_result:
        patient_id = patient_result[0]
        cursor.execute("""
            UPDATE patient_tests
            SET status = 'Verified', verification_date = CURRENT_TIMESTAMP, verified_by = ?
            WHERE patient_id = ?
        """, (session.get('username'), patient_id))

    log_action(
        cursor,
        session.get("username", "doctor"),
        "diagnosis_added",
        {
            "report_id": report_id,
            "diagnosis": diagnosis,
            "previous_diagnosis": current_diagnosis,
            "override": bool(doctor_override),
            "override_reason": doctor_override
        }
    )

    conn.commit()
    conn.close()

    return redirect("/doctor_dashboard")

@app.route("/reports")
@role_required("doctor")
def reports_list():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT r.report_id, p.name, r.overall_risk_score, r.diagnosis, r.created_date
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        ORDER BY r.created_date DESC
    """)
    reports = cursor.fetchall()
    conn.close()
    return render_template("all_reports.html", reports=reports)

@app.route("/view_report/<int:report_id>")
@role_required("doctor")
def view_report(report_id):
    return redirect(url_for('lab_view_report', report_id=report_id))

# ===============================
# PATIENT MODULE
# ===============================

@app.route("/patient_portal")
def patient_portal():
    return render_template("patient_portal.html")

@app.route("/patient_portal/<int:report_id>")
def patient_portal_report(report_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    # Get report data
    cursor.execute("""
        SELECT r.overall_risk_score, r.risk_level, r.hash_value, r.diagnosis, p.name,
               r.interpretation, r.recommendation, r.verification_status, r.created_date,
               r.verified_date, r.verified_by, p.age, p.gender
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.report_id = ?
    """, (report_id,))

    report = cursor.fetchone()

    if not report:
        conn.close()
        return "Report Not Found", 404

    (risk_score, risk_level, hash_value, diagnosis, patient_name,
     interpretation_json, recommendation, verification_status, created_date,
     verified_date, verified_by, patient_age, patient_gender) = report

    # Get all test results with detailed information
    cursor.execute("""
        SELECT 
            tr.parameter_name, 
            tr.parameter_value, 
            tr.unit, 
            tr.reference_range, 
            tr.flag,
            pt.test_type,
            pt.sample_type,
            pt.collection_date
        FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE pt.patient_id = (SELECT patient_id FROM reports WHERE report_id = ?)
        ORDER BY pt.test_type, tr.parameter_name
    """, (report_id,))

    raw_results = cursor.fetchall()
    
    # Format test results with interpretations
    test_results = []
    test_groups = {}
    
    for row in raw_results:
        param_name, param_value, unit, ref_range, flag, test_type, sample_type, collection_date = row
        
        # Generate interpretation based on flag
        interpretation = ""
        if flag == "Critical High":
            interpretation = "Critically high - requires immediate medical attention"
        elif flag == "Critical Low":
            interpretation = "Critically low - requires immediate medical attention"
        elif flag == "High":
            interpretation = "Above normal range - monitor and consult doctor"
        elif flag == "Low":
            interpretation = "Below normal range - monitor and consult doctor"
        elif flag == "Normal":
            interpretation = "Within normal range - good"
        else:
            interpretation = "Value needs review"
        
        test_results.append({
            'test_id': test_type,
            'test_name': test_type.replace('_', ' ').title(),
            'name': param_name.replace('_', ' ').title(),
            'value': param_value,
            'unit': unit,
            'range': ref_range,
            'flag': flag,
            'interpretation': interpretation,
            'sample_type': sample_type,
            'collection_date': collection_date
        })

    # Generate ML predictions based on test results
    ml_predictions = {}
    
    try:
        # Group results by test type for ML analysis
        for result in test_results:
            test_name = result['test_name']
            if test_name not in ml_predictions:
                ml_predictions[test_name] = {
                    'parameters': [],
                    'risk_level': 'Normal',
                    'confidence': 0.5,
                    'assessment': '',
                    'recommendations': []
                }
            
            # Add parameter to group
            ml_predictions[test_name]['parameters'].append(result)
            
            # Simple rule-based ML prediction (you can replace with actual ML model)
            value = float(result['value']) if result['value'].replace('.', '').isdigit() else 0
            flag = result['flag']
            
            # Update risk level based on parameters
            if 'Critical' in flag:
                ml_predictions[test_name]['risk_level'] = 'Critical'
                ml_predictions[test_name]['confidence'] = 0.95
            elif 'High' in flag and ml_predictions[test_name]['risk_level'] != 'Critical':
                ml_predictions[test_name]['risk_level'] = 'High'
                ml_predictions[test_name]['confidence'] = 0.85
            elif 'Low' in flag and ml_predictions[test_name]['risk_level'] not in ['Critical', 'High']:
                ml_predictions[test_name]['risk_level'] = 'Moderate'
                ml_predictions[test_name]['confidence'] = 0.75
        
        # Generate assessments and recommendations for each test
        for test_name, prediction in ml_predictions.items():
            if prediction['risk_level'] == 'Critical':
                prediction['assessment'] = f"CRITICAL: Your {test_name} results show severely abnormal values that require immediate medical attention. Please consult a doctor immediately."
                prediction['recommendations'] = [
                    "Seek immediate medical attention",
                    "Do not delay - visit the nearest healthcare facility",
                    "Bring this report with you",
                    "Avoid any strenuous activity until cleared by a doctor"
                ]
            elif prediction['risk_level'] == 'High':
                prediction['assessment'] = f"HIGH RISK: Your {test_name} results indicate significant abnormalities. You should schedule a doctor's appointment within 24-48 hours."
                prediction['recommendations'] = [
                    "Schedule an appointment with your doctor within 2 days",
                    "Monitor your symptoms closely",
                    "Avoid alcohol and maintain a light diet",
                    "Stay hydrated and get adequate rest"
                ]
            elif prediction['risk_level'] == 'Moderate':
                prediction['assessment'] = f"MODERATE RISK: Some values in your {test_name} test are outside the normal range. Follow up with your doctor within 2 weeks."
                prediction['recommendations'] = [
                    "Schedule a follow-up appointment within 2 weeks",
                    "Review your diet and lifestyle habits",
                    "Consider retesting after 3 months",
                    "Keep a log of any symptoms"
                ]
            else:
                prediction['assessment'] = f"LOW RISK: Your {test_name} results are within normal ranges. Continue maintaining a healthy lifestyle."
                prediction['recommendations'] = [
                    "Continue with regular health check-ups",
                    "Maintain a balanced diet",
                    "Exercise regularly",
                    "Get adequate sleep"
                ]
    
    except Exception as e:
        print(f"ML Prediction error: {e}")
        ml_predictions = {}

    conn.close()

    qr_filename = f"report_{report_id}.png"
    qr_path = url_for('static', filename=qr_filename) if os.path.exists(os.path.join('static', qr_filename)) else None

    interpretation = json.loads(interpretation_json) if interpretation_json else {}
    
    # Get sample type from first result if available
    sample_type = test_results[0]['sample_type'] if test_results else 'Blood/Urine'
    collection_date = test_results[0]['collection_date'] if test_results else created_date

    return render_template(
        "patient_report.html",
        report_id=report_id,
        patient_name=patient_name,
        patient_age=patient_age,
        patient_gender=patient_gender,
        risk_score=risk_score,
        risk_level=risk_level,
        hash_value=hash_value,
        diagnosis=diagnosis,
        interpretation=interpretation,
        recommendation=recommendation,
        verification_status=verification_status,
        created_date=created_date,
        verified_date=verified_date,
        verified_by=verified_by,
        test_results=test_results,
        qr_path=qr_path,
        ml_predictions=ml_predictions,
        sample_type=sample_type,
        collection_date=collection_date
    )

@app.route("/patient_view", methods=["POST"])
def patient_view():
    report_id = request.form.get("report_id")

    if not report_id or not report_id.isdigit():
        return "Invalid Report ID", 400

    report_id = int(report_id)
    return redirect(url_for('patient_portal_report', report_id=report_id))

@app.route("/patient_view_auto")
def patient_view_auto():
    report_id = request.args.get("report_id")

    if not report_id or not report_id.isdigit():
        return "Invalid Report ID", 400

    report_id = int(report_id)
    return redirect(url_for('patient_portal_report', report_id=report_id))

@app.route("/download_report/<int:report_id>")
def download_report(report_id):
    from pdf_generator import generate_pdf_report
    from flask import send_file, abort

    try:
        pdf_path = generate_pdf_report(report_id)

        if pdf_path and os.path.exists(pdf_path):
            return send_file(
                pdf_path,
                as_attachment=True,
                download_name=f"report_{report_id}.pdf",
                mimetype='application/pdf'
            )
        else:
            flash('PDF generation failed - file not created', 'error')
            return redirect(url_for('patient_portal_report', report_id=report_id))
    except Exception as e:
        print(f"❌ Error in download_report: {str(e)}")
        traceback.print_exc()
        flash(f'PDF generation failed: {str(e)}', 'error')
        return redirect(url_for('patient_portal_report', report_id=report_id))

# ===============================
# VERIFICATION MODULE
# ===============================

@app.route("/verify_page")
def verify_page():
    return render_template("verify.html")

@app.route("/verify", methods=["POST"])
def verify():
    report_id = request.form.get("report_id")
    entered_hash = request.form.get("hash_value")

    if not report_id or not entered_hash:
        return "Missing report ID or hash value", 400

    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("SELECT hash_value, verification_status, patient_id FROM reports WHERE report_id = ?", (report_id,))
    result = cursor.fetchone()

    if not result:
        conn.close()
        flash("Report not found!", "error")
        return redirect(url_for('verify_page'))

    stored_hash, verification_status, patient_id = result

    cursor.execute("SELECT name FROM patients WHERE patient_id = ?", (patient_id,))
    patient_result = cursor.fetchone()
    patient_name = patient_result[0] if patient_result else "Unknown"

    verification_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    verification_id = f"{report_id}-{random.randint(1000,9999)}"

    if stored_hash == entered_hash:
        if verification_status != 'Verified':
            cursor.execute("""
                UPDATE reports SET verification_status = 'Verified', 
                                   verified_date = CURRENT_TIMESTAMP
                WHERE report_id = ? AND verification_status != 'Verified'
            """, (report_id,))

        log_action(cursor, "patient", "verify_success", {"report_id": report_id, "patient_id": patient_id})
        conn.commit()
        conn.close()

        flash("Report verified successfully! Document is authentic.", "success")
        return render_template("verify_result.html",
                               success=True,
                               message="Document Authenticity Confirmed",
                               report_id=report_id,
                               patient_name=patient_name,
                               hash_value=entered_hash,
                               verification_method="SHA-256 Hash Comparison",
                               verification_time=verification_time,
                               verification_id=verification_id)
    else:
        log_action(cursor, "patient", "verify_failed", {"report_id": report_id, "entered_hash": entered_hash})
        conn.commit()
        conn.close()

        flash("Hash mismatch! Report may be tampered.", "error")
        return render_template("verify_result.html",
                               success=False,
                               message="Hash Mismatch - Document May Be Tampered",
                               report_id=report_id,
                               patient_name=patient_name,
                               stored_hash=stored_hash[:20] + "...",
                               entered_hash=entered_hash[:20] + "...",
                               verification_method="SHA-256 Hash Comparison",
                               verification_time=verification_time,
                               verification_id=verification_id)

@app.route("/verify_qr/<int:report_id>")
def verify_qr(report_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.hash_value, r.verification_status, p.name
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.report_id = ?
    """, (report_id,))

    result = cursor.fetchone()

    if not result:
        conn.close()
        return render_template("verify_result.html",
                             success=False,
                             message="Report Not Found!",
                             report_id=report_id,
                             verification_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                             verification_id=f"{report_id}-{random.randint(1000,9999)}")

    hash_value, status, patient_name = result

    cursor.execute("""
        UPDATE reports SET verification_status = 'Verified'
        WHERE report_id = ? AND verification_status != 'Verified'
    """, (report_id,))

    log_action(
        cursor,
        "patient",
        "qr_verify_success",
        {"report_id": report_id, "patient_name": patient_name}
    )

    conn.commit()
    conn.close()

    verification_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    verification_id = f"{report_id}-{random.randint(1000,9999)}"

    return render_template("verify_result.html",
                           success=True,
                           message="QR Code Verification Successful",
                           report_id=report_id,
                           patient_name=patient_name,
                           hash_value=hash_value,
                           verification_method="QR Code Scan",
                           verification_time=verification_time,
                           verification_id=verification_id)

# ===============================
# SECURE TOKEN-BASED REPORT ACCESS
# ===============================

@app.route("/secure_report/<token>")
def secure_report_access(token):
    """Secure route that validates token AND verifies report integrity"""
    try:
        # Parse token
        parts = token.split(':')
        if len(parts) != 3:
            return render_template("error.html",
                                 error_code=400,
                                 message="Invalid token format",
                                 current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                 request_path=request.path,
                                 request_method=request.method,
                                 session=session), 400
        
        report_id, token_value, signature = parts
        
        # VERIFICATION #1: HMAC Signature Verification
        expected_sig = hmac.new(
            key=app.secret_key.encode(),
            msg=f"{report_id}:{token_value}".encode(),
            digestmod=hashlib.sha256
        ).hexdigest()[:16]
        
        if not hmac.compare_digest(signature, expected_sig):
            # Log failed verification
            conn = sqlite3.connect("medical.db")
            cursor = conn.cursor()
            log_action(cursor, "unknown", "VERIFICATION_FAILED", 
                      {"reason": "HMAC signature mismatch", "token": token})
            conn.commit()
            conn.close()
            
            return render_template("error.html",
                                 error_code=403,
                                 message="Security validation failed - report may be tampered",
                                 current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                 request_path=request.path,
                                 request_method=request.method,
                                 session=session), 403
        
        # Check token in database
        conn = sqlite3.connect("medical.db", timeout=30)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT expires_at, used FROM access_tokens 
            WHERE report_id = ? AND token = ?
        """, (report_id, token_value))
        
        result = cursor.fetchone()
        
        if not result:
            conn.close()
            return render_template("error.html",
                                 error_code=404,
                                 message="Invalid or expired link",
                                 current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                 request_path=request.path,
                                 request_method=request.method,
                                 session=session), 404
        
        expires_at, used = result
        
        # VERIFICATION #2: Expiry Check
        from datetime import datetime
        if datetime.now() > datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S'):
            conn.close()
            return render_template("error.html",
                                 error_code=403,
                                 message="This link has expired. Please contact the lab for a new one.",
                                 current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                 request_path=request.path,
                                 request_method=request.method,
                                 session=session), 403
        
        # VERIFICATION #3: One-time Use Check
        if used == 1:
            conn.close()
            return render_template("error.html",
                                 error_code=403,
                                 message="This link has already been accessed. Each link can only be used once for security.",
                                 current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                                 request_path=request.path,
                                 request_method=request.method,
                                 session=session), 403
        
        # Mark as used
        cursor.execute("""
            UPDATE access_tokens SET used = 1, used_at = CURRENT_TIMESTAMP 
            WHERE report_id = ? AND token = ?
        """, (report_id, token_value))
        
        # Log successful access
        log_action(cursor, "patient", "SECURE_ACCESS_SUCCESS", 
                  {"report_id": report_id, "method": "secure_link"})
        
        conn.commit()
        
        # Get the report's hash for client-side verification
        cursor.execute("SELECT hash_value FROM reports WHERE report_id = ?", (report_id,))
        report_hash = cursor.fetchone()[0]
        
        conn.close()
        
        # Set session for this access
        session['secure_access'] = True
        session['accessed_report'] = report_id
        session['report_hash'] = report_hash  # Store hash in session
        
        flash("✅ Report accessed securely. Hash verification available.", "success")
        return redirect(url_for('patient_portal_report', report_id=report_id))
        
    except Exception as e:
        print(f"❌ Secure access error: {str(e)}")
        traceback.print_exc()
        return render_template("error.html",
                             error_code=500,
                             message="An error occurred during secure access",
                             current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                             request_path=request.path,
                             request_method=request.method,
                             session=session), 500

# ===============================
# API ENDPOINTS
# ===============================

@app.route("/api/report/<int:report_id>")
def api_get_report(report_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT r.overall_risk_score, r.risk_level, r.hash_value, r.diagnosis, p.name,
               r.interpretation, r.recommendation, r.created_date
        FROM reports r
        JOIN patients p ON r.patient_id = p.patient_id
        WHERE r.report_id = ?
    """, (report_id,))

    report = cursor.fetchone()
    conn.close()

    if not report:
        return {"error": "Report not found"}, 404

    return {
        "report_id": report_id,
        "patient_name": report[4],
        "risk_score": report[0],
        "risk_level": report[1],
        "hash_value": report[2],
        "diagnosis": report[3],
        "created_date": report[7]
    }

@app.route("/api/test_status/<int:patient_id>")
def api_test_status(patient_id):
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT test_type, status, collection_date, completion_date
        FROM patient_tests
        WHERE patient_id = ?
        ORDER BY collection_date DESC
    """, (patient_id,))

    tests = cursor.fetchall()
    conn.close()

    return {
        "patient_id": patient_id,
        "tests": [
            {
                "test_type": t[0],
                "status": t[1],
                "collection_date": t[2],
                "completion_date": t[3]
            } for t in tests
        ]
    }

# ===============================
# ERROR HANDLERS
# ===============================

@app.errorhandler(404)
def not_found_error(error):
    return render_template("error.html",
                         error_code=404,
                         message="The page you are looking for does not exist.",
                         current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                         request_path=request.path,
                         request_method=request.method,
                         session=session), 404

@app.errorhandler(500)
def internal_error(error):
    return render_template("error.html",
                         error_code=500,
                         message="An internal server error occurred. Please try again later.",
                         current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                         request_path=request.path,
                         request_method=request.method,
                         session=session,
                         debug_info=str(error) if session.get('role') == 'admin' else None), 500

@app.errorhandler(403)
def forbidden_error(error):
    return render_template("error.html",
                         error_code=403,
                         message="You don't have permission to access this page.",
                         current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                         request_path=request.path,
                         request_method=request.method,
                         session=session), 403

@app.errorhandler(400)
def bad_request_error(error):
    return render_template("error.html",
                         error_code=400,
                         message="Bad request. Please check your input.",
                         current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                         request_path=request.path,
                         request_method=request.method,
                         session=session), 400

@app.errorhandler(401)
def unauthorized_error(error):
    return render_template("error.html",
                         error_code=401,
                         message="Please log in to access this page.",
                         current_time=time.strftime('%Y-%m-%d %H:%M:%S'),
                         request_path=request.path,
                         request_method=request.method,
                         session=session), 401

def upgrade_database_for_tokens():
    """Add token columns to reports table if not exists"""
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    
    # Check if columns exist
    cursor.execute("PRAGMA table_info(reports)")
    columns = [col[1] for col in cursor.fetchall()]
    
    if 'qr_token' not in columns:
        try:
            cursor.execute("ALTER TABLE reports ADD COLUMN qr_token TEXT")
            print("✅ Added qr_token column to reports table")
        except:
            pass
    
    if 'qr_url' not in columns:
        try:
            cursor.execute("ALTER TABLE reports ADD COLUMN qr_url TEXT")
            print("✅ Added qr_url column to reports table")
        except:
            pass
    
    conn.commit()
    conn.close()

# Run the upgrade
upgrade_database_for_tokens()

if __name__ == "__main__":
    if not os.path.exists('static'):
        os.makedirs('static')
    debug_mode = os.environ.get('FLASK_DEBUG', 'True').lower() == 'true'
    app.run(host="0.0.0.0", port=5000, debug=debug_mode)