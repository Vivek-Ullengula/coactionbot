"""
Conversational RAG Agent using AWS Bedrock Knowledge Base.
Uses OpenAI GPT-4o for reasoning and Bedrock KB for retrieval.
"""
import asyncio
import os
from strands import Agent
from strands.models.openai import OpenAIModel
from strands_tools import retrieve
from app.config import get_settings
from app.session_manager import SessionManager
from app.logger import get_logger

logger = get_logger(__name__)

SYSTEM_PROMPT = """<role>
You are an expert Coaction underwriting assistant. Your sole purpose is to answer underwriting queries using ONLY the provided knowledge base containing the General Liability Manual and the Property Manual.
</role>
 
<tool_usage_rules>
- You have a "retrieve" tool that searches the Bedrock Knowledge Base.
- Call the retrieve tool ONCE per user question with a well-crafted search query.
- After receiving results, evaluate them immediately for ambiguity or missing context.
- If the first retrieval returns no relevant results, follow the fallback protocol. Do NOT retry.
</tool_usage_rules>
 
<core_directives>
1. NO HALLUCINATION: You are strictly forbidden from using any outside knowledge. Every fact in your answer MUST be supported by retrieved context.
2. ISOLATION: Do not mix General Liability and Property content. Answer only for the relevant line of business.
3. SOURCE ALIGNMENT: Ensure the response strictly reflects the retrieved manual content. Do not generalize or infer beyond it.
</core_directives>
 
<clarification_protocol>
MANDATORY DISAMBIGUATION PROTOCOL:
You must ask EXACTLY ONE clarifying question and STOP if any of the following ambiguity scenarios occur:

1. INSUFFICIENT DETAIL: The user query is too vague to search (e.g., searching for a "restaurant" without specific operation details or manual reference).
2. AMBIGUOUS RETRIEVAL (MULTIPLE MATCHES):
   - SAME NAME, DIFFERENT CODES: If the retrieved chunks show multiple different class code numbers for the same or similar business names, list the specific class codes and ask the user which one they are interested in.
   - MULTIPLE SECTIONS: If the query maps to different distinct sections in the manual for the same topic (e.g., "Special Projects" with conflicting requirements), ask the user for context.
3. CROSS-MANUAL CONFLICT: If retrieval returns relevant results from BOTH the Property Manual and the General Liability Manual for the same query, and the user hasn't specified which coverage they need, ask: "Are you inquiring about Property or General Liability coverage for this business?"

CLARIFICATION RULES:
- Guide the user to choose from valid options present in the retrieved content.
- Do NOT assume or infer missing details.
- Ask exactly ONE question and stop. NEVER proceed to answer until the ambiguity is resolved.
</clarification_protocol>
 
<class_code_rule>
- If the user provides a class code or business type:
  - If unique, return full details (description, coverage options, property notes, requirements, prohibited operations, forms).
  - If multiple similar codes exist, invoke the disambiguation protocol above to ask for the specific code.
</class_code_rule>
 
<answer_generation>
- Generate response ONLY once you have non-ambiguous, specific context.
- The response must be:
  - Direct and precise.
  - Fully cited: For every fact or requirement provided, you MUST append the specific source URL found in the tool metadata.
  - Every answer must end with a "Sources:" section listing the unique URLs used.
</answer_generation>
 
<response_format>
- Provide the answer first.
- Then suggest exactly 3 relevant follow-up questions formatted as:

**You might also want to ask:**
1. [question]
2. [question]
3. [question]
</response_format>
 
<fallback_protocol>
- OUT OF SCOPE: If the query is unrelated to underwriting, respond EXACTLY with: "I can only answer binding authority related questions."
- MISSING DATA: If the query is within scope but no answer is found in the manuals, respond EXACTLY with: "Please contact a Coaction underwriter."
</fallback_protocol>"""


