# CodeTurtle System Design Document

CodeTurtle is an **autonomous, local-first multi-agent swarm for repository-aware GitHub code reviews**. Unlike traditional LLM-based code review tools that operate on isolated diff snippets without project context, CodeTurtle indexes and traverses whole-codebase structures (AST symbols, call graphs, import dependencies, and semantic embeddings) using a hybrid vector-graph retrieval architecture, Graphify Model Context Protocol (MCP) integration, and a deterministic 6-phase LangGraph agent pipeline with multi-layer verification gates.

---

## 1. High-Level System Architecture

```mermaid
flowchart TB
    %% Entry Layer
    subgraph ClientLayer ["1. User & Interface Layer"]
        CLI["Typer CLI (cli/main.py)<br/>• review<br/>• add-repo<br/>• inspect-kb<br/>• graphify-test<br/>• session"]
        GitHubAPI["GitHub REST / GraphQL API<br/>• Pull Requests & Metadata<br/>• Unified Diffs<br/>• Commit Head SHA"]
        CLI <--> GitHubAPI
    end

    %% Ingestion & Knowledge Layer
    subgraph IngestionLayer ["2. Repository Intelligence & Knowledge Base"]
        direction TB
        GitWorktree["Local Git Worktree (repos/)"]
        ASTParser["AST Language Parsers<br/>(Python, TS, JS, Go, Java, Rust)"]
        Chunker["AST-Aware Code Chunker<br/>(chunker.py)"]
        ImportResolver["Call Graph & Import Resolver<br/>(import_resolver.py)"]

        GitWorktree --> ASTParser & Chunker & ImportResolver

        subgraph StorageLayer ["Dual-Store Index & MCP Knowledge"]
            Qdrant[("Qdrant Vector DB<br/>Semantic Embeddings")]
            Neo4j[("Neo4j Graph DB<br/>AST Call Hierarchy")]
            GraphifyEngine[("Graphify Knowledge Graph<br/>graphify-out/graph.json")]
        end

        Chunker --> Qdrant
        ASTParser & ImportResolver --> Neo4j
        GitWorktree --> GraphifyEngine

        MCPAdapter["Graphify MCP Adapter<br/>(core/repository_knowledge/graphify_mcp.py)<br/>• query • get_node • get_neighbors<br/>• shortest_path • get_pr_impact"]
        GraphifyEngine <--> MCPAdapter
    end

    %% Query Engine Subsystem
    subgraph QueryLayer ["3. Repository Query Engine (core/query_engine/)"]
        direction LR
        VRouter["VectorRouter<br/>(Qdrant)"]
        GRouter["GraphRouter<br/>(Neo4j)"]
        MRouter["ModelRouter<br/>(Capability-based)"]
        UnifiedEngine["RepositoryQueryEngine<br/>(Retrieval & Impact Analysis)"]
        
        VRouter & GRouter & MRouter --> UnifiedEngine
        Qdrant -.-> VRouter
        Neo4j -.-> GRouter
    end

    %% LangGraph Review Swarm
    subgraph SwarmLayer ["4. LangGraph Autonomous Review Swarm (core/graph.py)"]
        direction TB
        
        P1["Phase 1: PR Understanding Agent<br/>(Causal Intent, Risk Scoring, Scope Boundaries)"]
        P2["Phase 2: PR Analysis Agent<br/>(Diff Parsing, Modified Symbols, Hotspots)"]
        P3["Phase 3: Review Planner Agent<br/>(Hypothesis-Driven Questions, Gated Specialists)"]
        
        P4["Phase 4: Hybrid Retriever & Evidence Deduplicator<br/>(Diff-First Hunks, Symbol Search, Cross-Encoder Reranker)"]
        P4Sum["Context Summarizer<br/>(Distills evidence into focused context)"]

        subgraph ParallelSpecialists ["Phase 5: Parallel Specialist Swarm"]
            direction LR
            Correctness["Correctness Agent<br/>(Invariants & Claims)"]
            CodeQuality["Code Quality Agent<br/>(Structure & Extensibility)"]
            TestingAgent["Testing Agent<br/>(Assertions & Coverage Gaps)"]
            ContextGatherer["Context Gatherer<br/>(Breadcrumbs & Context)"]
        end

        subgraph ValidationGates ["Phase 5.5 - 5.8: Multi-Stage Verification Pipeline"]
            direction TB
            Validator["Deterministic Finding Validator<br/>(L1–L5 Fail-Fast Rules, No LLM)"]
            Investigator["Bounded Investigation Loop<br/>(Graphify MCP Tool Hops)"]
            HunkVerifier["Hunk-Level Claim Verifier<br/>(Supported / Uncertain / Unsupported)"]
            Executor["Sandboxed Test Execution<br/>(Isolated Pytest in Git Worktree)"]

            Validator --> Investigator --> HunkVerifier --> Executor
        end

        subgraph DecisionGates ["Phase 6: Critic Gate & Decision Engine"]
            direction LR
            Critic["Critic Agent<br/>(Deduplication & Grounding Filter)"]
            Recommender["Final Recommender<br/>(MERGE / REQUEST_CHANGES / COMMENT)"]
            Critic --> Recommender
        end

        P1 --> P2 --> P3 --> P4 --> P4Sum
        P4Sum --> ParallelSpecialists
        ParallelSpecialists --> Validator
        Executor --> Critic
    end

    %% AI Gateway & Telemetry
    subgraph GatewayLayer ["5. AI Gateway & Infrastructure (core/gateway/)"]
        direction TB
        AIGateway["AI Gateway (gateway.py)<br/>• Capability Registry<br/>• Schema Enforcement & Retries<br/>• Cost & Latency Tracking"]
        
        subgraph Providers ["LLM Provider Adapters"]
            Ollama["Ollama (Local Default)<br/>qwen2.5:7b, llama3"]
            OpenAI["OpenAI<br/>gpt-4o, o3-mini"]
            LiteLLM["LiteLLM Unified"]
        end

        Langfuse["Langfuse Observability<br/>(Traces, Tokens, Latencies)"]
        SessionDB[("SQLite Session DB<br/>(~/.codeturrle/memory/)")]

        AIGateway --> Providers
        AIGateway --> Langfuse
        Recommender --> SessionDB
    end

    %% Cross-subsystem bindings
    CLI --> SwarmLayer
    UnifiedEngine -.-> P4
    MCPAdapter -.-> P4 & Investigator
    SwarmLayer <--> AIGateway
```

