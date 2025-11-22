import logging
from flask import Flask
from flask_cors import CORS
from dotenv import load_dotenv

load_dotenv()

from app.config import Config
from app.core.database import init_db, create_tables
from app.core.auth import init_auth
from app.services.rag import init_rag
from app.services.llm import init_llm
from app.api.routes import api_bp

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("voicebot")

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    
    CORS(app)

    # Initialize Core
    init_db()
    create_tables()
    init_auth()

    # Initialize Services
    init_rag()
    init_llm()

    # Register Blueprints
    app.register_blueprint(api_bp)

    return app
