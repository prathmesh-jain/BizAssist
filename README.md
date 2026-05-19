# AI Business Operations Assistant

BizAssist is a full-stack AI assistant for business workflows: financial Q&A, document intelligence, and Google Sheets operations.

## Architecture

The backend uses a single LangGraph agent flow:

1. `summarize` node: compacts long checkpoint history into `message_summary`.
2. `guardrail` node: validates request scope and safety.
3. `agent` node: unified business assistant (`chat_agent`) with tool calling.
4. `tools` node: executes tool calls, then loops back to `agent`.

Graph flow:
- `summarize -> guardrail`
- `guardrail -> unsafe | agent`
- `agent -> tools | END`
- `tools -> agent`

## Core Capabilities

- Unified business assistant with grounded responses.
- RAG over indexed user documents (`rag_retrieve`, `list_ingested_documents`).
- Google Sheets read/write tooling.
- Chat attachment tooling for uploaded files.
- Interrupt-based clarification flow (`request_clarification`).
- SSE streaming responses with tool activity events.

## Document Pipeline

The document pipeline supports:
- RAG ingestion for `contract` and `report` files.
- Financial extraction for `invoice`, `receipt`, and `bank_statement`.
- PDF/TXT extraction and image-based extraction using multimodal LLM calls.
- Chunked extraction/merge for large documents.

## Tech Stack

### Backend
- FastAPI
- LangChain + LangGraph
- OpenAI models
- MongoDB 
- ChromaDB
- Firebase Admin

### Frontend
- React 19 + Vite
- TypeScript
- Tailwind CSS
- Zustand
- Framer Motion
- Recharts

## Setup

### Prerequisites
- Python 3.10+
- Node.js 18+
- MongoDB
- Firebase project credentials
- Google OAuth credentials (for Sheets integration)

### Backend
1. Go to `backend`.
2. Create a virtual environment and activate it.
3. Install dependencies:
```bash
pip install -r requirements.txt
```
4. Create `.env` with required settings (see `backend/app/config.py`), including:
- `MONGODB_URI`
- `DB_NAME`
- Firebase credentials
- Google OAuth credentials
5. API keys for model access are provided by users in-app (per-user settings), not through backend `.env`.
6. Run:
```bash
uvicorn app.main:app --reload
```

### Frontend
1. Go to `frontend`.
2. Install dependencies:
```bash
npm install
```
3. Create `.env` with:
- `VITE_API_URL` (backend base URL)
4. Run:
```bash
npm run dev
```

## Project Structure

- `backend/app/agents`: LangGraph state, nodes, and tool orchestration.
- `backend/app/services`: chat streaming, RAG, Sheets, and document processing.
- `backend/app/tools`: LangChain tools for Sheets and chat attachments.
- `backend/app/routers`: API routes for chat, documents, settings, integrations.
- `frontend/src/components`: chat, document, and settings UI.
- `frontend/src/store`: Zustand stores for auth, chat, settings, and theme.