---

## 2. Core Subsystems & Components

### 2.1 Interface & CLI Layer (`cli/`)
Built with **Typer** and styled with **Rich**:
- **`codeturtle review <owner/repo> <pr_number>`**: Orchestrates repository checkout, diff extraction, knowledge retrieval, and invokes the LangGraph swarm.
- **`codeturtle add-repo <path>`**: Triggers AST-aware chunking and builds dual-store indexes (Qdrant vectors + Neo4j/Graphify graphs).
- **`codeturtle graphify-test <owner/repo>`**: Interactively queries the Graphify knowledge base via Model Context Protocol (`--stats`, `--query`, `--node`, `--from/--to`).
- **`codeturtle inspect-kb <repo>`**: Queries vector embeddings and symbol relationships.
- **`codeturtle session`**: Manages SQLite review sessions and multi-turn state.

---

### 2.2 Dual-Store Knowledge & Graphify MCP Integration (`core/repository_knowledge/` & `core/repository_intelligence/`)
CodeTurtle enforces an abstraction boundary separating code review agents from underlying graph engines through `RepositoryKnowledgeProvider`.

```mermaid
classDiagram
    class RepositoryKnowledgeProvider {
        <<interface>>
        +get_node(name: str) Node
        +get_neighbors(name: str, depth: int) NeighborsResult
        +query(question: str, depth: int) QueryResult
        +shortest_path(from_node: str, to_node: str) PathResult
        +get_pr_impact(pr_number: int, repo: str) ImpactResult
        +stats() StatsResult
    }

    class GraphifyMCPProvider {
        -client: ClientSession
        -transport: StdioClientTransport / HttpClient
        +connect()
        +disconnect()
        +get_node(name: str) Node
        +get_neighbors(name: str, depth: int) NeighborsResult
        +query(question: str, depth: int) QueryResult
        +shortest_path(from_node: str, to_node: str) PathResult
    }

    class Neo4jKnowledgeProvider {
        -driver: Neo4jDriver
        +run_cypher(query: str, params: dict)
    }

    RepositoryKnowledgeProvider <|.. GraphifyMCPProvider
    RepositoryKnowledgeProvider <|.. Neo4jKnowledgeProvider
```

1. **Vector Store (Qdrant)**:
   - Stores code chunks created by `chunker.py`.
   - Chunks preserve structural metadata (`path`, `symbols`, `start_line`, `end_line`, `chunk_type`).
2. **Knowledge Graph (Neo4j / Graphify)**:
   - Preserves AST hierarchies, class inheritance, function calls (`CALLS`), and module dependencies (`IMPORTS`).
