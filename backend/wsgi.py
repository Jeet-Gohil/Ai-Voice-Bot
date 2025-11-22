import os
from app import create_app
from app.services.nlu import load_nlu_model
from flask_cors import CORS

# -----------------------------
# 1. Create Flask Application
# -----------------------------
app = create_app()

# ---------------------------------------------------------
# 2. CORS Configuration (THIS FIXES YOUR PRODUCTION ERRORS)
# ---------------------------------------------------------
FRONTEND_ORIGINS = [
    "https://ai-voice-bot-ashen.vercel.app",  # your deployed frontend
    "http://localhost:3000"                    # local dev
]

CORS(
    app,
    resources={r"/*": {"origins": FRONTEND_ORIGINS}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    methods=["GET", "POST", "OPTIONS"]
)

# ---------------------------------------------------------
# 3. Load NLU Model Globally on Startup (Gunicorn Ready)
# ---------------------------------------------------------
print("--- LOADING NLU MODEL FOR PRODUCTION ---")
load_nlu_model()

# ---------------------------------------------------------
# 4. Local Development Server (Ignored on Azure/Gunicorn)
# ---------------------------------------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
