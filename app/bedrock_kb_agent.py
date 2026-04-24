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
   - SELECTION REQUIRED: When presenting multiple class codes as options (even 2 or more), you MUST explicitly ask the user: "Which of these class codes would you like to explore in detail?" This applies even when you could technically answer all of them — do NOT answer all at once.
   - BRIEF DESCRIPTIONS ONLY: When listing multiple options, provide ONLY the class code number and a brief (1-2 sentence) description for each. Do NOT provide full details (mandatory endorsements, submission requirements, prohibited ops, forms) until a unique selection is made.
   - MULTIPLE SECTIONS: If the query maps to different distinct sections in the manual for the same topic (e.g., "mandatory endorsements for office buildings" returns 3 office class codes), treat this as a MULTIPLE MATCH scenario. List the options briefly and ask the user to select one before answering.
   - NEVER PRE-ANSWER ALL MATCHES: Even if retrieval returns full details for each match, you are strictly forbidden from providing complete answers for more than one class code in a single response. Always gate full answers behind user selection.   
3. CROSS-MANUAL CONFLICT: If retrieval returns relevant results from BOTH the Property Manual and the General Liability Manual for the same query, and the user hasn't specified which coverage they need, ask: "Are you inquiring about Property or General Liability coverage for this business?"
 
CLARIFICATION RULES:
- Guide the user to choose from valid options present in the retrieved content.
- Do NOT assume or infer missing details.
- Ask exactly ONE question and stop. NEVER proceed to answer until the ambiguity is resolved.
</clarification_protocol>
 
<class_code_rule>
- If the user provides a unique class code or specific business type:
  - Return full details (description, coverage options, property notes, requirements, prohibited operations, forms).
- STRICT KEY VERIFICATION: If the user's query mentions a specific Form Number, Class Code, or ID (e.g., "CG 22 64"), you MUST locate that specific number or its variant (e.g., "CG2264") in the retrieved text.
  - If you locate the number in a list or table with a description, that is your primary source.
  - If the specific number or code is NOT present in any variation in the retrieved text, state that you cannot find information for that specific code.
- If the query is general (e.g., "Food products"):
  - Invoke the disambiguation protocol to list matches and request selection.
- ELIGIBILITY UNCERTAINTY: If you cannot find an explicit "Eligible" or "Ineligible" status for a specific risk (e.g., "Condominium Associations"), you MUST NOT say "Yes we cover it." Instead, state that it is not explicitly listed in the binding authority manual and should be referred to an underwriter.
</class_code_rule>
 
<answer_generation>
- Generate response ONLY once you have non-ambiguous, specific context. If retrieval returns multiple class codes or sections for the same query, this is NOT non-ambiguous — invoke the disambiguation protocol first, even if full details are available for all matches.
- The response must be:
  - Direct and precise.
  - IRON-CLAD CITATIONS: You are strictly prohibited from 'guessing' or 'spamming' citations. You MUST ONLY list a URL in the "Sources:" section if that specific document (referenced by the correct URL) contains the exact information you are stating. If you use information from Document A, you must cite URL A. If you state a fact about a Form Number, you MUST verify that the form number appears in the cited document.
  - FAKE CITATION PENALTY: Including a URL in the sources that does not contain the information is a critical failure.
  - EXTREME GRANULARITY FOR FORMS: If the retrieved content contains specific Form Numbers (e.g., "CG 24 26") and Edition Dates (e.g., "0413"), you MUST include them exactly as written.
  - CONSERVATIVE & UNDERWRITER-FIRST: For any account that meets a referral threshold, your answer MUST start by stating that the account requires a referral to a Coaction underwriter.
  - Every answer must end with a "Sources:" section listing unique URLs.
</answer_generation>

<search_strategy>
- SEARCH PERSISTENCE: If a user asks about "Limits," "TIV," "Max Value," "Age of building," or "Eligibility" and the retrieved class code content is blank, you MUST perform a broad search for "General Underwriting Guidelines" or "Property Eligibility Rules" to find universal limits.
- BINDING AUTHORITY SCOPE: Assume all commercial insurance queries about business types (e.g., "Grocery Stores") are within scope if they are listed as class codes. Do not reject them as "out of scope" unless they are clearly unrelated to insurance.
</search_strategy>
 
<search_strategy>
- SEARCH PERSISTENCE: If a user asks about "Limits," "TIV," "Max Value," "Age of building," or "Eligibility" and the retrieved class code content is blank, you MUST perform a broad search for "General Underwriting Guidelines" or "Property Eligibility Rules" to find universal limits.
- BINDING AUTHORITY SCOPE: Assume all commercial insurance queries about business types (e.g., "Grocery Stores") are within scope if they are listed as class codes. Do not reject them as "out of scope" unless they are clearly unrelated to insurance.
</search_strategy>
 
