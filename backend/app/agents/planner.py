import logging
import json
from langchain_core.messages import SystemMessage
from app.agents.state import AgentState
from app.config import get_settings
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)
settings = get_settings()

INTENT_SYSTEM = """
You are the intent classifier for BizAssist, an AI assistant for business operations.

Your job is to classify the USER'S PRIMARY GOAL, not the tools or data sources.

Choose exactly ONE intent from:

conversation  
- General business questions, drafting, explanations, strategy, marketing, research.

financial_analysis  
- The user wants insights, numbers, trends, summaries, or reports based on their business data.
- This may require internal structured data, spreadsheets, or uploaded documents.

document_query  
- The user wants to search, summarize, or ask questions about specific uploaded files, contracts, reports, or documents.These files are not the files inside the chat. Document files are uploaded by the user in the dashboard. Which are chunked and embedded in the vector database. If user asks for something related to such documents, choose this intent.

spreadsheet_crud
- The user explicitly wants to view or modify or manage spreadsheets:
  creating sheets, adding rows, updating cells, formatting, renaming tabs, etc.
- any query related to google sheets should go to this intent.

Important rules:
- If the user asks for analysis or insights, choose financial_analysis even if spreadsheets or documents are mentioned.
- Do NOT select spreadsheet_crud unless the user clearly wants to modify sheet structure or rows.
- Data sources like Google Sheets or documents are NOT intents.
- Choose document_query only when the question is primarily about the contents of uploaded files.
- Default to conversation if unsure.

Respond with ONLY one word:
conversation | financial_analysis | document_query | spreadsheet_crud
"""


def _strip_attachments_context(text: str) -> tuple[str, bool]:
    """Remove the runtime-only ATTACHMENTS_CONTEXT block from the user message.

    The chat service appends a JSON block for the agent, but the planner should NOT
    use it for intent routing; intent must be derived from the user's instruction.
    """
    t = (text or "")
    marker = "ATTACHMENTS_CONTEXT:"
    if marker not in t:
        return t, False
    before = t.split(marker, 1)[0]
    return before.strip(), True


def _describe_attachments_from_context(text: str) -> str:
    t = (text or "")
    marker = "ATTACHMENTS_CONTEXT:"
    if marker not in t:
        return "User uploaded files."

    raw = t.split(marker, 1)[1].strip()
    try:
        payload = json.loads(raw)
        attachments = payload.get("attachments") if isinstance(payload, dict) else None
        if not isinstance(attachments, list) or not attachments:
            return "User uploaded files."
    except Exception:
        return "User uploaded files."

    has_pdf = False
    has_image = False
    has_other = False
    for a in attachments:
        if not isinstance(a, dict):
            continue
        ct = (a.get("content_type") or "").lower()
        if ct == "application/pdf":
            has_pdf = True
        elif ct.startswith("image/"):
            has_image = True
        else:
            has_other = True

    kinds: list[str] = []
    if has_image:
        kinds.append("image")
    if has_pdf:
        kinds.append("PDF")
    if has_other or not kinds:
        kinds.append("file")

    if len(kinds) == 1:
        return f"User uploaded a {kinds[0]}."
    return "User uploaded " + " and ".join(kinds) + "."


def _build_recent_messages_context(messages: list, max_messages: int = 3) -> str:
    if not messages:
        return ""

    selected = messages[-max(1, max_messages):]
    lines: list[str] = []
    for m in selected:
        role = "User" if getattr(m, "type", "") == "human" else "Assistant"
        content = getattr(m, "content", "")

        if role == "User" and isinstance(content, str):
            cleaned, had_ctx = _strip_attachments_context(content)
            if had_ctx and cleaned.strip().lower() in {"", "user uploaded files.", "uploaded files."}:
                cleaned = _describe_attachments_from_context(content)
            content = cleaned

        if not isinstance(content, str):
            content = str(content)
        content = content.strip()
        if not content:
            continue
        lines.append(f"{role}: {content}")

    return "\n".join(lines).strip()


async def planner_node(state: AgentState) -> dict:
    """
    Classify the user's intent and set routing for the execution agent.
    Uses the last 2-3 messages for better context (but still routes based on the user's goal).
    """
    msgs = state.get("messages") or []
    last_user_msg = next((m.content for m in reversed(msgs) if m.type == "human"), "")
    if not last_user_msg and not msgs:
        return {"intent": "conversation", "next": "conversation"}

    cleaned_last_user_msg, had_attachments_context = _strip_attachments_context(last_user_msg)
    file_only_upload = had_attachments_context and cleaned_last_user_msg.strip().lower() in {
        "",
        "user uploaded files.",
        "uploaded files.",
    }

    # If the user uploaded a file without text but there is prior context, keep that
    # context and turn the upload into an explicit message so intent classification is clearer.
    if file_only_upload:
        prior_human_exists = any(m.type == "human" and m.content for m in msgs[:-1])
        if not prior_human_exists:
            logger.info(
                f"Planner: defaulting to chat (file upload without instruction) for user {state['user_id']}"
            )
            return {"intent": "conversation", "next": "conversation"}

        synthesized = _describe_attachments_from_context(last_user_msg)
        context_text = _build_recent_messages_context(msgs[:-1], max_messages=3)
        cleaned_msg = (context_text + "\n" + f"User: {synthesized}").strip() if context_text else synthesized
    else:
        # Normal case: use a short recent transcript including the current user message.
        context_text = _build_recent_messages_context(msgs, max_messages=3)
        cleaned_msg = context_text or cleaned_last_user_msg

    llm = get_llm(
        model_name=settings.fast_model,
        temperature=0,
    )
    response = await llm.ainvoke([
        SystemMessage(content=INTENT_SYSTEM),
        {"role": "user", "content": cleaned_msg},
    ])

    intent = response.content.strip().lower()
    if intent not in {"conversation", "spreadsheet_crud", "financial_analysis", "document_query"}:
        intent = "conversation"

    logger.info(f"Planner: intent='{intent}' for user {state['user_id']}")
    return {"intent": intent, "next": intent}
