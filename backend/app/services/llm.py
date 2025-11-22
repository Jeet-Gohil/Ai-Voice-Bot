import time
import logging
from typing import Optional, List, Dict, Any

from google import genai
from google.genai import types
from google.api_core import exceptions as google_exceptions

from app.config import Config
from app.services.rag import safe_build_context

logger = logging.getLogger("voicebot")

GENAI_CLIENT = None


# ------------------------------------------------------------
#   Initialize Google GenAI client
# ------------------------------------------------------------
def init_llm():
    global GENAI_CLIENT
    if Config.GEMINI_KEY:
        try:
            GENAI_CLIENT = genai.Client(api_key=Config.GEMINI_KEY)
            logger.info("GenAI client initialized for model %s", Config.LLM_MODEL)
        except Exception as e:
            logger.exception("GenAI client init failed: %s", e)
    else:
        logger.warning("GEMINI_API_KEY not set; generation disabled.")


# ------------------------------------------------------------
#   New SDK CALL (Fix: replace generation_config→config)
# ------------------------------------------------------------
def generate_with_retry(model_name: str, prompt: str, max_retries: int = 3) -> Optional[str]:
    if not GENAI_CLIENT:
        logger.error("GENAI_CLIENT is None — GenAI not initialized.")
        return None

    for attempt in range(max_retries):
        try:
            # ⭐ NEW GOOGLE SDK SIGNATURE
            resp = GENAI_CLIENT.models.generate_content(
                model=model_name,
                contents=[{"role": "user", "parts": prompt}],
                config=types.GenerateContentConfig(
                    max_output_tokens=Config.MAX_RESPONSE_TOKENS,
                    temperature=Config.TEMPERATURE,
                )
            )

            # -------------- Extract Text --------------
            text = None

            if hasattr(resp, "text") and resp.text:
                text = resp.text

            elif hasattr(resp, "candidates") and resp.candidates:
                cand = resp.candidates[0]

                if hasattr(cand, "content") and cand.content:
                    content = cand.content

                    if isinstance(content, (list, tuple)):
                        parts = []
                        for part in content:
                            if isinstance(part, dict):
                                parts.append(part.get("text", ""))
                            else:
                                parts.append(str(part))
                        text = "".join(parts)
                    else:
                        text = str(content)

                elif hasattr(cand, "output") and cand.output:
                    text = str(cand.output)

                elif hasattr(cand, "text") and cand.text:
                    text = str(cand.text)

            elif isinstance(resp, dict):
                text = resp.get("text") or resp.get("output")
                if not text and "candidates" in resp:
                    c0 = resp["candidates"][0]
                    if isinstance(c0, dict):
                        text = c0.get("content") or c0.get("output") or c0.get("text")

            if not text:
                text = str(resp)

            text = text.strip() if isinstance(text, str) else None

            logger.info("GenAI success (len=%d) on attempt %d", len(text) if text else 0, attempt + 1)
            return text

        except google_exceptions.ResourceExhausted as e:
            wait_time = 2 * (attempt + 1)
            logger.warning("Rate limit / quota: %s. Retrying in %s seconds...", e, wait_time)
            time.sleep(wait_time)

        # -----------------------------------------
        # FIX: Older fallback (kept for safety)
        # -----------------------------------------
        except TypeError as e:
            logger.exception("TypeError calling GenAI (attempt %d): %s", attempt + 1, e)
            try:
                # fallback: call without config
                resp = GENAI_CLIENT.models.generate_content(
                    model=model_name,
                    contents=[{"role": "user", "parts": prompt}]
                )
                text = getattr(resp, "text", None) or str(resp)
                return text.strip() if text else None
            except Exception as e2:
                logger.exception("Fallback after TypeError also failed: %s", e2)
                return f"DEBUG_GENAI_ERROR: {type(e2).__name__}: {str(e2)}"

        except Exception as e:
            logger.exception("GenAI generation error (attempt %d): %s", attempt + 1, e)
            return f"DEBUG_GENAI_ERROR: {type(e).__name__}: {str(e)}"

    return "I'm currently receiving too many requests (Rate Limit). Please try again in a moment."


# ------------------------------------------------------------
#   RAG CALL
# ------------------------------------------------------------
def call_gemini_rag(question: str, chunks: List[Dict[str, Any]]) -> Optional[str]:
    if GENAI_CLIENT is None:
        return None

    context_text, used = safe_build_context(chunks, question)

    system_instruction = (
        "You are a helpful, accurate assistant. Use ONLY the provided sources to answer. "
        "If the answer is not in the sources, reply: 'I don't know. I can escalate to a human if you'd like.' "
        "Cite sources by bracketed index, e.g., [1]."
    )

    user_prompt = f"SYSTEM: {system_instruction}\n\nCONTEXT:\n{context_text}\n\nQUESTION: {question}\n\nAnswer concisely and cite sources."

    return generate_with_retry(Config.LLM_MODEL, user_prompt)


# ------------------------------------------------------------
#   GENERAL NON-RAG CALL
# ------------------------------------------------------------
def call_gemini_general(question: str) -> Optional[str]:
    if GENAI_CLIENT is None:
        return None

    system_instruction = (
        "You are a helpful assistant. Answer concisely. "
        "If unsure, say 'I am not sure' rather than guessing."
    )

    prompt = f"SYSTEM: {system_instruction}\n\nQUESTION: {question}"

    return generate_with_retry(Config.LLM_MODEL, prompt)
