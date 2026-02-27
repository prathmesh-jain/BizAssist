import logging
import re
import json

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from app.agents.state import AgentState
from app.config import get_settings
from app.services.llm_service import get_llm
from app.services.rag_service import retrieve, retrieve_top_filenames

logger = logging.getLogger(__name__)
settings = get_settings()

ANALYST_SYSTEM = """
You are a senior financial analyst agent inside BizAssist.

Your role is to help business owners understand their finances using all available internal data sources.

You are proactive, structured, and hypothesis-driven.

━━━━━━━━━
AVAILABLE DATA SOURCES
━━━━━━━━━

You may access:

1. Google Sheets (read-only)
2. Uploaded documents and invoices (via retrieval)

The user may not know where their data is stored. Your job is to figure this out.

━━━━━━━━━
CORE WORKFLOW
━━━━━━━━━

Always follow this reasoning process:

STEP 1 — Understand intent  
Classify the user's request:
- Expense analysis
- Profitability
- Cash flow
- Vendor or category analysis
- Trends and forecasting
- Financial health

STEP 2 — Infer where the data likely exists  
Use business reasoning:
- Expenses → Sheets, invoices
- Revenue → Sheets
- Vendors → invoices or sheets
- Reports → uploaded docs

STEP 3 — Check available sources  
If sheet metadata or document context is available, use it to decide.

STEP 4 — Retrieve data using tools  
Use tools proactively before asking the user.

STEP 5 — Only ask the user if absolutely necessary  
Examples:
- Multiple possible sources
- No relevant data found

━━━━━━━━━
TOOL USAGE RULES
━━━━━━━━━

Use tools strategically:

• Use rag_retrieve when:
  - Searching invoices
  - Looking for uploaded reports
  - Finding financial documents

• Use Google Sheets tools when:
  - The data likely lives in spreadsheets
  - You want structured numerical analysis

Start by exploring metadata (tabs, headers) before reading full ranges.

Never use write tools.

━━━━━━━━━
GROUNDING AND SAFETY
━━━━━━━━━

- Never invent numbers.
- Clearly state assumptions if data is partial.
- Explain where the data came from.
- If no data is found, suggest next steps.

━━━━━━━━━
OUTPUT STYLE
━━━━━━━━━

Your response must be:

• Structured  
• Actionable  
• Business-focused  

Include:

1. Key findings
2. Trends
3. Risks or inefficiencies
4. Recommendations

Format all numbers with commas and 2 decimal places.

━━━━━━━━━
PROACTIVE BEHAVIOR
━━━━━━━━━

You should:
- Explore before asking
- Suggest deeper analysis
- Identify anomalies
- Highlight cost-saving opportunities

If useful, suggest connecting more data sources.

You are not just answering questions — you are helping run the business.
Sheets Context:
{sheets_context}

Documents Context (Retrieved from uploaded documents):
{rag_hint_context}
"""

ANALYST_NO_DATA = """
I looked at your financial records but {reason}

To analyse your data, you can:
- **Connect Google Sheets** in Settings so I can read your spreadsheet
- **Provide a Google Sheets ID** (the long ID from your spreadsheet URL)
- **Upload relevant documents** and ask me to analyze them
"""


def _pick_readonly_sheets_tools(tools: list) -> list:
    allowed = {
        "sheets_list_tabs",
        "sheets_read_range",
        "sheets_get_headers",
        "sheets_get_metadata",
    }
    out = []
    for t in tools or []:
        name = getattr(t, "name", None)
        if name in allowed:
            out.append(t)
    return out