3. **Graphify MCP Protocol Bridge**:
   - Spawns a dedicated MCP server via stdio or connects via HTTP (`http://localhost:8080/mcp`).
   - Translates high-level agent queries into graph traversals to uncover non-local architectural side effects.

---

### 2.3 The 6-Phase Review Intelligence Swarm (`LangGraph`)

The core execution engine is a compiled LangGraph `StateGraph` operating over a shared `ReviewState` structure.

```mermaid
sequenceDiagram
    autonumber
    actor User as Engineer / CI
    participant CLI as CLI / ReviewPipeline
    participant P1 as Phase 1: PR Understanding
    participant P2 as Phase 2: PR Analysis
    participant P3 as Phase 3: Review Planner
    participant P4 as Phase 4: Hybrid Retriever
    participant P5 as Phase 5: Specialist Swarm
    participant V as Phase 5.5: L1-L5 Validator
    participant Inv as Phase 5.6: Bounded Investigation
    participant Ver as Phase 5.7: Hunk Claim Verifier
    participant Exe as Phase 5.8: Sandbox Pytest
    participant P6 as Phase 6: Critic & Final Decision
    participant GW as AI Gateway (Ollama/OpenAI)

    User->>CLI: codeturtle review owner/repo 42
    CLI->>CLI: Fetch PR, Build Full Diff & PR Facts
    CLI->>P1: Invoke Graph with initial ReviewState

    Note over P1,GW: Phase 1: Intent & Risk
    P1->>GW: Classify intent, risk, and boundary constraints
    P1->>P1: Deterministic refine_understanding (rule guardrails)
    P1->>P2: Emit PRUnderstanding

    Note over P2,GW: Phase 2: Structural Diff Analysis
    P2->>P2: Parse diff hunks deterministically (functions, classes, tests)
    P2->>GW: Identify logic changes and risk hotspots
    P2->>P3: Emit PRAnalysis

    Note over P3,GW: Phase 3: Review Planning
    P3->>P3: Rule-based & LLM-guided reviewer allocation
    P3->>P3: Formulate targeted retrieval hypotheses
    P3->>P4: Emit ReviewPlan

    Note over P4,P4: Phase 4: Diff-First Retrieval
    P4->>P4: Force diff hunks (primary ground truth)
    P4->>P4: Query vector store + Graphify MCP hops
    P4->>P4: Cross-Encoder Reranking & Global Deduplication
    P4->>P5: EvidencePackage + Summarized Context

    Note over P5,GW: Phase 5: Parallel Specialist Swarm
    par Parallel Agent Dispatch
        P5->>GW: CorrectnessAgent (Claims & Invariants)
        P5->>GW: CodeQualityAgent (Structure & Maintainability)
        P5->>GW: TestingAgent (Edge cases & Test Coverage)
        P5->>P5: ContextGatherer (Supplementary context)
    end
    P5->>V: Raw Specialist Findings

    Note over V,Exe: Verification & Guardrails Pipeline
    V->>V: L1–L5 Deterministic Validation (No LLM)
    V->>Inv: Validated Findings
    alt Finding needs investigation
        Inv->>Inv: Bounded Graphify MCP exploration (max calls/timeout)
    end
    Inv->>Ver: Investigation Evidence + Hypotheses
    Ver->>Ver: Hunk-level verification (Supported / Uncertain / Unsupported)
    opt execute_tests enabled
        Ver->>Exe: Sandboxed pytest in PR worktree
        Exe->>Exe: Run target tests, report failure slices
    end
    Exe->>P6: Stamped, verified findings

    Note over P6,GW: Phase 6: Critic Gate & Decision Engine
    P6->>GW: CriticAgent (Deduplication, Hallucination Filter)
    P6->>GW: FinalRecommender (MERGE / REQUEST_CHANGES / COMMENT)
    P6-->>CLI: Final Review State
    CLI->>User: Render Rich Terminal Markdown Review
```

---

## 3. Detailed Phase Specifications

