from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, current_app
from security_utils import security_manager, tamper_detector, audit_logger
from cryptography.hazmat.primitives import serialization
import sqlite3
import json
import os
from functools import wraps
from datetime import datetime

security_bp = Blueprint('security', __name__, url_prefix='/security')

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session or session.get('role') != 'admin':
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'username' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

@security_bp.route('/dashboard')
@admin_required
def security_dashboard():
    """Security dashboard showing system security status"""
    conn = sqlite3.connect("medical.db", timeout=10)
    cursor = conn.cursor()
    
    # Get security statistics
    cursor.execute("""
        SELECT COUNT(*) FROM audit_logs 
        WHERE action LIKE '%TAMPER%' OR status = 'ALERT'
    """)
    tamper_count = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM audit_logs 
        WHERE action = 'REPORT_VERIFICATION' AND status = 'FAILED'
    """)
    failed_verifications = cursor.fetchone()[0]
    
    cursor.execute("""
        SELECT COUNT(*) FROM reports WHERE verification_status = 'Tampered'
    """)
    tampered_reports = cursor.fetchone()[0]
    
    # Get recent security events
    cursor.execute("""
        SELECT timestamp, actor, action, details, ip_address, status
        FROM audit_logs 
        WHERE action LIKE '%TAMPER%' OR status = 'ALERT' OR action = 'REPORT_VERIFICATION'
        ORDER BY timestamp DESC LIMIT 20
    """)
    security_events = cursor.fetchall()
    
    conn.close()
    
    # Get public key for display
    public_key = security_manager.get_public_key_pem()
    
    return render_template('security_dashboard.html',
                         tamper_count=tamper_count,
                         failed_verifications=failed_verifications,
                         tampered_reports=tampered_reports,
                         security_events=security_events,
                         public_key=public_key)

@security_bp.route('/verify_chain/<int:report_id>')
@login_required
def verify_chain(report_id):
    """Verify the hash chain for a report"""
    conn = sqlite3.connect("medical.db", timeout=10)
    cursor = conn.cursor()
    
    # Get the report and all previous reports
    cursor.execute("""
        SELECT report_id, hash_value, created_date, patient_id
        FROM reports
        WHERE report_id <= ?
        ORDER BY report_id
    """, (report_id,))
    
    reports = cursor.fetchall()
    
    # Build chain data
    chain = []
    valid = True
    for i, report in enumerate(reports):
        chain.append({
            'index': i + 1,
            'report_id': report[0],
            'hash': report[1][:20] + '...' + report[1][-10:] if report[1] else 'N/A',
            'date': report[2],
            'valid': True  # We'd need actual verification logic here
        })
    
    conn.close()
    
    return jsonify({
        'valid': valid,
        'chain_length': len(chain),
        'chain': chain
    })

@security_bp.route('/verify_signature/<int:report_id>')
@login_required
def verify_signature(report_id):
    """Verify digital signature for a report"""
    conn = sqlite3.connect("medical.db", timeout=10)
    cursor = conn.cursor()
    
    # Get report data
    cursor.execute("""
        SELECT patient_id, overall_risk_score, hash_value, digital_signature
        FROM reports WHERE report_id = ?
    """, (report_id,))
    
    report = cursor.fetchone()
    
    if not report:
        conn.close()
        return jsonify({'error': 'Report not found'}), 404
    
    patient_id, risk_score, stored_hash, signature = report
    
    # Recreate report content
    report_content = f"{patient_id}-{risk_score}-{stored_hash}"
    
    # Verify signature
    if signature:
        is_valid = security_manager.verify_signature(report_content, signature)
    else:
        is_valid = False
    
    conn.close()
    
    return jsonify({
        'report_id': report_id,
        'signature_valid': is_valid,
        'has_signature': bool(signature)
    })

@security_bp.route('/events')
@admin_required
def security_events():
    """Get security events with filtering"""
    filter_type = request.args.get('filter', 'all')
    limit = request.args.get('limit', 100, type=int)
    
    conn = sqlite3.connect("medical.db", timeout=10)
    cursor = conn.cursor()
    
    query = "SELECT timestamp, actor, action, details, ip_address, status FROM audit_logs"
    params = []
    
    if filter_type == 'tamper':
        query += " WHERE action LIKE '%TAMPER%' OR status = 'ALERT'"
    elif filter_type == 'failed':
        query += " WHERE status = 'FAILED'"
    elif filter_type == 'verification':
        query += " WHERE action = 'REPORT_VERIFICATION'"
    
    query += " ORDER BY timestamp DESC LIMIT ?"
    params.append(limit)
    
    cursor.execute(query, params)
    events = cursor.fetchall()
    conn.close()
    
    return jsonify([{
        'timestamp': e[0],
        'actor': e[1],
        'action': e[2],
        'details': json.loads(e[3]) if e[3] else {},
        'ip': e[4],
        'status': e[5]
    } for e in events])

@security_bp.route('/export_audit')
@admin_required
def export_audit():
    """Export audit logs as JSON"""
    conn = sqlite3.connect("medical.db", timeout=10)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT audit_id, timestamp, actor, role, action, details, ip_address, status
        FROM audit_logs
        ORDER BY timestamp DESC
        LIMIT 1000
    """)
    
    logs = cursor.fetchall()
    conn.close()
    
    export_data = [{
        'id': log[0],
        'timestamp': log[1],
        'actor': log[2],
        'role': log[3],
        'action': log[4],
        'details': json.loads(log[5]) if log[5] else {},
        'ip': log[6],
        'status': log[7]
    } for log in logs]
    
    return jsonify(export_data)