class BedrockKBAgent:
    """Strands Agent with OpenAI LLM and Bedrock Knowledge Base retrieval."""

    def __init__(self, session_manager: SessionManager, knowledge_base_id: str | None = None):
        self.session_manager = session_manager
        self.agents: dict[str, Agent] = {}
        self.settings = get_settings()
        self.knowledge_base_id = knowledge_base_id or self.settings.bedrock_kb_id
        if not self.knowledge_base_id:
            raise ValueError("BEDROCK_KB_ID is required")
        if not self.settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required")
        logger.info("bedrock_kb_agent_initialized", kb_id=self.knowledge_base_id)

    def _get_or_create_agent(self, session_id: str) -> Agent:
        if session_id not in self.agents:
            logger.info("creating_agent_for_session", session_id=session_id)
            
            # Set environment variables for the retrieve tool (still uses Bedrock KB via boto3)
            os.environ["KNOWLEDGE_BASE_ID"] = self.knowledge_base_id
            os.environ["AWS_REGION"] = self.settings.aws_region
            if self.settings.aws_access_key_id:
                os.environ["AWS_ACCESS_KEY_ID"] = self.settings.aws_access_key_id
            if self.settings.aws_secret_access_key:
                os.environ["AWS_SECRET_ACCESS_KEY"] = self.settings.aws_secret_access_key
            
            # Initialize OpenAI model (GPT-4o)
            model = OpenAIModel(
                client_args={
                    "api_key": self.settings.openai_api_key,
                },
                model_id=self.settings.openai_chat_model,
                params={
                    "temperature": 0.2,
                    "max_tokens": 2048
                }
            )
            
            # Create agent with KB retrieve tool
            self.agents[session_id] = Agent(
                model=model,
                system_prompt=SYSTEM_PROMPT,
                tools=[retrieve],
            )
        
        return self.agents[session_id]

    async def query(
        self,
        session_id: str,
        query: str,
        top_k: int = 5
    ) -> tuple[str, list[str], list[str]]:
        """Process a query within a conversation session."""
        logger.info("processing_query", session_id=session_id)

        agent = self._get_or_create_agent(session_id)
        self.session_manager.add_message(session_id, "user", query)

        # Run agent
        response = await asyncio.to_thread(lambda: agent(query))
        answer = str(response)

        self.session_manager.add_message(session_id, "assistant", answer)
        logger.info("query_processed", session_id=session_id)

        # Extract sources and generate follow-up questions
        sources, follow_up_questions = await asyncio.gather(
            self._extract_sources_from_response(answer),
            self._generate_follow_up_questions(query, answer),
        )

        # Strip inline follow-up block from answer text to avoid duplication
        # (follow-ups are shown as clickable buttons in the UI instead)
        clean_answer, _ = self._parse_inline_follow_ups(answer)

        return clean_answer, sources, follow_up_questions

    # Phrases that indicate the answer was NOT grounded in retrieved content
    _FALLBACK_PHRASES = (
        "i can only answer binding authority related questions",
        "please contact a coaction underwriter",
        "not available in the binding authority",
        "please contact your underwriter",
        "i can only assist with",
        "no relevant context found",
    )

    async def _extract_sources_from_response(self, answer: str) -> list[str]:
        """Extract source URLs from agent response."""
        # Don't show sources for fallback / out-of-scope answers
        answer_lower = answer.lower()
        if any(phrase in answer_lower for phrase in self._FALLBACK_PHRASES):
            return []
        
        # Bedrock KB includes citations in response
        # Extract URLs from citations if present
        import re
        urls = re.findall(r'https?://[^\s<>"]+', answer)
        return list(dict.fromkeys(urls))[:3]  # Dedupe and limit to 3

    def _parse_inline_follow_ups(self, answer: str) -> tuple[str, list[str]]:
        """Parse follow-up questions already embedded in the agent's response.
        
        The system prompt instructs the agent to append:
          **You might also want to ask:**
          1. [question]
          2. [question]
          3. [question]
        
        Returns the cleaned answer (without the follow-up block) and the parsed questions.
        """
        import re
        # Match the follow-up block at the end of the response
        pattern = r'\*\*You might also want to ask:\*\*\s*\n((?:\s*\d+\.\s*.+\n?)+)'
        match = re.search(pattern, answer)
        if not match:
            return answer, []
        
        # Extract questions
        block = match.group(1)
        questions = re.findall(r'\d+\.\s*(.+)', block)
        questions = [q.strip().rstrip('?') + '?' for q in questions if q.strip()]
        
        # Remove the follow-up block from the answer
        clean_answer = answer[:match.start()].rstrip()
        
        return clean_answer, questions[:3]

    async def _generate_follow_up_questions(self, query: str, answer: str) -> list[str]:
        """Generate follow-up questions.
        
        First tries to parse follow-ups already embedded in the agent's response
        (per the system prompt). Falls back to a separate LLM call if none found.
        """
        # Try parsing inline follow-ups first
        _, inline_questions = self._parse_inline_follow_ups(answer)
        if inline_questions:
            return inline_questions
        
        # Fallback: generate via separate LLM call
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=self.settings.openai_api_key)
            
            prompt = (
                f"Based on the following underwriting conversation, generate exactly 3 relevant "
                f"follow-up questions the user might want to ask next.\n\n"
                f"User's Question: {query}\n\n"
                f"Agent's Response: {answer}\n\n"
                f"Requirements:\n"
                f"- Questions must be strictly related to Coaction underwriting topics "
                f"(General Liability Manual or Property Manual)\n"
                f"- If the agent asked a clarification question, suggest questions that "
                f"help the user provide the missing details\n"
                f"- Keep each question concise (under 100 characters)\n"
                f"- Return only the questions, one per line, without numbering or bullets"
            )
            
            response = await client.chat.completions.create(
                model=self.settings.openai_chat_model,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=200,
            )
            text = response.choices[0].message.content or ""
            return [q.strip() for q in text.strip().split("\n") if q.strip()][:3]
        except Exception as e:
            logger.warning("follow_up_generation_failed", error=str(e))
            return []

    def clear_session(self, session_id: str) -> None:
        """Clear conversation session."""
        self.session_manager.clear_session(session_id)
        self.agents.pop(session_id, None)
        logger.info("session_cleared", session_id=session_id)
