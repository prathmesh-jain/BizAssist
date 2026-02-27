import logging
from app.agents.state import AgentState
from app.services.rag_service import retrieve

logger = logging.getLogger(__name__)


async def retrieval_node(state: AgentState) -> dict:
    """
    Perform a semantic search over the user's uploaded documents.
    Adds retrieved context to state for use by the chat agent.
    """
    last_user_msg = ""
    for msg in reversed(state["messages"]):
        if msg.type == "human":
            last_user_msg = msg.content
            break

    context = await retrieve(query=last_user_msg, user_id=state["user_id"], k=5)
    logger.info(f"RAG retrieved {len(context)} chars for user {state['user_id']}")
    return {
        "retrieved_context": context,
        "tool_calls_made": state.get("tool_calls_made", []) + ["RAG Retrieval"],
    }
