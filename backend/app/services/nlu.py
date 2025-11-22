import logging
from transformers import pipeline

logger = logging.getLogger("voicebot")

_model_loaded = False
classifier = None

def load_nlu_model():
    global classifier, _model_loaded
    if _model_loaded: return
    logger.info("Loading Hugging Face NLU model...")
    # valhalla/distilbart-mnli-12-1 is excellent for zero-shot
    classifier = pipeline("zero-shot-classification", model="valhalla/distilbart-mnli-12-1")
    _model_loaded = True

def is_nlu_model_loaded() -> bool:
    return _model_loaded

def classify_intent_hf(text: str):
    if not classifier: return "general_question", 0.0
    
    # --- REFINED LABELS (Stronger Separation) ---
    labels_map = {
        # TRACKING (Strong keywords: status, arrive, where, tracking)
        "check the status of an existing order": "track_order",
        "track my package delivery": "track_order",
        "when will my order arrive": "track_order",
        "where is my shipment": "track_order",
        "check delivery date": "track_order",
        
        # CREATION (Strong keywords: buy, purchase, new, place)
        "create a new purchase order": "create_order",
        "buy a new product": "create_order",
        "place a new order for an item": "create_order",
        "i want to buy something": "create_order",
        
        # COUNTING
        "count how many orders i have": "count_orders",
        "total number of orders": "count_orders",
        
        # OTHER
        "say hello": "greeting",
        "say goodbye": "goodbye",
        "complain about a problem": "complaint",
        
        # FALLBACK
        "ask a general knowledge question": "general_question"
    }
    
    candidate_labels = list(labels_map.keys())
    
    try:
        # "hypothesis_template" helps the model understand the context is a REQUEST
        result = classifier(text, candidate_labels, hypothesis_template="The user wants to {}.")
        
        top_description = result['labels'][0]
        top_score = result['scores'][0]
        
        mapped_intent = labels_map.get(top_description, "general_question")
        
        # Debug log
        print(f"🧠 NLU: '{text}' -> '{top_description}' ({top_score:.2f}) -> {mapped_intent}")
        
        return mapped_intent, top_score

    except Exception as e:
        logger.error(f"NLU Error: {e}")
        return "general_question", 0.0