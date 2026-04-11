import sqlite3
import time
import threading
import random
import schedule
from datetime import datetime, timedelta
import json
import os

class AutoLabProcessor:
    """
    Automated Lab Processing System
    Simulates real laboratory automation - ONLY processes REAL patient tests
    """
    
    def __init__(self):
        self.is_running = False
        self.processing_queue = []
        self.simulation_speed = 1.0  # 1x speed (real-time)
        self.machines = [
            {"id": 1, "name": "Hematology Analyzer 1", "status": "idle", "current_test": None, "patient_test_id": None},
            {"id": 2, "name": "Chemistry Analyzer 2", "status": "idle", "current_test": None, "patient_test_id": None},
            {"id": 3, "name": "Immunology System 3", "status": "idle", "current_test": None, "patient_test_id": None},
            {"id": 4, "name": "Coagulation Timer 4", "status": "idle", "current_test": None, "patient_test_id": None}
        ]
        
        # Create notifications table if not exists
        self._init_notifications_table()
        
    def _init_notifications_table(self):
        """Create notifications table for tracking sent alerts"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        # Check if patients table has email column
        cursor.execute("PRAGMA table_info(patients)")
        columns = cursor.fetchall()
        has_email = any(col[1] == 'email' for col in columns)
        
        if not has_email:
            # Add email column if it doesn't exist
            try:
                cursor.execute("ALTER TABLE patients ADD COLUMN email TEXT")
                print("✅ Added email column to patients table")
            except:
                pass
        
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
        
        conn.commit()
        conn.close()
        
    def start_automation(self):
        """Start the automated lab processing engine"""
        self.is_running = True
        print("=" * 60)
        print("🤖 AUTOMATED LAB PROCESSING ENGINE STARTED")
        print("=" * 60)
        print("⚡ Mode: Delayed Automation (2 minute wait before processing)")
        print("📊 Status: Active - Waiting for patient tests...")
        print("⏰ Tests will be processed 2 minutes after collection")
        print("🔄 You can disable auto-processing for specific tests in Lab panel")
        print("=" * 60)
        
        # Start background threads
        threading.Thread(target=self._monitor_and_process, daemon=True, name="MonitorProcessor").start()
        threading.Thread(target=self._auto_verify, daemon=True, name="AutoVerifier").start()
        threading.Thread(target=self._notify_patients, daemon=True, name="Notifier").start()
        threading.Thread(target=self._check_critical_values, daemon=True, name="CriticalChecker").start()
        
    def stop_automation(self):
        """Stop the automation engine"""
        self.is_running = False
        print("=" * 60)
        print("🤖 AUTOMATED LAB PROCESSING ENGINE STOPPED")
        print("=" * 60)
        
    def _monitor_and_process(self):
        """Monitor for new tests and process them automatically with a delay"""
        print("📋 Test monitor started - waiting for patient tests...")
        processed_tests = set()
        
        while self.is_running:
            try:
                # Check every 10 seconds
                time.sleep(10)
                
                conn = sqlite3.connect("medical.db", timeout=20)
                cursor = conn.cursor()
                
                # Get tests that are in 'Collected' state for at least 2 MINUTES
                cursor.execute("""
                    SELECT pt.patient_test_id, pt.patient_id, pt.test_type, p.name, pt.priority
                    FROM patient_tests pt
                    JOIN patients p ON pt.patient_id = p.patient_id
                    WHERE pt.status = 'Collected' 
                    AND datetime(pt.collection_date) < datetime('now', '-2 minutes')
                    AND (pt.notes IS NULL OR pt.notes != 'MANUAL_ONLY')
                    AND pt.patient_test_id NOT IN (
                        SELECT patient_test_id FROM test_results GROUP BY patient_test_id
                    )
                    ORDER BY 
                        CASE pt.priority 
                            WHEN 'STAT' THEN 1
                            WHEN 'Urgent' THEN 2
                            ELSE 3
                        END,
                        pt.collection_date
                """)
                
                pending_tests = cursor.fetchall()
                conn.close()
                
                # Process only new tests
                new_tests = [test for test in pending_tests if test[0] not in processed_tests]
                
                if new_tests:
                    print(f"\n⏰ Processing {len(new_tests)} tests that are 2+ minutes old...")
                    for test in new_tests:
                        test_id, patient_id, test_type, patient_name, priority = test
                        print(f"🔔 Processing Test #{test_id} ({test_type}) for {patient_name}")
                        
                        # Process one test at a time
                        self._process_test_on_machine(test_id, patient_id, test_type, patient_name, priority)
                        processed_tests.add(test_id)
                        time.sleep(3)  # Delay between tests
                
            except Exception as e:
                print(f"❌ Error in monitor: {e}")
                time.sleep(5)
    
    def _process_test_on_machine(self, test_id, patient_id, test_type, patient_name, priority="Normal"):
        """Process a test on a machine"""
        try:
            # Find available machine
            available_machine = None
            for machine in self.machines:
                if machine["status"] == "idle":
                    available_machine = machine
                    break
            
            if not available_machine:
                print(f"⏳ No machines available - test #{test_id} queued")
                self.processing_queue.append((test_id, patient_id, test_type, patient_name, priority))
                return
            
            machine = available_machine
            machine["status"] = "running"
            machine["current_test"] = f"Test #{test_id}"
            machine["patient_test_id"] = test_id
            
            print(f"🔧 {machine['name']} started processing {test_type} test for {patient_name}")
            
            # Update to Processing
            self._update_status(test_id, 'Processing')
            
            # Simulate processing time
            base_time = {
                'cbc': 3,
                'diabetes': 4,
                'lipid': 5,
                'bp': 2,
                'bmi': 2,
                'lft': 4,
                'kft': 4,
                'thyroid': 5
            }.get(test_type, 3)
            
            priority_multiplier = {
                'STAT': 0.5,
                'Urgent': 0.75,
                'Normal': 1.0
            }.get(priority, 1.0)
            
            processing_time = base_time * priority_multiplier
            time.sleep(processing_time)
            
            # Generate and upload results
            results = self._generate_results(test_type)
            self._auto_upload_results(test_id, patient_id, test_type, results)
            
            # Mark as Completed
            self._update_status(test_id, 'Completed')
            print(f"✅ {machine['name']} completed test #{test_id} for {patient_name}")
            
            # Check for critical values and auto-verify if none
            if self._should_auto_verify(test_id):
                self._update_status(test_id, 'Verified')
                print(f"🔐 Test #{test_id} auto-verified - no critical values")
            
            # Free up the machine
            machine["status"] = "idle"
            machine["current_test"] = None
            machine["patient_test_id"] = None
            
            # IMPORTANT: Check and generate report after each test
            self._check_and_generate_report(patient_id, patient_name)
            
        except Exception as e:
            print(f"❌ Error processing test #{test_id}: {e}")
            if 'machine' in locals():
                machine["status"] = "idle"
                machine["current_test"] = None
                machine["patient_test_id"] = None
        
    def _generate_results(self, test_type):
        """Generate realistic results based on test type"""
        import random
        
        # Use test_id as part of seed for consistent but varied results
        random.seed(int(time.time()) + random.randint(1, 100))
        
        results = {}
        
        if test_type == "cbc":
            results = {
                "hemoglobin": round(random.uniform(10.0, 18.0), 1),
                "wbc": random.randint(3500, 12000),
                "rbc": round(random.uniform(3.8, 6.2), 1),
                "platelets": random.randint(140000, 500000),
                "hematocrit": round(random.uniform(35, 52), 1),
                "mcv": random.randint(75, 105),
                "mch": random.randint(25, 35),
                "mchc": random.randint(30, 38)
            }
        elif test_type == "diabetes":
            results = {
                "fasting_glucose": random.randint(65, 250),
                "postprandial_glucose": random.randint(80, 300),
                "hba1c": round(random.uniform(4.0, 10.0), 1)
            }
        elif test_type == "lipid":
            total = random.randint(120, 320)
            hdl = random.randint(25, 85)
            ldl = random.randint(50, 220)
            triglycerides = random.randint(50, 400)
            results = {
                "total_cholesterol": total,
                "hdl": hdl,
                "ldl": ldl,
                "triglycerides": triglycerides,
                "vldl": round(triglycerides / 5, 1),
                "cardiac_ratio": round(total / hdl, 2) if hdl > 0 else 0
            }
        elif test_type == "bp":
            results = {
                "systolic": random.randint(90, 190),
                "diastolic": random.randint(60, 120),
                "pulse_rate": random.randint(55, 115)
            }
        elif test_type == "bmi":
            height = round(random.uniform(1.45, 2.0), 2)
            weight = random.randint(45, 120)
            results = {
                "height": height,
                "weight": weight,
                "bmi": round(weight / (height * height), 1)
            }
        
        # Occasionally generate critical values (10% chance) for realism
        if random.random() < 0.1:
            for key in results:
                if random.random() < 0.3:  # 30% chance per parameter
                    if isinstance(results[key], (int, float)):
                        results[key] = results[key] * random.choice([1.5, 2.0, 0.5, 0.3])
                        print(f"⚠️ Critical value generated for {key}: {results[key]}")
        
        return results
    
    def _auto_upload_results(self, patient_test_id, patient_id, test_type, results):
        """Auto-upload results to database with reference range checking"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        # Get patient details for reference ranges
        cursor.execute("SELECT age, gender FROM patients WHERE patient_id = ?", (patient_id,))
        patient = cursor.fetchone()
        patient_age = patient[0] if patient else 30
        patient_gender = patient[1] if patient else 'Both'
        
        # Import reference checker
        from reference_utils import ReferenceChecker
        
        for key, value in results.items():
            # Check against reference ranges
            ref_range = ReferenceChecker.get_reference_range(test_type, key, patient_age, patient_gender)
            flag = ReferenceChecker.check_value(value, ref_range) if ref_range else 'Unknown'
            
            cursor.execute("""
                INSERT INTO test_results 
                (patient_test_id, parameter_name, parameter_value, unit, reference_range, flag, entered_by, entry_method)
                VALUES (?, ?, ?, ?, ?, ?, 'AUTO_SYSTEM', 'Machine')
            """, (
                patient_test_id, 
                key, 
                str(value),
                ref_range['unit'] if ref_range else '',
                f"{ref_range['normal_min']}-{ref_range['normal_max']}" if ref_range else '',
                flag
            ))
            
            # Check for critical values
            if 'Critical' in flag:
                self._create_critical_alert(patient_test_id, patient_id, key, value, ref_range)
        
        conn.commit()
        conn.close()
        
    def _create_critical_alert(self, patient_test_id, patient_id, test_name, test_value, ref_range):
        """Create a critical value alert in database"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        critical_range = f"< {ref_range['critical_low']} or > {ref_range['critical_high']}" if ref_range else "Critical"
        
        cursor.execute("""
            INSERT INTO critical_alerts 
            (patient_test_id, patient_id, test_name, test_value, critical_range, acknowledged)
            VALUES (?, ?, ?, ?, ?, 0)
        """, (patient_test_id, patient_id, test_name, str(test_value), critical_range))
        
        conn.commit()
        conn.close()
        
        print(f"🚨 CRITICAL ALERT: Patient {patient_id} - {test_name} = {test_value}")
        
    def _update_status(self, patient_test_id, status):
        """Update test status"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        if status == 'Processing':
            cursor.execute("""
                UPDATE patient_tests 
                SET status = ?, processing_start_date = CURRENT_TIMESTAMP
                WHERE patient_test_id = ?
            """, (status, patient_test_id))
        elif status == 'Completed':
            cursor.execute("""
                UPDATE patient_tests 
                SET status = ?, completion_date = CURRENT_TIMESTAMP
                WHERE patient_test_id = ?
            """, (status, patient_test_id))
        elif status == 'Verified':
            cursor.execute("""
                UPDATE patient_tests 
                SET status = ?, verification_date = CURRENT_TIMESTAMP, verified_by = 'AUTO_SYSTEM'
                WHERE patient_test_id = ?
            """, (status, patient_test_id))
        else:
            cursor.execute("""
                UPDATE patient_tests 
                SET status = ?
                WHERE patient_test_id = ?
            """, (status, patient_test_id))
        
        conn.commit()
        conn.close()
        
    def _should_auto_verify(self, patient_test_id):
        """Check if test should be auto-verified"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT COUNT(*) FROM test_results 
            WHERE patient_test_id = ? 
            AND flag LIKE '%Critical%'
        """, (patient_test_id,))
        
        criticals = cursor.fetchone()[0]
        conn.close()
        
        return criticals == 0
        
    def _check_and_generate_report(self, patient_id, patient_name):
        """Check if all tests done and generate report"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        # Check if all tests are completed/verified
        cursor.execute("""
            SELECT COUNT(*) FROM patient_tests 
            WHERE patient_id = ? AND status NOT IN ('Completed', 'Verified')
        """, (patient_id,))
        
        pending = cursor.fetchone()[0]
        
        # Check if any results exist
        cursor.execute("""
            SELECT COUNT(*) FROM test_results tr
            JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
            WHERE pt.patient_id = ?
        """, (patient_id,))
        
        results_count = cursor.fetchone()[0]
        
        conn.close()
        
        # If no pending tests AND there are results, generate report
        if pending == 0 and results_count > 0:
            try:
                # Import here to avoid circular imports
                from app import generate_final_report
                report_id, risk_score, risk_level = generate_final_report(patient_id)
                print(f"📄 Report #{report_id} auto-generated for patient {patient_name}")
                
                # Queue notification
                self._queue_notification(patient_id, report_id)
                return True
            except Exception as e:
                print(f"❌ Error generating report: {e}")
                return False
        else:
            print(f"⏳ Waiting for patient {patient_name}: {pending} tests pending, {results_count} results")
            return False
            
    def _generate_report(self, patient_id):
        """Generate final report"""
        from app import generate_final_report
        report_id, risk_score, risk_level = generate_final_report(patient_id)
        return report_id
        
    def _queue_notification(self, patient_id, report_id):
        """Queue notification for patient"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO notifications (report_id, patient_id, notification_type, method)
            VALUES (?, ?, 'report_ready', 'auto')
        """, (report_id, patient_id))
        
        conn.commit()
        conn.close()
    
    def _auto_verify(self):
        """Auto-verify tests after 30 seconds if no criticals"""
        print("🔐 Auto-verifier started - monitoring completed tests...")
        while self.is_running:
            try:
                conn = sqlite3.connect("medical.db")
                cursor = conn.cursor()
                
                # Get tests completed more than 30 seconds ago but not verified
                cursor.execute("""
                    SELECT pt.patient_test_id, pt.patient_id, p.name
                    FROM patient_tests pt
                    JOIN patients p ON pt.patient_id = p.patient_id
                    LEFT JOIN test_results tr ON pt.patient_test_id = tr.patient_test_id
                    WHERE pt.status = 'Completed' 
                    AND pt.completion_date < datetime('now', '-30 seconds')
                    GROUP BY pt.patient_test_id
                    HAVING SUM(CASE WHEN tr.flag LIKE '%Critical%' THEN 1 ELSE 0 END) = 0
                """)
                
                to_verify = cursor.fetchall()
                
                for test_id, patient_id, patient_name in to_verify:
                    self._update_status(test_id, 'Verified')
                    print(f"🔐 Test #{test_id} for {patient_name} auto-verified (no critical values)")
                    
                    # Check for report generation
                    self._check_and_generate_report(patient_id, patient_name)
                
                conn.close()
                time.sleep(10)
                
            except Exception as e:
                print(f"❌ Error in auto-verify: {e}")
                time.sleep(10)
    
    def _check_critical_values(self):
        """Monitor for critical values and create alerts"""
        print("🚨 Critical value monitor started - watching for critical results...")
        while self.is_running:
            try:
                conn = sqlite3.connect("medical.db")
                cursor = conn.cursor()
                
                # Get unacknowledged critical alerts
                cursor.execute("""
                    SELECT ca.alert_id, ca.patient_id, ca.test_name, ca.test_value, 
                           ca.critical_range, p.name, p.contact
                    FROM critical_alerts ca
                    JOIN patients p ON ca.patient_id = p.patient_id
                    WHERE ca.acknowledged = 0
                """)
                
                alerts = cursor.fetchall()
                
                for alert in alerts:
                    print(f"🚨 ACTIVE CRITICAL ALERT: {alert[5]} - {alert[2]} = {alert[3]}")
                    
                    # In real system, you would:
                    # - Send SMS to doctor
                    # - Send email to nurse
                    # - Trigger alarm in lab
                    # - Update dashboard
                
                conn.close()
                time.sleep(15)
                
            except Exception as e:
                print(f"❌ Error in critical monitor: {e}")
                time.sleep(15)
            
    def _notify_patients(self):
        """Auto-notify patients when reports ready"""
        print("📱 Patient notifier started - waiting for reports...")
        while self.is_running:
            try:
                conn = sqlite3.connect("medical.db")
                cursor = conn.cursor()
                
                # Get unsent notifications - get contact and email
                cursor.execute("""
                    SELECT n.notification_id, n.report_id, n.patient_id, p.name, p.contact, p.email
                    FROM notifications n
                    JOIN patients p ON n.patient_id = p.patient_id
                    WHERE n.status = 'sent'
                """)
                
                new_notifications = cursor.fetchall()
                
                for notif in new_notifications:
                    notif_id, report_id, patient_id, name, contact, email = notif
                    
                    print(f"📱 Sending notification to {name} about report #{report_id}")
                    
                    # Try email first (if available)
                    if email:
                        print(f"   📧 Email notification ready for {email}")
                    # Then try SMS (if contact available)
                    elif contact:
                        print(f"   📱 SMS notification ready for {contact}")
                    else:
                        print(f"   ⚠️ No contact information available for {name}")
                    
                    # Update status
                    cursor.execute("""
                        UPDATE notifications 
                        SET status = 'delivered' 
                        WHERE notification_id = ?
                    """, (notif_id,))
                
                conn.commit()
                conn.close()
                time.sleep(20)
                
            except Exception as e:
                print(f"❌ Error in notifier: {e}")
                time.sleep(20)
            
    def _daily_maintenance(self):
        """Daily maintenance tasks"""
        print("🧹 Running daily maintenance...")
        
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        # Archive old alerts (older than 30 days)
        cursor.execute("""
            UPDATE critical_alerts 
            SET acknowledged = 1, acknowledged_by = 'SYSTEM' 
            WHERE created_at < date('now', '-30 days')
        """)
        
        # Clean up old notifications
        cursor.execute("""
            DELETE FROM notifications 
            WHERE sent_at < date('now', '-90 days')
        """)
        
        conn.commit()
        conn.close()
        
        print("✅ Daily maintenance complete")

    def get_automation_stats(self):
        """Get automation statistics"""
        conn = sqlite3.connect("medical.db", timeout=10)
        cursor = conn.cursor()
        
        # Fix: Use a different query that doesn't rely on 'entered_by' column
        # Get today's auto-processed count - using processing_start_date instead
        cursor.execute("""
            SELECT COUNT(*) FROM patient_tests 
            WHERE date(processing_start_date) = date('now')
            AND processing_start_date IS NOT NULL
        """)
        auto_processed = cursor.fetchone()[0]
        
        # Get auto-verified count
        cursor.execute("""
            SELECT COUNT(*) FROM patient_tests 
            WHERE date(verification_date) = date('now')
            AND verified_by = 'AUTO_SYSTEM'
        """)
        auto_verified = cursor.fetchone()[0]
        
        # Get reports generated today
        cursor.execute("""
            SELECT COUNT(*) FROM reports 
            WHERE date(created_date) = date('now')
        """)
        reports_today = cursor.fetchone()[0]
        
        # Get notifications sent today
        cursor.execute("""
            SELECT COUNT(*) FROM notifications 
            WHERE date(sent_at) = date('now')
        """)
        notifications_today = cursor.fetchone()[0]
        
        # Get active critical alerts
        cursor.execute("""
            SELECT COUNT(*) FROM critical_alerts 
            WHERE acknowledged = 0
        """)
        active_alerts = cursor.fetchone()[0]
        
        conn.close()
        
        return {
            'auto_processed': auto_processed,
            'auto_verified': auto_verified,
            'reports_generated': reports_today,
            'notifications_sent': notifications_today,
            'active_alerts': active_alerts
        }

# Singleton instance
auto_lab = AutoLabProcessor()