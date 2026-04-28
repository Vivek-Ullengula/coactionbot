import re
from app.core.logger import get_logger

logger = get_logger(__name__)

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
