import sqlite3

class ReferenceChecker:
    """Utility class to check test results against reference ranges"""
    
    @staticmethod
    def get_reference_range(test_type, parameter_name, patient_age, patient_gender):
        """Get appropriate reference range for a patient"""
        conn = sqlite3.connect("medical.db", timeout=10)
        cursor = conn.cursor()
        
        # First try gender and age specific
        cursor.execute("""
            SELECT unit, normal_min, normal_max, critical_low, critical_high
            FROM test_reference_ranges
            WHERE test_type = ? AND parameter_name = ?
            AND (gender_specific = ? OR gender_specific = 'Both')
            AND age_min <= ? AND age_max >= ?
            ORDER BY 
                CASE WHEN gender_specific = ? THEN 1 
                     WHEN gender_specific = 'Both' THEN 2 
                END
            LIMIT 1
        """, (test_type, parameter_name, patient_gender, patient_age, patient_age, patient_gender))
        
        result = cursor.fetchone()
        conn.close()
        
        if result:
            return {
                'unit': result[0],
                'normal_min': result[1],
                'normal_max': result[2],
                'critical_low': result[3],
                'critical_high': result[4]
            }
        else:
            # Try without gender specificity
            conn = sqlite3.connect("medical.db", timeout=10)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT unit, normal_min, normal_max, critical_low, critical_high
                FROM test_reference_ranges
                WHERE test_type = ? AND parameter_name = ?
                AND gender_specific = 'Both'
                AND age_min <= ? AND age_max >= ?
                LIMIT 1
            """, (test_type, parameter_name, patient_age, patient_age))
            
            result = cursor.fetchone()
            conn.close()
            
            if result:
                return {
                    'unit': result[0],
                    'normal_min': result[1],
                    'normal_max': result[2],
                    'critical_low': result[3],
                    'critical_high': result[4]
                }
            else:
                return None
    
    @staticmethod
    def check_value(value, reference_range):
        """Check a value against reference range and return flag"""
        try:
            val = float(value)
            
            if val < reference_range['critical_low']:
                return 'Critical Low'
            elif val < reference_range['normal_min']:
                return 'Low'
            elif val <= reference_range['normal_max']:
                return 'Normal'
            elif val <= reference_range['critical_high']:
                return 'High'
            else:
                return 'Critical High'
        except (ValueError, TypeError):
            return 'Invalid'
    
    @staticmethod
    def get_flag_color(flag):
        """Return color code for flag"""
        colors = {
            'Critical Low': 'purple',
            'Low': 'orange',
            'Normal': 'green',
            'High': 'orange',
            'Critical High': 'red',
            'Invalid': 'gray'
        }
        return colors.get(flag, 'black')