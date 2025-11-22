#!/usr/bin/env python3
"""
app.py
Entry point for the modular Voice Bot backend.
"""
import os
from app import create_app
from app.services.nlu import load_nlu_model

app = create_app()

if __name__ == "__main__":
    load_nlu_model()
    port = int(os.environ.get("PORT", 8000))
    app.run(host="0.0.0.0", port=port, debug=True)