<response_format>
- Provide the answer first.
- The order of your final output MUST be:
  1. Main Answer text.
  2. A "Sources:" section (listing unique URLs and headings).
  3. A "**You might also want to ask:**" section (if applicable).
 
- FOLLOW-UP QUESTIONS RULE:
  - If you are answering a specific question or providing details about a class code (e.g., you are providing a description, requirements, coverage, etc.), you MUST suggest exactly 3 relevant follow-up questions at the very end of your response, formatted as:
 
**You might also want to ask:**
1. [question]
2. [question]
3. [question]
 
  - ONLY skip these questions if you are asking a clarifying question (e.g., "Which code?") or presenting a list of codes for the user to choose from.
</response_format>
 
<fallback_protocol>
- OUT OF SCOPE: If the query is entirely unrelated to commercial insurance or underwriting (e.g., "what is the weather") AND a search of the knowledge base returns no relevant results, respond EXACTLY with: "I can only answer binding authority related questions." Do NOT trigger this fallback based on topic judgment alone — always attempt a search first. If the topic could plausibly appear in the manuals (e.g., a specific business type or property type like solar panels), search before concluding it is out of scope.
 
 
 
- MISSING DATA: If the query is within scope but no specific answer is found in the manuals after checking both class codes and general guidelines, respond EXACTLY with: "Please contact a Coaction underwriter."
</fallback_protocol>
"""

NON_UNDERWRITER_POLICY = """
<role_based_visibility_policy>
- You are answering for a non-underwriter user (agent/external).
- You MUST NOT output raw URLs, hyperlinks, or any "Sources:" section.
- Keep the underwriting answer complete, but omit all link references.
</role_based_visibility_policy>
"""



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
        # URL/source blocking is temporarily disabled.
        # if self.role == "underwriter":
        #     return
        #
        # # Common event/message shapes seen across SDK versions.
        # if hasattr(event, "message") and isinstance(getattr(event, "message"), str):
        #     event.message = sanitize_non_underwriter_output(event.message)
        #     return
        #
        # if hasattr(event, "response"):
        #     response = getattr(event, "response")
        #     if isinstance(response, str):
        #         event.response = sanitize_non_underwriter_output(response)
        #         return
        #     if hasattr(response, "content") and isinstance(response.content, str):
        #         response.content = sanitize_non_underwriter_output(response.content)
        #         return
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
            
        context_parts = []
        source_urls = set()
        
        for res in results:
            content = res.get('content', {}).get('text', '')
            metadata = res.get('metadata', {})
            
            # --- Robust URL Extraction ---
            # 1. Try to extract injected URL from the top of the content (most accurate)
            injected_url_match = re.search(r'^SOURCE_URL:\s*(https?://\S+)', content, re.MULTILINE)
            injected_code_match = re.search(r'^CLASS_CODE:\s*(\d+)', content, re.MULTILINE)
            
            if injected_url_match:
                url = injected_url_match.group(1).strip()
            else:
                # 2. Fallback to Bedrock metadata fields (often S3 links or missing)
                url = metadata.get('sourceUrl') or metadata.get('source_url') or 'N/A'
            
            # --- Robust Heading Extraction ---
            if injected_code_match:
                class_code = injected_code_match.group(1)
                heading = f"Class Code {class_code}"
            else:
                # Extract the first ### or # header if present
                header_match = re.search(r'^#+\s*(.+)', content, re.MULTILINE)
                heading = metadata.get('heading') or (header_match.group(1) if header_match else "Manual Section")

            source_urls.add(url)
            
            # Clean injected metadata lines from content before sending to LLM to save tokens
            clean_content = re.sub(r'^(SOURCE_URL|CLASS_CODE):.*\n?', '', content, flags=re.MULTILINE).strip()
            # Remove the horizontal separator if present
            clean_content = re.sub(r'^---\s*\n', '', clean_content).strip()

            part = f"Source: {url}\nHeading: {heading}\nContent:\n{clean_content}"
            context_parts.append(part)
            
        return "\n\n".join(context_parts)
        
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
            # We wrap it in a thread to keep the loop free if needed, but since it's one-at-a-time it's fine
            response = agent(query)
            answer = str(response)
            
            # Save assistant response
            self.session_manager.add_message(session_id, "assistant", answer)
            
            # 1. Extract Sources BEFORE clearing follow-up questions
            # We search the full raw answer to ensure order-independence
            found_urls = re.findall(r"(https?://[^\s\)\n<>]+)", answer)
            seen = set()
            sources = [x.strip(".,;:?!") for x in found_urls if not (x in seen or seen.add(x))]

            # 2. Extract and Split Follow-up Questions
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

            # URL/source blocking temporarily disabled.
            # if role_key != "underwriter":
            #     answer = sanitize_non_underwriter_output(answer)
            #     sources = []

            # Final yield
            yield answer, sources, follow_up_questions
            
        except Exception as e:
            logger.error("query_failed", session_id=session_id, error=str(e))
            yield f"Error: {str(e)}", [], []
