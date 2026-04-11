import sqlite3
from datetime import datetime
from flask import session
import json

class StatusManager:
    """Utility class for managing sample/test status workflow"""
    
    STATUS_FLOW = {
        'Collected': ['Processing', 'Completed'],  # Collected can go to Processing or directly to Completed
        'Processing': ['Completed'],               # Processing can only go to Completed
        'Completed': ['Verified'],                  # Completed can go to Verified
        'Verified': []                              # Final state
    }
    
    @staticmethod
    def validate_transition(current_status, new_status):
        """Check if status transition is valid"""
        if current_status == new_status:
            return True, "Same status"
        
        allowed = StatusManager.STATUS_FLOW.get(current_status, [])
        if new_status in allowed:
            return True, "Valid transition"
        else:
            return False, f"Cannot change from {current_status} to {new_status}"
    
    @staticmethod
    def update_status(patient_test_id, new_status, note="", cursor=None):
        """Update test status with timeline tracking"""
        close_conn = False
        if not cursor:
            conn = sqlite3.connect("medical.db", timeout=10)
            cursor = conn.cursor()
            close_conn = True
        
        # Get current status
        cursor.execute("""
            SELECT status FROM patient_tests 
            WHERE patient_test_id = ?
        """, (patient_test_id,))
        result = cursor.fetchone()
        
        if not result:
            if close_conn:
                conn.close()
            return False, "Test not found"
        
        current_status = result[0]
        
        # Validate transition
        valid, message = StatusManager.validate_transition(current_status, new_status)
        if not valid:
            if close_conn:
                conn.close()
            return False, message
        
        # Calculate duration from last status change
        duration = None
        cursor.execute("""
            SELECT updated_at FROM sample_tracking 
            WHERE patient_test_id = ? 
            ORDER BY tracking_id DESC LIMIT 1
        """, (patient_test_id,))
        last_update = cursor.fetchone()
        
        if last_update:
            try:
                last_time = datetime.strptime(last_update[0], '%Y-%m-%d %H:%M:%S')
                now = datetime.now()
                duration = int((now - last_time).total_seconds() / 60)  # Duration in minutes
            except:
                duration = None
        
        # Update patient_tests with appropriate timestamp
        update_fields = {"status": new_status}
        
        if new_status == 'Processing' and current_status == 'Collected':
            update_fields["processing_start_date"] = datetime.now()
        elif new_status == 'Completed':
            update_fields["completion_date"] = datetime.now()
        elif new_status == 'Verified':
            update_fields["verification_date"] = datetime.now()
            update_fields["verified_by"] = session.get('username', 'system')
        
        # Build update query dynamically
        set_clause = ", ".join([f"{k} = ?" for k in update_fields.keys()])
        values = list(update_fields.values())
        values.append(patient_test_id)
        
        cursor.execute(f"""
            UPDATE patient_tests 
            SET {set_clause}
            WHERE patient_test_id = ?
        """, values)
        
        # Insert into sample_tracking
        cursor.execute("""
            INSERT INTO sample_tracking 
            (patient_test_id, status, updated_by, note, duration_minutes)
            VALUES (?, ?, ?, ?, ?)
        """, (patient_test_id, new_status, 
              session.get('username', 'system'), note, duration))
        
        if close_conn:
            conn.commit()
            conn.close()
        
        return True, f"Status updated to {new_status}"
    
    @staticmethod
    def get_timeline(patient_test_id):
        """Get complete status timeline for a test"""
        conn = sqlite3.connect("medical.db", timeout=10)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT status, updated_at, updated_by, note, duration_minutes
            FROM sample_tracking
            WHERE patient_test_id = ?
            ORDER BY tracking_id
        """, (patient_test_id,))
        
        timeline = cursor.fetchall()
        conn.close()
        return timeline
    
    @staticmethod
    def get_test_status_summary(patient_id=None):
        """Get summary of all tests by status"""
        conn = sqlite3.connect("medical.db", timeout=10)
        cursor = conn.cursor()
        
        if patient_id:
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM patient_tests
                WHERE patient_id = ?
                GROUP BY status
            """, (patient_id,))
        else:
            cursor.execute("""
                SELECT status, COUNT(*) as count
                FROM patient_tests
                GROUP BY status
            """)
        
        summary = dict(cursor.fetchall())
        conn.close()
        
        # Ensure all statuses are represented
        for status in ['Collected', 'Processing', 'Completed', 'Verified']:
            if status not in summary:
                summary[status] = 0
        
        return summary
    
    @staticmethod
    def calculate_avg_processing_time(test_type=None):
        """Calculate average processing time for tests"""
        conn = sqlite3.connect("medical.db", timeout=10)
        cursor = conn.cursor()
        
        query = """
            SELECT AVG(duration_minutes)
            FROM sample_tracking st
            JOIN patient_tests pt ON st.patient_test_id = pt.patient_test_id
            WHERE st.status = 'Completed'
        """
        params = []
        
        if test_type:
            query += " AND pt.test_type = ?"
            params.append(test_type)
        
        cursor.execute(query, params)
        avg_time = cursor.fetchone()[0]
        conn.close()
        
        return round(avg_time, 2) if avg_time else None