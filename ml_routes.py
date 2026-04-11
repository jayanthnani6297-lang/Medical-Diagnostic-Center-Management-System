# ml_routes.py
from flask import Blueprint, render_template, request, jsonify, session, flash, redirect, url_for
from ml_models import ml_disease_model
from decorators import role_required
import sqlite3
import json

ml_bp = Blueprint('ml', __name__, url_prefix='/ml')

@ml_bp.route('/dashboard')
@role_required('doctor')
def ml_dashboard():
    """ML Dashboard for disease predictions"""
    
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    
    # Get patients with test results
    cursor.execute("""
        SELECT DISTINCT p.patient_id, p.name, 
               COUNT(DISTINCT pt.patient_test_id) as test_count
        FROM patients p
        JOIN patient_tests pt ON p.patient_id = pt.patient_id
        JOIN test_results tr ON pt.patient_test_id = tr.patient_test_id
        GROUP BY p.patient_id
        ORDER BY p.name
        LIMIT 20
    """)
    
    patients_data = cursor.fetchall()
    
    # If no patients with test results, get all patients
    if not patients_data:
        cursor.execute("""
            SELECT patient_id, name, 0 as test_count
            FROM patients
            ORDER BY name
            LIMIT 20
        """)
        patients_data = cursor.fetchall()
    
    conn.close()
    
    patients = []
    for p in patients_data:
        patients.append({
            'id': p[0],
            'name': p[1],
            'test_count': p[2]
        })
    
    return render_template('ml_dashboard.html', patients=patients)

@ml_bp.route('/predict/<int:patient_id>', methods=['GET', 'POST'])
@role_required('doctor')
def predict_patient(patient_id):
    """Predict disease for a specific patient"""
    
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    
    # Get patient name first
    cursor.execute("SELECT name FROM patients WHERE patient_id = ?", (patient_id,))
    patient_result = cursor.fetchone()
    
    if not patient_result:
        conn.close()
        flash("Patient not found", "error")
        return redirect(url_for('ml.ml_dashboard'))
    
    patient_name = patient_result[0]
    
    # Get patient's latest test results
    cursor.execute("""
        SELECT tr.parameter_name, tr.parameter_value
        FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE pt.patient_id = ?
        ORDER BY tr.created_date DESC
        LIMIT 50
    """, (patient_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    # Check if patient has any test results
    if not results:
        flash(f"No test results found for patient {patient_name}. Please process tests first.", "warning")
        return redirect(url_for('ml.ml_dashboard'))
    
    # Convert to dictionary
    test_dict = {}
    for param, value in results:
        try:
            test_dict[param] = float(value)
        except (ValueError, TypeError):
            test_dict[param] = 0
    
    # Make prediction
    prediction = ml_disease_model.predict_disease(test_dict)
    
    # Check for errors
    if 'error' in prediction:
        flash(prediction['error'], "error")
        return redirect(url_for('ml.ml_dashboard'))
    
    # Get recommendations
    recommendations = ml_disease_model.get_recommendations(prediction['primary_diagnosis'])
    
    return render_template('ml_prediction.html',
                         patient_id=patient_id,
                         patient_name=patient_name,
                         prediction=prediction,
                         recommendations=recommendations,
                         test_results=test_dict)

@ml_bp.route('/api/predict/<int:patient_id>', methods=['GET'])
@role_required('doctor')
def api_predict(patient_id):
    """API endpoint for disease prediction"""
    
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT tr.parameter_name, tr.parameter_value
        FROM test_results tr
        JOIN patient_tests pt ON tr.patient_test_id = pt.patient_test_id
        WHERE pt.patient_id = ?
        ORDER BY tr.created_date DESC
        LIMIT 50
    """, (patient_id,))
    
    results = cursor.fetchall()
    conn.close()
    
    if not results:
        return jsonify({'error': 'No test results found'}), 404
    
    test_dict = {}
    for param, value in results:
        try:
            test_dict[param] = float(value)
        except (ValueError, TypeError):
            test_dict[param] = 0
    
    prediction = ml_disease_model.predict_disease(test_dict)
    
    return jsonify(prediction)

@ml_bp.route('/analyze_report/<int:report_id>')
@role_required('doctor')
def analyze_report(report_id):
    """Analyze a generated report with ML"""
    
    conn = sqlite3.connect("medical.db")
    cursor = conn.cursor()
    
    # Get patient_id from report
    cursor.execute("SELECT patient_id FROM reports WHERE report_id = ?", (report_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result:
        flash("Report not found", "error")
        return redirect(url_for('ml.ml_dashboard'))
    
    patient_id = result[0]
    
    return redirect(url_for('ml.predict_patient', patient_id=patient_id))

# Health check endpoint
@ml_bp.route('/health')
def ml_health():
    """Check if ML model is loaded"""
    if ml_disease_model and ml_disease_model.model:
        return jsonify({
            'status': 'healthy',
            'model_loaded': True,
            'diseases': list(ml_disease_model.label_decoder.values())
        })
    else:
        return jsonify({
            'status': 'unhealthy',
            'model_loaded': False
        }), 503