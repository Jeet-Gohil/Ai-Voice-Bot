# /mnt/data/wsgi.py

import os
import threading
from app import create_app
from flask_cors import CORS
from app.services.nlu import load_nlu_model, is_nlu_model_loaded  # implement is_nlu_model_loaded

app = create_app()

FRONTEND_ORIGINS = [
    "https://ai-voice-bot-ashen.vercel.app",
    "http://localhost:3000"
]

CORS(
    app,
    resources={r"/*": {"origins": FRONTEND_ORIGINS}},
    supports_credentials=True,
    allow_headers=["Content-Type", "Authorization", "X-Requested-With", "Accept"],
    methods=["GET", "POST", "OPTIONS"]
)

def _background_load_nlu():
    try:
        app.logger.info("Background: starting NLU model load")
        load_nlu_model()
        app.logger.info("Background: NLU model loaded successfully")
    except Exception as e:
        app.logger.exception("Background: NLU model failed to load: %s", e)

t = threading.Thread(target=_background_load_nlu, daemon=True)
t.start()

# local run
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
