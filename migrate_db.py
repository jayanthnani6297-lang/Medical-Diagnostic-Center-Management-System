import sqlite3

conn = sqlite3.connect("medical.db")
cursor = conn.cursor()

# Check if email column exists
cursor.execute("PRAGMA table_info(patients)")
columns = cursor.fetchall()
has_email = any(col[1] == 'email' for col in columns)

if not has_email:
    try:
        cursor.execute("ALTER TABLE patients ADD COLUMN email TEXT")
        print("✅ Added email column to patients table")
    except Exception as e:
        print(f"❌ Error: {e}")
else:
    print("✅ Email column already exists")

conn.close()