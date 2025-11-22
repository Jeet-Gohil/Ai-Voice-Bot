
import os
from app import create_app
from app.services.nlu import load_nlu_model
from flask_cors import CORS  # <--- 1. Import CORS

# 1. Create the Flask App
app = create_app()

# 2. Enable CORS for ALL routes and domains (Fixes the error)
# This allows your Vercel frontend to talk to this Azure backend
CORS(app, resources={r"/*": {"origins": "*"}})

# 3. Load AI Model Globally (Runs immediately when Gunicorn starts)
# This ensures the model is ready before the first request comes in
print("--- LOADING NLU MODEL FOR PRODUCTION ---")
load_nlu_model()

# 4. Development Server Block (Only runs locally with 'python wsgi.py')
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
