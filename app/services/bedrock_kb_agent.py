"""
Conversational RAG Agent using AWS Bedrock Knowledge Base (backed by Aurora PGVector).
Uses OpenAI GPT-4o for reasoning.
"""
import re
import asyncio
from typing import AsyncGenerator, Optional
from strands import Agent
from strands.models.openai import OpenAIModel
from app.core.config import get_settings
from app.services.session_manager import SessionManager
from app.core.logger import get_logger

# Import refactored logic
from app.core.prompts import SYSTEM_PROMPT, NON_UNDERWRITER_POLICY
from app.services.bedrock_retriever import search_manuals
from app.utils.hooks import RoleBasedOutputHook

logger = get_logger(__name__)


class BedrockKBAgent:
    """Strands Agent with OpenAI LLM and Managed AWS Bedrock Knowledge Base (Aurora)."""

    def __init__(self, session_manager: SessionManager):
        self.session_manager = session_manager
        self.agents: dict[tuple[str, str], Agent] = {}
        self.settings = get_settings()
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        logger.info("bedrock_kb_agent_initialized", kb_id=self.settings.bedrock_kb_id)

    def _build_agent(self, model: OpenAIModel, role_key: str) -> Agent:
        # URL/source blocking policy temporarily disabled for all roles.
        # role_policy = NON_UNDERWRITER_POLICY if role_key != "underwriter" else ""
        role_policy = ""
        prompt = f"{SYSTEM_PROMPT}\n\n{role_policy}".strip()

        # Build with hook provider when supported by installed Strands SDK.
        hook_provider: Optional[RoleBasedOutputHook] = None
        try:
            hook_provider = RoleBasedOutputHook(role_key)
            return Agent(
                model=model,
                system_prompt=prompt,
                tools=[search_manuals],
                hooks=[hook_provider],
            )
        except TypeError:
            logger.warning("agent_hooks_not_supported_fallback")
            return Agent(
                model=model,
                system_prompt=prompt,
                tools=[search_manuals],
            )

    def _get_or_create_agent(self, session_id: str, role: str) -> Agent:
        role_key = (role or "").strip().lower()
        cache_key = (session_id, role_key)
        if cache_key not in self.agents:
            # Initialize OpenAI model
            model = OpenAIModel(
                client_args={
                    "api_key": self.settings.openai_api_key,
                },
                model_id=self.settings.openai_chat_model,
                params={
                    "temperature": 0,
                    "max_tokens": 2048
                }
            )
            
            self.agents[cache_key] = self._build_agent(model, role_key)
        
        return self.agents[cache_key]

    async def query(
        self,
        session_id: str,
        query: str,
        role: str,
        top_k: int = 5
    ) -> AsyncGenerator[tuple[str, list[str], list[str]], None]:
        """Stream a query within a conversation session."""
        logger.info("processing_query_stream", session_id=session_id)

        try:
            # Initial state
            yield "🔍 Searching Coaction manuals...", [], []
            
            role_key = (role or "").strip().lower()
            agent = self._get_or_create_agent(session_id, role_key)
            
            # Simulate a small delay for retrieval start to ensure UI updates
            await asyncio.sleep(0.1)
            
            # Add user message to memory
            self.session_manager.add_message(session_id, "user", query)
            
            # Second state
            yield "📝 Analyzing manual content...", [], []
            
            # Execute agent synchronously (Strands call)
            response = agent(query)
            answer = str(response)
            
            # Save assistant response
            self.session_manager.add_message(session_id, "assistant", answer)
            
            # Extract and Split Follow-up Questions
            follow_up_questions = []
            fu_marker = "**You might also want to ask:**"
            if fu_marker in answer:
                parts = answer.split(fu_marker)
                answer = parts[0].strip()
                fu_text = parts[1]
                matches = re.findall(r"\d+\.\s*(.+)", fu_text)
                follow_up_questions = [m.strip() for m in matches if m.strip()][:3]

            # Extract Sources
            found_urls = re.findall(r"(https?://[^\s\)\n<>]+)", answer)
            seen = set()
            sources = [x.strip(".,;:?!") for x in found_urls if not (x in seen or seen.add(x))]

            # Final yield
            yield answer, sources, follow_up_questions
            
        except Exception as e:
            logger.error("query_failed", session_id=session_id, error=str(e))
            yield f"Error: {str(e)}", [], []
