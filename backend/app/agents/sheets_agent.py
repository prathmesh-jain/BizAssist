import json
import logging
import re

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.state import AgentState
from app.services.llm_service import get_llm

logger = logging.getLogger(__name__)

SHEETS_SYSTEM = """\
You are BizAssist Sheets, a specialist agent for Google Sheets access and editing.

Goal: execute Google Sheets tasks correctly and with minimal user friction.

Rules:
1) Default spreadsheet:
   - If a default spreadsheet is connected, use it automatically.
   - Never ask the user for spreadsheet ID unless there is no default.

1b) Sheet tab selection:
   - Do NOT assume a default tab name.
   - If the user didn't specify a sheet/tab name, call sheets_list_tabs and ask the user to pick
     one of the available tabs OR ask if they want to create a new tab.

2) Column grounding:
   - Before claiming a column is missing or choosing column letters, call sheets_get_headers.
   - Use the returned header_map to select the correct columns.

3) Safety:
   - You have access to both read and write tools.
   - Never guess sheet/tab names; list tabs if needed.
   - Never guess columns; fetch headers first if mapping is required.

3b) Error truthfulness:
   - Only say a tool failed if you actually called a tool and it returned ok=false (or returned an error).
   - If a tool failed, include the exact error message.

4) Reading uploaded files (attachments):
   - If the user is asking to add invoices from an uploaded PDF/image/text file, do NOT ask the user to paste data.
   - Instead, call chat_list_attachments to locate the file, then call chat_read_attachment_text (for PDFs/text) to read it.
   - The system stores extracted text artifacts as text/plain. You MUST page through the attachment text using
     chat_read_attachment_text(start_char=...) until has_more=false so you capture ALL invoices.
   - Do NOT stop after the first chunk if the user asked to add all invoices.

5) Writing extracted rows:
   - Do NOT write placeholders like "sample text extracted".
   - Create a tab if requested.
   - If creating a new table, write a header row first (via sheets_update_values on row 1), then append rows.
   - If multiple invoices are present, append one row per invoice (bulk append preferred).

6) Avoid duplicates:
   - Before appending, call sheets_read_range on the target tab (e.g. "Invoices!A:F") to fetch existing rows.
   - Compute a stable key per row (use a concatenation of key fields such as invoice number + vendor + date + amount).
   - Only append rows whose key is not already present.

Respond concisely and confirm what was changed.
"""


async def sheets_node(state: AgentState) -> dict:
    from app.agents.memory import prepare_messages_for_llm
    from app.services.google_sheets_service import get_default_spreadsheet_id
    from app.services.google_sheets_service import get_spreadsheet_tabs_with_headers

    messages = prepare_messages_for_llm(
        state["messages"],
        state.get("message_summary", ""),
    )

    last_user_msg = next((m.content for m in reversed(state["messages"]) if m.type == "human"), "")
    chat_id = state.get("chat_id")

    # Provide default spreadsheet status as additional system context (only in sheets agent).
    default_sid = await get_default_spreadsheet_id(state["user_id"])
    spreadsheet_info = ""
    if default_sid:
        spreadsheet_info = (
            f"\n\nDEFAULT SPREADSHEET: A default Google Spreadsheet is connected (ID: {default_sid}). "
            "Use it automatically unless the user specifies otherwise."
        )

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
                spreadsheet_info += "\n\nAVAILABLE SHEETS:\n" + "\n".join(lines)
    else:
        spreadsheet_info = (
            "\n\nNO DEFAULT SPREADSHEET: The user hasn't connected Google Sheets yet. "
            "Ask them to connect in Settings if they want Sheets features."
        )

    llm_messages = [SystemMessage(content=SHEETS_SYSTEM + spreadsheet_info)] + messages[:-1]
    llm_messages.append(HumanMessage(content=last_user_msg))

    llm = get_llm(temperature=0.2, streaming=False)

    from app.tools.google_sheets_tools import get_sheets_tools
    from app.tools.chat_attachments_tools import get_chat_attachments_tools

    tools = (
        get_sheets_tools(user_id=state["user_id"], chat_id=chat_id)
        + get_chat_attachments_tools(user_id=state["user_id"], chat_id=chat_id)
    )

    # Schema-driven tool loop: bind available tools and let the model choose.
    llm_with_tools = llm.bind_tools(tools)
    tool_by_name = {t.name: t for t in tools}

    messages_for_tools = list(llm_messages)
    final_text = ""
    max_rounds = 10

    for i in range(max_rounds):
        response = await llm_with_tools.ainvoke(messages_for_tools)
        messages_for_tools.append(response)

        tool_calls = getattr(response, "tool_calls", None) or []
        if not tool_calls:
            final_text = response.content or ""
            break

        for tc in tool_calls:
            name = tc.get("name")
            args = tc.get("args") or {}
            tc_id = tc.get("id")

            logger.info(f"Sheets tool_call: {name} args_keys={list(args.keys()) if isinstance(args, dict) else type(args).__name__}")

            tool = tool_by_name.get(name)
            if not tool:
                messages_for_tools.append(
                    ToolMessage(
                        content=json.dumps({"ok": False, "error": f"Unknown tool: {name}"}),
                        tool_call_id=tc_id,
                    )
                )
                continue

            try:
                result = await tool.ainvoke(args)
            except Exception as e:
                result = {"ok": False, "error": str(e)}

            if isinstance(result, dict):
                logger.info(f"Sheets tool_result: {name} ok={result.get('ok', True)}")
                if result.get("ok") is False:
                    logger.info(f"Sheets tool_error: {name} error={result.get('error')}")

            messages_for_tools.append(ToolMessage(content=json.dumps(result), tool_call_id=tc_id))

        if i == max_rounds - 1:
            final_text = (
                "I reached the tool-call limit for this step before producing a final response. "
                "Please reply with 'continue' or specify the exact next change."
            )

    if not (final_text or "").strip():
        final_text = "I couldn't generate a response for that step. Please try again."

    return {"messages": [AIMessage(content=final_text)]}