| Phase | Module | Primary Purpose | Key Algorithms / Guardrails |
| :--- | :--- | :--- | :--- |
| **Phase 1: PR Understanding** | `pr_understanding.py` | Extracts causal intent, risk tier, and scope boundaries. | `refine_understanding`: Core path bugfixes automatically bumped to medium risk; filters banned subjective risk phrases. |
| **Phase 2: PR Analysis** | `pr_analysis.py` | AST/hunk parsing of changed symbols, modified classes, lines, and tests. | Deterministic diff hunk parser (`analyze_diff`), symbol context recovery, hotspot detection. |
| **Phase 3: Review Planning** | `review_intelligence/planner.py` | Hypothesis-driven query generation and specialist reviewer gating. | Dynamic reviewer allocation: `CORRECTNESS` (always), `TESTING` (if code/test changed), `CODE_QUALITY` (if risk $\ge$ medium or $>3$ files). Formulates targeted questions. |
| **Phase 4: Hybrid Retrieval** | `hybrid_retriever.py` | Combines path-forced diff hunks with vector similarity and graph neighbors. | **Diff-First Context Packing**: Unified diff leads context; cross-encoder reranker (`reranker.py`); `merge_evidence_packages` global deduplicator. |
| **Phase 5: Specialist Swarm** | `agents.py` | Parallel specialist reviewers challenging claims under anti-summarization contracts. | Explicit Pydantic schemas (`SpecialistReview`); forced concrete claims (`SpecialistFinding.claim`); positive confirmation (`verified`). |
| **Phase 5.5: Finding Validator** | `finding_validator.py` | Deterministic verification of finding grounding (Zero LLM reliance). | **L1–L5 Validation Gates**: Checks evidence existence, PR path membership, trivial file exclusion, code-vs-trivia mismatch, and diff symbol validation. |
| **Phase 5.6: Bounded Investigation** | `investigation/loop.py` | Explores graph neighborhoods for uncertain claims. | Bounded Graphify MCP calls (`get_node`, `get_neighbors`, `query`, `shortest_path`), hypothesis tracking, strict timeout guardrails. |
| **Phase 5.7: Claim Verification** | `verification/loop.py`, `hunk_verifier.py` | Cross-checks claims directly against unified diff hunks. | Stamps findings with status: `supported`, `uncertain`, `unsupported`. Suggests policy-based review recommendation. |
| **Phase 5.8: Sandboxed Execution** | `verification/execute.py` | Optional active test verification. | Path-jailed worktree runner, no `shell=True`, timeout enforcement, lockfile PR skip logic, isolated venv/uv sync. |
| **Phase 6: Critic & Recommendation** | `agents.py` | Final review synthesis, contradiction resolution, and decision issuing. | `CriticAgent` removes redundant claims and cross-contradictions; `FinalRecommender` computes confidence and outputs structured markdown comment. |

---

## 4. Multi-Layer Guardrail & Anti-Hallucination Pipeline

A cornerstone of CodeTurtle's architecture is its **defense-in-depth against LLM hallucination and shallow summarization**:

```mermaid
flowchart TD
    RawFindings["Raw Specialist Findings (Phase 5)"] --> Norm["Normalizer & Path Repair<br/>(Fills omitted changed paths if mentioned in text)"]
    
    subgraph L1L5 ["Deterministic L1–L5 Validator (finding_validator.py)"]
        direction TB
        L1{"L1: Evidence Exists?"} -->|No| Drop1["DROP: missing_evidence_path"]
        L1 -->|Yes| L2{"L2: Path in PR Files?"}
        L2 -->|No| Drop2["DROP: evidence_not_in_pr"]
        L2 -->|Yes| L3{"L3: Trivial File Only?<br/>(e.g., LICENSE, .gitignore)"}
        L3 -->|Yes, but code changed| Drop3["DROP: trivial_evidence_only"]
        L3 -->|No| L4{"L4: Discusses code but<br/>cites trivial file?"}
        L4 -->|Yes| Drop4["DROP: discussed_code_but_cited_trivial_file"]
        L4 -->|No| L5{"L5: Symbol in Diff?"}
        L5 -->|No| Drop5["DROP: unknown_symbol"]
        L5 -->|Yes| PassL["PASS: Kept Findings"]
    end

    Norm --> L1
    PassL --> Inv{"Needs Investigation?"}
    
    subgraph BoundedInv ["Bounded Investigation Loop (investigation/loop.py)"]
        Inv -->|Yes| GCall["Graphify MCP Tool Calls<br/>(get_node, get_neighbors, shortest_path)<br/>Budget: Max 6 calls, Timeout: 30s"]
        GCall --> Reval["Re-validate against PR Facts"]
        Inv -->|No| HunkCheck
        Reval --> HunkCheck
    end

    subgraph HunkVer ["Hunk-Level Verification (verification/loop.py)"]
        HunkCheck["Regex & AST Hunk Matching"] --> Classify["Classify Status:<br/>• Supported<br/>• Uncertain<br/>• Unsupported"]
    end

    Classify --> CriticGate["Critic Agent & Decision Engine (Phase 6)"]
```

---

## 5. AI Gateway & Provider Abstraction (`core/gateway/`)

All LLM calls within CodeTurtle route through a centralized `AIGateway`:

