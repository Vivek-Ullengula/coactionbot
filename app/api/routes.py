import uuid
import json
from fastapi import APIRouter, HTTPException
from fastapi import Depends
from fastapi.responses import StreamingResponse
from app.schemas.schema import QueryRequest, QueryResponse
from app.core.logger import get_logger
from app.core.auth import get_current_user

logger = get_logger(__name__)
router = APIRouter()

_session_manager = None
_conversational_agent = None


def set_dependencies(session_manager, conversational_agent):
    global _session_manager, _conversational_agent
    _session_manager = session_manager
    _conversational_agent = conversational_agent


@router.post("/query")
async def query_knowledge_base(request: QueryRequest, user=Depends(get_current_user)):
    """
    Unified query endpoint. Returns a stream of events including:
    - {'type': 'status', 'message': '...'}
    - {'type': 'final', 'answer': '...', 'sources': [...], 'follow_up_questions': [...]}
    """
    if _conversational_agent is None:
        raise HTTPException(status_code=500, detail="Agent not initialized")

    session_id = request.session_id or _session_manager.create_session(user_email=user.email)

    async def stream_generator():
        try:
            async for answer, sources, follow_ups in _conversational_agent.query(
                session_id=session_id,
                query=request.query,
                role=user.role,
                top_k=request.top_k,
                user_email=user.email  # Pass user_email so agent can save it
            ):
                # If follow_ups is empty, it's a status update
                if not follow_ups and (answer.startswith("🔍") or answer.startswith("📝")):
                    yield f"data: {json.dumps({'type': 'status', 'message': answer})}\n\n"
                else:
                    payload = {
                        'type': 'final',
                        'answer': answer,
                        'sources': sources,
                        'follow_up_questions': follow_ups,
                        'session_id': session_id
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.error("stream_failed", error=str(e))
            yield f"data: {json.dumps({'type': 'error', 'message': str(e)})}\n\n"

    return StreamingResponse(stream_generator(), media_type="text/event-stream")


@router.get("/sessions")
async def get_sessions(user=Depends(get_current_user)):
    """Get all chat sessions for the current user."""
    if _session_manager is None:
        raise HTTPException(status_code=500, detail="Session manager not initialized")
    return _session_manager.get_user_sessions(user.email)


@router.get("/sessions/{session_id}")
async def get_session_history(session_id: str, user=Depends(get_current_user)):
    """Get history for a specific session."""
    if _session_manager is None:
        raise HTTPException(status_code=500, detail="Session manager not initialized")
    
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Security check: ensure user owns this session
    if session.get("user_email") != user.email:
        raise HTTPException(status_code=403, detail="Not authorized to access this session")
        
    return {"messages": session.get("messages", [])}


@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, user=Depends(get_current_user)):
    """Delete a specific session."""
    if _session_manager is None:
        raise HTTPException(status_code=500, detail="Session manager not initialized")
        
    session = _session_manager.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
        
    # Security check: ensure user owns this session
    if session.get("user_email") != user.email:
        raise HTTPException(status_code=403, detail="Not authorized to delete this session")
        
    _session_manager.clear_session(session_id)
    return {"status": "success"}
