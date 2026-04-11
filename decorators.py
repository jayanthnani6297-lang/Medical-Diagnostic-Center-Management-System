# decorators.py
from functools import wraps
from flask import session, redirect
import time

def role_required(required_role):
    def wrapper(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            if "username" not in session:
                return redirect("/login")
            
            if "last_activity" in session:
                if time.time() - session["last_activity"] > 3600:
                    session.clear()
                    return redirect("/login")
            
            session["last_activity"] = time.time()
            
            if session.get("role") != required_role:
                return "Access Denied - Insufficient Privileges", 403

            return func(*args, **kwargs)
        return decorated_function
    return wrapper

def admin_or_role_required(allowed_roles):
    def wrapper(func):
        @wraps(func)
        def decorated_function(*args, **kwargs):
            if "username" not in session:
                return redirect("/login")
            
            if "last_activity" in session:
                if time.time() - session["last_activity"] > 3600:
                    session.clear()
                    return redirect("/login")
            
            session["last_activity"] = time.time()
            
            if session.get("role") == "admin":
                return func(*args, **kwargs)
            
            if session.get("role") not in allowed_roles:
                return "Access Denied - Insufficient Privileges", 403

            return func(*args, **kwargs)
        return decorated_function
    return wrapper