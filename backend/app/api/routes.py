import time
import logging
from flask import Blueprint, request, jsonify
import sqlalchemy as sa

from app.config import Config
from app.core.auth import firebase_auth_required
from app.core.database import (
    get_or_create_user_by_firebase_uid,
    insert_voice_query,
    get_order_status_by_email,
    engine
)

from app.services.rag import retrieve_docs, load_index
from app.services.llm import call_gemini_rag, call_gemini_general
from app.services.nlu import classify_intent_hf

logger = logging.getLogger("voicebot")

api_bp = Blueprint("api", __name__)

@api_bp.route("/health", methods=["GET"])
def health():
    return "ok", 200

# 🟢 FIX: Add "OPTIONS" to the methods list
@api_bp.route("/auth/sync", methods=["POST", "OPTIONS"])
@firebase_auth_required
def auth_sync():
    # If it's OPTIONS, the decorator handles the headers, we just return OK
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    try:
        firebase_user = getattr(request, "firebase_user", {})
        uid = firebase_user.get("uid")
        email = firebase_user.get("email")
        name = firebase_user.get("name") or firebase_user.get("displayName")
        photo = firebase_user.get("picture")
        user_id = get_or_create_user_by_firebase_uid(uid, email=email, name=name, photo_url=photo)
        return jsonify({"status":"ok","user_id": user_id})
    except Exception as e:
        logger.exception("auth_sync failed")
        return jsonify({"error":"server_error","detail":str(e)}), 500

# 🟢 FIX: Add "OPTIONS" to the methods list
@api_bp.route("/query", methods=["POST", "OPTIONS"])
@firebase_auth_required
def query():
    if request.method == "OPTIONS":
        return jsonify({"status": "ok"}), 200

    payload = request.json or {}
    transcript = (payload.get("transcript") or "").strip()
    audio_url = payload.get("audio_url")
    session_id = payload.get("session_id", f"sess_{int(time.time())}")
    duration_ms = payload.get("duration_ms")

    if not transcript and not audio_url:
        return jsonify({"error":"empty transcript and no audio_url"}), 400

    firebase_user = getattr(request, "firebase_user", {})
    firebase_uid = firebase_user.get("uid")
    email = firebase_user.get("email")
    name = firebase_user.get("name") or firebase_user.get("displayName")

    user_id = None
    try:
        if firebase_uid:
            user_id = get_or_create_user_by_firebase_uid(firebase_uid, email=email, name=name)
    except Exception:
        logger.exception("Failed to map/create user for firebase_uid: %s", firebase_uid)

    if not transcript and audio_url:
        try:
            transcript = "[transcribed audio]"
        except Exception:
            transcript = ""

    # Init vars
    intent = None
    reply = None
    sources = []
    model_text = None
    model_ms = None
    success = False

    # 1. NLU Classification
    hf_intent, hf_score = classify_intent_hf(transcript)
    
    print(f"\n🛑 DEBUG: User said: '{transcript}'", flush=True)
    print(f"🛑 DEBUG: HF Model Prediction: Intent='{hf_intent}' | Score={hf_score:.4f}", flush=True)
    logger.info(f"🤖 HF MODEL PREDICTION: Intent='{hf_intent}' | Confidence={hf_score:.4f}")

    # 2. Feature 5 (Order Logic)
    is_order_intent = (hf_intent == "check order status" and hf_score > 0.4)

    if is_order_intent:
        print("✅ DEBUG: Logic decided to check Database!", flush=True)
        logger.info("✅ HF Model decided to check Database")
        
        if email:
            reply = get_order_status_by_email(email)
            intent = "order_tracking"
            success = True
        else:
            reply = "Please sign in so I can look up your order details."
            intent = "auth_required"
            success = True

    # 3. Fallback Logic
    if reply is None:
        try:
            intent = "open_question"
            docs = retrieve_docs(transcript, top_k=Config.TOP_K)
            sources = docs
            if docs:
                start = time.time()
                gen = call_gemini_rag(transcript, docs)
                model_ms = int((time.time() - start) * 1000)
                model_text = gen
                reply = gen if gen else f"I found info in {docs[0].get('source','unknown')}."
                success = True
            else:
                start = time.time()
                gen = call_gemini_general(transcript)
                model_ms = int((time.time() - start) * 1000)
                model_text = gen
                reply = gen if gen else "I don't know the answer to that right now."
                success = False if not gen else True
        except Exception as e:
            logger.exception("Processing error: %s", e)
            reply = "Internal server error processing your request."
            success = False

    # 4. Persistence
    qid = None
    try:
        qid = insert_voice_query(
            user_id=user_id, 
            session_id=session_id, 
            transcript=transcript, 
            intent=intent, 
            reply=reply, 
            model_response=model_text, 
            sources=sources, 
            model_ms=model_ms, 
            success=success, 
            audio_url=audio_url, 
            duration_ms=duration_ms
        )
    except Exception:
        logger.exception("Failed to persist voice query")

    response = {
        "reply": reply, 
        "intent": intent, 
        "sources": [{"id": s.get("id"), "source": s.get("source"), "score": s.get("score")} for s in sources] if sources else [], 
        "query_id": qid
    }
    return jsonify(response)

@api_bp.route("/history", methods=["GET", "OPTIONS"])
@firebase_auth_required
def history():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    
    firebase_user = getattr(request, "firebase_user", {})
    uid = firebase_user.get("uid")
    if not uid:
        return jsonify({"history": []})

    limit = int(request.args.get("limit", 20))
    try:
        if engine is None:
            return jsonify({"history": []})
        with engine.begin() as conn:
            row = conn.execute(sa.text("SELECT id FROM users WHERE firebase_uid = :fu"), {"fu": uid}).fetchone()
            if not row:
                return jsonify({"history": []})
            user_id = row[0]
            rows = conn.execute(sa.text("SELECT id, session_id, transcript, intent, response, rag_sources, confidence, duration_ms, created_at FROM voice_queries WHERE user_id = :uid ORDER BY created_at DESC LIMIT :lim"), {"uid": user_id, "lim": limit}).fetchall()
            result = []
            for r in rows:
                result.append({
                    "id": str(r[0]),
                    "session_id": r[1],
                    "transcript": r[2],
                    "intent": r[3],
                    "response": r[4],
                    "rag_sources": r[5],
                    "confidence": r[6],
                    "duration_ms": r[7],
                    "created_at": r[8].isoformat() if r[8] else None
                })
            return jsonify({"history": result})
    except Exception as e:
        logger.exception("history failed: %s", e)
        return jsonify({"error":"server_error","detail": str(e)}), 500

@api_bp.route("/debug_retrieve", methods=["POST", "OPTIONS"])
@firebase_auth_required
def debug_retrieve():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    payload = request.json or {}
    q = payload.get("query","")
    if not q:
        return jsonify({"error":"empty query"}), 400
    docs = retrieve_docs(q, top_k=10)
    return jsonify({"retrieved": docs})

@api_bp.route("/reload_index", methods=["POST", "OPTIONS"])
@firebase_auth_required
def reload_index():
    if request.method == "OPTIONS": return jsonify({"status": "ok"}), 200
    try:
        load_index()
        return jsonify({"ok": True, "msg": "Index reloaded"})
    except Exception as e:
        logger.exception("reload_index failed: %s", e)
        return jsonify({"ok": False, "error": str(e)}), 500