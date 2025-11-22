import os
import json
import logging
from typing import List, Dict, Any, Tuple

from sentence_transformers import SentenceTransformer
import numpy as np

from app.config import Config

logger = logging.getLogger("voicebot")

# FAISS (optional)
try:
    import faiss
    FAISS_AVAILABLE = True
except Exception:
    faiss = None
    FAISS_AVAILABLE = False

# Tiktoken fallback for token estimates (optional)
try:
    import tiktoken
    TIKTOKEN_AVAILABLE = True
except Exception:
    TIKTOKEN_AVAILABLE = False

# ---------- Load embedding model ----------
EMBED_MODEL = None
FAISS_INDEX = None
DOCS_META: Dict[str, Dict[str, Any]] = {}

def init_rag():
    global EMBED_MODEL
    logger.info("Loading embedding model: %s", Config.EMBED_MODEL_NAME)
    try:
        EMBED_MODEL = SentenceTransformer(Config.EMBED_MODEL_NAME)
    except Exception as e:
        logger.exception("Failed to load embedding model: %s", e)
        EMBED_MODEL = None
    
    load_index()

def load_index(index_path: str = Config.FAISS_INDEX_PATH, meta_path: str = Config.DOCS_META_PATH):
    global FAISS_INDEX, DOCS_META
    if not FAISS_AVAILABLE:
        logger.warning("faiss not available; retrieval disabled.")
        FAISS_INDEX = None
        DOCS_META = {}
        return
    try:
        if os.path.exists(index_path) and os.path.exists(meta_path):
            FAISS_INDEX = faiss.read_index(index_path)
            with open(meta_path, "r", encoding="utf8") as f:
                DOCS_META = json.load(f)
            logger.info("Loaded FAISS index and docs meta.")
        else:
            logger.warning("FAISS index/meta not found at configured paths.")
            FAISS_INDEX = None
            DOCS_META = {}
    except Exception as e:
        logger.exception("Failed to load index/meta: %s", e)
        FAISS_INDEX = None
        DOCS_META = {}

def estimate_tokens(text: str) -> int:
    """
    Rough estimate. If tiktoken is available, use it; else fallback to chars/4.
    """
    if not text:
        return 1
    if TIKTOKEN_AVAILABLE:
        try:
            enc = tiktoken.get_encoding("cl100k_base")
            return len(enc.encode(text))
        except Exception:
            pass
    return max(1, len(text) // 4)

def retrieve_docs(query: str, top_k: int = Config.TOP_K) -> List[Dict[str, Any]]:
    if FAISS_INDEX is None or EMBED_MODEL is None:
        return []
    q_emb = EMBED_MODEL.encode([query], convert_to_numpy=True)
    try:
        faiss.normalize_L2(q_emb)
    except Exception:
        pass
    D, I = FAISS_INDEX.search(q_emb, top_k)
    results = []
    for score, idx in zip(D[0], I[0]):
        if int(idx) < 0:
            continue
        if float(score) < Config.SCORE_THRESHOLD:
            continue
        meta = DOCS_META.get(str(int(idx)), {})
        results.append({
            "id": int(idx),
            "score": float(score),
            "text": meta.get("chunk","")[:2000],
            "source": meta.get("source","unknown")
        })
    return results

def safe_build_context(chunks: List[Dict[str, Any]], question: str, token_budget: int = Config.MAX_PROMPT_TOKENS) -> Tuple[str, List[Dict[str, Any]]]:
    used = []
    context_parts = []
    q_tokens = estimate_tokens(question)
    tokens_remaining = token_budget - q_tokens - 200
    if tokens_remaining <= 0:
        return ("", [])
    for c in chunks:
        text = c.get("text","")
        t = estimate_tokens(text)
        if t <= tokens_remaining:
            context_parts.append(f"Source: {c.get('source','unknown')}\n{text}")
            used.append(c)
            tokens_remaining -= t
        else:
            if tokens_remaining > 50:
                char_budget = tokens_remaining * 4
                snippet = text[:char_budget]
                context_parts.append(f"Source: {c.get('source','unknown')}\n{snippet}")
                used.append({**c, "text": snippet})
                tokens_remaining = 0
            break
    return ("\n\n".join(context_parts), used)