async def analyst_node(state: AgentState) -> dict:
    """
    Financial analytics agent.

    Uses tool access to:
    - read Google Sheets (read-only)
    - retrieve uploaded-document context via RAG
    """
    last_user_msg = next((m.content for m in reversed(state["messages"]) if m.type == "human"), "")

    from app.tools.google_sheets_tools import get_sheets_tools
    from app.services.google_sheets_service import get_default_spreadsheet_id
    from app.services.google_sheets_service import get_spreadsheet_tabs_with_headers

    @tool("rag_retrieve")
    async def rag_retrieve(query: str, k: int = 5) -> dict:
        """Retrieve relevant passages from the user's uploaded documents (RAG)."""
        ctx = await retrieve(query=query, user_id=state["user_id"], k=int(k or 5))
        return {"ok": True, "query": query, "k": int(k or 5), "context": ctx}

    sheets_tools = _pick_readonly_sheets_tools(
        get_sheets_tools(user_id=state["user_id"], chat_id=state.get("chat_id"))
    )
    tools = [rag_retrieve] + sheets_tools
    tool_by_name = {t.name: t for t in tools}

    sheets_context = ""
    rag_hint_context = ""
    try:
        default_sid = await get_default_spreadsheet_id(state["user_id"])
    except Exception:
        default_sid = None

    # Lightweight relevance hint: which uploaded docs look most related to the query?
    try:
        top_files = await retrieve_top_filenames(query=last_user_msg, user_id=state["user_id"], k=3)
    except Exception:
        top_files = []

    if top_files:
        rag_hint_context = "\n\nRAG RELEVANCE HINT:\nLikely relevant uploaded documents:\n" + "\n".join(
            [f"- {fn}" for fn in top_files[:3]]
        )
        rag_hint_context += "\nIf the user is asking about document contents or vendors/invoices, call rag_retrieve first."

    if default_sid:
        try:
            ctx = await get_spreadsheet_tabs_with_headers(user_id=state["user_id"], spreadsheet_id=default_sid)
        except Exception:
            ctx = {}

        items = ctx.get("items") if isinstance(ctx, dict) else None
        if items and isinstance(items, list):
            lines: list[str] = []
            for i, it in enumerate(items, start=1):
                if not isinstance(it, dict):
                    continue
                sheet = (it.get("sheet") or "").strip()
                if not sheet:
                    continue
                headers = it.get("headers") if isinstance(it.get("headers"), list) else []
                headers = [str(h).strip() for h in headers if str(h).strip()]
                if headers:
                    lines.append(f"{i}. {sheet} ({', '.join(headers)})")
                else:
                    lines.append(f"{i}. {sheet}")

            if lines:
                sheets_context = "\n\nAVAILABLE SHEETS:\n" + "\n".join(lines)
    system_prompt = ANALYST_SYSTEM.format(sheets_context=sheets_context,rag_hint_context=rag_hint_context)
    system_prompt += (
        "\n\nYou have tool access. Use it when needed:\n"
        "- Use rag_retrieve to pull relevant passages from uploaded documents.\n"
        "- Use sheets_list_tabs/sheets_get_headers/sheets_read_range to read the user's Google Sheets.\n"
        "Do NOT use any write operations. If you cannot access any data sources, explain what is missing."
        "Confirm from user from where they want the data to be analyzed from sheets or from documents retrieved from rag, and if sheets then which sheet"
    )

    llm = get_llm(temperature=0.2, streaming=False)
    llm_with_tools = llm.bind_tools(tools)
    messages_for_tools = [SystemMessage(content=system_prompt), HumanMessage(content=last_user_msg)]

    final_text = ""
    max_rounds = 10
    tool_calls_made: list[str] = []

    for i in range(max_rounds):
        response = await llm_with_tools.ainvoke(messages_for_tools)
        messages_for_tools.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            final_text = (response.content or "").strip()
            break

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args") or {}
            tc_id = tc.get("id")

            tool_obj = tool_by_name.get(name)
            if not tool_obj:
                messages_for_tools.append(
                    ToolMessage(content=json.dumps({"ok": False, "error": f"Unknown tool: {name}"}), tool_call_id=tc_id)
                )
                continue

            try:
                result = await tool_obj.ainvoke(args)
            except Exception as e:
                result = {"ok": False, "error": str(e)}

            tool_calls_made.append(name)
            messages_for_tools.append(ToolMessage(content=json.dumps(result), tool_call_id=tc_id))

        if i == max_rounds - 1 and not final_text:
            final_text = (
                "I reached the tool-call limit for this step before producing a final response. "
                "Please reply with 'continue' or specify the exact analysis you want."
            )

    if not final_text:
        final_text = ANALYST_NO_DATA.format(reason="I couldn't access any relevant data sources yet.")

    return {
        "messages": [AIMessage(content=final_text)],
        "tool_calls_made": state.get("tool_calls_made", []) + tool_calls_made,
    }
