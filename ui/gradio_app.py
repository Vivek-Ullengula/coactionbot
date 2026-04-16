"""
Gradio UI for Coaction Bot.
Connects to the FastAPI backend for RAG queries against Bedrock Knowledge Base.
Displays follow-up questions as clickable buttons and sources as links.

Compatible with Gradio 6.x.
"""
import gradio as gr
import requests
import os
import uuid

API_BASE = os.getenv("API_BASE_URL", "http://localhost:8000/api/v1")

# -- Session management -------------------------------------------------------

def create_session() -> str:
    """Create a new backend session and return session_id."""
    try:
        resp = requests.post(f"{API_BASE}/session/create", json={}, timeout=5)
        resp.raise_for_status()
        return resp.json().get("session_id", str(uuid.uuid4()))
    except Exception:
        return str(uuid.uuid4())


def check_api_health() -> str:
    """Check backend API health."""
    try:
        resp = requests.get(API_BASE.replace("/api/v1", "/health"), timeout=3)
        if resp.ok:
            return "🟢 API Online"
        return "🟡 API Degraded"
    except Exception:
        return "🔴 API Unreachable"


# -- Query backend ------------------------------------------------------------

def query_backend(message: str, session_id: str, top_k: int = 5) -> dict:
    """Send query to FastAPI backend and return structured response."""
    try:
        resp = requests.post(
            f"{API_BASE}/query",
            json={
                "query": message,
                "top_k": top_k,
                "session_id": session_id,
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()
        return {
            "answer": data.get("answer", "No answer received."),
            "sources": data.get("sources", []),
            "follow_up_questions": data.get("follow_up_questions", []),
            "session_id": data.get("session_id", session_id),
        }
    except requests.exceptions.Timeout:
        return {
            "answer": "The request timed out. Please try again.",
            "sources": [],
            "follow_up_questions": [],
            "session_id": session_id,
        }
    except Exception as e:
        return {
            "answer": f"Error communicating with backend: {str(e)}",
            "sources": [],
            "follow_up_questions": [],
            "session_id": session_id,
        }


# -- Format response with sources ---------------------------------------------

def format_response_with_sources(answer: str, sources: list[str]) -> str:
    """Format the answer with clickable numbered sources below."""
    formatted = answer.strip()

    if sources:
        formatted += "\n\n---\n**Sources:** &nbsp; "
        source_links = []
        for i, url in enumerate(sources, 1):
            source_links.append(f"[[{i}]]({url})")
        formatted += " &nbsp; ".join(source_links)

    return formatted


# -- Chat handler --------------------------------------------------------------

def chat_handler(
    message: str,
    history: list[dict],
    session_id: str,
    top_k: int,
):
    """
    Main chat handler. Sends the message to the backend, gets structured
    response, and returns the formatted answer with sources and follow-ups.
    """
    if not message or not message.strip():
        yield (
            history or [],
            session_id,
            gr.update(visible=False),
            gr.update(visible=False),
            gr.update(visible=False),
        )
        return

    # Create session on first message
    if not session_id:
        session_id = create_session()

    # Build chat history with user message immediately
    history = history or []
    history.append({"role": "user", "content": message})
    
    # Yield history immediately to show user message
    yield history, session_id, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)

    # Add temporary "thinking" message
    thinking_html = """
    <div class="thinking-dots">
        <span class="dot"></span><span class="dot"></span><span class="dot"></span>
    </div>
    """
    history.append({"role": "assistant", "content": thinking_html})
    yield history, session_id, gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)

    # Query backend
    result = query_backend(message, session_id, top_k)
    answer = result["answer"]
    sources = result["sources"]
    follow_ups = result["follow_up_questions"]
    session_id = result["session_id"]

    # Format response with sources
    formatted_answer = format_response_with_sources(answer, sources)

    # Replace "thinking" message with actual response
    history[-1] = {"role": "assistant", "content": formatted_answer}

    # Build follow-up button updates
    fu1 = (
        gr.update(value=follow_ups[0], visible=True)
        if len(follow_ups) > 0
        else gr.update(visible=False)
    )
    fu2 = (
        gr.update(value=follow_ups[1], visible=True)
        if len(follow_ups) > 1
        else gr.update(visible=False)
    )
    fu3 = (
        gr.update(value=follow_ups[2], visible=True)
        if len(follow_ups) > 2
        else gr.update(visible=False)
    )

    yield history, session_id, fu1, fu2, fu3


