import logging
from langchain_core.messages import SystemMessage, AIMessage, ToolMessage, HumanMessage
from app.agents.state import AgentState
from app.services.llm_service import get_llm
from app.agents.tooling import build_tools_for_agent

logger = logging.getLogger(__name__)


def _clean_message_history(messages: list) -> list:
    """
    Ensure the message history is valid for OpenAI.
    Specifically: an AIMessage with tool_calls must be followed by ToolMessages.
    If a tool call is missing its response, we remove the tool call from the AIMessage.
    """
    clean_msgs = []
    for i, msg in enumerate(messages):
        if isinstance(msg, AIMessage) and msg.tool_calls:
            # Check if all tool calls have a corresponding ToolMessage in the subsequent messages
            valid_tool_calls = []
            for tc in msg.tool_calls:
                tc_id = tc.get("id")
                # Look ahead for a ToolMessage with this ID
                found = False
                for j in range(i + 1, len(messages)):
                    next_msg = messages[j]
                    if isinstance(next_msg, ToolMessage) and next_msg.tool_call_id == tc_id:
                        found = True
                        break
                    if not isinstance(next_msg, ToolMessage):
                        # Stop looking if we hit a non-tool message
                        break
                
                if found:
                    valid_tool_calls.append(tc)
            
            # If no tool calls are valid, we convert the AIMessage to a plain message or skip tool_calls
            if not valid_tool_calls:
                # Create a new AIMessage without tool_calls
                clean_msgs.append(AIMessage(content=msg.content))
            else:
                # Update tool_calls to only include valid ones
                msg.tool_calls = valid_tool_calls
                clean_msgs.append(msg)
        else:
            clean_msgs.append(msg)
    return clean_msgs


CHAT_SYSTEM = """
You are BizAssist, an AI business operations assistant.
Your goal is to help users manage financial data, spreadsheets, and business documents.

━━━ CAPABILITIES ━━━
• Financial Analysis: Analyze spending, trends, and business performance.
• Spreadsheet Management: Read, write, and update Google Sheets.
• Document Intelligence: Answer questions based on uploaded PDFs, DOCX, and images.
• Business Insights: Provide actionable recommendations grounded in user data.

━━━ CORE RULES ━━━
1. GROUNDING: Use ONLY the data provided via tools (spreadsheets, RAG, attachments). Never fabricate numbers, vendors, or dates.
2. CONFIRMATION: Ask for confirmation before making significant changes to financial data.
3. CONCISION: Be practical, confident, and concise. Avoid unnecessary filler.
4. UNCERTAINTY: If data is missing or a request is ambiguous, ask clarifying questions using 'request_clarification'.
5. SCOPE: Focus on business and finance. Redirect unrelated technical or general queries.

━━━ TOOL USAGE ━━━
• Use 'list_ingested_documents' to see all documents in the RAG knowledge base.
• Use 'rag_retrieve' to search indexed documents. You can filter by filename if a specific document is requested.
• Use attachment tools to inspect newly uploaded files in the current chat.
• Use Google Sheets tools to manage spreadsheet data. Always fetch headers before writing to ensure correct mapping.
"""


async def chat_node(state: AgentState) -> dict:
    """Main agent node that handles all business operations."""
    from app.services.google_sheets_service import get_default_spreadsheet_id
    
    user_id = state["user_id"]
    
    # Optional: inject default spreadsheet info into system prompt for context
    default_sid = await get_default_spreadsheet_id(user_id)
    spreadsheet_info = ""
    if default_sid:
        spreadsheet_info = f"\n\n[Context] Default Spreadsheet ID: {default_sid}"
    else:
        spreadsheet_info = "\n\n[Context] No default spreadsheet connected. Ask user to connect in Settings if needed."

    llm = await get_llm(
        user_id=user_id,
        purpose="primary",
        temperature=0.2,
        streaming=True,
    )
    
    # Build tools for the unified agent
    tools = build_tools_for_agent(state)
    llm_with_tools = llm.bind_tools(tools)

    # Use the main messages list
    messages = state.get("messages") or []
    
    # Clean history to avoid 400 errors from OpenAI
    messages = _clean_message_history(messages)
    
    # Prepend summary if exists
    summary = state.get("message_summary")
    system_content = CHAT_SYSTEM + spreadsheet_info
    if summary:
        system_content += f"\n\n[Earlier Conversation Summary]\n{summary}"
        
    llm_messages = [SystemMessage(content=system_content)] + messages

    response = await llm_with_tools.ainvoke(llm_messages)

    return {"messages": [response]}
