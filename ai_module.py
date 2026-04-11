def calculate_risk(sugar, cholesterol, bp_string, bmi):

    risk_score = 0

    # -----------------------
    # Safe BP Parsing
    # -----------------------
    try:
        systolic = int(bp_string.split("/")[0])
    except:
        systolic = 0

    # -----------------------
    # Blood Pressure
    # -----------------------
    if systolic > 160:
        risk_score += 25
    elif systolic > 140:
        risk_score += 20
    elif systolic > 120:
        risk_score += 10

    # -----------------------
    # Sugar
    # -----------------------
    if sugar > 250:
        risk_score += 30
    elif sugar > 140:
        risk_score += 15

    # -----------------------
    # Cholesterol
    # -----------------------
    if cholesterol > 240:
        risk_score += 25
    elif cholesterol > 200:
        risk_score += 15

    # -----------------------
    # BMI
    # -----------------------
    if bmi > 30:
        risk_score += 15
    elif bmi > 25:
        risk_score += 8

    # -----------------------
    # Risk Level
    # -----------------------
    if risk_score >= 70:
        risk_level = "Critical"
    elif risk_score >= 40:
        risk_level = "High"
    elif risk_score >= 20:
        risk_level = "Moderate"
    else:
        risk_level = "Low"

    return risk_score, risk_level


def interpret_results(results_dict):

    interpretation = {}
    critical_flags = []

    hba1c = float(results_dict.get("hba1c", 0))
    if hba1c > 6.5:
        interpretation["hba1c"] = "Diabetic Range"
    elif hba1c > 5.7:
        interpretation["hba1c"] = "Pre-diabetic"
    else:
        interpretation["hba1c"] = "Normal"

    cardiac_ratio = float(results_dict.get("cardiac_ratio", 0))
    if cardiac_ratio > 5:
        interpretation["cardiac_ratio"] = "High Cardiac Risk"
    else:
        interpretation["cardiac_ratio"] = "Normal"    

    sugar = float(results_dict.get("sugar", 0))
    if sugar > 250:
        interpretation["sugar"] = "Critical Hyperglycemia"
        critical_flags.append("Sugar")
    elif sugar > 140:
        interpretation["sugar"] = "High Sugar"
    else:
        interpretation["sugar"] = "Normal"

    cholesterol = float(results_dict.get("total_cholesterol", 0))
    if cholesterol > 240:
        interpretation["cholesterol"] = "High Cholesterol"
        critical_flags.append("Cholesterol")
    elif cholesterol > 200:
        interpretation["cholesterol"] = "Borderline High"
    else:
        interpretation["cholesterol"] = "Normal"

    try:
        systolic = int(results_dict.get("systolic", 0))
    except:
        systolic = 0

    if systolic > 160:
        interpretation["bp"] = "Stage 2 Hypertension"
        critical_flags.append("Blood Pressure")
    elif systolic > 140:
        interpretation["bp"] = "Stage 1 Hypertension"
    elif systolic > 120:
        interpretation["bp"] = "Elevated BP"
    else:
        interpretation["bp"] = "Normal"

    bmi = float(results_dict.get("bmi", 0))
    if bmi > 30:
        interpretation["bmi"] = "Obese"
        critical_flags.append("BMI")
    elif bmi > 25:
        interpretation["bmi"] = "Overweight"
    else:
        interpretation["bmi"] = "Normal"

    if critical_flags:
        recommendation = "Immediate medical consultation required."
    else:
        recommendation = "All parameters within acceptable limits."

    return interpretation, recommendation