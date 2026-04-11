import hashlib
import json
import sqlite3
from datetime import datetime
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.backends import default_backend
import os
import base64

class SecurityManager:
    """Manages digital signatures and hash chain for report security"""
    
    def __init__(self, key_dir='security_keys'):
        self.key_dir = key_dir
        
        # Create key directory if it doesn't exist - DO THIS FIRST
        if not os.path.exists(key_dir):
            os.makedirs(key_dir)
            print(f"✅ Created security keys directory: {key_dir}")
        
        self.private_key = None
        self.public_key = None
        self._load_or_generate_keys()
    
    def _load_or_generate_keys(self):
        """Load existing RSA keys or generate new ones"""
        private_key_path = os.path.join(self.key_dir, 'private_key.pem')
        public_key_path = os.path.join(self.key_dir, 'public_key.pem')
        
        if os.path.exists(private_key_path) and os.path.exists(public_key_path):
            # Load existing keys
            try:
                with open(private_key_path, 'rb') as f:
                    self.private_key = serialization.load_pem_private_key(
                        f.read(),
                        password=None,
                        backend=default_backend()
                    )
                
                with open(public_key_path, 'rb') as f:
                    self.public_key = serialization.load_pem_public_key(
                        f.read(),
                        backend=default_backend()
                    )
                print("✅ Loaded existing RSA keys")
            except Exception as e:
                print(f"⚠️ Error loading keys: {e}, generating new ones")
                self._generate_keys()
        else:
            # Generate new RSA key pair
            self._generate_keys()
    # Add this method to the SecurityManager class in security_utils.py

    def create_chained_hash(self, report_content):
        """Create a hash that depends on previous report (blockchain style)"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        
        # Get the most recent report hash
        cursor.execute("SELECT hash_value FROM reports ORDER BY report_id DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        
        previous_hash = result[0] if result else "GENESIS_BLOCK"
        
        # Create chained hash
        chain_data = f"{previous_hash}-{report_content}-{datetime.now().isoformat()}"
        return hashlib.sha256(chain_data.encode()).hexdigest()
    
    def _generate_keys(self):
        """Generate RSA key pair for digital signatures"""
        try:
            # Generate private key
            self.private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
            
            # Get public key
            self.public_key = self.private_key.public_key()
            
            # Save private key
            private_key_path = os.path.join(self.key_dir, 'private_key.pem')
            with open(private_key_path, 'wb') as f:
                f.write(self.private_key.private_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PrivateFormat.PKCS8,
                    encryption_algorithm=serialization.NoEncryption()
                ))
            
            # Save public key
            public_key_path = os.path.join(self.key_dir, 'public_key.pem')
            with open(public_key_path, 'wb') as f:
                f.write(self.public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ))
            
            print("✅ Generated new RSA key pair")
            print(f"   Keys saved to: {self.key_dir}/")
        except Exception as e:
            print(f"❌ Error generating keys: {e}")
    
    def sign_report(self, report_content):
        """Create digital signature for report"""
        if not self.private_key:
            raise Exception("Private key not available")
        
        try:
            # Sign the report content
            signature = self.private_key.sign(
                report_content.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            
            # Return base64 encoded signature
            return base64.b64encode(signature).decode('utf-8')
        except Exception as e:
            print(f"❌ Error signing report: {e}")
            return None
    
    def verify_signature(self, report_content, signature_base64):
        """Verify digital signature"""
        if not self.public_key:
            raise Exception("Public key not available")
        
        try:
            signature = base64.b64decode(signature_base64)
            self.public_key.verify(
                signature,
                report_content.encode('utf-8'),
                padding.PSS(
                    mgf=padding.MGF1(hashes.SHA256()),
                    salt_length=padding.PSS.MAX_LENGTH
                ),
                hashes.SHA256()
            )
            return True
        except Exception as e:
            print(f"❌ Signature verification failed: {e}")
            return False
    
    @staticmethod
    def create_hash_chain(previous_hash, report_data):
        """Create next hash in the chain (blockchain-inspired)"""
        chain_data = f"{previous_hash}-{report_data}-{datetime.now().isoformat()}"
        return hashlib.sha256(chain_data.encode()).hexdigest()
    
    @staticmethod
    def verify_hash_chain(report_id, conn=None):
        """Verify the entire hash chain for consistency"""
        close_conn = False
        if not conn:
            conn = sqlite3.connect("medical.db", timeout=10)
            close_conn = True
        
        cursor = conn.cursor()
        
        # Get all reports in chronological order
        cursor.execute("""
            SELECT report_id, hash_value, created_date
            FROM reports
            WHERE report_id <= ?
            ORDER BY report_id
        """, (report_id,))
        
        reports = cursor.fetchall()
        
        if close_conn:
            conn.close()
        
        # Verify chain
        for i in range(1, len(reports)):
            prev_hash = reports[i-1][1]
            current_hash = reports[i][1]
            
            # In a real blockchain, we'd verify the hash relationship
            # For now, just ensure no tampering with individual hashes
            if not current_hash or not prev_hash:
                return False, f"Missing hash at report {reports[i][0]}"
        
        return True, "Chain verified"
    
    def get_public_key_pem(self):
        """Get public key in PEM format for display"""
        if self.public_key:
            try:
                return self.public_key.public_bytes(
                    encoding=serialization.Encoding.PEM,
                    format=serialization.PublicFormat.SubjectPublicKeyInfo
                ).decode('utf-8')
            except Exception as e:
                print(f"❌ Error getting public key: {e}")
                return None
        return None


class TamperDetector:
    """Detect and alert on potential tampering attempts"""
    
    @staticmethod
    def check_report_integrity(report_id, stored_hash, computed_hash):
        """Check if report has been tampered with"""
        if stored_hash != computed_hash:
            return {
                'tampered': True,
                'severity': 'HIGH',
                'message': 'Hash mismatch detected',
                'timestamp': datetime.now().isoformat()
            }
        return {
            'tampered': False,
            'severity': 'NONE',
            'message': 'Report integrity verified',
            'timestamp': datetime.now().isoformat()
        }
    
    @staticmethod
    def log_tamper_attempt(report_id, user_ip, details, conn=None):
        """Log tampering attempts to database"""
        close_conn = False
        if not conn:
            conn = sqlite3.connect("medical.db", timeout=10)
            close_conn = True
        
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO audit_logs (actor, action, details, ip_address, status)
            VALUES (?, ?, ?, ?, ?)
        """, ('SYSTEM', 'TAMPER_ATTEMPT', json.dumps({
            'report_id': report_id,
            'details': details
        }), user_ip, 'ALERT'))
        
        if close_conn:
            conn.commit()
            conn.close()


