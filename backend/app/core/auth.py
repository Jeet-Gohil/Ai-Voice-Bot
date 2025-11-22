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
#  🔥 ROBUST Firebase Admin Initialization
# -----------------------------------------------------------
def init_auth():
    """
    Initializes Firebase Admin SDK.
    Supports:
    1. Base64 Encoded JSON (Env: FIREBASE_SERVICE_ACCOUNT_B64)
    2. Raw JSON String (Env: FIREBASE_CREDENTIALS)
    3. Local File (serviceAccountKey.json)
    """
    if firebase_admin._apps:
        return  # Already initialized

    # Try to get credentials from various sources
    b64_creds = os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64")
    json_creds = os.environ.get("FIREBASE_CREDENTIALS")
    
    cred_dict = None

    try:
        # Method 1: Base64 Environment Variable
        if b64_creds:
            logger.info("Initializing Firebase from BASE64 env var...")
            # Fix: Add padding if missing (common base64 issue)
            b64_creds += "=" * ((4 - len(b64_creds) % 4) % 4)
            decoded_bytes = base64.b64decode(b64_creds)
            cred_dict = json.loads(decoded_bytes.decode("utf-8"))
            
        # Method 2: Raw JSON Environment Variable
        elif json_creds:
            logger.info("Initializing Firebase from JSON env var...")
            # Clean up potential quotes added by accident
            json_creds = json_creds.strip().strip("'").strip('"')
            cred_dict = json.loads(json_creds)
            
        # Method 3: Local File (Dev Mode)
        elif os.path.exists("serviceAccountKey.json"):
            logger.info("Initializing Firebase from local file...")
            cred = credentials.Certificate("serviceAccountKey.json")
            firebase_admin.initialize_app(cred)
            return

        if cred_dict:
            # 🛠️ CRITICAL FIX: Handle escaped newlines in private key
            if "private_key" in cred_dict:
                cred_dict["private_key"] = cred_dict["private_key"].replace("\\n", "\n")

            cred = credentials.Certificate(cred_dict)
            firebase_admin.initialize_app(cred)
            logger.info("🔥 Firebase initialized successfully.")
        else:
            logger.warning("⚠️ No Firebase credentials found. Authentication will fail.")

    except Exception as e:
        logger.exception("❌ Firebase initialization failed: %s", e)
        # We log but don't crash immediately, so /health check can still pass


# -----------------------------------------------------------
#  🔐 Token Verification Decorator (With Manual CORS)
# -----------------------------------------------------------
def firebase_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        
        # ============================================================
        # 🟢 FIX: MANUALLY INJECT CORS HEADERS FOR PREFLIGHT
        # ============================================================
        # This allows the browser's CORS check to pass without a token
        if request.method == "OPTIONS":
            response = make_response()
            response.headers.add("Access-Control-Allow-Origin", "*")
            response.headers.add("Access-Control-Allow-Headers", "Content-Type,Authorization")
            response.headers.add("Access-Control-Allow-Methods", "GET,PUT,POST,DELETE,OPTIONS")
            return response, 200
        # ============================================================

        # 2. CHECK AUTHORIZATION HEADER
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing id token"}), 401

        id_token = auth_header.split(" ", 1)[1].strip()

        # 3. VERIFY TOKEN
        try:
            # Lazy load: Ensure auth is initialized before checking token
            if not firebase_admin._apps:
                init_auth()

            decoded = firebase_auth.verify_id_token(id_token)
            request.firebase_user = decoded
            
        except Exception as e:
            logger.error(f"Firebase token verify failed: {e}")
            return jsonify({"error": "invalid or expired token", "detail": str(e)}), 401

        return f(*args, **kwargs)

    return wrapper