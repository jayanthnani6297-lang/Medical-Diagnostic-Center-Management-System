import requests
import random

SERVER = "http://127.0.0.1:5000/machine_upload"

def simulate(patient_id, test_type):

    if test_type == "blood":
        results = {
            "hemoglobin": round(random.uniform(10, 17), 1),
            "wbc": random.randint(4000, 12000),
            "platelets": random.randint(150000, 450000)
        }

    elif test_type == "sugar":
        results = {
            "sugar": random.randint(70, 250)
        }

    elif test_type == "bp":
        results = {
            "systolic": random.randint(100, 180),
            "diastolic": random.randint(70, 110)
        }

    elif test_type == "bmi":
        results = {
            "bmi": round(random.uniform(18, 35), 1)
        }

    elif test_type == "lipid":
        results = {
            "hdl": random.randint(30, 70),
            "ldl": random.randint(80, 200),
            "triglycerides": random.randint(100, 300),
            "total_cholesterol": random.randint(150, 300)
        }

    else:
        print("Unknown Test")
        return

    payload = {
        "patient_id": patient_id,
        "test_type": test_type,
        "results": results
    }

    response = requests.post(SERVER, json=payload)
    print(response.json())


# Example run
simulate(1, "blood")