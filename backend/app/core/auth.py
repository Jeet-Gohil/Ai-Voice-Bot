import os
import json
import base64
import logging
from functools import wraps
from flask import request, jsonify

import firebase_admin
from firebase_admin import credentials, auth as firebase_auth

logger = logging.getLogger("voicebot")


# -----------------------------------------------------------
#  🔥 BASE64-ONLY Firebase Admin Initialization
# -----------------------------------------------------------
def init_auth():
    if firebase_admin._apps:
        return  # already initialized

    b64 = os.environ.get("FIREBASE_SERVICE_ACCOUNT_B64")

    if not b64:
        raise RuntimeError(
            "❌ FIREBASE_SERVICE_ACCOUNT_B64 not set. Cannot initialize Firebase Admin."
        )

    try:
        logger.info("Initializing Firebase from BASE64 env var...")

        # Decode from Base64 → JSON → Certificate dict
        decoded = base64.b64decode(b64)
        cred_dict = json.loads(decoded.decode("utf-8"))

        # Initialize Firebase Admin
        cred = credentials.Certificate(cred_dict)
        firebase_admin.initialize_app(cred)

        logger.info("🔥 Firebase initialized from BASE64 successfully.")

    except Exception as e:
        logger.exception("❌ Firebase BASE64 initialization failed: %s", e)
        raise RuntimeError(
            f"Firebase Admin initialization failed. Base64 credentials invalid. Error: {e}"
        )


# -----------------------------------------------------------
#  🔐 Token Verification Decorator
# -----------------------------------------------------------
def firebase_auth_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):

        # Allow preflight CORS requests
        if request.method == "OPTIONS":
            return "", 200

        # Check Authorization header
        auth_header = request.headers.get("Authorization", "")
        if not auth_header.startswith("Bearer "):
            return jsonify({"error": "missing id token"}), 401

        id_token = auth_header.split(" ", 1)[1].strip()

        try:
            decoded = firebase_auth.verify_id_token(id_token)
            request.firebase_user = decoded
        except Exception as e:
            logger.exception("Firebase token verify failed: %s", e)
            return jsonify({"error": "invalid or expired token", "detail": str(e)}), 401

        return f(*args, **kwargs)

    return wrapper
