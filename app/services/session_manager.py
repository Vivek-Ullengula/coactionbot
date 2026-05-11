from typing import Optional
import uuid
from datetime import datetime, timedelta, timezone
from app.db.database import SessionLocal
from app.db.models import DBChatSession

# Indian Standard Time (IST) offset is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

class SessionManager:
    """
    Manages conversation sessions stored statelessly in PostgreSQL via SQLAlchemy.
    """
    def __init__(self):
        pass # Stateless! No cleanup thread needed inline.
    
    def create_session(self, user_email: Optional[str] = None, metadata: Optional[dict] = None) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.now(IST)
        with SessionLocal() as db:
            session = DBChatSession(
                session_id=session_id,
                user_email=user_email,
                created_at=now,
                last_accessed=now,
                messages=[],
                metadata_=metadata or {}
            )
            db.add(session)
            db.commit()
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str, user_email: Optional[str] = None) -> None:
        now = datetime.now(IST)
        with SessionLocal() as db:
            session = db.query(DBChatSession).filter(DBChatSession.session_id == session_id).first()
            if not session:
                session = DBChatSession(
                    session_id=session_id,
                    user_email=user_email,
                    created_at=now,
                    last_accessed=now,
                    messages=[],
                    metadata_={}
                )
                db.add(session)
            
            # Auto-generate title from the first user message if title is empty
            if role == "user" and not session.title:
                # Use the first 30 chars of the message as a simple title
                session.title = content[:30] + ("..." if len(content) > 30 else "")

            # If user_email is provided but not set on the session, set it now
            if user_email and not session.user_email:
                session.user_email = user_email
            
            # Because modifying a JSON array in-place might not trigger dirty flag
            messages = list(session.messages) if session.messages else []
            messages.append({
                "role": role,
                "content": content,
                "timestamp": now.isoformat()
            })
            session.messages = messages
            session.last_accessed = now
            db.commit()

    def get_messages(self, session_id: str) -> list[dict]:
        with SessionLocal() as db:
            session = db.query(DBChatSession).filter(DBChatSession.session_id == session_id).first()
            if session:
                session.last_accessed = datetime.now(IST)
                db.commit()
                return session.messages
            return []

    def get_session(self, session_id: str) -> Optional[dict]:
        with SessionLocal() as db:
            session = db.query(DBChatSession).filter(DBChatSession.session_id == session_id).first()
            if session:
                return {
                    "session_id": session.session_id,
                    "user_email": session.user_email,
                    "title": session.title,
                    "created_at": session.created_at,
                    "last_accessed": session.last_accessed,
                    "messages": session.messages,
                    "metadata": session.metadata_
                }
            return None

    def get_user_sessions(self, user_email: str) -> list[dict]:
        """Fetch all sessions for a specific user, ordered by last_accessed descending."""
        if not user_email:
            return []
            
        with SessionLocal() as db:
            sessions = db.query(DBChatSession).filter(
                DBChatSession.user_email == user_email
            ).order_by(DBChatSession.last_accessed.desc()).all()
            
            return [{
                "session_id": s.session_id,
                "title": s.title or "New Chat",
                "last_accessed": s.last_accessed.isoformat() if s.last_accessed else None
            } for s in sessions]

    def clear_session(self, session_id: str) -> None:
        with SessionLocal() as db:
            db.query(DBChatSession).filter(DBChatSession.session_id == session_id).delete()
            db.commit()


