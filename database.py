import sqlite3
import bcrypt
import os
from datetime import datetime

# Comprehensive test prices dictionary
TEST_PRICES = {
    # Hematology
    'cbc': 500,
    'hemoglobin': 150,
    'wbc_count': 200,
    'platelet_count': 200,
    'esr': 180,
    'peripheral_smear': 300,
    'blood_group': 150,
    
    # Diabetes
    'fasting_glucose': 150,
    'postprandial_glucose': 150,
    'random_glucose': 150,
    'hba1c': 400,
    'gtt': 600,  # Glucose Tolerance Test
    
    # Lipid Profile
    'lipid_profile': 800,
    'total_cholesterol': 200,
    'hdl': 250,
    'ldl': 250,
    'vldl': 250,
    'triglycerides': 250,
    
    # Liver Function
    'lft': 1000,  # Liver Function Test
    'sgpt_alt': 200,
    'sgot_ast': 200,
    'alkaline_phosphatase': 200,
    'total_bilirubin': 180,
    'direct_bilirubin': 180,
    'total_protein': 150,
    'albumin': 150,
    'globulin': 150,
    'ag_ratio': 100,
    
    # Kidney Function
    'kft': 900,  # Kidney Function Test
    'blood_urea': 180,
    'serum_creatinine': 180,
    'uric_acid': 200,
    'sodium': 250,
    'potassium': 250,
    'chloride': 200,
    
    # Thyroid
    'tsh': 400,
    't3': 400,
    't4': 400,
    'ft3': 450,
    'ft4': 450,
    
    # Cardiac
    'troponin_i': 1200,
    'troponin_t': 1200,
    'ck_mb': 800,
    'ck_total': 600,
    'ldh': 500,
    
    # Other
    'vitamin_d': 1500,
    'vitamin_b12': 1200,
    'iron_studies': 800,
    'ferritin': 600,
    'crp': 500,
    'rheumatoid_factor': 600,
    
    # Urine
    'urine_routine': 300,
    'urine_culture': 800,
    'microalbumin': 600,
    
    # Microbiology
    'blood_culture': 1000,
    'widal': 500,
    'dengue_ns1': 1200,
    'dengue_igg_igm': 1500,
    'malaria': 600,
    'typhoid': 700,
}

# Test categories for organization
TEST_CATEGORIES = {
    'Hematology': ['cbc', 'hemoglobin', 'wbc_count', 'platelet_count', 'esr', 'peripheral_smear', 'blood_group'],
    'Diabetes': ['fasting_glucose', 'postprandial_glucose', 'random_glucose', 'hba1c', 'gtt'],
    'Lipid Profile': ['lipid_profile', 'total_cholesterol', 'hdl', 'ldl', 'vldl', 'triglycerides'],
    'Liver Function': ['lft', 'sgpt_alt', 'sgot_ast', 'alkaline_phosphatase', 'total_bilirubin', 'direct_bilirubin', 'total_protein', 'albumin', 'globulin', 'ag_ratio'],
    'Kidney Function': ['kft', 'blood_urea', 'serum_creatinine', 'uric_acid', 'sodium', 'potassium', 'chloride'],
    'Thyroid': ['tsh', 't3', 't4', 'ft3', 'ft4'],
    'Cardiac': ['troponin_i', 'troponin_t', 'ck_mb', 'ck_total', 'ldh'],
    'Vitamins': ['vitamin_d', 'vitamin_b12', 'ferritin'],
    'Infectious Diseases': ['crp', 'rheumatoid_factor', 'widal', 'dengue_ns1', 'dengue_igg_igm', 'malaria', 'typhoid'],
    'Urine': ['urine_routine', 'urine_culture', 'microalbumin'],
    'Microbiology': ['blood_culture'],
}

# Test definitions mapping for parameter generation
TEST_DEFINITIONS = {
    "cbc": [
        "hemoglobin", "wbc", "rbc", "platelets", "hematocrit",
        "mcv", "mch", "mchc"
    ],
    "diabetes": [
        "fasting_glucose", "postprandial_glucose", "hba1c"
    ],
    "lipid": [
        "total_cholesterol", "hdl", "ldl", "triglycerides", "vldl", "cardiac_ratio"
    ],
    "bp": [
        "systolic", "diastolic", "pulse_rate"
    ],
    "bmi": [
        "height", "weight", "bmi"
    ],
    # Additional test definitions
    "lft": [
        "sgpt_alt", "sgot_ast", "alkaline_phosphatase", "total_bilirubin", 
        "direct_bilirubin", "total_protein", "albumin", "globulin", "ag_ratio"
    ],
    "kft": [
        "blood_urea", "serum_creatinine", "uric_acid", "sodium", "potassium", "chloride"
    ],
    "thyroid": [
        "tsh", "t3", "t4", "ft3", "ft4"
    ],
    "cardiac": [
        "troponin_i", "troponin_t", "ck_mb", "ck_total", "ldh"
    ]
}

