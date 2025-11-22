import os
import json
import base64
import logging
from functools import wraps
from flask import request, jsonify, make_response

import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

logger = logging.getLogger("voicebot")

# -----------------------------------------------------------
#  🔥 BASE64-ONLY Firebase Admin Initialization
# -----------------------------------------------------------
def init_auth():
    # 1. Check if already initialized
    if firebase_admin._apps:
        return

    # 2. Try loading from Env Var (Base64)
    b64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64")
    
    # 3. Try loading from Env Var (Raw JSON - fallback)
    raw_json = os.environ.get("FIREBASE_CREDENTIALS")

    cred_dict = None

    try:
        if b64:
            logger.info("Initializing Firebase from BASE64 env var...")
            decoded = base64.b64decode(b64)
            cred_dict = json.loads(decoded.decode("utf-8"))
        elif raw_json:
            logger.info("Initializing Firebase from RAW JSON env var...")
            cred_dict = json.loads(raw_json)
        else:
            # Fallback: Check for local file
            local_path = "serviceAccountKey.json"
            if os.path.exists(local_path):
                logger.info("Initializing Firebase from local JSON file...")
                cred = credentials.Certificate(local_path)
                firebase_admin.initialize_app(cred)
                return
            else:
                logger.warning("❌ No Firebase credentials found (Base64, JSON, or File). Auth may fail.")
                return

        # --- 🛠️ FIX: Handle Private Key Newlines ---
        if cred_dict and "private_key" in cred_dict:
            cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")

        if cred_dict:
            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("🔥 Firebase initialized successfully.")

    except Exception as e:
        logger.exception("❌ Firebase initialization failed: %s", e)
        # We don't raise RuntimeError here to avoid crashing the whole app on startup, 
        # but auth will fail later.
        pass


# -----------------------------------------------------------
#  🔐 Token Verification Decorator
# -----------------------------------------------------------
def firebase_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        # --- 1. Handle CORS Preflight (OPTIONS) ---
        if request.method == "OPTIONS":
            response = make_response()
            response.headers.add("Access-Control-Allow-Origin", "*")
            response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
            response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
            return response

        # --- 2. Check Authorization Header ---
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing id token"}), 401

        id_token = auth_header.split(" ", 1)[1].strip()

        # --- 3. Verify Token ---
        try:
            # Ensure app is initialized (lazy load check)
            if not firebase_admin._apps:
                init_auth()
                
            decoded = firebase_auth.verify_id_token(id_token)
            request.firebase_user = decoded
        except Exception as e:
            logger.exception("Firebase token verify failed: %s", e)
            return jsonify({"error": "invalid or expired token", "detail": str(e)}), 401

        return f(*args, **kwargs)

    return wrapper