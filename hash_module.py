import hashlib

def generate_hash(data_string):
    return hashlib.sha256(data_string.encode()).hexdigest()
