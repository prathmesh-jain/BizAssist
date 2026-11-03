# BizAssist

BizAssist is an AI assistant for small businesses. It first learns how a business works: it asks a few
questions, researches what's public, and lets the owner confirm the result. After that it helps with
everyday work: answering from the business's own documents, reading and updating Google Sheets,
handling Google Calendar and Meet, and keeping a whole team on the same page.

It's a FastAPI + LangGraph backend on PostgreSQL and Qdrant, with a React 19 + Vite frontend.

## Contents

- [What it does](#what-it-does)
- [Status](#status)
- [Architecture](#architecture)
- [Agent graph](#agent-graph)
- [Tools](#tools)
- [Business onboarding and research](#business-onboarding-and-research)
- [Documents](#documents)
- [Organizations, roles, and invitations](#organizations-roles-and-invitations)
- [Storage](#storage)
- [Guardrails](#guardrails)
- [Frontend](#frontend)
- [Local setup](#local-setup)
- [Tests](#tests)
- [Known gaps](#known-gaps)

## What it does

- **Business profile.** An onboarding flow collects the basics. A research workflow then searches the web,
  reads the business's website, and drafts a profile with competitors, industry trends, and improvement
  opportunities. Every researched field is labelled *verified*, *estimated*, or *not found*, with its sources.
  Nothing is used until an admin reviews and confirms it.
- **Chat grounded in your data.** Answers come from the conversation, files attached in chat (PDF, TXT, images
  via OCR), and the organization's indexed documents, with sources shown under the reply.
- **Google Sheets.** The assistant reads, appends, updates, and reorganizes spreadsheets through tool calls.
- **Google Calendar and Meet.** Each user connects their own calendar. The assistant can check the schedule,
  find free time, and create, move, or cancel events with Meet links. Every change requires an explicit
  Accept/Decline approval in the chat.
- **Teams.** Organizations have owners, admins, members, and viewers; invitation links; suspension and removal;
  and switching between several organizations.
- **Streaming UX.** Tokens, tool activity, planner status, and approval prompts stream to the browser over SSE.

## Status

| Phase | Item | Status |
|---|---|---|
| 0 | PostgreSQL, roles, invites | ✅ Done |
| 1 | Business onboarding and profile | ✅ Done |
| 2 | Web search and research agent | ✅ Done |
| 3 | Competitors and improvement suggestions | ✅ Done (part of research) |
| 4 | Google Calendar and Meet | 🟡 Built; not yet tested against a real Google account |
| 5 | Reminders and background scheduler | ⬜ Next |
| 6 | Long-term business memory | ⬜ Not started |
| 7 | Domain-specific tools and workflows | ⬜ Not started |
| 8 | Proactive insights and notifications | ⬜ Not started |
| 9 | Dashboard and automation screens | ⬜ Not started |
| 10 | Evaluation and production hardening | 🟡 Backend test suite exists; ongoing |
| 11 | Managed billing | ⬜ Later |

See [Known gaps](#known-gaps) for what still needs real-world testing.

## Architecture

```text
frontend/  React 19 · Vite · TypeScript · Tailwind CSS v4 · Zustand · Firebase Web SDK
   │  REST + SSE (Firebase ID token, X-Organization-Id header)
backend/   FastAPI · LangGraph · LangChain · OpenAI
   ├─ PostgreSQL   app data (SQLAlchemy async + Alembic) and LangGraph checkpoints
   ├─ Qdrant       document vectors and the tool catalog
   ├─ Firebase     identity (ID token verification via firebase-admin)
   ├─ Google APIs  Sheets, Calendar/Meet (per-user OAuth, encrypted tokens)
   └─ Playwright   headless Chromium for research search and website crawling
```

Users bring their own OpenAI API key (saved encrypted per user in Settings). Chat stays disabled until a key is added.

## Agent graph

```mermaid
flowchart TD
    S[Summarize] --> G[Guardrail]
    G -->|unsafe| U[Unsafe]
    G -->|safe| C[Chat Agent]

    C -->|direct answer| E([End])
    C -->|tool call| T[Tools]
    C -->|delegate_to_planner| P[Planner]

    P -->|tool call| T
    P -->|plan ready| X[Executor]

    X -->|tool call| T
    X -->|execution complete| C

    T -->|active_agent=chat| C
    T -->|active_agent=planner| P
    T -->|active_agent=executor| X
```

- **summarize**: folds older checkpoint messages into a rolling summary so state stays small.
- **guardrail**: stops out-of-scope requests before the main agent runs (see [Guardrails](#guardrails)).
- **chat**: the entry point. It handles conversation, chat attachments, and single-step retrieval, and
  delegates broader or external work to the planner. The confirmed business profile is injected as context.
- **planner**: writes a compact, structured plan for multi-step tasks. Loops are capped
  (`PLANNER_MAX_ITERATIONS`) and adjacent duplicate steps are dropped.
- **executor**: runs the plan using only the brief, the steps, and its own tool scratchpad. It doesn't reread the chat.
- **tools**: one shared tool node for all three agents.

Approvals and clarifications use LangGraph `interrupt()`. The run pauses, the frontend renders an approval
card, and `/chat/{id}/interrupt-resolve` resumes it from the Postgres checkpoint.

## Tools

Not every tool is bound to every model call. The tool catalog is indexed in Qdrant
(`QDRANT_TOOL_CATALOG_COLLECTION`, default `tool_catalog`), and the planner and executor load only the tools
that match the task, so prompts stay small as the catalog grows. The executor can look up more tools at
runtime with `search_available_tools`. Lexical search is the fallback if Qdrant is unavailable.

The chat agent always has a small direct set: `request_clarification`, `list_documents`,
`chat_read_attachment_text`, `rag_retrieve`, and `delegate_to_planner`.

Other registered tools:

- `app/tools/google_sheets_tools.py`: list tabs, read ranges, headers and metadata, append, update, clear,
  batch update, create, rename, or delete tabs, resize, and insert rows or columns.
- `app/tools/google_calendar_tools.py`: list events, find free time, and create, update, or cancel events
  with Meet links. All writes go through `request_approval`.
- `app/tools/chat_attachments_tools.py`: read text extracted from files attached in chat.

After changing tool registrations, re-sync the catalog:

```bash
cd backend
python scripts/reindex_tool_catalog.py
```

The script inserts new tools, updates changed ones (by metadata hash), and removes stale ones.

## Business onboarding and research

`app/research/` runs the research workflow behind `POST /api/business-profile/research`:

1. Search the web with the configured provider (`RESEARCH_SEARCH_PROVIDER`):
   - `browser` (default): headless Chromium across the engines in `RESEARCH_SEARCH_ENGINES`
   - `openai`: web search on the user's own OpenAI key
   - `google_api`: Programmable Search; needs `GOOGLE_SEARCH_API_KEY` and `GOOGLE_SEARCH_ENGINE_ID`
2. Crawl up to `RESEARCH_MAX_WEBSITE_PAGES` pages of the business's website (`RESEARCH_CRAWLER=browser|http`).
3. Draft the profile, public facts, competitors, industry trends, and opportunities. Each item carries a basis
   and its sources.

Runs are stored in Postgres and polled by the frontend. Today they execute inside the API process: a restart
marks in-flight runs as failed, and runs aren't shared across multiple API servers. Moving them onto the
background worker is part of phase 5.

## Documents

There are two document paths.

**Chat attachments** (PDF, TXT, JPEG/PNG/GIF/WEBP, up to 10 MB) are text-extracted. Images go through a
multimodal OCR call. The text is stored per chat under `backend/tmp/chats/{chat_id}` and swept after
`CHAT_TMP_TTL_SECONDS` (default 24h).

**Organization documents** (PDF, DOCX, TXT) uploaded on the Documents page are extracted, chunked
(`CHUNK_SIZE=1200`, `CHUNK_OVERLAP=120`), embedded with `EMBEDDING_MODEL` (default `text-embedding-3-small`),
and stored in Qdrant (`QDRANT_DOCUMENTS_COLLECTION`, default `business_docs`). Retrieval is filtered by
organization, so every member shares the same knowledge base. Document records live in Postgres.

## Organizations, roles, and invitations

Every user belongs to one or more organizations. The frontend sends the active one as `X-Organization-Id`.
Permissions are defined in `app/authz.py`:

| Role | Can |
|---|---|
| viewer | chat, read documents, read the business profile, see members |
| member | everything a viewer can, plus upload documents and update spreadsheets |
| admin | everything a member can, plus manage members, invitations, integrations, the organization, and the business profile |
| owner | full control, including other owners |

Invitations are one-time links bound to an email address and valid for `INVITATION_TTL_DAYS` (default 7).
The token travels in the URL fragment so it isn't logged by servers, and accepting requires a verified email.
**Invitation emails aren't sent yet**: an admin copies the link and sends it themselves.

Chats and Google connections (Sheets and Calendar) belong to each person. Documents and the business profile
are shared across the organization.

## Storage

**PostgreSQL** (SQLAlchemy async, migrations in `backend/alembic/versions/`) stores users and identities,
organizations, memberships, and invitations; chats and visible message history; document records; per-user
AI settings with the encrypted OpenAI key; OAuth connections and states with encrypted Google tokens; and
business profiles and research runs. LangGraph checkpoints are in the same database via `AsyncPostgresSaver`.

**Qdrant** stores document vectors and the tool catalog.

## Guardrails

The `guardrail` node classifies each request with the small model and stops out-of-scope ones (writing code,
database queries, unrelated topics).

> **Current behaviour:** the node only checks the server-wide `USE_GUARDRAIL` setting (default `false`). The
> per-user toggle in Settings is saved to `user_ai_settings.guardrail_enabled` but isn't read by the graph
> yet, so flipping it has no effect. Fixing this is the next item on the list.

## Frontend

React 19 + Vite + TypeScript, Tailwind CSS v4, Zustand, and React Router. Routes:

| Path | Screen |
|---|---|
| `/` | Landing page |
| `/login`, `/signup` | Firebase email/password and Google sign-in |
| `/invite#token=…` | Accept an organization invitation |
| `/app/chat/:chatId?` | Assistant |
| `/app/onboarding`, `/app/business` | Business onboarding, research review, and the confirmed profile |
| `/app/documents` | Organization documents |
| `/app/team` | Members and invitations |
| `/app/settings` | Google Calendar and Sheets, OpenAI key and models, guardrail |
| `/oauth-callback` | Google OAuth popup landing |

### Design system

Light and airy with a fresh green: cool off-white backgrounds with a faint mint and blue wash, white cards with
soft, wide shadows, a green primary (`#25A060`), and small pastel icon chips for variety. Motion is limited to
micro-interactions.

- **Tokens** live in `src/index.css` as HSL CSS variables (`--primary`, `--highlight` for the mint wash,
  `--success`, `--warning`, `--wash-1/2`, and the `--tint-*` pastel pairs) with light and `.dark` sets, exposed to
  Tailwind via `@theme`. Use tokens, not raw palette colors.
- **Type**: Plus Jakarta Sans for the UI and Geist Mono for small `.eyebrow` labels.
- **Surfaces**: `.app-wash` (page background), `.shadow-soft` and `.shadow-lifted` for cards and popovers, and
  `.chip-green|blue|violet|amber|teal|rose` for icon chips and avatars. Keep green for primary actions and
  selection; use the pastel chips only for small icons.
- **Micro-interactions**: buttons scale slightly on press (global), the primary button (`.btn-glow`, a solid green
  despite the name) lifts 1px on hover, cards darken their border with a faint cursor light (`.spotlight` /
  `SpotlightCard`), inputs get a green focus ring (`.beam-border.beam-on-focus`), and icons nudge on hover.
- **Entrance motion**: `.rise-in`, `Reveal`, `RotatingWords`, `Marquee`, `ScrollTilt`, and `useTypewriter`
  in `src/components/fx/`. Everything respects `prefers-reduced-motion`.
- **Dark mode** is class-based (`@custom-variant dark`). The first visit follows the OS and the toggle is
  remembered; an inline script in `index.html` sets it before first paint.
- **Shared pieces** in `src/components/ui/`: `Logo`/`LogoMark`, `PageHeader`, `StatusChip`, `GoogleIcon`.
- **Markdown** in assistant replies is styled by the `.md` class.

### SEO and social sharing

The production site is **https://bizassist.prathmeshjain.in**. That URL is hard-coded in `frontend/index.html`,
`frontend/src/lib/seo.ts`, `frontend/scripts/prerender.mjs`, and `public/robots.txt`, `sitemap.xml`, and the
legal pages, so update all of them if the domain changes.

- **Prerendered landing page**: `npm run build` also runs an SSR build (`vite.prerender.config.ts`, with a
  signed-out auth stub so no Firebase runs at build time) and `scripts/prerender.mjs`, which writes the landing
  page's real HTML into `dist/index.html`. Crawlers and link previews see the full content without JavaScript;
  in the browser React mounts over it as usual.
- **Per-route shells**: the same script writes `dist/login.html` and `dist/signup.html` with their own titles,
  descriptions, and canonical URLs, plus `dist/app.html` (`noindex`) for the app. `frontend/vercel.json` rewrites
  `/login`, `/signup`, and all other paths to these files, and adds `X-Robots-Tag: noindex` on `/app`, `/invite`,
  and `/oauth-callback`. At runtime, `usePageMeta()` (`src/lib/seo.ts`) keeps the title, description, canonical
  URL, and robots tag in sync on client-side navigation.
- **Structured data**: Organization, WebSite, and SoftwareApplication JSON-LD in `index.html`, plus FAQPage
  generated from `src/content/faq.ts`, which also drives the landing page's FAQ section. Keep those answers factual.
- **Social cards**: Open Graph and Twitter `summary_large_image` tags pointing at `public/og-image.png` (1200×630).
- **Icons**: `favicon.ico` (16/32/48), `favicon.svg`, `apple-touch-icon.png`, `icon-192/512.png`, a maskable icon,
  and `site.webmanifest`.
- **Crawling**: `public/robots.txt` (blocks `/app`, `/invite`, and `/oauth-callback`) and `public/sitemap.xml`.
  Bump `lastmod` when public pages change.
- **Accessibility**: the light-theme green (`#1E804F`) and muted text meet WCAG AA contrast. Lighthouse on the
  built site scores 100 for SEO and accessibility.

After deploying, submit the sitemap in Google Search Console (the site-verification meta tag is already in
`index.html`) and Bing Webmaster Tools, and check the card with the LinkedIn Post Inspector or opengraph.xyz.

## Local setup

### Prerequisites

- Python 3.10+
- Node.js 18+
- PostgreSQL 14+ (local or Docker)
- A Qdrant instance (Qdrant Cloud or `docker run -p 6333:6333 qdrant/qdrant`)
- A Firebase project (or the Firebase Auth emulator for local testing)
- A Google Cloud OAuth client with the Sheets and Calendar APIs enabled
- An OpenAI API key (each user adds their own in the app)

### Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
playwright install chromium     # needed for the default research search provider
cp .env.example .env            # Windows: copy .env.example .env
```

Fill in `backend/.env`. `backend/app/config.py` is the source of truth for settings and defaults. The ones
you must set:

| Setting | Notes |
|---|---|
| `DATABASE_URL` | e.g. `postgresql+asyncpg://bizassist:bizassist@localhost:5432/bizassist`. **Required:** without it the app falls back to a placeholder URL and won't start. |
| `USER_SECRETS_ENCRYPTION_KEY` | Fernet key for stored OpenAI keys |
| `GOOGLE_OAUTH_TOKEN_ENCRYPTION_KEY` | Fernet key for stored Google tokens |
| `FIREBASE_*` | Service-account fields from the Firebase console |
| `GOOGLE_OAUTH_CLIENT_ID` / `_SECRET` / `_REDIRECT_URI` | Redirect URI is `{FRONTEND_URL}/oauth-callback` |
| `QDRANT_URL`, `QDRANT_API_KEY` | |
| `CORS_ORIGINS`, `FRONTEND_URL` | Defaults suit `http://localhost:5173` |

Generate a Fernet key with:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Create the schema, then start the API:

```bash
alembic upgrade head
uvicorn app.main:app --reload
```

Run `alembic upgrade head` again after pulling changes that add migrations. After changing tool
registrations, run `python scripts/reindex_tool_catalog.py`.

### Frontend

```bash
cd frontend
npm install
cp .env.example .env
```

Set `VITE_API_URL` (default `http://localhost:8000`) and the `VITE_FIREBASE_*` web config, then:

```bash
npm run dev       # http://localhost:5173
npm run build     # type-check and production build
npm run lint
```

To develop against the Firebase Auth emulator instead of a real project, start
`firebase emulators:start --only auth --project demo-bizassist` and run `node frontend/scripts/dev-emulator.mjs`.

## Tests

Backend tests run against a disposable PostgreSQL database. Every table is truncated between tests, so never
point them at real data:

```bash
docker run -d --name bizassist-pg-test -e POSTGRES_USER=bizassist -e POSTGRES_PASSWORD=bizassist \
  -e POSTGRES_DB=bizassist -p 55432:5432 postgres:16-alpine
cd backend
pip install -r requirements-dev.txt
export TEST_DATABASE_URL=postgresql+asyncpg://bizassist:bizassist@localhost:55432/bizassist
DATABASE_URL=$TEST_DATABASE_URL alembic upgrade head
pytest
```

Tests marked `no_db` run without a database. The suite covers smoke flows, authorization, team management,
the business profile, the research workflow, search-engine parsing, and the Calendar tools, with Google and
OpenAI faked.

## Known gaps

Built, but not yet exercised against the real services since the PostgreSQL migration:

- **Google Calendar and Meet:** connect, read, create with Meet, and move, against a real account.
- **Resuming after an approval:** Accept/Decline on a real interrupted run. The Calendar tests fake this step.
- **Documents:** upload a document, then ask about it.
- **Google Sheets:** read and write with a real account.
- **Real Firebase sign-in:** tests used the emulator.

Smaller items:

- The Settings guardrail toggle is saved but not enforced (see [Guardrails](#guardrails)).
- Invitations and signup don't send email (no invite email, no verification email on signup).
- Only the research workflow can search the web. The chat assistant can't yet.
- Google OAuth verification is needed for the Sheets and Calendar scopes before outside customers can connect.
- Gmail, Google Drive, and in-app or email notifications are on the roadmap but not started.
