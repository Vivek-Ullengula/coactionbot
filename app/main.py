from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.api.routes import router, set_dependencies
from app.api.sessions import router as session_router, set_session_manager
from app.api.auth import router as auth_router
from app.logger import setup_logging, get_logger
from app.session_manager import SessionManager
from app.config import get_settings
from app.auth import init_auth_table

logger = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    logger.info("startup", service="bedrock-kb-rag")

    settings = get_settings()
    session_manager = SessionManager()
    init_auth_table()
    
    # Initialize Bedrock KB agent
    logger.info("initializing_bedrock_kb_agent", kb_id=settings.bedrock_kb_id)
    from app.bedrock_kb_agent import BedrockKBAgent
    conversational_agent = BedrockKBAgent(
        session_manager=session_manager
    )

    set_session_manager(session_manager)
    set_dependencies(session_manager, conversational_agent)

    logger.info("ready", agent_type="bedrock_kb")
    yield

    session_manager.stop()
    logger.info("shutdown", service="bedrock-kb-rag")


app = FastAPI(
    title="RAG Pipeline API",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api/v1", tags=["RAG"])
app.include_router(session_router, prefix="/api/v1/session", tags=["Sessions"])
app.include_router(auth_router, prefix="/api/v1/auth", tags=["Auth"])


@app.get("/health")
async def health():
    return {"status": "ok"}