def follow_up_click(
    fu_text: str,
    history: list[dict],
    session_id: str,
    top_k: int,
):
    """Handle follow-up button clicks by sending the question as a new message."""
    yield from chat_handler(fu_text, history, session_id, top_k)


def clear_chat():
    """Clear conversation and reset state."""
    return [], "", gr.update(visible=False), gr.update(visible=False), gr.update(visible=False)


# -- Custom CSS ----------------------------------------------------------------

CUSTOM_CSS = """
/* -- Global -- */
:root {
    --primary: #f97316;
    --primary-hover: #ea580c;
    --bg-light: #f9fafb;
    --bg-card: #ffffff;
    --bg-input: #ffffff;
    --text-primary: #111827;
    --text-secondary: #4b5563;
    --border: #e5e7eb;
    --accent-glow: rgba(249, 115, 22, 0.05);
}

.gradio-container {
    background: var(--bg-light) !important;
    max-width: 1200px !important;
    margin: 0 auto !important;
    font-family: 'Inter', 'Segoe UI', system-ui, -apple-system, sans-serif !important;
}

/* -- Header -- */
.app-header {
    text-align: center;
    padding: 2.5rem 1rem 1.5rem;
    background: #ffffff;
    border-bottom: 1px solid var(--border);
    border-radius: 16px 16px 0 0;
    margin-bottom: 0;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}
.app-header h1 {
    font-size: 2rem;
    font-weight: 800;
    color: var(--primary);
    margin: 0 0 0.5rem 0;
    letter-spacing: -0.025em;
}
.app-header p {
    color: var(--text-secondary);
    font-size: 0.95rem;
    margin: 0;
}

/* -- Chatbot area -- */
.chatbot-container {
    border: 1px solid var(--border) !important;
    border-radius: 0 0 16px 16px !important;
    background: #ffffff !important;
    min-height: 520px !important;
    box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.05);
}

/* -- Follow-up buttons -- */
.follow-up-container {
    display: flex;
    gap: 0.75rem;
    padding: 1rem 0;
    flex-wrap: wrap;
    justify-content: center;
}
.follow-up-btn {
    flex: 1;
    min-width: 200px;
    max-width: 380px;
}
.follow-up-btn button {
    width: 100% !important;
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    color: var(--text-primary) !important;
    border-radius: 12px !important;
    padding: 0.75rem 1.25rem !important;
    font-size: 0.875rem !important;
    line-height: 1.5 !important;
    transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1) !important;
    cursor: pointer !important;
    text-align: left !important;
    white-space: normal !important;
    min-height: 50px !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
}
.follow-up-btn button:hover {
    background: var(--bg-light) !important;
    border-color: var(--primary) !important;
    color: var(--primary) !important;
    transform: translateY(-2px);
    box-shadow: 0 4px 12px rgba(0, 0, 0, 0.05) !important;
}

/* -- Input textbox -- */
.input-row textarea {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    color: var(--text-primary) !important;
    font-size: 0.95rem !important;
    padding: 0.875rem 1.25rem !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
}
.input-row textarea:focus {
    border-color: var(--primary) !important;
    box-shadow: 0 0 0 4px var(--accent-glow) !important;
}

/* -- Send button -- */
.send-btn button {
    background: var(--primary) !important;
    color: #ffffff !important;
    border: none !important;
    border-radius: 12px !important;
    padding: 0.875rem 1.75rem !important;
    font-weight: 700 !important;
    transition: all 0.2s ease !important;
}
.send-btn button:hover {
    background: var(--primary-hover) !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1) !important;
}

/* -- Clear button -- */
.clear-btn button {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    color: var(--text-secondary) !important;
    border-radius: 12px !important;
}
.clear-btn button:hover {
    border-color: #ef4444 !important;
    color: #ef4444 !important;
}

/* -- Settings sidebar -- */
.settings-panel {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: 16px !important;
    padding: 1.5rem !important;
    box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
}

/* -- Status badge -- */
.status-badge {
    text-align: center;
    padding: 0.5rem 1rem;
    border-radius: 9999px;
    font-size: 0.8125rem;
    font-weight: 600;
    background: #f3f4f6;
    border: 1px solid var(--border);
    color: var(--text-secondary);
}

/* -- Source links (Clickable Numbers) -- */
.message a {
    color: var(--primary) !important;
    font-weight: 600 !important;
    text-decoration: none !important;
}
.message a:hover {
    text-decoration: underline !important;
}

/* -- Suggestion buttons -- */
.suggestion-card button {
    background: #ffffff !important;
    border: 1px solid var(--border) !important;
    border-radius: 12px !important;
    padding: 1rem !important;
    color: var(--text-primary) !important;
    font-weight: 500 !important;
    box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05) !important;
}
.suggestion-card button:hover {
    border-color: var(--primary) !important;
    background: var(--bg-light) !important;
    transform: translateY(-2px);
}

/* -- Thinking indicator -- */
.thinking-dots {
    display: flex;
    gap: 4px;
}
.dot {
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--primary);
    animation: bounce 1.4s infinite ease-in-out both;
}
.dot:nth-child(2) { animation-delay: 0.2s; }
.dot:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
    0%, 80%, 100% { transform: scale(0); opacity: 0.3; }
    40% { transform: scale(1); opacity: 1; }
}

footer { display: none !important; }
"""

