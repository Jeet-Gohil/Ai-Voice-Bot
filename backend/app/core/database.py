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
    This function is safe to call multiple times.
    """
    global engine, metadata
    if engine is not None:
        return
    try:
        if not getattr(Config, "DATABASE_URL", None):
            logger.error("Config.DATABASE_URL not set. DB will remain uninitialized.")
            return
        # Prefer psycopg2 driver style URL if provided by Config; SQLAlchemy will accept many formats.
        engine = sa.create_engine(Config.DATABASE_URL, pool_pre_ping=True)
        metadata = sa.MetaData()
        logger.info("SQLAlchemy engine created for DATABASE_URL (masked).")
    except Exception as e:
        logger.exception("Failed to create SQLAlchemy engine: %s", e)
        engine = None
        metadata = None


# ---------- Database helpers & schema ----------

def create_tables():
    """
    Create or ensure users, voice_queries, and orders tables exist.
    """
    if engine is None:
        logger.warning("Engine is None; skipping create_tables()")
        return
    try:
        with engine.begin() as conn:
            try:
                conn.execute(sql_text("CREATE EXTENSION IF NOT EXISTS pgcrypto"))
            except Exception:
                # ignore if extension creation fails (may not be allowed on hosted DB)
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

            # 2. Voice Queries Table
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

            # 3. Orders Table (Feature 5)
            conn.execute(sql_text("""
            CREATE TABLE IF NOT EXISTS orders (
                id SERIAL PRIMARY KEY,
                user_email TEXT,
                status TEXT,
                delivery_date TEXT,
                item_name TEXT
            )
            """))

        logger.info("Ensured users, voice_queries, and orders tables exist.")
    except Exception as e:
        logger.exception("create_tables() failed: %s", e)


def get_or_create_user_by_firebase_uid(firebase_uid: str, email: Optional[str] = None, name: Optional[str] = None, photo_url: Optional[str] = None) -> Optional[str]:
    """
    Returns internal Postgres user.id (uuid string) for the given firebase_uid.
    Creates the user row if not present.
    """
    if engine is None:
        logger.error("DB engine not configured")
        return None
    try:
        with engine.begin() as conn:
            q = sa.text("SELECT id FROM users WHERE firebase_uid = :fu")
            row = conn.execute(q, {"fu": firebase_uid}).fetchone()
            if row:
                user_id = row[0]
                try:
                    conn.execute(sa.text("UPDATE users SET last_seen = now(), email = coalesce(:email, email), display_name = coalesce(:name, display_name), photo_url = coalesce(:photo_url, photo_url) WHERE id = :id"),
                                 {"email": email, "name": name, "photo_url": photo_url, "id": user_id})
                except Exception:
                    logger.exception("Failed to update user fields for id=%s", user_id)
                return str(user_id)
            ins = sa.text("INSERT INTO users (firebase_uid, email, display_name, photo_url) VALUES (:fu, :email, :name, :photo_url) RETURNING id")
            res = conn.execute(ins, {"fu": firebase_uid, "email": email, "name": name, "photo_url": photo_url})
            new_row = res.fetchone()
            if new_row:
                logger.info("Inserted new user id=%s for firebase_uid=%s", new_row[0], firebase_uid)
                return str(new_row[0])
    except Exception as e:
        logger.exception("get_or_create_user_by_firebase_uid exception: %s", e)
    return None


def insert_voice_query(conn_or_engine, user_id: Optional[str], session_id: str, transcript: str,
                       intent: Optional[str], reply: Optional[str], model_response: Optional[str],
                       sources: Optional[List[Dict[str, Any]]], model_ms: Optional[int], success: bool,
                       audio_url: Optional[str] = None, slots: Optional[dict] = None,
                       confidence: Optional[float] = None, duration_ms: Optional[int] = None) -> Optional[str]:
    """
    Insert a voice_queries row and return the inserted id (uuid string).
    conn_or_engine can be None (global engine will be used), an Engine, or a Connection.
    """
    global engine

    # If caller passed None, use global engine
    if conn_or_engine is None:
        conn_or_engine = engine

    if conn_or_engine is None:
        logger.error("No DB engine/connection available to insert voice_query")
        return None

    # Prepare JSONB-safe payloads
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
        # Engine (use transaction)
        if hasattr(conn_or_engine, "begin"):
            with conn_or_engine.begin() as conn:
                res = conn.execute(insert_sql, {
                    "user_id": user_id,
                    "session_id": session_id,
                    "transcript": transcript,
                    "audio_url": audio_url,
                    "intent": intent,
                    "slots": slots_json,
                    "response": response_json,
                    "rag_sources": rag_json,
                    "confidence": confidence,
                    "duration_ms": duration_ms
                })
                new_row = res.fetchone()
                if new_row:
                    logger.info("Persisted voice_query id=%s", new_row[0])
                    return str(new_row[0])
                return None
        else:
            # Connection-like object
            res = conn_or_engine.execute(insert_sql, {
                "user_id": user_id,
                "session_id": session_id,
                "transcript": transcript,
                "audio_url": audio_url,
                "intent": intent,
                "slots": slots_json,
                "response": response_json,
                "rag_sources": rag_json,
                "confidence": confidence,
                "duration_ms": duration_ms
            })
            new_row = res.fetchone()
            if new_row:
                logger.info("Persisted voice_query id=%s", new_row[0])
                return str(new_row[0])
            return None

    except Exception as e:
        logger.exception("Failed to insert voice_query: %s", e)
        return None


# ---------- Feature 5: Order Lookup ----------

def get_order_status_by_email(email: str) -> str:
    """
    Fetches the latest order status for a given email.
    """
    if engine is None:
        return "Database connection is not available."

    try:
        with engine.connect() as conn:
            # Select the most recent order for this email
            query = sql_text("""
                SELECT item_name, status, delivery_date 
                FROM orders 
                WHERE user_email = :email 
                ORDER BY id DESC LIMIT 1
            """)
            result = conn.execute(query, {"email": email}).fetchone()

            if result:
                item = result[0]
                status = result[1]
                date = result[2]
                return f"Your order for {item} is currently **{status}**. It is expected to arrive by {date}."
            else:
                return "I couldn't find any recent orders linked to your account."
    except Exception as e:
        logger.error(f"Order lookup failed: {e}")
        return "I encountered an error checking the order database."


# Ensure DB is initialized on import
init_db()
create_tables()
