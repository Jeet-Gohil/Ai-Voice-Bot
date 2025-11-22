import logging
import json
import time
import sqlalchemy as sa
from sqlalchemy import text as sql_text
from typing import Optional, List, Dict, Any

from app.config import Config

logger = logging.getLogger("voicebot")

# ---------- Init DB (SQLAlchemy) ----------
engine: Optional[sa.engine.Engine] = None
metadata = None


def init_db():
    """
    Initialize the SQLAlchemy engine using Config.DATABASE_URL.
    """
    global engine, metadata
    if engine is not None:
        return
    try:
        if not getattr(Config, "DATABASE_URL", None):
            logger.error("Config.DATABASE_URL not set. DB will remain uninitialized.")
            return
        engine = sa.create_engine(Config.DATABASE_URL, pool_pre_ping=True)
        metadata = sa.MetaData()
        logger.info("SQLAlchemy engine created.")
    except Exception as e:
        logger.exception("Failed to create SQLAlchemy engine: %s", e)
        engine = None
        metadata = None


# ---------- Database helpers & schema ----------

def create_tables():
    """
    Create or ensure users, voice_queries, orders, AND chat_sessions tables exist.
    """
    if engine is None:
        logger.warning("Engine is None; skipping create_tables()")
        return
    try:
        with engine.begin() as conn:
            try:
                conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            except Exception:
                pass

            # 1. Users Table
            conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS users (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                firebase_uid text UNIQUE NOT NULL,
                email text,
                display_name text,
                photo_url text,
                meta jsonb DEFAULT '{}'::jsonb,
                created_at timestamptz DEFAULT now(),
                last_seen timestamptz
            )
            """))

            # 2. Chat Sessions Table (NEW - For Context)
            conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS chat_sessions (
                session_uuid text PRIMARY KEY,
                user_email text,
                current_context text,
                updated_at timestamptz DEFAULT now()
            )
            """))

            # 3. Voice Queries Table
            conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS voice_queries (
                id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
                user_id uuid REFERENCES users(id),
                session_id text,
                transcript text,
                audio_url text,
                intent text,
                slots jsonb DEFAULT '{}'::jsonb,
                response jsonb DEFAULT '{}'::jsonb,
                rag_sources jsonb DEFAULT '[]'::jsonb,
                confidence double precision,
                duration_ms integer,
                created_at timestamptz DEFAULT now()
            )
            """))

            # 4. Orders Table (Matches your existing schema)
            conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_email TEXT,
                status TEXT,
                delivery_date TEXT,
                item_name TEXT
            )
            """))

        logger.info("Ensured all tables exist.")
    except Exception as e:
        logger.exception("create_tables() failed: %s", e)


def get_or_create_user_by_firebase_uid(firebase_uid: str, email: Optional[str] = None, name: Optional[str] = None, photo_url: Optional[str] = None) -> Optional[str]:
    if engine is None: return None
    try:
        with engine.begin() as conn:
            q = sa.text("SELECT id FROM users WHERE firebase_uid = :fu")
            row = conn.execute(q, {"fu": firebase_uid}).fetchone()
            if row:
                user_id = row[0]
                conn.execute(sa.text("UPDATE users SET last_seen = now(), email = coalesce(:email, email) WHERE id = :id"),
                             {"email": email, "id": user_id})
                return str(user_id)
            ins = sa.text("INSERT INTO users (firebase_uid, email, display_name, photo_url) VALUES (:fu, :email, :name, :photo_url) RETURNING id")
            res = conn.execute(ins, {"fu": firebase_uid, "email": email, "name": name, "photo_url": photo_url})
            return str(res.fetchone()[0])
    except Exception as e:
        logger.exception("User fetch failed: %s", e)
    return None


def insert_voice_query(conn_or_engine, user_id: Optional[str], session_id: str, transcript: str,
                       intent: Optional[str], reply: Optional[str], model_response: Optional[str],
                       sources: Optional[List[Dict[str, Any]]], model_ms: Optional[int], success: bool,
                       audio_url: Optional[str] = None, slots: Optional[dict] = None,
                       confidence: Optional[float] = None, duration_ms: Optional[int] = None) -> Optional[str]:
    
    global engine
    if conn_or_engine is None: conn_or_engine = engine
    if conn_or_engine is None: return None

    slots_json = json.dumps(slots or {})
    response_obj = {"reply": reply, "model_text": model_response, "ts": int(time.time())}
    response_json = json.dumps(response_obj)
    rag_json = json.dumps(sources or [])

    insert_sql = sa.text("""
        INSERT INTO voice_queries
          (user_id, session_id, transcript, audio_url, intent, slots, response, rag_sources, confidence, duration_ms, created_at)
        VALUES
          (:user_id, :session_id, :transcript, :audio_url, :intent, :slots::jsonb, :response::jsonb, :rag_sources::jsonb, :confidence, :duration_ms, now())
        RETURNING id
    """)

    try:
        # Check if we are in a transaction or need to start one
        if hasattr(conn_or_engine, "begin"):
            with conn_or_engine.begin() as conn:
                res = conn.execute(insert_sql, {
                    "user_id": user_id, "session_id": session_id, "transcript": transcript, "audio_url": audio_url,
                    "intent": intent, "slots": slots_json, "response": response_json, "rag_sources": rag_json,
                    "confidence": confidence, "duration_ms": duration_ms
                })
                return str(res.fetchone()[0])
        else:
            res = conn_or_engine.execute(insert_sql, {
                "user_id": user_id, "session_id": session_id, "transcript": transcript, "audio_url": audio_url,
                "intent": intent, "slots": slots_json, "response": response_json, "rag_sources": rag_json,
                "confidence": confidence, "duration_ms": duration_ms
            })
            return str(res.fetchone()[0])
    except Exception as e:
        logger.exception("Failed to insert voice_query: %s", e)
        return None

# ---------- Order & Context Helpers ----------

def get_order_status_by_email(email: str) -> str:
    """Legacy helper, kept for backward compatibility."""
    if engine is None: return "DB Error"
    try:
        with engine.connect() as conn:
            query = sql_text("SELECT item_name, status, delivery_date FROM orders WHERE user_email = :email ORDER BY id DESC LIMIT 1")
            result = conn.execute(query, {"email": email}).fetchone()
            if result:
                return f"Your order for {result[0]} is {result[1]}."
            return "No orders found."
    except Exception:
        return "Error checking orders."

# Initialize
init_db()
create_tables()