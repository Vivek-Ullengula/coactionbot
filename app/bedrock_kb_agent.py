"""
Conversational RAG Agent using AWS Bedrock Knowledge Base (backed by Aurora PGVector).
Uses OpenAI GPT-4o for reasoning.
"""
import boto3
import re
import asyncio
from typing import AsyncGenerator, Optional
from strands import Agent, tool
from strands.models.openai import OpenAIModel
from app.config import get_settings
from app.session_manager import SessionManager
from app.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

SYSTEM_PROMPT = """<role>
You are an expert Coaction underwriting assistant. Your sole purpose is to answer underwriting queries using ONLY the provided knowledge base containing the General Liability Manual and the Property Manual.
</role>
 
<tool_usage_rules>
- You have a "search_manuals" tool that searches the Bedrock Knowledge Base.
- Call the search_manuals tool ONCE per user question with a well-crafted search query.
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
  - Fully cited: For every fact or requirement provided, you MUST append the specific raw source URL (starting with http) found in the tool metadata. DO NOT convert these to [1] or [Source 1].
  - Every answer must end with a "Sources:" section listing every unique URL and its corresponding heading used in the answer.
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

NON_UNDERWRITER_POLICY = """
<role_based_visibility_policy>
- You are answering for a non-underwriter user (agent/external).
- You MUST NOT output raw URLs, hyperlinks, or any "Sources:" section.
- Keep the underwriting answer complete, but omit all link references.
</role_based_visibility_policy>
"""

URL_PATTERN = re.compile(r"https?://[^\s)\]<>]+")


def sanitize_non_underwriter_output(answer: str) -> str:
    answer = re.sub(r"\[([^\]]+)\]\(https?://[^)\s]+\)", r"\1", answer)
    answer = URL_PATTERN.sub("", answer)
    answer = re.sub(r"\n\s*Sources:\s*(.|\n)*$", "", answer, flags=re.IGNORECASE)
    answer = re.sub(r"[ \t]{2,}", " ", answer)
    answer = re.sub(r"\n{3,}", "\n\n", answer)
    return answer.strip()


class RoleBasedOutputHook:
    """
    Strands hook-style output policy for non-underwriters.
    Uses duck-typing so it remains compatible across SDK event shape changes.
    """

    def __init__(self, role: str):
        self.role = (role or "").strip().lower()

    def register_hooks(self, registry) -> None:
        # Prefer AfterModelCallEvent if available; fallback silently if hook API differs.
        try:
            from strands.hooks.events import AfterModelCallEvent

            registry.add_callback(AfterModelCallEvent, self._after_model_call)
        except Exception:
            logger.warning("hook_registration_unavailable")

    def _after_model_call(self, event) -> None:
        if self.role == "underwriter":
            return

        # Common event/message shapes seen across SDK versions.
        if hasattr(event, "message") and isinstance(getattr(event, "message"), str):
            event.message = sanitize_non_underwriter_output(event.message)
            return

        if hasattr(event, "response"):
            response = getattr(event, "response")
            if isinstance(response, str):
                event.response = sanitize_non_underwriter_output(response)
                return
            if hasattr(response, "content") and isinstance(response.content, str):
                response.content = sanitize_non_underwriter_output(response.content)
                return


@tool
def search_manuals(query: str) -> str:
    """Search the Coaction underwriting manuals (General Liability and Property) using the AWS Knowledge Base.

    Args:
        query: The search query to find relevant manual content.
    """
    try:
        client = boto3.client(
            'bedrock-agent-runtime',
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key
        )
        
        logger.info("searching_bedrock_kb", query=query, kb_id=settings.bedrock_kb_id)
        
        response = client.retrieve(
            knowledgeBaseId=settings.bedrock_kb_id,
            retrievalQuery={'text': query},
            retrievalConfiguration={
                'vectorSearchConfiguration': {
                    'numberOfResults': 5
                }
            }
        )
        
        results = response.get('retrievalResults', [])
        logger.info("retrieval_complete", result_count=len(results))
        
        if not results:
            return "No relevant information found in the manuals."
            
        formatted_results = []
        for r in results:
            content = r.get('content', {}).get('text', '')
            meta = r.get('metadata', {})
            
            # Extract metadata attributes we saved during S3 upload
            source = meta.get('source_url', 'Unknown Source')
            heading = meta.get('heading', 'General Info')
            
            formatted_results.append(f"--- DOCUMENT ---\nHeading: {heading}\nSource: {source}\n\n{content}\n")
            
        return "\n\n".join(formatted_results)
        
    except Exception as e:
        logger.error("bedrock_retrieval_failed", error=str(e))
        return f"Error searching manuals: {str(e)}"


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
        role_policy = NON_UNDERWRITER_POLICY if role_key != "underwriter" else ""
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
            # We wrap it in a thread to keep the loop free if needed, but since it's one-at-a-time it's fine
            response = agent(query)
            answer = str(response)
            
            # Save assistant response
            self.session_manager.add_message(session_id, "assistant", answer)
            
            # 1. Extract Follow-up Questions
            follow_up_questions = []
            fu_marker = "**You might also want to ask:**"
            if fu_marker in answer:
                parts = answer.split(fu_marker)
                answer = parts[0].strip()
                fu_text = parts[1]
                matches = re.findall(r"\d+\.\s*(.+)", fu_text)
                follow_up_questions = [m.strip() for m in matches if m.strip()][:3]

            # 2. Extract Sources
            found_urls = re.findall(r"(https?://[^\s\)\n<>]+)", answer)
            seen = set()
            sources = [x.strip(".,;:?!") for x in found_urls if not (x in seen or seen.add(x))]

            if role_key != "underwriter":
                answer = sanitize_non_underwriter_output(answer)
                sources = []

            # Final yield
            yield answer, sources, follow_up_questions
            
        except Exception as e:
            logger.error("query_failed", session_id=session_id, error=str(e))
            yield f"Error: {str(e)}", [], []
