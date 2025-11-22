import time
import logging
from typing import Optional, List, Dict, Any

from google import genai
from google.api_core import exceptions as google_exceptions

from app.config import Config
from app.services.rag import safe_build_context

logger = logging.getLogger("voicebot")

GENAI_CLIENT = None

def init_llm():
    global GENAI_CLIENT
    if Config.GEMINI_KEY:
        try:
            GENAI_CLIENT = genai.Client(api_key=Config.GEMINI_KEY)
            logger.info("GenAI client initialized.")
        except Exception as e:
            logger.exception("GenAI init failed: %s", e)

def generate_with_retry(model_name: str, prompt: str, max_retries: int = 3) -> Optional[str]:
    if not GENAI_CLIENT:
        return None

    for attempt in range(max_retries):
        try:
            # Send inputs as simple strings/dicts to avoid SDK ValidationErrors
            response = GENAI_CLIENT.models.generate_content(
                model=model_name,
                contents=str(prompt),
                config={
                    "max_output_tokens": Config.MAX_RESPONSE_TOKENS,
                    "temperature": Config.TEMPERATURE,
                }
            )
            
            if response.text:
                return response.text.strip()
            return None

        except google_exceptions.ResourceExhausted:
            time.sleep(2 * (attempt + 1))
        except Exception as e:
            logger.error(f"GenAI Error: {e}")
            return None
            
    return None

def call_gemini_rag(question: str, chunks: List[Dict[str, Any]]) -> Optional[str]:
    if GENAI_CLIENT is None: return None
    context_text, _ = safe_build_context(chunks, question)
    prompt = f"SYSTEM: You are a helpful assistant. Use these sources to answer.\n\nSOURCES:\n{context_text}\n\nQUESTION: {question}"
    return generate_with_retry(Config.LLM_MODEL, prompt)

def call_gemini_general(question: str) -> Optional[str]:
    if GENAI_CLIENT is None: return None
    prompt = f"SYSTEM: You are a helpful assistant. Answer concisely.\n\nQUESTION: {question}"
    return generate_with_retry(Config.LLM_MODEL, prompt)