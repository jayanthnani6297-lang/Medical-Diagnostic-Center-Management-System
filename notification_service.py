import sqlite3
import random
import time
from datetime import datetime
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

class NotificationService:
    
    @staticmethod
    def generate_random_email(patient_name, patient_id):
        """Generate a random email for demo purposes"""
        name_part = patient_name.lower().replace(' ', '.')
        random_num = random.randint(100, 999)
        domains = ['gmail.com', 'yahoo.com', 'outlook.com', 'patient.com', 'demo.com']
        domain = random.choice(domains)
        return f"{name_part}.{random_num}@{domain}"
    
    @staticmethod
    def simulate_send_email(recipient, subject, message, link):
        """Simulate sending an email (for demo)"""
        print("\n" + "="*60)
        print("📧 SIMULATED EMAIL SENT")
        print("="*60)
        print(f"📨 TO: {recipient}")
        print(f"📌 SUBJECT: {subject}")
        print("-"*40)
        print("📝 MESSAGE:")
        print(message)
        print("-"*40)
        print(f"🔗 LINK: {link}")
        print("="*60 + "\n")
        time.sleep(0.5)
        return {'success': True, 'simulated': True}
    
    @staticmethod
    def simulate_send_sms(mobile, message, link):
        """Simulate sending an SMS (for demo)"""
        print("\n" + "="*60)
        print("📱 SIMULATED SMS SENT")
        print("="*60)
        print(f"📲 TO: {mobile}")
        print("-"*40)
        print("📝 MESSAGE:")
        print(message)
        print("-"*40)
        print(f"🔗 LINK: {link}")
        print("="*60 + "\n")
        time.sleep(0.5)
        return {'success': True, 'simulated': True}
    
    @staticmethod
    def simulate_send_whatsapp(mobile, message, link):
        """Simulate sending WhatsApp message"""
        print("\n" + "="*60)
        print("💬 SIMULATED WHATSAPP SENT")
        print("="*60)
        print(f"📲 TO: {mobile}")
        print("-"*40)
        print("📝 MESSAGE:")
        print(message)
        print("-"*40)
        print(f"🔗 LINK: {link}")
        print("="*60 + "\n")
        return {'success': True, 'simulated': True}
    
    @classmethod
    def send_report_notification(cls, report_id, patient_id, patient_name, 
                                  contact_info, preference, secure_link, token):
        """Send report notification based on preference"""
        
        email_subject = f"🔐 Your Medical Report #{report_id} is Ready"
        email_message = f"""
DEAR {patient_name.upper()},

Your medical report has been generated and is ready for secure viewing.

📋 REPORT DETAILS:
• Report ID: #{report_id}
• Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
• Valid Until: 7 days from generation

🔐 SECURE ACCESS LINK:
{secure_link}

⚠️ SECURITY NOTES:
• This link works ONLY ONCE
• Expires in 7 days
• Do not share this link

---
Medical Laboratory System
        """
        
        sms_message = f"🔐 Report #{report_id} ready. View once: {secure_link} (expires 7 days)"
        
        recipient = None
        notif_type = preference
        
        if preference == "email":
            recipient = contact_info.get('email') or cls.generate_random_email(patient_name, patient_id)
            cls.simulate_send_email(recipient, email_subject, email_message, secure_link)
        
        elif preference == "sms":
            recipient = contact_info.get('mobile')
            if recipient:
                cls.simulate_send_sms(recipient, sms_message, secure_link)
            else:
                print(f"⚠️ No mobile for {patient_name}, skipping SMS")
                return False
        
        elif preference == "whatsapp":
            recipient = contact_info.get('mobile')
            if recipient:
                cls.simulate_send_whatsapp(recipient, sms_message, secure_link)
            else:
                print(f"⚠️ No mobile for {patient_name}, skipping WhatsApp")
                return False
        
        elif preference == "both":
            email_recipient = contact_info.get('email') or cls.generate_random_email(patient_name, patient_id)
            sms_recipient = contact_info.get('mobile')
            
            if email_recipient:
                cls.simulate_send_email(email_recipient, email_subject, email_message, secure_link)
            if sms_recipient:
                cls.simulate_send_sms(sms_recipient, sms_message, secure_link)
            recipient = f"Email: {email_recipient}, SMS: {sms_recipient}"
        
        else:
            recipient = cls.generate_random_email(patient_name, patient_id)
            cls.simulate_send_email(recipient, email_subject, email_message, secure_link)
            notif_type = "email (auto)"
        
        # Store in database
        try:
            conn = sqlite3.connect("medical.db")
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO notifications 
                (report_id, patient_id, recipient, type, subject, message, secure_link, token, status, sent_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'sent', CURRENT_TIMESTAMP)
            """, (report_id, patient_id, str(recipient), notif_type, email_subject, email_message, secure_link, token))
            conn.commit()
            conn.close()
            print(f"✅ Notification stored for {patient_name}")
            return True
        except Exception as e:
            print(f"❌ Error storing notification: {e}")
            return False