# ml_models.py
import pickle
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.model_selection import train_test_split
from sklearn.metrics import accuracy_score, classification_report
import os
import json

class DiseasePredictionModel:
    """
    Machine Learning model for disease prediction based on lab test results
    """
    
    def __init__(self):
        self.model = None
        self.label_encoder = {}
        self.label_decoder = {}
        self.feature_columns = []
        self.disease_categories = {
            'diabetes': ['fasting_glucose', 'postprandial_glucose', 'hba1c'],
            'heart_disease': ['total_cholesterol', 'hdl', 'ldl', 'triglycerides', 'systolic', 'diastolic'],
            'liver_disease': ['sgpt_alt', 'sgot_ast', 'total_bilirubin', 'albumin', 'alkaline_phosphatase'],
            'kidney_disease': ['blood_urea', 'serum_creatinine', 'uric_acid'],
            'thyroid_disorder': ['tsh', 't3', 't4'],
            'anemia': ['hemoglobin', 'rbc', 'mcv', 'mch', 'mchc']
        }
        self.model_path = 'ml_models.pkl'
        self.load_or_create_model()
    
    def generate_training_data(self):
        """Generate synthetic training data for demonstration"""
        np.random.seed(42)
        n_samples = 1000
        
        data = []
        labels = []
        
        for i in range(n_samples):
            # Generate random test results
            sample = {
                'fasting_glucose': np.random.normal(100, 20),
                'postprandial_glucose': np.random.normal(140, 30),
                'hba1c': np.random.normal(5.5, 1),
                'total_cholesterol': np.random.normal(200, 40),
                'hdl': np.random.normal(50, 10),
                'ldl': np.random.normal(120, 30),
                'triglycerides': np.random.normal(150, 50),
                'systolic': np.random.normal(120, 15),
                'diastolic': np.random.normal(80, 10),
                'sgpt_alt': np.random.normal(30, 15),
                'sgot_ast': np.random.normal(35, 15),
                'total_bilirubin': np.random.normal(1, 0.5),
                'albumin': np.random.normal(4.5, 0.5),
                'alkaline_phosphatase': np.random.normal(80, 30),
                'blood_urea': np.random.normal(20, 8),
                'serum_creatinine': np.random.normal(1, 0.3),
                'uric_acid': np.random.normal(5, 1.5),
                'tsh': np.random.normal(2.5, 1.5),
                't3': np.random.normal(120, 25),
                't4': np.random.normal(7, 1.5),
                'hemoglobin': np.random.normal(14, 2),
                'rbc': np.random.normal(5, 0.5),
                'mcv': np.random.normal(90, 5),
                'mch': np.random.normal(30, 2),
                'mchc': np.random.normal(33, 1)
            }
            
            # Rule-based labeling for demonstration
            # Diabetes
            if (sample['fasting_glucose'] > 126 or 
                sample['hba1c'] > 6.5):
                label = 'diabetes'
            # Heart disease
            elif (sample['total_cholesterol'] > 240 or 
                  sample['ldl'] > 160 or
                  sample['systolic'] > 140):
                label = 'heart_disease'
            # Liver disease
            elif (sample['sgpt_alt'] > 50 or 
                  sample['sgot_ast'] > 50):
                label = 'liver_disease'
            # Kidney disease
            elif (sample['serum_creatinine'] > 1.3 or
                  sample['blood_urea'] > 30):
                label = 'kidney_disease'
            # Thyroid disorder
            elif (sample['tsh'] > 4.5 or sample['tsh'] < 0.5):
                label = 'thyroid_disorder'
            # Anemia
            elif (sample['hemoglobin'] < 12):
                label = 'anemia'
            else:
                label = 'normal'
            
            data.append(sample)
            labels.append(label)
        
        return pd.DataFrame(data), labels
    
    def load_or_create_model(self):
        """Load existing model or train a new one"""
        if os.path.exists(self.model_path):
            try:
                with open(self.model_path, 'rb') as f:
                    self.model = pickle.load(f)
                print("✅ Loaded existing ML model")
                
                # Try to load feature columns if they exist
                if os.path.exists('feature_columns.pkl'):
                    with open('feature_columns.pkl', 'rb') as fc:
                        self.feature_columns = pickle.load(fc)
                return
            except Exception as e:
                print(f"⚠️ Could not load model ({e}), training new one...")
        
        # Generate training data
        X, y = self.generate_training_data()
        
        # Prepare features
        feature_columns = list(self.disease_categories.values())
        feature_columns = [item for sublist in feature_columns for item in sublist]
        feature_columns = list(set(feature_columns))  # Remove duplicates
        self.feature_columns = feature_columns
        
        X = X[feature_columns]
        
        # Fill missing values with mean
        X = X.fillna(X.mean())
        
        # Encode labels
        unique_labels = sorted(set(y))
        self.label_encoder = {label: i for i, label in enumerate(unique_labels)}
        self.label_decoder = {i: label for label, i in self.label_encoder.items()}
        y_encoded = [self.label_encoder[label] for label in y]
        
        # Split data
        X_train, X_test, y_train, y_test = train_test_split(
            X, y_encoded, test_size=0.2, random_state=42, stratify=y_encoded
        )
        
        # Train Random Forest model
        self.model = RandomForestClassifier(
            n_estimators=100,
            max_depth=10,
            random_state=42,
            class_weight='balanced'
        )
        self.model.fit(X_train, y_train)
        
        # Evaluate
        y_pred = self.model.predict(X_test)
        accuracy = accuracy_score(y_test, y_pred)
        print(f"✅ Trained new ML model with accuracy: {accuracy:.2f}")
        
        # Print per-class accuracy
        print("\n📊 Per-class accuracy:")
        for i, label in self.label_decoder.items():
            mask = [idx for idx, val in enumerate(y_test) if val == i]
            if mask:
                class_acc = sum([1 for idx in mask if y_pred[idx] == i]) / len(mask)
                print(f"  • {label}: {class_acc:.2f}")
        
        # Save model
        with open(self.model_path, 'wb') as f:
            pickle.dump(self.model, f)
        
        # Save feature columns for later use
        with open('feature_columns.pkl', 'wb') as fc:
            pickle.dump(self.feature_columns, fc)
        
        return self.model
    
    def predict_disease(self, test_results):
        """
        Predict disease based on test results
        
        Args:
            test_results: Dictionary with test parameters and values
        
        Returns:
            Dictionary with prediction results
        """
        # Check if model is loaded
        if not self.model:
            self.load_or_create_model()
            if not self.model:
                return {
                    'error': 'Model not loaded',
                    'primary_diagnosis': 'unknown',
                    'confidence': 0,
                    'risk_level': 'Unknown',
                    'top_predictions': [],
                    'all_probabilities': {}
                }
        
        # Check if test_results is empty
        if not test_results or all(v == 0 for v in test_results.values()):
            return {
                'primary_diagnosis': 'insufficient_data',
                'confidence': 0,
                'risk_level': 'Insufficient Data',
                'top_predictions': [
                    {'disease': 'insufficient_data', 'probability': 1.0, 'confidence': 0}
                ],
                'all_probabilities': {'insufficient_data': 1.0}
            }
        
        # Prepare feature vector
        features = []
        missing_features = []
        
        for feature in self.feature_columns:
            value = float(test_results.get(feature, 0))
            if value == 0 and feature not in test_results:
                missing_features.append(feature)
            features.append(value)
        
        # If too many features missing, return warning
        if len(missing_features) > len(self.feature_columns) * 0.5:
            return {
                'primary_diagnosis': 'insufficient_data',
                'confidence': 0,
                'risk_level': 'Insufficient Data',
                'top_predictions': [
                    {'disease': 'insufficient_data', 'probability': 1.0, 'confidence': 0}
                ],
                'all_probabilities': {'insufficient_data': 1.0},
                'missing_features': missing_features
            }
        
        # Convert to numpy array and reshape
        features = np.array(features).reshape(1, -1)
        
        # Make prediction
        try:
            prediction = self.model.predict(features)[0]
            probabilities = self.model.predict_proba(features)[0]
        except Exception as e:
            return {
                'error': f'Prediction error: {str(e)}',
                'primary_diagnosis': 'error',
                'confidence': 0,
                'risk_level': 'Error',
                'top_predictions': [],
                'all_probabilities': {}
            }
        
        # Get disease name
        disease_name = self.label_decoder[prediction]
        
        # Get top 3 predictions
        top_indices = np.argsort(probabilities)[-3:][::-1]
        top_predictions = [
            {
                'disease': self.label_decoder[i],
                'probability': float(probabilities[i]),
                'confidence': float(probabilities[i] * 100)
            }
            for i in top_indices
        ]
        
        return {
            'primary_diagnosis': disease_name,
            'confidence': float(probabilities[prediction] * 100),
            'risk_level': self.get_risk_level(disease_name),
            'top_predictions': top_predictions,
            'all_probabilities': {
                self.label_decoder[i]: float(probabilities[i])
                for i in range(len(probabilities))
            }
        }
    
    def get_risk_level(self, disease):
        """Get risk level based on disease"""
        high_risk = ['heart_disease', 'diabetes', 'kidney_disease']
        moderate_risk = ['liver_disease', 'thyroid_disorder']
        
        if disease in high_risk:
            return 'High'
        elif disease in moderate_risk:
            return 'Moderate'
        elif disease == 'normal':
            return 'Low'
        else:
            return 'Moderate'
    
    def get_recommendations(self, disease):
        """Get health recommendations based on predicted disease"""
        recommendations = {
            'diabetes': [
                "Monitor blood glucose levels regularly",
                "Follow a balanced diet low in sugar and carbohydrates",
                "Exercise regularly (30 minutes daily)",
                "Take prescribed medication as directed",
                "Regular eye and foot checkups"
            ],
            'heart_disease': [
                "Reduce sodium intake (aim for < 2300mg/day)",
                "Exercise regularly with doctor's approval",
                "Take prescribed medications consistently",
                "Monitor blood pressure at home",
                "Quit smoking if applicable"
            ],
            'liver_disease': [
                "Avoid alcohol completely",
                "Maintain healthy weight",
                "Take only prescribed medications",
                "Get vaccinated for hepatitis A and B",
                "Regular liver function tests"
            ],
            'kidney_disease': [
                "Limit salt and potassium intake",
                "Stay hydrated but follow fluid restrictions",
                "Avoid NSAIDs (ibuprofen, aspirin)",
                "Monitor blood pressure regularly",
                "Regular kidney function tests"
            ],
            'thyroid_disorder': [
                "Take thyroid medication consistently",
                "Regular thyroid function tests",
                "Maintain iodine balance in diet",
                "Exercise regularly",
                "Get adequate sleep"
            ],
            'anemia': [
                "Increase iron-rich foods (spinach, beans, red meat)",
                "Take iron supplements as prescribed",
                "Include vitamin C for better iron absorption",
                "Regular hemoglobin checks",
                "Avoid tea/coffee with meals"
            ],
            'normal': [
                "Maintain healthy lifestyle",
                "Regular health check-ups",
                "Balanced diet and exercise",
                "Adequate sleep (7-8 hours)",
                "Stay hydrated"
            ],
            'insufficient_data': [
                "Please ensure all relevant tests are completed",
                "More test results needed for accurate prediction",
                "Consult with doctor for complete health assessment"
            ]
        }
        
        return recommendations.get(disease, recommendations['normal'])

# Create global instance
ml_disease_model = DiseasePredictionModel()