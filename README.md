# DeepResearch Agent

DeepResearch Agent is a production-grade, AI-powered autonomous research system that transforms a natural language question into a comprehensive, structured research report. It orchestrates a multi-agent pipeline — clarifying intent, planning research strategy, executing concurrent web searches, summarizing raw content, and synthesizing a polished final report — all through a conversational chat interface.

The system is designed for depth and accuracy over speed. Rather than returning a single search result or a surface-level summary, it behaves like a team of analysts: a lead researcher breaks the topic into sub-questions, delegates them to specialized research agents that run in parallel, and a writer synthesizes everything into a single cohesive report.

---

## Table of Contents

- [How It Works](#how-it-works)
- [Architecture Overview](#architecture-overview)
  - [Agent Pipeline](#agent-pipeline)
  - [Scope Agent](#1-scope-agent)
  - [Supervisor Agent](#2-supervisor-agent)
  - [Research Agent](#3-research-agent)
  - [Writer Agent](#4-writer-agent)
- [Tech Stack](#tech-stack)
- [Project Structure](#project-structure)
- [API Reference](#api-reference)
- [Setup & Installation](#setup--installation)
  - [Prerequisites](#prerequisites)
  - [Environment Variables](#environment-variables)
  - [Backend Setup](#backend-setup)
  - [Frontend Setup](#frontend-setup)
- [Configuration](#configuration)
- [Supported LLM Providers](#supported-llm-providers)
- [Supported Search APIs](#supported-search-apis)

---

## How It Works

A user types a research question into the chat interface. The system first checks whether the question is specific enough to research — if not, it asks a clarifying question and waits for the user's response. Once the intent is clear, it automatically:

1. Writes a structured research brief from the conversation
2. Sends the brief to a Supervisor (Lead Researcher) that decides which sub-topics to investigate
3. Spawns up to 3 Research Agents concurrently — each performing iterative web searches, reflecting on findings, and compressing results into structured notes
4. Collects all notes and synthesizes a final report with the Writer

The entire process is transparent to the user: a "thinking" state is shown in the frontend while research runs, and the final report is returned as a full markdown document when complete.

Each conversation is tracked via a `thread_id`, allowing the system to maintain context across multiple turns (e.g., follow-up clarifications before research begins).

---

## Architecture Overview

### Agent Pipeline

```
User Message
     │
     ▼
┌─────────────────────────────────────────┐
│              Scope Agent                │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │      clarify_with_user           │   │  ← Structured output: ClarifyWithUser
│  │  Asks if clarification needed    │   │
│  └──────────────┬───────────────────┘   │
│                 │ (if clear)            │
│  ┌──────────────▼───────────────────┐   │
│  │      write_research_brief        │   │  ← Structured output: ResearchQuestion
│  │  Converts messages → brief       │   │
│  └──────────────────────────────────┘   │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│            Supervisor Agent             │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │           supervisor()           │   │  ← Uses: think_tool, ConductResearch,
│  │   Decides what to research       │   │           ResearchComplete
│  └──────────────┬───────────────────┘   │
│                 │                       │
│  ┌──────────────▼───────────────────┐   │
│  │        supervisor_tools()        │   │
│  │  Routes tool calls:              │   │
│  │  - think_tool → sequential loop  │   │
│  │  - ConductResearch → asyncio     │   │  ← Up to 3 research agents in parallel
│  └──────────────┬───────────────────┘   │
│                 │ (loops up to 6x)      │
└─────────────────┼───────────────────────┘
                  │ (for each ConductResearch call)
                  ▼
┌─────────────────────────────────────────┐
│            Research Agent               │
│  (one instance per sub-topic)           │
│                                         │
│  ┌─────────────────────────────────┐    │
│  │          llm_call()             │    │  ← Uses: tavily_search, think_tool
│  │  Searches + reflects on results │    │
│  └─────────────┬───────────────────┘    │
│                │ (loops until done)     │
│  ┌─────────────▼───────────────────┐    │
│  │       compress_research()       │    │  ← Compresses AI + tool messages into notes
│  └─────────────────────────────────┘    │
└─────────────────┬───────────────────────┘
                  │ compressed_research returned per agent
                  ▼
┌─────────────────────────────────────────┐
│             Writer Agent                │
│                                         │
│  ┌──────────────────────────────────┐   │
│  │    final_report_generation()     │   │  ← Combines all notes → final markdown report
│  └──────────────────────────────────┘   │
└─────────────────┬───────────────────────┘
                  │
                  ▼
            Final Report
         returned to user
```

---

### 1. Scope Agent

**File:** [deepresearch-agent/deepresearch/agents/scope/graph.py](deepresearch-agent/deepresearch/agents/scope/graph.py)

The entry point for every user message. It performs two jobs:

**`clarify_with_user`** — Uses a structured LLM output (`ClarifyWithUser`) to decide whether the user's question is specific enough to research. If clarification is needed, it returns a question to the user and ends the graph (the thread stays alive for the follow-up). If the question is clear, it proceeds.

**`write_research_brief`** — Converts the full conversation history into a concise, well-structured research brief using structured output (`ResearchQuestion`). This brief is passed downstream to the Supervisor as the authoritative statement of what to investigate.

The scope agent uses `InMemorySaver` as a checkpointer, so thread state is preserved across the user's clarification turns.

---

### 2. Supervisor Agent

**File:** [deepresearch-agent/deepresearch/agents/supervisor/graph.py](deepresearch-agent/deepresearch/agents/supervisor/graph.py)

The orchestrator of the research pipeline. It acts as a Lead Researcher that strategically plans and delegates work.

**Tools available:**
- `think_tool` — Records strategic reflections without external I/O. Processed sequentially (simple for loop) since it is a near-instant in-memory operation with no benefit from parallelization.
- `ConductResearch` — Delegates a research sub-topic to a full Research Agent sub-graph. Processed concurrently using `asyncio.gather()` because each invocation performs multiple web searches and LLM calls that can take 10–60 seconds. Running 3 tasks in parallel instead of sequentially saves 50–70% wall-clock time.
- `ResearchComplete` — Signals that research is complete and the pipeline should move to writing.

**Iteration limits:**
- Maximum 6 Supervisor iterations before forcing completion
- Maximum 3 Research Agents running concurrently per iteration

The supervisor loops — thinking, delegating research, receiving compressed notes — until it decides research is sufficiently thorough, then calls `ResearchComplete`.

---

### 3. Research Agent

**File:** [deepresearch-agent/deepresearch/agents/research/graph.py](deepresearch-agent/deepresearch/agents/research/graph.py)

Each Research Agent handles one specific sub-topic. It runs its own internal loop:

**`llm_call`** — The LLM decides the next search query and calls tools.

**`tool_node`** — Executes tool calls:
- `tavily_search` — Queries the Tavily API for web content. Results are deduplicated by URL, and raw webpage content is passed through `summarize_webpage_content()` which uses an LLM to extract a summary and key excerpts before returning to the agent.
- `think_tool` — Allows the agent to reflect on what it found, identify gaps, and decide whether to keep searching or conclude.

**`compress_research`** — Once the agent finishes searching, all tool messages and AI responses are compressed into a structured summary (`compressed_research`). Raw notes are also preserved for the Writer. This compression step prevents the final report from being buried in raw search output.

The should_continue router checks the last message: if it contains tool calls, loop back to `tool_node`; otherwise, compress and return.

---

### 4. Writer Agent

**File:** [deepresearch-agent/deepresearch/agents/writer/graph.py](deepresearch-agent/deepresearch/agents/writer/graph.py)

The Writer takes all compressed research notes collected by the Supervisor and generates the final report. It formats the research brief and all findings into a prompt and invokes the LLM to produce a single, polished, long-form markdown document. The result is stored in `final_report` on the state and returned to the API layer.

---

## Tech Stack

### Backend

| Layer | Technology | Purpose |
|---|---|---|
| Agent Framework | [LangGraph](https://langchain-ai.github.io/langgraph/) | Multi-agent state graph orchestration |
| LLM Framework | [LangChain](https://langchain.com) | LLM abstraction, tool use, structured output |
| API Server | [FastAPI](https://fastapi.tiangolo.com) | REST API with async support |
| ASGI Server | [Uvicorn](https://www.uvicorn.org) | Production-grade async server |
| Prompt Management | [Opik](https://www.comet.com/docs/opik/) | Centralized prompt versioning |
| LLM Providers | OpenAI, Google Gemini, Groq, Anthropic, Together AI | Configurable via `LLM_PROVIDER` env var |
| Search APIs | Tavily, Perplexity, Exa, DuckDuckGo, NewsAPI | Web research tool backends |
| Memory/State | LangGraph `InMemorySaver` | Conversation thread persistence |
| Validation | Pydantic | Request/response schema, structured LLM output |
| Code Quality | Ruff, Black, isort, mypy, flake8 | Linting and formatting |
| Evaluation | DeepEval | LLM output evaluation framework |

### Frontend

| Layer | Technology | Purpose |
|---|---|---|
| Framework | [Vue 3](https://vuejs.org) (Composition API) | Reactive UI |
| Build Tool | [Vite](https://vite.dev) | Fast dev server and bundler |
| CSS | Tailwind CSS + Bootstrap 5 | Styling and layout |
| CSS Preprocessor | SCSS (via Sass) | Extended stylesheet support |

---

## Project Structure

```
deepresearch-agent/
│
├── deepresearch-agent/              # Python backend
│   ├── deepresearch/
│   │   │
│   │   ├── agents/                  # LangGraph agent definitions
│   │   │   ├── scope/
│   │   │   │   └── graph.py         # Entry point: clarify + write brief
│   │   │   ├── supervisor/
│   │   │   │   └── graph.py         # Lead researcher: delegates sub-topics
│   │   │   ├── research/
│   │   │   │   ├── graph.py         # Research loop: search + reflect + compress
│   │   │   │   ├── methods.py       # Dedup, summarize, format search results
│   │   │   │   └── summarizer.py    # Webpage content LLM summarizer
│   │   │   └── writer/
│   │   │       └── graph.py         # Final report generation + full pipeline
│   │   │
│   │   ├── tools/                   # LangChain tool definitions
│   │   │   ├── tool.py              # tavily_search, think_tool, ConductResearch, ResearchComplete
│   │   │   ├── tavilyapi.py         # Tavily search client
│   │   │   ├── pplxapi.py           # Perplexity search client
│   │   │   └── utils.py             # Utility functions (date, session ID)
│   │   │
│   │   ├── core/                    # Shared core types and constants
│   │   │   ├── state.py             # LangGraph state classes (AgentState, ResearcherState, etc.)
│   │   │   ├── model.py             # Pydantic models for structured LLM output
│   │   │   ├── constants.py         # GraphNode, ConfigClass, OpikPrompts enums
│   │   │   └── opik_prompts.py      # Opik prompt loader
│   │   │
│   │   ├── config/                  # Application configuration
│   │   │   ├── env.py               # All environment variable loading
│   │   │   ├── llm.py               # LlmService: selects and returns the configured LLM
│   │   │   ├── gemini_models.py     # Gemini model name enum
│   │   │   └── logging.py           # Logging configuration
│   │   │
│   │   └── interface/               # FastAPI application
│   │       ├── main.py              # All routes: /chat, /health, /threads
│   │       └── schema.py            # ChatRequest and ChatResponse Pydantic models
│   │
│   ├── docs/
│   │   ├── README.md                # Documentation index
│   │   └── tool-execution-patterns.md  # Design decisions: sequential vs concurrent tool execution
│   │
│   ├── pyproject.toml               # Python dependencies and build config (Poetry)
│   ├── langgraph.json               # LangGraph deployment config
│   └── run.sh                       # Convenience script to start uvicorn
│
└── web/
    └── deepresearch/                # Vue 3 frontend
        ├── src/
        │   ├── App.vue              # Root component: state management, message handling
        │   ├── main.js              # Vue app entry point
        │   ├── components/
        │   │   ├── ChatHeader.vue   # Connection status bar
        │   │   ├── ChatWindow.vue   # Message history display
        │   │   ├── ChatInput.vue    # User input and submit
        │   │   └── ChatMessage.vue  # Individual message bubble
        │   └── services/
        │       └── chatService.js   # API client: sendMessage, healthCheck, thread management
        ├── package.json
        └── vite.config.js
```

---

## API Reference

All API endpoints are served by the FastAPI backend on port `8000`.

### `POST /chat`

Send a message and receive a response. Handles both clarification turns and full research runs.

**Request body:**
```json
{
  "thread_id": "optional-existing-thread-id",
  "message": "What are the long-term economic effects of automation on middle-skill labor markets?"
}
```

**Response body:**
```json
{
  "thread_id": "abc123",
  "response": "To ensure I give you the most relevant report, could you specify which country or region you're focused on?",
  "is_followup": true,
  "report": null
}
```

When research completes (`is_followup: false`), `response` and `report` both contain the final markdown report, and a fresh `thread_id` is returned for the next conversation.

| Field | Description |
|---|---|
| `thread_id` | Pass back on subsequent messages to continue the same conversation |
| `is_followup` | `true` = agent needs more information; `false` = research is complete |
| `report` | Contains the final report when research is complete, otherwise `null` |

---

### `GET /health`

Returns server health status.

```json
{ "status": "healthy", "service": "DeepResearch Chatbot" }
```

---

### `GET /threads`

Lists all active thread IDs currently held in memory.

```json
{ "active_threads": ["abc123", "def456"], "count": 2 }
```

---

### `GET /threads/{thread_id}`

Returns configuration details for a specific thread.

---

### `DELETE /threads/{thread_id}`

Deletes a thread and frees its memory.

---

## Setup & Installation

### Prerequisites

| Requirement | Version |
|---|---|
| Python | 3.12 or higher |
| Node.js | 20.19.0 or 22.12.0+ |
| npm | Comes with Node.js |
| pip / Poetry | For Python dependency management |

### Environment Variables

Create a `.env` file inside the `deepresearch-agent/` directory:

```env
# ─── LLM Provider ─────────────────────────────────────────
# Choose one: openai | google
LLM_PROVIDER=openai

# ─── LLM API Keys ─────────────────────────────────────────
OPENAI_API_KEY=your_openai_api_key
GOOGLE_API_KEY=your_google_api_key
GROQ_API_KEY=your_groq_api_key

# ─── Search APIs ──────────────────────────────────────────
# Tavily is required for the core research agent
TAVILY_API_KEY=your_tavily_api_key

# Optional additional search backends
EXA_API_KEY=your_exa_api_key

# Perplexity (optional)
PPLX_API_KEY=your_perplexity_api_key
PPLX_API_URL=https://api.perplexity.ai
PPLX_MODEL=sonar
PPLX_INSIGHTS_MODEL=sonar-pro

# ─── Observability (optional) ─────────────────────────────
OPIK_API_KEY=your_opik_api_key
```

**Minimum required keys to run:**
- One LLM key matching your `LLM_PROVIDER` (e.g. `OPENAI_API_KEY` if `LLM_PROVIDER=openai`)
- `TAVILY_API_KEY` for web search

You can get free or trial keys at:
- OpenAI: https://platform.openai.com
- Google AI: https://aistudio.google.com
- Tavily: https://tavily.com

---

### Backend Setup

```bash
# Navigate to the backend directory
cd deepresearch-agent

# Install dependencies with pip (editable install)
pip install -e .

# OR with Poetry
poetry install

# Start the server
uvicorn deepresearch.interface.main:app --reload --host 0.0.0.0 --port 8000

# OR use the convenience script
chmod +x run.sh
./run.sh
```

The backend is now running at **http://localhost:8000**.

Verify it is healthy:
```bash
curl http://localhost:8000/health
```

---

### Frontend Setup

Open a second terminal:

```bash
# Navigate to the frontend directory
cd web/deepresearch

# Install dependencies
npm install

# Start the dev server
npm run dev
```

The frontend is now running at **http://localhost:5173**.

Open that URL in your browser to start chatting.

---

### Running Both Together

| Terminal | Command | URL |
|---|---|---|
| 1 — Backend | `uvicorn deepresearch.interface.main:app --reload --port 8000` | http://localhost:8000 |
| 2 — Frontend | `npm run dev` | http://localhost:5173 |

---

### Building for Production (Frontend)

```bash
cd web/deepresearch
npm run build
# Output is in web/deepresearch/dist/
```

---

## Configuration

### Changing the LLM

Set `LLM_PROVIDER` in your `.env` file:

```env
LLM_PROVIDER=openai    # uses gpt-4o-mini
LLM_PROVIDER=google    # uses gemini-2.5-flash
```

The model selection is centralized in [deepresearch-agent/deepresearch/config/llm.py](deepresearch-agent/deepresearch/config/llm.py).

### Tuning Research Depth

These constants are defined at the top of [deepresearch-agent/deepresearch/agents/supervisor/graph.py](deepresearch-agent/deepresearch/agents/supervisor/graph.py):

```python
max_researcher_iteration = 6   # Max times the supervisor loops before ending
max_concurrent_researcher = 3  # Max research agents running at the same time
```

Increasing `max_researcher_iteration` produces deeper research but takes longer. Increasing `max_concurrent_researcher` speeds up research but uses more API tokens simultaneously.

### Changing the Recursion Limit

The FastAPI layer sets:
```python
RECURSION_LIMIT = 50  # in deepresearch/interface/main.py
```

This is the LangGraph recursion guard. Raise it if you extend iteration limits.

---

## Supported LLM Providers

| Provider | `LLM_PROVIDER` value | Model Used | Key Required |
|---|---|---|---|
| OpenAI | `openai` | `gpt-4o-mini` | `OPENAI_API_KEY` |
| Google Gemini | `google` | `gemini-2.5-flash` | `GOOGLE_API_KEY` |

Additional providers are available as dependencies (`langchain-groq`, `langchain-anthropic`, `langchain-ollama`, etc.) and can be added to `LlmService.get_model()` in [llm.py](deepresearch-agent/deepresearch/config/llm.py).

---

## Supported Search APIs

| Search API | Tool | Notes |
|---|---|---|
| [Tavily](https://tavily.com) | `tavily_search` | Primary search — used by all research agents. Supports `general`, `news`, and `finance` topic filters with raw content retrieval |
| [Perplexity](https://www.perplexity.ai) | `perplexity_search` | Secondary search — supports `web` and `academic` modes |
| [Exa](https://exa.ai) | via `exa-py` | Available as a dependency |
| [DuckDuckGo](https://duckduckgo.com) | via `duckduckgo-search` | Available as a dependency |

Search results are automatically deduplicated by URL and passed through an LLM summarizer that extracts concise summaries and key excerpts before the research agent sees them.