# -- Welcome suggestions ------------------------------------------------------

SUGGESTIONS = [
    ("What is class code 10040?"),
    ("Tell me about binding authority property manual"),
    ("What are the submission requirements for GL?"),
    ("What operations are prohibited?"),
]

# -- Gradio 6 compatible theme ------------------------------------------------

THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.orange,
    secondary_hue=gr.themes.colors.amber,
    neutral_hue=gr.themes.colors.slate,
    font=gr.themes.GoogleFont("Inter"),
).set(
    body_background_fill="#f9fafb",
    body_background_fill_dark="#f9fafb",
    block_background_fill="#ffffff",
    block_background_fill_dark="#ffffff",
    input_background_fill="#ffffff",
    input_background_fill_dark="#ffffff",
    body_text_color="#111827",
    body_text_color_dark="#111827",
    block_label_text_color="#4b5563",
    block_label_text_color_dark="#4b5563",
    border_color_primary="#e5e7eb",
    border_color_primary_dark="#e5e7eb",
)


# -- Build the Gradio app -----------------------------------------------------

def build_app() -> gr.Blocks:
    """Build and return the Gradio Blocks application (Gradio 6 compatible)."""

    with gr.Blocks(title="Coaction Bot") as app:

        # -- State --
        session_state = gr.State("")

        # -- Sidebar for Settings --
        with gr.Sidebar(label="Settings", open=False):
            gr.Markdown("### ⚙️ Underwriting Settings")
            top_k_slider = gr.Slider(
                minimum=1,
                maximum=20,
                value=5,
                step=1,
                label="Results to retrieve",
                info="Number of KB chunks to search",
            )
            gr.Markdown("---")
            kb_id = os.getenv("BEDROCK_KB_ID", "")
            gr.Markdown(
                f"**KB ID:** `{kb_id}`" if kb_id else "**KB ID:** _not set_",
            )
            status_text = check_api_health()
            gr.HTML(f'<div class="status-badge">{status_text}</div>')
            gr.Markdown("---")
            gr.Markdown(
                '<p style="font-size:0.75rem;color:#6b7280;text-align:center;">'
                "Coaction Binding Authority<br>Underwriting Assistant</p>"
            )

        # -- Main Chat Area --
        with gr.Row():
            with gr.Column(scale=1):
                chatbot = gr.Chatbot(
                    label="Chat",
                    height=600,
                    buttons=["copy"],
                    avatar_images=(
                        None, 
                        "https://www.coactionspecialty.com/favicon.ico"
                    ),
                    elem_classes=["chatbot-container"],
                    placeholder=(
                        '<div style="text-align:center; padding: 5rem 1rem; color: #9ca3b8;">'
                        '<p style="font-size:1.5rem; font-weight:600; '
                        "background:linear-gradient(135deg,#f97316,#fbbf24);"
                        "-webkit-background-clip:text;-webkit-text-fill-color:transparent;"
                        'margin-bottom:0.5rem;">How can I help you today?</p>'
                        '<p style="font-size:0.95rem; opacity: 0.8;">Ask me about class codes, '
                        "underwriting guidelines, or coverage details.</p></div>"
                    ),
                )

                # -- Follow-up question buttons --
                gr.HTML(
                    '<div id="fu-label" style="display:none; text-align:center; '
                    'font-size:0.78rem; color:#6b7280; margin-top:0.3rem;">'
                    "Suggested follow-up questions</div>"
                )
                with gr.Row(elem_classes=["follow-up-container"]):
                    fu_btn_1 = gr.Button(
                        visible=False,
                        elem_classes=["follow-up-btn"],
                        size="sm",
                    )
                    fu_btn_2 = gr.Button(
                        visible=False,
                        elem_classes=["follow-up-btn"],
                        size="sm",
                    )
                    fu_btn_3 = gr.Button(
                        visible=False,
                        elem_classes=["follow-up-btn"],
                        size="sm",
                    )

                # -- Input row --
                with gr.Row():
                    msg_input = gr.Textbox(
                        placeholder="Message Coaction Bot...",
                        show_label=False,
                        scale=6,
                        container=False,
                        elem_classes=["input-row"],
                        lines=1,
                        max_lines=4,
                    )
                    send_btn = gr.Button(
                        "Send",
                        scale=1,
                        elem_classes=["send-btn"],
                        variant="primary",
                    )
                    clear_btn = gr.Button(
                        "Clear",
                        scale=1,
                        elem_classes=["clear-btn"],
                    )

                # -- Suggestion cards --
                gr.HTML(
                    '<p style="text-align:center;color:#6b7280;font-size:0.8rem;'
                    'margin-top:0.5rem;">Try one of these questions</p>'
                )
                with gr.Row():
                    sug_btns = []
                    for text in SUGGESTIONS:
                        btn = gr.Button(
                            text,
                            elem_classes=["suggestion-card"],
                            size="sm",
                        )
                        sug_btns.append((btn, text))

        # -- Wire events -------------------------------------------------------

        chat_outputs = [chatbot, session_state, fu_btn_1, fu_btn_2, fu_btn_3]
        chat_inputs = [msg_input, chatbot, session_state, top_k_slider]

        # Send button
        send_btn.click(
            fn=chat_handler,
            inputs=chat_inputs,
            outputs=chat_outputs,
        ).then(fn=lambda: "", outputs=[msg_input])

        # Enter key
        msg_input.submit(
            fn=chat_handler,
            inputs=chat_inputs,
            outputs=chat_outputs,
        ).then(fn=lambda: "", outputs=[msg_input])

        # Follow-up button clicks
        for fu_btn in [fu_btn_1, fu_btn_2, fu_btn_3]:
            fu_btn.click(
                fn=follow_up_click,
                inputs=[fu_btn, chatbot, session_state, top_k_slider],
                outputs=chat_outputs,
            )

        # Suggestion button clicks
        for btn, question_text in sug_btns:
            # Use default argument to capture the closure variable properly
            btn.click(
                fn=lambda q=question_text: q,
                outputs=[msg_input],
            ).then(
                fn=chat_handler,
                inputs=chat_inputs,
                outputs=chat_outputs,
            ).then(fn=lambda: "", outputs=[msg_input])

        # Clear chat
        clear_btn.click(fn=clear_chat, outputs=chat_outputs)

    return app


# -- Launch --------------------------------------------------------------------

if __name__ == "__main__":
    demo = build_app()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
        css=CUSTOM_CSS,
        theme=THEME,
    )
