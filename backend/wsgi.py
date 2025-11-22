#!/usr/bin/env python3
"""
wsgi.py (formerly app.py)
Entry point for the modular Voice Bot backend.
"""
import os
from app import create_app
from app.services.nlu import load_nlu_model

# 1. Create the Flask App
app = create_app()

# 2. Load AI Model Globally (Runs immediately when Gunicorn starts)
print("--- LOADING NLU MODEL FOR PRODUCTION ---")
load_nlu_model()

# 3. Development Server Block (Only runs locally with 'python wsgi.py')
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
