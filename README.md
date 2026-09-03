# CodeTurtle

> **Autonomous, Local-First Multi-Agent Swarm for Repository-Aware GitHub Code Reviews**

[![Python Version](https://img.shields.io/badge/python-3.10%2B-3776AB.svg?style=flat&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![Orchestration](https://img.shields.io/badge/Orchestration-LangGraph-FF6B6B.svg?style=flat)](https://github.com/langchain-ai/langgraph)
[![Vector Database](https://img.shields.io/badge/VectorDB-Qdrant-DC2626.svg?style=flat&logo=qdrant&logoColor=white)](https://qdrant.tech/)
[![Graph Database](https://img.shields.io/badge/GraphDB-Neo4j-008CC1.svg?style=flat&logo=neo4j&logoColor=white)](https://neo4j.com/)
[![Local LLM](https://img.shields.io/badge/LLM-Ollama%20(Local)-000000.svg?style=flat&logo=ollama&logoColor=white)](https://ollama.ai/)
[![Cloud LLM](https://img.shields.io/badge/LLM-OpenAI%20%7C%20LiteLLM-10A37F.svg?style=flat&logo=openai&logoColor=white)](https://openai.com/)
[![Observability](https://img.shields.io/badge/Observability-Langfuse-6366F1.svg?style=flat)](https://langfuse.com/)
[![CLI Framework](https://img.shields.io/badge/CLI-Typer%20%2B%20Rich-0284C7.svg?style=flat)](https://typer.tiangolo.com/)

---

## Table of Contents

- [Overview](#-overview)
- [Key Architectural Highlights](#-key-architectural-highlights)
- [System Architecture (Colorful System Design)](#-system-architecture)
- [The 6-Phase Review Intelligence Swarm](#-the-6-phase-review-intelligence-swarm)
  - [Phase Sequence & Data Flow](#phase-sequence--data-flow)
  - [Detailed Phase Breakdown](#detailed-phase-breakdown)
- [Repository Intelligence & Dual-Store Hybrid RAG](#-repository-intelligence--dual-store-hybrid-rag)
- [Decoupled Query Engine Subsystem](#-decoupled-query-engine-subsystem)
- [AI Gateway & Observability](#-ai-gateway--observability)
- [Session Memory & Persistence](#-session-memory--persistence)
- [Repository Structure](#-repository-structure)
- [Quick Start Guide](#-quick-start-guide)
  - [Prerequisites](#prerequisites)
  - [Installation (uv & pip)](#1-installation)
  - [Environment Configuration](#2-environment-configuration)
  - [Spinning up Databases (Qdrant & Neo4j)](#3-start-local-databases)
  - [Pulling Local LLM (Ollama)](#4-pull-local-model)
- [CLI Command Reference](#-cli-command-reference)
- [Quantitative Evaluation & Benchmark Suite](#-quantitative-evaluation--benchmark-suite)
- [Contributing](#-contributing)
- [License](#-license)

---

## Overview

Standard LLM-powered code review bots operate under a severe structural handicap: **they inspect diff hunks in complete isolation**. Without context of the enclosing project, callers, callees, symbol hierarchies, and architectural patterns, they hallucinate API assumptions, report superficial formatting trivia, and miss critical runtime invariants and regression risks.

**CodeTurtle** solves this fundamentally by bringing **deep, local-first repository intelligence** to automated code reviews. Before reviewing a line of code, CodeTurtle parses and indexes the whole repository into a **dual-store vector-graph knowledge base** (Qdrant + Neo4j). When a pull request arrives, CodeTurtle executes an autonomous **6-phase LangGraph agent swarm** that:

1. Formulates the **causal chain** of what broke, why, and how the fix addresses it.
2. Performs **deterministic AST hunk and symbol parsing**.
3. Dynamically **plans targeted retrieval hypotheses** and gates specialist reviewers.
4. Executes **diff-first hybrid retrieval** (path-forcing, symbol matching, graph traversal, and cross-encoder structural reranking).
5. Dispatches **parallel domain specialists** (Correctness, Code Quality, Testing) governed by strict **anti-summarization contracts**.
6. Filters ungrounded claims through a **critic reasoning gate** to deliver a conclusive, structured verdict: `MERGE`, `REQUEST_CHANGES`, or `COMMENT`.

---

## Key Architectural Highlights

- **Dual-Store Repository Intelligence**: Integrates **Qdrant** for semantic vector embeddings and **Neo4j** for AST call graphs (`CALLS`), inheritance hierarchies, and import dependencies (`IMPORTS`).
- **Diff-First Context Packing**: The unified diff is treated as **primary ground truth**. Path-forced diff hunks are permanently pinned at the top of prompt contexts, guaranteeing that review specialists never hallucinate or critique unchanged code.
- **Hypothesis-Driven Review Planning**: Generates targeted retrieval questions based on modified symbols and risk hotspots, rather than flooding the LLM with generic vector chunks.
- **Dynamic Plan-Gated Specialist Swarm**: Specialist reviewers (`CorrectnessAgent`, `CodeQualityAgent`, `TestingAgent`, `ContextGatherer`) are dynamically allocated based on PR risk and files touched.
- **Anti-Summarization Prompt Contracts**: Review specialists are strictly prohibited from explaining what unchanged functions do or issuing vague commentary. Findings must state concrete claims anchored in modified lines.
- **Deterministic Guardrails & Grounding Gates**: Includes `refine_understanding` (automatically escalates core-path bugfixes to medium/high risk), evidence grounding checks (demotes ungrounded blockers), and relevance filters.
- **Decoupled Query Engine Subsystem**: Independent query engine with dedicated routers (`VectorRouter`, `GraphRouter`, `ModelRouter`) supporting contextual retrieval and blast radius impact analysis.
- **Production-Grade AI Gateway**: Capability-based routing across local models via **Ollama** (`qwen2.5:7b`), **OpenAI** (`gpt-4o`, `o3-mini`), and **LiteLLM** with exponential-backoff retries, schema enforcement, and **Langfuse** telemetry.
- **Built-in Benchmark & Evaluation Suite**: Includes `evals/ri/` to quantitatively test and score each individual pipeline phase against real-world open-source pull requests.

---

## System Architecture

The following diagram illustrates CodeTurtle's complete multi-layer architecture as implemented in the `main` branch. It visualizes the end-to-end data flow spanning CLI commands, ingestion, dual-store knowledge indexing, the query engine, the 6-phase LangGraph swarm, and the AI gateway infrastructure:

```mermaid
flowchart TB
    %% =========================================================================
    %% Mermaid Color Styles & Class Definitions
    %% =========================================================================
    classDef clientLayer fill:#0f172a,stroke:#38bdf8,stroke-width:2px,color:#f8fafc;
    classDef ingestionLayer fill:#1e1b4b,stroke:#818cf8,stroke-width:2px,color:#f8fafc;
    classDef storageLayer fill:#172554,stroke:#60a5fa,stroke-width:2px,color:#f8fafc;
    classDef routerLayer fill:#134e4a,stroke:#2dd4bf,stroke-width:2px,color:#f8fafc;
    classDef swarmPhase fill:#2e1065,stroke:#c084fc,stroke-width:2px,color:#f8fafc;
    classDef specialist fill:#064e3b,stroke:#34d399,stroke-width:2px,color:#f8fafc;
    classDef decision fill:#831843,stroke:#f472b6,stroke-width:2px,color:#f8fafc;
    classDef gatewayLayer fill:#701a75,stroke:#f43f5e,stroke-width:2px,color:#f8fafc;
    classDef memoryLayer fill:#451a03,stroke:#f59e0b,stroke-width:2px,color:#f8fafc;

    %% =========================================================================
    %% Layer 1: Client & User Interface
    %% =========================================================================
    subgraph Layer1 ["1. Client & CLI Orchestration Layer (cli/)"]
        direction LR
        CLIEntry["Typer CLI App<br/>(cli/main.py)"]:::clientLayer
        CmdNewSession["codeturtle new-session<br/>(cli/commands/session.py)"]:::clientLayer
        CmdAddRepo["codeturtle add-repo<br/>(cli/commands/add_repo.py)"]:::clientLayer
        CmdInspect["codeturtle inspect-kb<br/>(cli/commands/inspect_kb.py)"]:::clientLayer
        CmdReview["codeturtle review<br/>(cli/commands/review.py)"]:::clientLayer
        GitHubAPI["GitHub REST / GraphQL API<br/>(PyGithub / Unified Diff)"]:::clientLayer

        CLIEntry --> CmdNewSession & CmdAddRepo & CmdInspect & CmdReview
        CmdReview <--> GitHubAPI
    end

    %% =========================================================================
    %% Layer 2: Repository Intelligence & Ingestion
    %% =========================================================================
    subgraph Layer2 ["2. Repository Intelligence & Ingestion Pipeline (core/repository_intelligence/)"]
        direction TB
        GitWorktree["Local Git Worktree<br/>(repos/owner_repo)"]:::ingestionLayer
        Scanner["Directory Scanner & Language Detector<br/>(Python, TS, JS, Go, Java)"]:::ingestionLayer
        ASTParsers["AST Parsers & Symbol Extractor<br/>(core/repository_intelligence/parsers/)"]:::ingestionLayer
        CallExtractor["Call Graph & Import Resolver<br/>(call_extractor.py & import_resolver.py)"]:::ingestionLayer
        Chunker["AST-Aware Code Chunker<br/>(core/chunker.py - PythonChunker)"]:::ingestionLayer
        Analyzer["Repository Analyzer & Snapshot<br/>(core/repository_analyzer.py)"]:::ingestionLayer

        GitWorktree --> Scanner --> ASTParsers
        ASTParsers --> CallExtractor & Chunker & Analyzer
    end

    %% =========================================================================
    %% Layer 3: Dual-Store Knowledge Base
    %% =========================================================================
    subgraph Layer3 ["3. Dual-Store Knowledge Base & Persistence Layer"]
        direction LR
        subgraph VectorStore ["Vector Store"]
            QdrantDB[("Qdrant Vector DB<br/>• Code Chunk Embeddings<br/>• Path, Line & Symbol Payload")]:::storageLayer
        end

        subgraph GraphStore ["Graph Store"]
            Neo4jDB[("Neo4j Graph DB<br/>• Node Types: File, Symbol<br/>• Edges: CALLS, IMPORTS,<br/>DEFINES, OVERRIDES")]:::storageLayer
        end

        subgraph MetaStore ["Model & Session Store"]
            RepoJSON[("RepositoryModel JSON<br/>(data/models/*.json)")]:::memoryLayer
            SQLiteDB[("SQLite Session DB<br/>(data/codeturtle.db)")]:::memoryLayer
        end

        Chunker --> QdrantDB
        CallExtractor --> Neo4jDB
        Analyzer --> RepoJSON
    end

    %% =========================================================================
    %% Layer 4: Decoupled Query Engine
    %% =========================================================================
    subgraph Layer4 ["4. Repository Query Engine Subsystem (core/query_engine/)"]
        direction LR
        VRouter["VectorRouter<br/>(Qdrant Semantic Search)"]:::routerLayer
        GRouter["GraphRouter<br/>(Neo4j Cypher Traversal)"]:::routerLayer
        MRouter["ModelRouter<br/>(In-Memory Symbol/File Index)"]:::routerLayer
        QueryEngine["RepositoryQueryEngine<br/>• retrieve_context()<br/>• impact_analysis()"]:::routerLayer

        QdrantDB -.-> VRouter
        Neo4jDB -.-> GRouter
        RepoJSON -.-> MRouter
        VRouter & GRouter & MRouter --> QueryEngine
    end

    %% =========================================================================
    %% Layer 5: LangGraph 6-Phase Review Intelligence Swarm
    %% =========================================================================
    subgraph Layer5 ["5. LangGraph 6-Phase Review Intelligence Swarm (core/graph.py)"]
        direction TB

        subgraph Phase1 ["Phase 1: PR Understanding"]
            P1["PR Understanding Agent (core/pr_understanding.py)<br/>• Causal Chain: What broke → Why → Fix<br/>• Risk Classification (low/med/high/crit)<br/>• refine_understanding() deterministic guardrail"]:::swarmPhase
        end

        subgraph Phase2 ["Phase 2: PR Analysis"]
            P2["PR Analysis Agent (core/pr_analysis.py)<br/>• Deterministic diff hunk parser (analyze_diff)<br/>• extract_functions (modified/added defs & consts)<br/>• Hotspots, language stats & test changes"]:::swarmPhase
        end

        subgraph Phase3 ["Phase 3: Review Planning"]
            P3["Review Planner Agent (core/review_intelligence/planner.py)<br/>• Dynamic reviewer allocation (_deterministic_reviewers)<br/>• Targeted RetrievalQuestion formulation with prefer_symbols"]:::swarmPhase
        end

        subgraph Phase4 ["Phase 4: Hybrid Retrieval & Evidence Assembly"]
            P4Pack["build_evidence_package (core/agents.py)<br/>• Path-Forcing diff chunks (diff_chunks_for_paths)<br/>• Vector similarity + Neo4j 1/2-hop neighborhood expansion<br/>• Structural Reranker (reranker.py) + Global Deduplication"]:::swarmPhase
            P4Sum["Context Summarizer Agent<br/>(Distills evidence into high-signal architecture context)"]:::swarmPhase
            P4Pack --> P4Sum
        end

        subgraph Phase5 ["Phase 5: Parallel Specialist Swarm (core/agents.py)"]
            direction LR
            Correctness["Correctness Agent<br/>• Claims, invariants & edge cases<br/>• Tie-breaking & failure modes<br/>• Anti-summarization rules"]:::specialist
            CodeQuality["Code Quality Agent<br/>• Changed lines maintainability<br/>• Hardcoded values vs config<br/>• Naming, coupling & errors"]:::specialist
            Testing["Testing Agent<br/>• Assertions vs mock trivia<br/>• Missing edge-case test gaps<br/>• Regression lockdown"]:::specialist
            ContextGather["Context Gatherer Agent<br/>• Reviewer synthesis<br/>• Downstream impact notes"]:::specialist
        end

        subgraph Phase6 ["Phase 6: Critic Gate & Decision Engine (core/agents.py)"]
            direction TB
            Critic["Critic Agent (Reasoning Gate)<br/>• Drops boilerplate, empty & irrelevant findings<br/>• Resolves cross-specialist contradictions<br/>• Deduplicates near-identical claims"]:::decision
            Recommender["Final Recommender<br/>• Calibrated Decision: MERGE / REQUEST_CHANGES / COMMENT<br/>• Confidence Score (0.0 – 1.0) & Structured Markdown"]:::decision
            Critic --> Recommender
        end

        P1 --> P2 --> P3 --> P4Pack
        P4Sum --> Correctness & CodeQuality & Testing & ContextGather
        Correctness & CodeQuality & Testing & ContextGather --> Critic
    end

    %% =========================================================================
    %% Layer 6: AI Gateway & Telemetry
    %% =========================================================================
    subgraph Layer6 ["6. AI Gateway & Infrastructure (core/gateway/)"]
        direction TB
        AIGateway["AI Gateway (gateway.py)<br/>• Capability-based routing (reasoning, review, summary)<br/>• Pydantic schema validation & retry loops<br/>• Per-call latency & token tracking"]:::gatewayLayer

        subgraph Providers ["LLM Provider Integrations"]
            Ollama["Ollama (Local Default)<br/>qwen2.5:7b, llama3"]:::gatewayLayer
            OpenAI["OpenAI<br/>gpt-4o, o3-mini"]:::gatewayLayer
            LiteLLM["LiteLLM Adapter"]:::gatewayLayer
        end

        Langfuse["Langfuse Observability<br/>(Full Traces, Prompts & Costs)"]:::gatewayLayer

        AIGateway --> Ollama & OpenAI & LiteLLM
        AIGateway --> Langfuse
    end

    %% =========================================================================
    %% Inter-Layer Connections
    %% =========================================================================
    CmdAddRepo --> Layer2
    CmdInspect --> RepoJSON
    CmdReview --> Layer5
    QueryEngine -.-> P4Pack
    Layer5 <--> AIGateway
    Recommender --> SQLiteDB
    Recommender --> TerminalOutput["Rich Terminal Formatted Output & Review Comment"]:::clientLayer
```

---

## The 6-Phase Review Intelligence Swarm

CodeTurtle uses a compiled **LangGraph `StateGraph`** (`core/graph.py`) passing a centralized `ReviewState` structure across deterministic guardrails and LLM specialist agents.

### Phase Sequence & Data Flow

### Detailed Phase Breakdown

#### Phase 1: PR Understanding (`core/pr_understanding.py`)
- **Objective**: Establishes high-level understanding of the author's intent before inspecting code changes.
- **Causal Chain Modeling**: Maps the causal sequence of the pull request: `What broke` $\rightarrow$ `Why it broke` $\rightarrow$ `How the fix addresses it`.
- **Risk Classification**: Classifies risk tier (`low`, `medium`, `high`, `critical`) based on semantic blast radius rather than raw lines of code.
- **Deterministic Guardrails (`refine_understanding`)**:
  - Automatically escalates any bugfix touching core directories (`core`, `engine`, `runtime`, `auth`, `db`, `api`, `server`, `client`, `model`, `service`, `security`, `cache`) to at least `medium` risk.
  - Strips banned subjective risk fluff (`"subtle"`, `"thoroughly"`, `"carefully reviewed"`, `"may introduce"`).
  - Validates `has_tests` and `has_docs` against actual file extensions.

#### Phase 2: PR Analysis (`core/pr_analysis.py`)
- **Objective**: Extracts concrete, deterministic structural facts directly from the unified diff.
- **Deterministic Diff Parsing (`analyze_diff`)**:
  - Calculates line insertions and deletions.
  - Automatically identifies programming languages (`Python`, `TypeScript`, `JavaScript`, `Go`, `Java`, `Rust`, `C++`, etc.).
  - Detects test changes, documentation changes, and configuration modifications.
- **Symbol & Function Extraction (`extract_functions`)**:
  - Extracts added, modified, and removed functions using AST heuristics and hunk headers (`@@ def name`).
  - Extracts added module-level constants (`PLUS_CONST`).
- **Semantic Hotspots**: Identifies behavioral invariants, design assumptions, and downstream impact areas.

#### Phase 3: Review Planning (`core/review_intelligence/planner.py`)
- **Objective**: Devises a hypothesis-driven review strategy and allocates specialist reviewers.
- **Dynamic Reviewer Allocation (`_deterministic_reviewers`)**:
  - `CORRECTNESS`: Always allocated for all code modifications.
  - `TESTING`: Allocated whenever tests are touched or executable code files are changed.
  - `CODE_QUALITY`: Allocated if PR risk is $\ge$ `medium` or more than 3 files are touched.
  - `DOCUMENTATION`: Allocated if the pull request strictly touches documentation (`.md`, `.rst`).
- **Targeted Retrieval Questions**:
  - Generates concrete `RetrievalQuestion` instances paired with `prefer_symbols` and `prefer_paths` to explore callers, callees, and dependencies.

#### Phase 4: Hybrid Retrieval & Evidence Assembly (`core/hybrid_retriever.py`, `core/agents.py`)
- **Objective**: Gathers relevant repository context without drowning the LLM in noise.
- **Path-Forcing (`diff_chunks_for_paths`)**: Guarantees that diff hunks of changed files are **always** placed in the context window as primary evidence.
- **Dual-Store Search**:
  - Semantic vector search in **Qdrant** using query embeddings.
  - Structural graph exploration in **Neo4j** finding 1-hop and 2-hop caller/callee neighborhoods and imports.
- **Cross-Encoder Structural Reranker (`core/reranker.py`)**:
  - Computes a `structural_bonus` awarding extra weight to exact file path matches (+3.0), package/directory matches (+1.5), and symbol occurrences (+2.0).
- **Global Deduplication (`merge_evidence_packages`)**: Performs a stable rank union across all retrieval questions, capping total chunks at 18 items.
- **Context Summarizer**: Compresses retrieved evidence into a crisp architectural briefing (`summarized_context`).

#### Phase 5: Parallel Specialist Swarm (`core/agents.py`)
- **Objective**: Concurrent deep-dive review across specific engineering axes.
- **Parallel Fan-Out**: LangGraph concurrently dispatches:
  - **`CorrectnessAgent`**: Checks whether the stated bug is actually fixed in the changed lines; tests edge cases (equal priority/ties, empty inputs, order dependence), failure paths, and backward compatibility.
  - **`CodeQualityAgent`**: Evaluates maintainability, hardcoded configs vs extensibility, naming, coupling, and modularity of the changed code.
  - **`TestingAgent`**: Analyzes what new tests actually assert (behavior vs superficial coverage), missing edge cases, and regression risks.
  - **`ContextGatherer`**: Formulates downstream impact notes.
- **Anti-Summarization Contracts**: Prompts forbid agents from describing unchanged helper functions, restating function signatures, or generating empty `"looks good"` findings.
- **Grounding Enforcement (`_ground_specialist_review`)**:
  - Every `blocking` finding must cite a file path present in the PR or retrieved context; ungrounded blockers are automatically demoted to `concern`.
  - Findings must satisfy `is_pr_relevant_finding`, filtering out boilerplate and unrelated code tours.

#### Phase 6: Critic Gate & Decision Engine (`core/agents.py`)
- **Objective**: Reasoning gate that eliminates false positives and issues the definitive review verdict.
- **Critic Gate (`critic_agent`)**:
  - Strips empty findings, boilerplate approvals, and findings with no PR relevance.
  - Deduplicates overlapping findings across different specialists.
  - Resolves contradictions between specialist reviewers.
- **Final Recommender (`final_recommender`)**:
  - Evaluates residual risks and severity distribution:
    - Any `blocking`, `critical`, or `high` finding $\rightarrow$ **`REQUEST_CHANGES`**.
    - Any `medium` or `concern` finding $\rightarrow$ **`COMMENT`**.
    - Only `low`, `verified`, or clean changes $\rightarrow$ **`MERGE`**.
  - Outputs a confidence score ($0.0$ to $1.0$) and a rich, actionable markdown summary.

---

## Repository Intelligence & Dual-Store Hybrid RAG

CodeTurtle rejects simplistic vector-only RAG. A repository is not an unstructured corpus of text; it is an interconnected graph of syntax trees, module boundaries, and execution paths.

```mermaid
flowchart LR
    subgraph InputContext ["Diff & Question Input"]
        Diff["Unified Diff (full_diff)"]
        Plan["ReviewPlan (RetrievalQuestions)"]
    end

    subgraph DualStoreRetrieval ["Dual-Store Retrieval"]
        direction TB
        PathForce["1. Path-Forcing<br/>diff_chunks_for_paths()"]
        VectorQuery["2. Qdrant Vector Search<br/>(Semantic Embeddings)"]
        GraphQuery["3. Neo4j Graph Queries<br/>(Callers, Callees, Imports)"]
    end

    subgraph AssemblyAndRerank ["Reranking & Deduplication"]
        direction TB
        ScoreBonus["Structural Bonus Reranker<br/>• Exact path: +3.0<br/>• Directory match: +1.5<br/>• Symbol match: +2.0"]
        GlobalDedupe["merge_evidence_packages()<br/>(Stable rank union, max 18 chunks)"]
        ContextBuild["ContextBuilder.to_agent_context()<br/>(Diff-First Markdown packing)"]
    end

    Diff --> PathForce
    Plan --> VectorQuery & GraphQuery
    PathForce & VectorQuery & GraphQuery --> ScoreBonus
    ScoreBonus --> GlobalDedupe --> ContextBuild
```

1. **Qdrant Vector Database**:
   - Stores code chunks generated by `core/chunker.py`.
   - Chunks preserve structural metadata: `path`, `symbols`, `start_line`, `end_line`, `chunk_type`, and `chunk_index`.
2. **Neo4j Graph Database**:
   - Node labels: `File`, `Symbol`, `Class`, `Function`.
   - Relationships: `CALLS`, `IMPORTS`, `DEFINES`, `OVERRIDES`.
   - Allows agents to instantly navigate from a modified function to all its upstream call sites.

---

## Decoupled Query Engine Subsystem

Located in `core/query_engine/`, CodeTurtle features a standalone, decoupled read API that isolates storage engines from the rest of the application:

```
core/query_engine/
├── engine.py              # RepositoryQueryEngine (unified high-level read interface)
├── errors.py              # Custom exceptions (GraphUnavailableError, RepoNotIndexedError)
├── types.py               # Pydantic schemas (FileHit, SymbolHit, ImpactReport, CallEdge)
└── routers/
    ├── vector_router.py   # Semantic similarity queries against Qdrant
    ├── graph_router.py    # Cypher queries against Neo4j (calls, imports, paths)
    └── model_router.py    # In-memory symbol and file metadata lookups
```

### Key Capabilities

- **`find_symbol(name, path=None)`**: Locates symbol definitions across the entire codebase.
- **`find_dependencies(path)` / `find_dependents(path)`**: Returns inbound and outbound module dependencies.
- **`find_callers(symbol, path=None)` / `find_callees(symbol, path=None)`**: Traces runtime execution paths.
- **`impact_analysis(paths, symbols)`**: Automatically computes the blast radius of a set of modified files or functions before executing reviews.

---

## AI Gateway & Observability

All LLM interactions pass through a centralized **AI Gateway** (`core/gateway/gateway.py`):

- **Capability-Based Model Routing**: Maps agent roles to specific models and providers:
  - `reasoning` $\rightarrow$ `qwen2.5:7b` (Ollama)
  - `correctness_review` $\rightarrow$ `qwen2.5:7b` (Ollama)
  - `code_quality_review` $\rightarrow$ `qwen2.5:7b` (Ollama)
  - `testing_review` $\rightarrow$ `qwen2.5:7b` (Ollama)
  - `summarization` $\rightarrow$ `qwen2.5:7b` (Ollama)
  - `final_recommendation` $\rightarrow$ `qwen2.5:7b` (Ollama)
- **Multi-Provider Support**: Switch seamlessly between local Ollama instances, OpenAI (`gpt-4o`, `o3-mini`), or any LiteLLM-supported provider via `.env`.
- **Structured Output Retries**: Pydantic schema validation with automatic exponential-backoff retries.
- **Langfuse Observability**: Real-time tracing of prompt/completion tokens, latency, cost estimation, retry counts, and execution trees.

---

## Session Memory & Persistence

CodeTurtle maintains conversation history and multi-turn state in a local SQLite database (`data/codeturtle.db`):

- **`conversations`**: Tracks unique session IDs (`UUID`), creation times, and activity timestamps.
- **`repositories`**: Maps indexed repositories to active sessions.
- **`reviews`**: Stores PR review records, full diffs, findings, confidence ratings, and final verdicts.
- **Active Session Tracking**: Persists the currently active session in `.current_session`.

---

## Repository Structure

The following tree represents the complete codebase layout as built in the `main` branch:

```
CodeTurtle/
├── cli/                                  # Typer CLI application & Rich interface
│   ├── commands/                         # CLI subcommands
│   │   ├── __init__.py
│   │   ├── add_repo.py                   # Index repository into KnowledgeBase
│   │   ├── init.py                       # Check environment configuration
│   │   ├── inspect_kb.py                 # Query repository stats and symbols
│   │   ├── review.py                     # Orchestrates 6-phase review pipeline
│   │   └── session.py                    # Manage sessions (new-session, list-sessions)
│   ├── __init__.py
│   └── main.py                           # CLI entrypoint (`codeturtle`)
│
├── core/                                 # Core review engine & agent swarm
│   ├── gateway/                          # AI Gateway & LLM adapters
│   │   ├── providers/
│   │   │   ├── __init__.py
│   │   │   ├── ollama_provider.py        # Ollama local LLM integration
│   │   │   └── openai_provider.py        # OpenAI API integration
│   │   ├── __init__.py
│   │   └── gateway.py                    # AIGateway capability routing & telemetry
│   │
│   ├── memory/                           # SQLite review session memory
│   │   ├── __init__.py
│   │   ├── database.py                   # SQLite tables & connection management
│   │   └── manager.py                    # Session CRUD operations
│   │
│   ├── query_engine/                     # Decoupled repository query engine
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── graph_router.py           # Neo4j Cypher queries
│   │   │   ├── model_router.py           # In-memory symbol lookup
│   │   │   └── vector_router.py          # Qdrant semantic search
│   │   ├── __init__.py
│   │   ├── engine.py                     # Unified RepositoryQueryEngine API
│   │   ├── errors.py                     # Query engine exceptions
│   │   └── types.py                      # Hit & edge Pydantic schemas
│   │
│   ├── repository_intelligence/          # Whole-codebase parsing & indexing
│   │   ├── compiler/                     # AST symbol resolution & compilation
│   │   ├── graph/                        # Neo4j graph store & query builders
│   │   ├── models/                       # Symbol, Node & Relationship schemas
│   │   ├── parsers/                      # Language AST parsers (Python, TS, JS, Go)
│   │   ├── semantic/                     # Code chunking & vector embeddings
│   │   ├── call_extractor.py             # AST function call hierarchy extractor
│   │   ├── pipeline.py                   # Indexing pipeline coordinator
│   │   └── service.py                    # RepositoryIntelligenceService API
│   │
│   ├── review_intelligence/              # Review planner & hypothesis generation
│   │   ├── __init__.py
│   │   ├── evidence_util.py              # Evidence package normalizers
│   │   ├── models.py                     # ReviewPlan & RetrievalQuestion schemas
│   │   ├── planner.py                    # Phase 3 Review Planner Agent
│   │   └── retrieval_plan.py             # Retrieval query planner models
│   │
│   ├── agents.py                         # Phase 5 Specialists & Phase 6 Critic/Recommender
│   ├── chunker.py                        # AST-aware code chunking (PythonChunker)
│   ├── context_builder.py                # Diff-first prompt context formatter
│   ├── document_builder.py               # Document builder for vector store
│   ├── evidence.py                       # EvidencePackage dataclass & schemas
│   ├── graph.py                          # LangGraph StateGraph review workflow
│   ├── hybrid_retriever.py               # Phase 4 Hybrid retriever & deduplicator
│   ├── knowledge_base.py                 # Qdrant vector store manager
│   ├── llm.py                            # Base LLM initialization
│   ├── llm_gateway.py                    # Gateway bridge
│   ├── models.py                         # Domain schemas (PRUnderstanding, PRAnalysis)
│   ├── observability.py                  # Langfuse tracing & structlog logger
│   ├── pr_analysis.py                    # Phase 2 PR Analysis Agent
│   ├── pr_understanding.py               # Phase 1 PR Understanding Agent
│   ├── query_builder.py                  # RetrievalQuery helpers
│   ├── repository_analyzer.py            # Codebase structural analyzer
│   ├── repository_indexer.py             # Vector indexer
│   ├── repository_model.py               # In-memory repository snapshot
│   ├── repository_persistence.py         # JSON model file persistence
│   ├── reranker.py                       # Cross-encoder & structural reranker
│   ├── state.py                          # LangGraph ReviewState TypedDict
│   └── utils.py                          # Error handling & formatting utilities
│
├── evals/                                # Quantitative evaluation benchmark suite
│   ├── outputs/                          # Evaluation runs and artifact snapshots
│   └── ri/                               # Phase-by-phase review intelligence evals
│       ├── fixtures.py                   # Golden PR snapshots & test fixtures
│       ├── phase1_understanding.py       # Phase 1 evaluation
│       ├── phase2_analysis.py            # Phase 2 evaluation
│       ├── phase3_planner.py             # Phase 3 evaluation
│       ├── phase4_retrieval.py           # Phase 4 evaluation
│       ├── phase5_specialists.py         # Phase 5 evaluation
│       ├── phase6_critic_final.py        # Phase 6 evaluation
│       ├── report.py                     # Evaluation metrics & formatting
│       └── run_all.py                    # Master benchmark suite runner
│
├── manual_tests/                         # Phase-by-phase standalone validation scripts
├── config.py                             # Pydantic Settings & environment loader
├── main.py                               # Package entrypoint
├── pyproject.toml                        # Project dependencies & packaging
└── README.md                             # Documentation
```

---

## Quick Start Guide

### Prerequisites

- **Python**: `^3.10`
- **Package Manager**: [`uv`](https://github.com/astral-sh/uv) (recommended) or `pip`
- **Local LLM**: [Ollama](https://ollama.ai/) installed and running
- **Databases**: [Docker](https://www.docker.com/) for running Qdrant and Neo4j

---

### 1. Installation

Clone the repository and install dependencies:

```bash
git clone https://github.com/venkatpachala/CodeTurtle.git
cd CodeTurtle

# Using uv (recommended)
uv venv
# On Linux/macOS:
source .venv/bin/activate
# On Windows:
.venv\Scripts\activate

uv sync

# Or using standard pip
pip install -e .
```

---

### 2. Environment Configuration

Create a `.env` file in the project root:

```ini
# GitHub Access Token (required for fetching pull requests and repositories)
GITHUB_TOKEN=github_pat_your_personal_access_token_here

# LLM Gateway Configuration
LLM_BACKEND=ollama
OLLAMA_MODEL=qwen2.5:7b
OLLAMA_BASE_URL=http://localhost:11434

# Optional: OpenAI (if routing capabilities to OpenAI)
OPENAI_API_KEY=sk-proj-your-key-here

# Optional: Langfuse Telemetry & Observability
LANGFUSE_PUBLIC_KEY=pk-lf-...
LANGFUSE_SECRET_KEY=sk-lf-...
LANGFUSE_HOST=https://cloud.langfuse.com

# Graph Database (Neo4j)
NEO4J_URI=bolt://localhost:7687
NEO4J_USER=neo4j
NEO4J_PASSWORD=codeturtle123

# Vector Database (Qdrant)
QDRANT_HOST=localhost
QDRANT_PORT=6333
```

---

### 3. Start Local Databases

Run Qdrant and Neo4j using Docker:

```bash
# Start Qdrant Vector Database
docker run -d --name codeturtle-qdrant -p 6333:6333 -p 6334:6334 \
    -v $(pwd)/qdrant_data:/qdrant/storage \
    qdrant/qdrant:latest

# Start Neo4j Graph Database
docker run -d --name codeturtle-neo4j -p 7474:7474 -p 7687:7687 \
    -e NEO4J_AUTH=neo4j/codeturtle123 \
    neo4j:5-community
```

---

### 4. Pull Local Model

Ensure Ollama has the default review model pulled:

```bash
ollama pull qwen2.5:7b
```

---

## CLI Command Reference

All CLI commands are executed via `python -m cli.main`:

### 1. Start a New Review Session

Create an active SQLite session:

```bash
python -m cli.main new-session
```

*Output:*
```
✓ New Session Started
Session ID: 4f18c89b-02b4-4b52-9b2f-48d6174bb7c4
Started at: 2026-09-03 12:00:00
```

To list past sessions:

```bash
python -m cli.main list-sessions
```

---

### 2. Verify Configuration

Validate environment setup:

```bash
python -m cli.main init
```

---

### 3. Index a Repository

Clone (if not already local) and index a codebase into vector and graph stores:

```bash
# Index a GitHub repository
python -m cli.main add-repo Graphify-Labs/graphify

# Force full re-indexing
python -m cli.main add-repo Graphify-Labs/graphify --force
```

---

### 4. Inspect Knowledge Base

Query indexed files, symbols, and stats:

```bash
# Display summary statistics
python -m cli.main inspect-kb Graphify-Labs/graphify --stats

# List indexed symbols
python -m cli.main inspect-kb Graphify-Labs/graphify --symbols

# Search for symbols or filenames
python -m cli.main inspect-kb Graphify-Labs/graphify --search "chunker"
```

---

### 5. Run an Autonomous PR Review

Execute the full 6-phase review swarm on a GitHub pull request:

```bash
# Review a public or private GitHub PR
python -m cli.main review Graphify-Labs/graphify 2400

# Review with verbose trace logs
python -m cli.main review Graphify-Labs/graphify 2400 --verbose

# Dry run (skips posting review comments)
python -m cli.main review Graphify-Labs/graphify 2400 --dry-run
```

---

## Quantitative Evaluation & Benchmark Suite

CodeTurtle includes an automated benchmark suite (`evals/ri/`) that tests each phase of the review pipeline against real-world pull requests with known bugs and changes:

```bash
# Run the complete end-to-end benchmark suite
python evals/ri/run_all.py Graphify-Labs/graphify 2400

# Run specific phase benchmark evaluations
python evals/ri/phase1_understanding.py Graphify-Labs/graphify 2400
python evals/ri/phase2_analysis.py      Graphify-Labs/graphify 2400
python evals/ri/phase3_planner.py       Graphify-Labs/graphify 2400
python evals/ri/phase4_retrieval.py     Graphify-Labs/graphify 2400
python evals/ri/phase5_specialists.py   Graphify-Labs/graphify 2400
python evals/ri/phase6_critic_final.py  Graphify-Labs/graphify 2400
```

### What Each Phase Evaluates

| Phase Eval Script | Evaluation Focus | Acceptance Criteria |
| :--- | :--- | :--- |
| **`phase1_understanding.py`** | Causal chain & risk score | Identifies root cause mechanism; risk is correctly calibrated (medium/high for core bugfixes); zero banned risk fluff. |
| **`phase2_analysis.py`** | Structural AST parsing | Exact line count matches; modified/added functions detected; test function alterations captured. |
| **`phase3_planner.py`** | Review plan formulation | Correctness and Testing reviewers allocated; targeted questions generate relevant symbols. |
| **`phase4_retrieval.py`** | Retrieval quality & dedupe | Path-forcing preserves diff hunks; reranker prioritizes modified symbols; deduplication prevents token overflow. |
| **`phase5_specialists.py`** | Specialist claim validity | Specialists challenge core claims; zero generic "file X does Y" descriptions; blockers cite valid PR paths. |
| **`phase6_critic_final.py`** | Synthesis & decision calibration | Drops boilerplate findings; deduplicates near-identical items; verdict (`MERGE`/`REQUEST_CHANGES`) reflects finding severities. |

---

## Configuration Reference

| Environment Variable | Type | Default | Description |
| :--- | :--- | :--- | :--- |
| `GITHUB_TOKEN` | `str` | `""` | GitHub Personal Access Token (classic or fine-grained) |
| `LLM_BACKEND` | `str` | `"ollama"` | Active LLM backend (`"ollama"`, `"openai"`, `"litellm"`) |
| `OLLAMA_MODEL` | `str` | `"qwen2.5:7b"` | Model tag to invoke in Ollama |
| `OLLAMA_BASE_URL` | `str` | `"http://localhost:11434"` | URL of the local Ollama instance |
| `OPENAI_API_KEY` | `str` | `""` | API key for OpenAI endpoints |
| `NEO4J_URI` | `str` | `"bolt://localhost:7687"` | Bolt protocol URI for Neo4j database |
| `NEO4J_USER` | `str` | `"neo4j"` | Neo4j database username |
| `NEO4J_PASSWORD` | `str` | `""` | Neo4j database password |
| `QDRANT_HOST` | `str` | `"localhost"` | Hostname for Qdrant vector database |
| `QDRANT_PORT` | `int` | `6333` | REST port for Qdrant vector database |
| `LANGFUSE_PUBLIC_KEY` | `str` | `""` | Langfuse observability public key |
| `LANGFUSE_SECRET_KEY` | `str` | `""` | Langfuse observability secret key |
| `LANGFUSE_HOST` | `str` | `"https://cloud.langfuse.com"` | Langfuse host URL |

---

## Contributing

Contributions are warmly welcomed! To contribute:

1. **Fork** the repository and create a feature branch (`git checkout -b feat/my-feature`).
2. Run the evaluation suite on a sample PR to make sure all 6 phases pass:
   ```bash
   python evals/ri/run_all.py Graphify-Labs/graphify 2400
   ```
3. Commit your changes with clear, descriptive messages.
4. Push your branch and open a Pull Request explaining your improvements.

---

