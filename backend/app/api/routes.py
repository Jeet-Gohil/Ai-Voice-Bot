import time
import logging
import random
from datetime import datetime, timedelta
from flask import Blueprint, request, jsonify
import sqlalchemy as sa

from app.config import Config
from app.core.auth import firebase_auth_required
from app.core.database import get_or_create_user_by_firebase_uid, insert_voice_query, engine

from app.services.rag import retrieve_docs, load_index
from app.services.llm import call_gemini_rag, call_gemini_general
from app.services.nlu import classify_intent_hf

logger = logging.getLogger("voicebot")
api_bp = Blueprint("api", __name__)

# --- Helpers ---
def set_session_context(session_id, context_str):
    try:
        with engine.begin() as conn:
            conn.execute(sa.text("UPDATE chat_sessions SET current_context = :ctx WHERE session_uuid = :sid"), {"ctx": context_str, "sid": session_id})
    except: pass

def get_session_context(session_id):
    try:
        with engine.connect() as conn:
            row = conn.execute(sa.text("SELECT current_context FROM chat_sessions WHERE session_uuid = :sid"), {"sid": session_id}).fetchone()
            return row[0] if row else None
    except: return None

def extract_item_gemini(text: str):
    prompt = f"Extract ONLY the product name from: '{text}'. If none, return 'None'. No punctuation."
    res = call_gemini_general(prompt)
    if res:
        clean = res.strip().replace(".", "").replace('"', "")
        return clean if clean.lower() != "none" else None
    return None

@api_bp.route("/query", methods=["POST"])
@firebase_auth_required
def query():
    payload = request.json or {}
    transcript = (payload.get("transcript") or "").strip()
    session_id = payload.get("session_id", f"sess_{int(time.time())}")
    
    fb_user = getattr(request, "firebase_user", {})
    email = fb_user.get("email")
    uid = fb_user.get("uid")
    
    user_id = None
    if uid:
        try:
            user_id = get_or_create_user_by_firebase_uid(uid, email=email, name=fb_user.get("name"))
        except: pass

    intent = "general"
    reply = None
    
    # ---------------------------------------------------------
    # 1. CONTEXT CHECK (Disambiguation - "Which one?")
    # ---------------------------------------------------------
    context = get_session_context(session_id)
    
    if context == 'AWAITING_CLARIFICATION' and email:
        try:
            with engine.connect() as conn:
                # User is answering "Which order?". Check if their answer matches an order item.
                orders = conn.execute(sa.text("SELECT item_name, delivery_date, status FROM orders WHERE user_email = :e"), {"e": email}).fetchall()
                
                # Fuzzy match the user's answer against their orders
                matched = next((o for o in orders if transcript.lower() in o[0].lower() or o[0].lower() in transcript.lower()), None)
                
                if matched:
                    reply = f"Your order for **{matched[0]}** is currently **{matched[2]}**. It is expected to arrive on {matched[1]}."
                    # Resolution complete, clear context
                    set_session_context(session_id, None)
                    intent = "order_tracking_resolved"
                else:
                    # Still ambiguous
                    reply = "I couldn't match that to one of your orders. Please say the item name exactly (e.g., 'Laptop')."
                    intent = "order_tracking_failed"
        except Exception as e:
            logger.error(f"Context error: {e}")

    # ---------------------------------------------------------
    # 2. NLU INTENT PROCESSING
    # ---------------------------------------------------------
    if not reply:
        hf_intent, score = classify_intent_hf(transcript)
        
        if score > 0.35:
            
            # --- A. TRACK ORDER (The Flow You Requested) ---
            if hf_intent == "track_order" or hf_intent == "check order status":
                if email:
                    try:
                        with engine.connect() as conn:
                            # Fetch ALL active orders
                            orders = conn.execute(sa.text("SELECT item_name, delivery_date, status FROM orders WHERE user_email = :e ORDER BY id DESC"), {"e": email}).fetchall()
                        
                        if not orders:
                            reply = "You don't have any active orders right now."
                        else:
                            # 1. Check for SPECIFIC ITEM mention ("When will my burger arrive?")
                            specific_match = next((o for o in orders if o[0].lower() in transcript.lower()), None)
                            
                            if specific_match:
                                reply = f"Your order for **{specific_match[0]}** is currently **{specific_match[2]}** and arrives on {specific_match[1]}."
                            
                            # 2. Only one order exists? Just show it.
                            elif len(orders) == 1:
                                o = orders[0]
                                reply = f"Your order for {o[0]} is {o[2]} and arrives on {o[1]}."
                                
                            # 3. AMBIGUITY HANDLING (Your Requested Flow)
                            else:
                                item_list = ", ".join([o[0] for o in orders[:3]]) # List first 3
                                if len(orders) > 3: 
                                    item_list += f", and {len(orders)-3} others"
                                
                                # This is the EXACT response you wanted:
                                reply = f"You have {len(orders)} active orders: {item_list}. Which order are you talking about?"
                                
                                # CRITICAL: Set context so the NEXT reply is treated as an answer
                                set_session_context(session_id, 'AWAITING_CLARIFICATION')
                                    
                    except Exception as e:
                        logger.error(f"Tracking error: {e}")
                        reply = "I encountered an error accessing your order history."
                else:
                    reply = "Please sign in so I can check your orders."

            # --- B. CREATE ORDER ---
            elif hf_intent == "create_order":
                if email:
                    item = extract_item_gemini(transcript)
                    if item:
                        date_str = (datetime.now() + timedelta(days=5)).strftime("%b %d, %Y")
                        try:
                            with engine.begin() as conn:
                                conn.execute(sa.text("INSERT INTO orders (user_email, item_name, delivery_date, status) VALUES (:e, :i, :d, 'Processing')"), 
                                             {"e": email, "i": item, "d": date_str})
                            reply = f"Order placed for {item}. Arriving {date_str}."
                        except: reply = "Error saving order."
                    else:
                        reply = "What item would you like to order?"
                else:
                    reply = "Please sign in to place orders."
            
            # --- C. COUNT ORDERS ---
            elif hf_intent == "count_orders":
                if email:
                    try:
                        with engine.connect() as conn:
                            count = conn.execute(sa.text("SELECT COUNT(*) FROM orders WHERE user_email = :e"), {"e": email}).scalar()
                        reply = f"You have a total of {count} active orders."
                    except: reply = "DB Error."
                else: reply = "Please sign in."

            # --- D. OTHER ---
            elif hf_intent == "greeting":
                reply = "Hello! I can help you order items, track packages, or count your orders."
            elif hf_intent == "goodbye":
                reply = "Goodbye!"
            elif hf_intent == "complaint":
                reply = "I'm sorry. I can connect you to a human agent."

    # ---------------------------------------------------------
    # 3. FALLBACK (LLM)
    # ---------------------------------------------------------
    if not reply:
        docs = retrieve_docs(transcript)
        reply = call_gemini_rag(transcript, docs) if docs else call_gemini_general(transcript)
        if not reply: reply = "I'm having trouble connecting to my AI brain."

    # 4. Persist
    try:
        insert_voice_query(engine, user_id, session_id, transcript, intent, reply, None, [], 0, True)
    except: pass

    return jsonify({"reply": reply, "intent": hf_intent})

@api_bp.route("/history", methods=["GET"])
@firebase_auth_required
def history(): return jsonify({"history": []})

@api_bp.route("/debug_retrieve", methods=["POST"])
@firebase_auth_required
def debug_retrieve(): return jsonify({"retrieved": []})

@api_bp.route("/reload_index", methods=["POST"])
@firebase_auth_required
def reload_index(): return jsonify({"ok": True})