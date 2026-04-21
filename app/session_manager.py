"""
Session management for multi-turn conversations.

This module provides session management capabilities for the RAG agent,
enabling multi-turn conversations with conversation history tracking.
"""

from dataclasses import dataclass, field
from typing import Optional
import uuid
from datetime import datetime, timedelta
import threading
import time


@dataclass
class ConversationSession:
    """Represents a conversation session with message history."""
    
    session_id: str
    created_at: datetime
    last_accessed: datetime
    messages: list[dict] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class SessionManager:
    """
    Manages conversation sessions for multi-turn interactions.
    
    Stores sessions in memory with TTL-based cleanup. Sessions are automatically
    expired after a configurable time period to prevent memory leaks.
    
    Thread-safe implementation using locks for concurrent access.
    """
    
    def __init__(
        self,
        ttl_hours: int = 24,
        cleanup_interval_hours: int = 6
    ):
        """
        Initialize the session manager.
        
        Args:
            ttl_hours: Time-to-live for sessions in hours (default: 24)
            cleanup_interval_hours: Interval between cleanup runs in hours (default: 6)
        """
        self.sessions: dict[str, ConversationSession] = {}
        self.ttl_hours = ttl_hours
        self.cleanup_interval_hours = cleanup_interval_hours
        self._lock = threading.Lock()
        self._cleanup_thread: Optional[threading.Thread] = None
        self._stop_cleanup = threading.Event()
        
        # Start cleanup thread
        self._start_cleanup_thread()
    
    def _start_cleanup_thread(self) -> None:
        """Start the background cleanup thread."""
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._stop_cleanup.clear()
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                daemon=True
            )
            self._cleanup_thread.start()
    
    def _cleanup_loop(self) -> None:
        """Background loop that periodically cleans up expired sessions."""
        while not self._stop_cleanup.is_set():
            # Wait for cleanup interval or stop signal
            if self._stop_cleanup.wait(timeout=self.cleanup_interval_hours * 3600):
                break
            
            # Perform cleanup
            self._cleanup_expired_sessions()
    
    def _cleanup_expired_sessions(self) -> None:
        """Remove sessions that have exceeded their TTL."""
        now = datetime.utcnow()
        ttl_delta = timedelta(hours=self.ttl_hours)
        
        with self._lock:
            expired_sessions = [
                session_id
                for session_id, session in self.sessions.items()
                if now - session.last_accessed > ttl_delta
            ]
            
            for session_id in expired_sessions:
                del self.sessions[session_id]
    
    def create_session(self, metadata: Optional[dict] = None) -> str:
        """
        Create a new conversation session.
        
        Args:
            metadata: Optional metadata to associate with the session
            
        Returns:
            Unique session identifier (UUID)
        """
        session_id = str(uuid.uuid4())
        now = datetime.utcnow()
        
        session = ConversationSession(
            session_id=session_id,
            created_at=now,
            last_accessed=now,
            messages=[],
            metadata=metadata or {}
        )
        
        with self._lock:
            self.sessions[session_id] = session
        
        return session_id
    
    def get_session(self, session_id: str) -> Optional[ConversationSession]:
        """
        Retrieve a session by ID and update last accessed time.
        
        Args:
            session_id: Session identifier
            
        Returns:
            ConversationSession if found, None otherwise
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if session:
                session.last_accessed = datetime.utcnow()
            return session
    
    def add_message(
        self,
        session_id: str,
        role: str,
        content: str
    ) -> None:
        """
        Add a message to the session history. Auto-creates session if not found.
        """
        with self._lock:
            session = self.sessions.get(session_id)
            if not session:
                # Auto-create session
                now = datetime.utcnow()
                session = ConversationSession(
                    session_id=session_id,
                    created_at=now,
                    last_accessed=now,
                    messages=[],
                    metadata={}
                )
                self.sessions[session_id] = session
            
            session.last_accessed = datetime.utcnow()
            session.messages.append({
                "role": role,
                "content": content,
                "timestamp": datetime.utcnow().isoformat()
            })
    
    def get_messages(self, session_id: str) -> list[dict]:
        """
        Get all messages for a session.
        
        Args:
            session_id: Session identifier
            
        Returns:
            List of messages in chronological order, empty list if session not found
        """
        session = self.get_session(session_id)
        return session.messages if session else []
    
    def clear_session(self, session_id: str) -> None:
        """
        Clear a session's conversation history and remove it from storage.
        
        Args:
            session_id: Session identifier
        """
        with self._lock:
            if session_id in self.sessions:
                del self.sessions[session_id]
    
    def stop(self) -> None:
        """Stop the cleanup thread. Call this during shutdown."""
        self._stop_cleanup.set()
        if self._cleanup_thread and self._cleanup_thread.is_alive():
            self._cleanup_thread.join(timeout=5)
    
    def __del__(self):
        """Cleanup on deletion."""
        self.stop()