def init_db():
    conn = sqlite3.connect("medical.db", timeout=30)
    cursor = conn.cursor()

    cursor.execute("PRAGMA journal_mode=WAL;")
    cursor.execute("PRAGMA foreign_keys = ON;")
    cursor.execute("PRAGMA busy_timeout = 30000;")

    # --------------------
    # Patients Table
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patients (
            patient_id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            age INTEGER,
            gender TEXT,
            contact TEXT,
            email TEXT,  
            registered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # --------------------
    # Patient Tests Table (Enhanced Status Tracking)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS patient_tests (
            patient_test_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            test_type TEXT,
            status TEXT DEFAULT 'Collected',
            assigned_to TEXT,
            priority TEXT DEFAULT 'Normal',
            collection_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            collection_time TIMESTAMP,
            collected_by TEXT,
            sample_type TEXT,
            sample_barcode TEXT,
            processing_start_date TIMESTAMP,
            completion_date TIMESTAMP,
            verification_date TIMESTAMP,
            verified_by TEXT,
            notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
        )
    """)

    # --------------------
    # Test Reference Ranges Table
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_reference_ranges (
            range_id INTEGER PRIMARY KEY AUTOINCREMENT,
            test_type TEXT,
            parameter_name TEXT,
            unit TEXT,
            normal_min REAL,
            normal_max REAL,
            critical_low REAL,
            critical_high REAL,
            gender_specific TEXT DEFAULT 'Both',
            age_min INTEGER DEFAULT 0,
            age_max INTEGER DEFAULT 150,
            description TEXT
        )
    """)

    # --------------------
    # Test Results Table (Enhanced)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS test_results (
            result_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_test_id INTEGER,
            parameter_name TEXT,
            parameter_value TEXT,
            unit TEXT,
            reference_range TEXT,
            flag TEXT,
            entered_by TEXT,
            entry_method TEXT,
            entered_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_flag BOOLEAN DEFAULT 0,
            verified_by TEXT,
            verified_date TIMESTAMP,
            FOREIGN KEY(patient_test_id) REFERENCES patient_tests(patient_test_id) ON DELETE CASCADE
        )
    """)

    # --------------------
    # Reports Table (Enhanced)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS reports (
            report_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER,
            overall_risk_score REAL,
            risk_level TEXT,
            hash_value TEXT,
            digital_signature TEXT,
            interpretation TEXT,
            recommendation TEXT,
            diagnosis TEXT,
            ai_decision TEXT,
            doctor_override TEXT,
            verification_status TEXT DEFAULT 'Pending',
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            verified_date TIMESTAMP,
            verified_by TEXT,
            pdf_path TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
        )
    """)

    # --------------------
    # Audit Logs Table (Enhanced)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS audit_logs (
            audit_id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            actor TEXT,
            role TEXT,
            action TEXT,
            details TEXT,
            ip_address TEXT,
            status TEXT DEFAULT 'Success'
        )
    """)
    
    # --------------------
    # Sample Tracking Table (Enhanced Timeline)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sample_tracking (
            tracking_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_test_id INTEGER,
            status TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by TEXT,
            note TEXT,
            duration_minutes INTEGER,
            FOREIGN KEY(patient_test_id) REFERENCES patient_tests(patient_test_id) ON DELETE CASCADE
        )
    """)
    
    # --------------------
    # Users Table
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE,
            password TEXT,
            role TEXT,
            full_name TEXT,
            email TEXT,
            created_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)

    # --------------------
    # Notifications Table (New for automation)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS notifications (
            notification_id INTEGER PRIMARY KEY AUTOINCREMENT,
            report_id INTEGER,
            patient_id INTEGER,
            notification_type TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'sent',
            method TEXT,
            FOREIGN KEY(report_id) REFERENCES reports(report_id),
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id)
        )
    """)

    # --------------------
    # Critical Alerts Table (New for automation)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS critical_alerts (
            alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_test_id INTEGER,
            patient_id INTEGER,
            test_name TEXT,
            test_value TEXT,
            critical_range TEXT,
            acknowledged BOOLEAN DEFAULT 0,
            acknowledged_by TEXT,
            acknowledged_at TIMESTAMP,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(patient_test_id) REFERENCES patient_tests(patient_test_id),
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id)
        )
    """)

    # --------------------
    # Billing Table (NEW)
    # --------------------
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS billing (
            bill_id INTEGER PRIMARY KEY AUTOINCREMENT,
            patient_id INTEGER NOT NULL,
            test_ids TEXT NOT NULL,
            total_amount REAL NOT NULL,
            paid_amount REAL NOT NULL,
            payment_mode TEXT NOT NULL,
            payment_status TEXT DEFAULT 'Paid',
            bill_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            receipt_number TEXT UNIQUE,
            created_by TEXT,
            notes TEXT,
            FOREIGN KEY(patient_id) REFERENCES patients(patient_id) ON DELETE CASCADE
        )
    """)
    
    # Create index on billing table for faster queries
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_billing_patient ON billing(patient_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_billing_date ON billing(bill_date)")

    # --------------------
    # Add payment columns to patients table if they don't exist (for backward compatibility)
    # --------------------
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN payment_mode TEXT")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN amount_paid REAL DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # Column already exists
    
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN payment_date TIMESTAMP")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # --------------------
    # INSERT REFERENCE RANGES
    # --------------------
    insert_reference_ranges(cursor)
    
    # --------------------
    # Insert default users if empty
    # --------------------
    cursor.execute("SELECT COUNT(*) FROM users")
    if cursor.fetchone()[0] == 0:
        # Hash passwords with bcrypt
        reception_pw = bcrypt.hashpw("1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        lab_pw = bcrypt.hashpw("1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        doctor_pw = bcrypt.hashpw("1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        admin_pw = bcrypt.hashpw("1234".encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
        
        # Original users
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                      ("reception", reception_pw, "receptionist", "Reception User"))
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                      ("lab", lab_pw, "lab", "Lab Technician"))
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                      ("doctor", doctor_pw, "doctor", "Dr. Smith"))
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                      ("admin", admin_pw, "admin", "Admin User"))
        
        # NEW: Collector and Technician users
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                      ("collector", lab_pw, "collector", "Sample Collector"))
        cursor.execute("INSERT INTO users (username, password, role, full_name) VALUES (?, ?, ?, ?)", 
                      ("technician", lab_pw, "technician", "Lab Technician"))
        
        print("Default users created with bcrypt hashed passwords")
        print("   - reception/1234 (receptionist)")
        print("   - lab/1234 (lab)")
        print("   - doctor/1234 (doctor)")
        print("   - admin/1234 (admin)")
        print("   - collector/1234 (collector) - NEW")
        print("   - technician/1234 (technician) - NEW")

    conn.commit()
    conn.close()
    print("Database initialized successfully with complete test panels and billing table!")

def insert_reference_ranges(cursor):
    """Insert clinical reference ranges for all test parameters"""
    
    # Clear existing ranges (optional - comment out if you want to keep existing)
    cursor.execute("DELETE FROM test_reference_ranges")
    
    # CBC Reference Ranges
    cbc_ranges = [
        ("cbc", "hemoglobin", "g/dL", 13.5, 17.5, 7.0, 20.0, "Male", 18, 150),
        ("cbc", "hemoglobin", "g/dL", 12.0, 16.0, 7.0, 20.0, "Female", 18, 150),
        ("cbc", "hemoglobin", "g/dL", 11.0, 14.5, 6.0, 18.0, "Both", 1, 17),
        ("cbc", "wbc", "cells/µL", 4500, 11000, 2000, 30000, "Both", 0, 150),
        ("cbc", "rbc", "million/µL", 4.5, 5.9, 2.5, 7.0, "Male", 18, 150),
        ("cbc", "rbc", "million/µL", 4.1, 5.1, 2.5, 7.0, "Female", 18, 150),
        ("cbc", "platelets", "cells/µL", 150000, 450000, 50000, 1000000, "Both", 0, 150),
        ("cbc", "hematocrit", "%", 41, 50, 25, 60, "Male", 18, 150),
        ("cbc", "hematocrit", "%", 36, 44, 25, 60, "Female", 18, 150),
        ("cbc", "mcv", "fL", 80, 100, 60, 120, "Both", 0, 150),
        ("cbc", "mch", "pg", 27, 33, 20, 40, "Both", 0, 150),
        ("cbc", "mchc", "g/dL", 32, 36, 25, 40, "Both", 0, 150),
    ]
    
    # Diabetes Reference Ranges
    diabetes_ranges = [
        ("diabetes", "fasting_glucose", "mg/dL", 70, 99, 40, 400, "Both", 0, 150),
        ("diabetes", "fasting_glucose", "mg/dL", 100, 125, 40, 400, "Both", 0, 150),
        ("diabetes", "postprandial_glucose", "mg/dL", 70, 140, 40, 400, "Both", 0, 150),
        ("diabetes", "hba1c", "%", 4.0, 5.6, 3.5, 14.0, "Both", 0, 150),
        ("diabetes", "hba1c", "%", 5.7, 6.4, 3.5, 14.0, "Both", 0, 150),
    ]
    
    # Lipid Profile Reference Ranges
    lipid_ranges = [
        ("lipid", "total_cholesterol", "mg/dL", 125, 200, 100, 400, "Both", 0, 150),
        ("lipid", "hdl", "mg/dL", 40, 60, 20, 100, "Male", 0, 150),
        ("lipid", "hdl", "mg/dL", 50, 60, 20, 100, "Female", 0, 150),
        ("lipid", "ldl", "mg/dL", 0, 100, 50, 200, "Both", 0, 150),
        ("lipid", "triglycerides", "mg/dL", 0, 150, 50, 500, "Both", 0, 150),
        ("lipid", "vldl", "mg/dL", 0, 30, 10, 80, "Both", 0, 150),
        ("lipid", "cardiac_ratio", "ratio", 3.0, 5.0, 2.0, 8.0, "Both", 0, 150),
    ]
    
    # BP Reference Ranges
    bp_ranges = [
        ("bp", "systolic", "mmHg", 90, 120, 70, 200, "Both", 0, 150),
        ("bp", "diastolic", "mmHg", 60, 80, 40, 120, "Both", 0, 150),
        ("bp", "pulse_rate", "bpm", 60, 100, 40, 150, "Both", 0, 150),
    ]
    
    # BMI Reference Ranges
    bmi_ranges = [
        ("bmi", "bmi", "kg/m²", 18.5, 24.9, 15.0, 35.0, "Both", 18, 150),
        ("bmi", "bmi", "kg/m²", 17.0, 27.0, 14.0, 32.0, "Both", 2, 17),
    ]
    
    # Insert all ranges
    all_ranges = cbc_ranges + diabetes_ranges + lipid_ranges + bp_ranges + bmi_ranges
    
    for range_data in all_ranges:
        test_type, parameter, unit, normal_min, normal_max, critical_low, critical_high, gender, age_min, age_max = range_data
        
        # Check if this specific range already exists
        cursor.execute("""
            SELECT COUNT(*) FROM test_reference_ranges 
            WHERE test_type = ? AND parameter_name = ? AND gender_specific = ? 
            AND age_min = ? AND age_max = ?
        """, (test_type, parameter, gender, age_min, age_max))
        
        if cursor.fetchone()[0] == 0:
            cursor.execute("""
                INSERT INTO test_reference_ranges 
                (test_type, parameter_name, unit, normal_min, normal_max, 
                 critical_low, critical_high, gender_specific, age_min, age_max)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (test_type, parameter, unit, normal_min, normal_max, 
                  critical_low, critical_high, gender, age_min, age_max))
    
    print(f"Inserted {len(all_ranges)} reference ranges")

