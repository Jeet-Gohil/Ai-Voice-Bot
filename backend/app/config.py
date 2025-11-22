import os
import json
import logging

# Configure a basic logger for config issues
logger = logging.getLogger("voicebot.config")

class Config:
    # Firebase
    # We keep the raw string here
    FIREBASE_CREDENTIALS_JSON = os.environ.get("FIREBASE_CREDENTIALS")
    FIREBASE_SA_PATH = os.environ.get("FIREBASE_SA_PATH", "serviceAccountKey.json")

    # Database
    DATABASE_URL = os.environ.get(
        "DATABASE_URL",
        "postgresql://neondb_owner:npg_ut8BzGwFa6Vm@ep-summer-wildflower-aep44r8k-pooler.c-2.us-east-2.aws.neon.tech/neondb?sslmode=require&channel_binding=require"
    )

    # GenAI / LLM
    GEMINI_KEY = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    LLM_MODEL = os.environ.get("LLM_MODEL", "gemini-2.0-flash")
    
    # RAG / Embeddings
    EMBED_MODEL_NAME = os.environ.get("EMBED_MODEL_NAME", "all-MiniLM-L6-v2")
    FAISS_INDEX_PATH = os.environ.get("FAISS_INDEX_PATH", os.path.join("ingest", "faiss.index"))
    DOCS_META_PATH = os.environ.get("DOCS_META_PATH", os.path.join("ingest", "docs_meta.json"))

    # Logging
    LOGFILE = os.environ.get("LOGFILE", "interactions.log")

    # Generation Parameters
    MAX_PROMPT_TOKENS = int(os.environ.get("MAX_PROMPT_TOKENS", "8000"))
    MAX_RESPONSE_TOKENS = int(os.environ.get("MAX_RESPONSE_TOKENS", "500"))
    TEMPERATURE = float(os.environ.get("TEMPERATURE", "0.3"))
    TOP_K = int(os.environ.get("TOP_K", "3"))
    SCORE_THRESHOLD = float(os.environ.get("SCORE_THRESHOLD", "0.25"))

    # App
    PORT = int(os.environ.get("PORT", 8000))

    @staticmethod
    def get_firebase_credentials():
        """
        Parses and cleans the FIREBASE_CREDENTIALS environment variable.
        Returns a dictionary suitable for firebase_admin.credentials.Certificate.
        """
        creds_json = os.environ.get("FIREBASE_CREDENTIALS")
        
        # 1. Fallback: Check if we should just return None (to let caller use file path)
        if not creds_json:
            return None

        try:
            # 2. Clean the string before parsing (Remove accidentally copied quotes)
            creds_json = creds_json.strip()
            if creds_json.startswith("'") and creds_json.endswith("'"):
                creds_json = creds_json[1:-1]
            elif creds_json.startswith('"') and creds_json.endswith('"'):
                creds_json = creds_json[1:-1]

            # 3. Parse JSON
            cred_dict = json.loads(creds_json)
            
            # 4. Fix Private Key (The source of your "ASN.1 parsing error")
            if "private_key" in cred_dict:
                private_key = cred_dict["private_key"]
                
                # Replace escaped newlines with actual newlines
                # This handles the case where .env or cloud env vars escape the \n
                private_key = private_key.replace("\\n", "\n")
                
                cred_dict["private_key"] = private_key
            
            return cred_dict

        except json.JSONDecodeError as e:
            logger.error(f"Error: FIREBASE_CREDENTIALS is not valid JSON. Detail: {e}")
            return None
        except Exception as e:
            logger.error(f"Error parsing FIREBASE_CREDENTIALS: {e}")
            return None