```mermaid
flowchart LR
    subgraph Agents ["Agents (P1–P6)"]
        P1A["PR Understanding"]
        P2A["PR Analysis"]
        P3A["Review Planner"]
        P5A["Specialists"]
        P6A["Critic & Recommender"]
    end

    subgraph Gateway ["AI Gateway (gateway.py)"]
        Router{"Capability Registry<br/>• reasoning<br/>• correctness_review<br/>• code_quality_review<br/>• testing_review<br/>• summarization"}
        RetryEngine["Schema Enforcement Loop<br/>(Automatic Pydantic Validation & Retries)"]
        Telemetry["Telemetry Tracker<br/>(Tokens, Latency, Cost, Errors)"]
    end

    subgraph Backends ["LLM Providers"]
        OllamaLocal["Ollama (qwen2.5:7b, llama3)"]
        OpenAICloud["OpenAI (gpt-4o, o3-mini)"]
        LiteLLMProvider["LiteLLM Endpoint"]
    end

    subgraph Observability ["Telemetry & Observability"]
        LangfuseCloud["Langfuse Client (Tracing & Spans)"]
        RichConsole["Rich Console Logs"]
    end

    Agents --> Router
    Router --> RetryEngine
    RetryEngine --> Backends
    RetryEngine --> Telemetry
    Telemetry --> LangfuseCloud & RichConsole
```

- **Capability Mapping**: Decouples prompt requirements from concrete models (e.g. `correctness_review` $\rightarrow$ `ollama / qwen2.5:7b`).
- **Pydantic Structured Output**: Enforces valid JSON according to strongly typed schemas; re-prompts on parsing errors up to configurable retry limits.
- **Full Observability**: Logs prompt tokens, completion tokens, latency, retry counts, and estimated cost per agent execution into **Langfuse**.

---

## 6. Persistence & State Data Structures

### 6.1 Unified Review State (`core/state.py`)
```python
class ReviewState(TypedDict):
    repo: str
    number: int
    title: str
    body: str
    author: str
    full_diff: str
    files_changed: List[str]
    pr_facts: NotRequired[dict]
    
    # Review Intelligence
    pr_understanding: Optional[dict]
    pr_analysis: Optional[PRAnalysis]
    review_plan: Optional[dict]
    evidence_package: Optional[Dict]
    summarized_context: str

    # Findings
    correctness_findings: List[Finding]
    quality_findings: List[Finding]
    testing_findings: List[Finding]
    validated_findings: List[Finding]
    findings: List[Finding]

    # Verification & Reports
    hypotheses: NotRequired[list]
    investigation_evidence: NotRequired[list]
    investigation_report: NotRequired[dict]
    verification_report: NotRequired[dict]
    execution_report: NotRequired[dict]

    # Decisions & Metadata
    critique: Dict
    final_comment: Dict
    recommendation: Literal["MERGE", "REQUEST_CHANGES", "COMMENT"]
    traces: Annotated[List[dict], operator.add]
```

### 6.2 SQLite Session Memory (`core/memory/`)
Stored under `~/.codeturrle/memory/memory.db`:
- **`sessions` table**: Tracks active session UUIDs, repository context, and target pull requests.
- **`reviews` table**: Persists historical review outputs, findings, recommendations, confidence scores, and raw state for multi-turn conversational queries.

---

## 7. Technology Stack Summary

| Layer | Component / Technology | Justification / Role |
| :--- | :--- | :--- |
| **CLI & UI** | Typer, Rich | Ergonomic command-line flags, interactive terminals, and markdown tables. |
| **Agent Orchestration** | LangGraph, LangChain | Deterministic graph state transitions, parallel fan-out / fan-in execution. |
| **Protocol Integration** | Model Context Protocol (MCP stdio/HTTP) | Decoupled client-server graph queries against Graphify knowledge graphs. |
| **Vector Database** | Qdrant (`qdrant-client`, `langchain-qdrant`) | High-performance embedding similarity search with rich metadata filtering. |
| **Graph Database** | Neo4j (`neo4j`), Graphify | Deep AST symbol and import dependency traversal, shortest paths, neighborhood analysis. |
| **LLM Gateway** | Ollama, OpenAI SDK, LiteLLM | Local-first inference with zero cloud dependency; cloud fallbacks on demand. |
| **Observability** | Langfuse, Structlog | Per-agent token tracking, distributed trace visualization, latency analysis. |
| **Evaluation Suite** | Python benchmark harnesses (`evals/ri/`) | Phase-by-phase quantitative benchmarking on real-world pull requests. |
