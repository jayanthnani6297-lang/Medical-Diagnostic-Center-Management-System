# qr_module.py
import qrcode
import os

def generate_qr(data, filename):
    """Generate QR code and save to static folder"""
    try:
        static_dir = 'static'
        if not os.path.exists(static_dir):
            os.makedirs(static_dir)
        
        filepath = os.path.join(static_dir, filename)
        
        qr = qrcode.QRCode(version=1, box_size=10, border=5)
        qr.add_data(data)
        qr.make(fit=True)
        
        img = qr.make_image(fill_color="black", back_color="white")
        img.save(filepath)
        print(f"✅ QR Code saved: {filepath}")
        return True
    except Exception as e:
        print(f"❌ QR Generation error: {e}")
        return False