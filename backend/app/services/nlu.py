# backend/app/services/nlu.py
import logging
from transformers import pipeline


_model_loaded = False

def load_nlu_model():
    global _model_loaded
    if _model_loaded:
        return
    # heavy initialization (downloads, load weights)
    # ... your current initialization ...
    _model_loaded = True

def is_nlu_model_loaded() -> bool:
    return _model_loaded

logger = logging.getLogger("voicebot")

# Load a small, fast classification model
# We use "valhalla/distilbart-mnli-12-1" because it is lighter than the default large models
classifier = None

def load_nlu_model():
    global classifier
    logger.info("Loading Hugging Face NLU model...")
    classifier = pipeline("zero-shot-classification", model="valhalla/distilbart-mnli-12-1")
    logger.info("NLU Model loaded!")

def classify_intent_hf(text: str):
    """
    Uses Hugging Face to decide what the user wants.
    Returns: (intent_label, confidence_score)
    """
    if not classifier:
        # Fallback if model isn't loaded yet
        return "unknown", 0.0
    
    # Define the possible "buckets" our bot understands
    candidate_labels = ["check order status", "general question", "greeting", "goodbye", "complaint"]
    
    result = classifier(text, candidate_labels)
    
    # Get top result
    top_label = result['labels'][0]
    top_score = result['scores'][0]
    
    return top_label, top_score