def get_test_price(test_type):
    """Get price for a specific test type from the TEST_PRICES dictionary"""
    return TEST_PRICES.get(test_type.lower(), 0)

def get_test_category(test_type):
    """Get the category of a test type"""
    test_type = test_type.lower()
    for category, tests in TEST_CATEGORIES.items():
        if test_type in tests:
            return category
    return 'Other'

def get_tests_by_category(category):
    """Get all test types in a category"""
    return TEST_CATEGORIES.get(category, [])

def get_all_categories():
    """Get all test categories"""
    return list(TEST_CATEGORIES.keys())

def get_all_test_types():
    """Get all available test types"""
    all_tests = []
    for tests in TEST_CATEGORIES.values():
        all_tests.extend(tests)
    return sorted(all_tests)

def generate_receipt_number():
    """Generate a unique receipt number"""
    from datetime import datetime
    import random
    
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    random_num = random.randint(1000, 9999)
    return f"RCPT-{timestamp}-{random_num}"

if __name__ == "__main__":
    init_db()
    print("✅ Database initialized with comprehensive test panels")
    print("💰 Test prices configured for", len(TEST_PRICES), "tests")
    print("📊 Test categories:", len(TEST_CATEGORIES), "categories")
    print("\n📋 Sample prices:")
    print("   - CBC: ₹500")
    print("   - Diabetes Profile: ₹600")
    print("   - Lipid Profile: ₹800")
    print("   - Liver Function (LFT): ₹1000")
    print("   - Kidney Function (KFT): ₹900")
    print("   - Thyroid Profile (TSH, T3, T4): ₹1200")
    print("   - Vitamin D: ₹1500")
    print("   - Cardiac Markers: ₹1200+")