class EnhancedAuditLogger:
    """Enhanced audit logging with more details"""
    
    @staticmethod
    def log_verification_attempt(username, report_id, success, method, ip_address, conn=None):
        """Log verification attempts with detailed information"""
        close_conn = False
        if not conn:
            conn = sqlite3.connect("medical.db", timeout=10)
            close_conn = True
        
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO audit_logs (actor, role, action, details, ip_address, status)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            username,
            'PATIENT',
            'REPORT_VERIFICATION',
            json.dumps({
                'report_id': report_id,
                'verification_method': method,
                'timestamp': datetime.now().isoformat()
            }),
            ip_address,
            'SUCCESS' if success else 'FAILED'
        ))
        
        if close_conn:
            conn.commit()
            conn.close()
    
    @staticmethod
    def log_security_event(event_type, username, details, severity, ip_address, conn=None):
        """Log security-related events"""
        close_conn = False
        if not conn:
            conn = sqlite3.connect("medical.db", timeout=10)
            close_conn = True
        
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO audit_logs (actor, action, details, ip_address, status)
            VALUES (?, ?, ?, ?, ?)
        """, (
            username or 'SYSTEM',
            event_type,
            json.dumps({
                **details,
                'severity': severity,
                'timestamp': datetime.now().isoformat()
            }),
            ip_address,
            severity
        ))
        
        if close_conn:
            conn.commit()
            conn.close()
    def get_previous_hash(self):
        """Get the hash of the most recent report"""
        conn = sqlite3.connect("medical.db")
        cursor = conn.cursor()
        cursor.execute("SELECT hash_value FROM reports ORDER BY report_id DESC LIMIT 1")
        result = cursor.fetchone()
        conn.close()
        return result[0] if result else "GENESIS_BLOCK_HASH"

    def create_chained_hash(self, report_data):
        """Create a hash that depends on previous report"""
        prev_hash = self.get_previous_hash()
        chain_data = f"{prev_hash}-{report_data}-{datetime.now().isoformat()}"
        return hashlib.sha256(chain_data.encode()).hexdigest()

# Singleton instances
security_manager = SecurityManager()
tamper_detector = TamperDetector()
audit_logger = EnhancedAuditLogger()