"""
Session management API endpoints.

This module provides REST API endpoints for managing conversation sessions,
enabling multi-turn conversations with the RAG agent.
"""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel
from typing import Optional
from app.core.logger import get_logger

logger = get_logger(__name__)
router = APIRouter()

# Session manager will be injected via dependency
_session_manager = None


def set_session_manager(manager):
    """Set the session manager instance for the router."""
    global _session_manager
    _session_manager = manager


class CreateSessionRequest(BaseModel):
    """Request model for creating a new session."""
    metadata: Optional[dict] = None


class CreateSessionResponse(BaseModel):
    """Response model for session creation."""
    session_id: str
    created_at: str


class SessionResponse(BaseModel):
    """Response model for session details."""
    session_id: str
    created_at: str
    last_accessed: str
    messages: list[dict]
    metadata: dict


class DeleteSessionResponse(BaseModel):
    """Response model for session deletion."""
    status: str
    session_id: str


@router.post("/create", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """
    Create a new conversation session.
    
    Args:
        request: Session creation request with optional metadata
        
    Returns:
        CreateSessionResponse with session_id and created_at timestamp
        
    Example:
        POST /api/v1/session/create
        {
            "metadata": {"user_id": "123", "topic": "documentation"}
        }
        
        Response:
        {
            "session_id": "550e8400-e29b-41d4-a716-446655440000",
            "created_at": "2024-01-15T10:30:00.000000"
        }
    """
    if _session_manager is None:
        logger.error("session_manager_not_initialized")
        raise HTTPException(
            status_code=500,
            detail="Session manager not initialized"
        )
    
    try:
        session_id = _session_manager.create_session(request.metadata)
        session = _session_manager.get_session(session_id)
        
        if not session:
            logger.error("session_creation_failed", session_id=session_id)
            raise HTTPException(
                status_code=500,
                detail="Failed to create session"
            )
        
        logger.info(
            "session_created",
            session_id=session_id,
            metadata=request.metadata
        )
        
        return CreateSessionResponse(
            session_id=session_id,
            created_at=session.created_at.isoformat()
        )
    except Exception as e:
        logger.error("session_creation_error", error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create session: {str(e)}"
        )

@router.get("/{session_id}", response_model=SessionResponse)
async def get_session(session_id: str):
    """
    Get session details and message history.
    
    Args:
        session_id: Unique session identifier
        
    Returns:
        SessionResponse with session details and all messages
        
    Raises:
        HTTPException: 404 if session not found
        
    Example:
        GET /api/v1/session/550e8400-e29b-41d4-a716-446655440000
        
        Response:
        {
            "session_id": "550e8400-e29b-41d4-a716-446655440000",
            "created_at": "2024-01-15T10:30:00.000000",
            "last_accessed": "2024-01-15T10:35:00.000000",
            "messages": [
                {
                    "role": "user",
                    "content": "What is RAG?",
                    "timestamp": "2024-01-15T10:30:15.000000"
                },
                {
                    "role": "assistant",
                    "content": "RAG stands for...",
                    "timestamp": "2024-01-15T10:30:18.000000"
                }
            ],
            "metadata": {"user_id": "123"}
        }
    """
    if _session_manager is None:
        logger.error("session_manager_not_initialized")
        raise HTTPException(
            status_code=500,
            detail="Session manager not initialized"
        )
    
    try:
        session = _session_manager.get_session(session_id)
        
        if not session:
            logger.warning("session_not_found", session_id=session_id)
            raise HTTPException(
                status_code=404,
                detail=f"Session {session_id} not found"
            )
        
        logger.info(
            "session_retrieved",
            session_id=session_id,
            message_count=len(session.get("messages", []))
        )
        
        return SessionResponse(
            session_id=session["session_id"],
            created_at=session["created_at"].isoformat() if hasattr(session["created_at"], "isoformat") else str(session["created_at"]),
            last_accessed=session["last_accessed"].isoformat() if hasattr(session["last_accessed"], "isoformat") else str(session["last_accessed"]),
            messages=session.get("messages", []),
            metadata=session.get("metadata", {})
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error("session_retrieval_error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to retrieve session: {str(e)}"
        )


@router.delete("/{session_id}", response_model=DeleteSessionResponse)
async def delete_session(session_id: str):
    """
    Delete a conversation session and clear its history.
    
    Args:
        session_id: Unique session identifier
        
    Returns:
        DeleteSessionResponse with status and session_id
        
    Note:
        This endpoint does not return 404 if the session doesn't exist,
        as the end result (session not existing) is the same.
        
    Example:
        DELETE /api/v1/session/550e8400-e29b-41d4-a716-446655440000
        
        Response:
        {
            "status": "deleted",
            "session_id": "550e8400-e29b-41d4-a716-446655440000"
        }
    """
    if _session_manager is None:
        logger.error("session_manager_not_initialized")
        raise HTTPException(
            status_code=500,
            detail="Session manager not initialized"
        )
    
    try:
        # Check if session exists before deletion for logging purposes
        session_existed = _session_manager.get_session(session_id) is not None
        
        # Clear the session (idempotent operation)
        _session_manager.clear_session(session_id)
        
        if session_existed:
            logger.info("session_deleted", session_id=session_id)
        else:
            logger.info("session_delete_noop", session_id=session_id)
        
        return DeleteSessionResponse(
            status="deleted",
            session_id=session_id
        )
    except Exception as e:
        logger.error("session_deletion_error", session_id=session_id, error=str(e))
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete session: {str(e)}"
        )
