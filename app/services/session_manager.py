from typing import Optional
import uuid
from datetime import datetime
from app.db.database import SessionLocal
from app.db.models import DBChatSession

class SessionManager:
    """
    Manages conversation sessions stored statelessly in PostgreSQL via SQLAlchemy.
    """
    def __init__(self):
        pass # Stateless! No cleanup thread needed inline.
    
    def create_session(self, metadata: Optional[dict] = None) -> str:
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        with SessionLocal() as db:
            session = DBChatSession(
                session_id=session_id,
                created_at=now,
                last_accessed=now,
                messages=[],
                metadata_=metadata or {}
            )
            db.add(session)
            db.commit()
        return session_id
    
    def add_message(self, session_id: str, role: str, content: str) -> None:
        now = datetime.utcnow()
        with SessionLocal() as db:
            session = db.query(DBChatSession).filter(DBChatSession.session_id == session_id).first()
            if not session:
                session = DBChatSession(
                    session_id=session_id,
                    created_at=now,
                    last_accessed=now,
                    messages=[],
                    metadata_={}
                )
                db.add(session)
            
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
                session.last_accessed = datetime.utcnow()
                db.commit()
                return session.messages
            return []

    def get_session(self, session_id: str) -> Optional[dict]:
        with SessionLocal() as db:
            session = db.query(DBChatSession).filter(DBChatSession.session_id == session_id).first()
            if session:
                return {
                    "session_id": session.session_id,
                    "created_at": session.created_at,
                    "last_accessed": session.last_accessed,
                    "messages": session.messages,
                    "metadata": session.metadata_
                }
            return None

    def clear_session(self, session_id: str) -> None:
        with SessionLocal() as db:
            db.query(DBChatSession).filter(DBChatSession.session_id == session_id).delete()
            db.commit()


