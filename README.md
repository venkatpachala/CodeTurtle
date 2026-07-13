# CodeTurtle

> A local-first, multi-agent autonomous code review system with repository intelligence, persistent memory, and full observability.

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-Agent_Orchestration-FF6B6B)](https://langchain-ai.github.io/langgraph/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

CodeTurtle is an **AI-native code review platform** that goes beyond simple diff analysis. It builds a semantic understanding of your entire repository, maintains session memory across reviews, and uses a multi-agent swarm to deliver high-quality, context-aware feedback — all running locally with Ollama.

---

## 🎯 Vision

Transform code review from a manual, context-losing process into a **stateful, repository-aware, and observable AI workflow**.

CodeTurtle has evolved from a simple LLM wrapper into a structured AI engineering system with clear architectural boundaries:

- **Repository Intelligence** (RAG)
- **Context Processing**
- **Multi-Agent Workflow**
- **Persistent Memory**
- **Observability**

---

## ✨ Key Features

- **Repository-Aware RAG** — Indexes your entire codebase into a vector database for semantic retrieval.
- **Context Summarization Layer** — Compresses retrieved context before feeding it to agents.
- **Multi-Agent Review Swarm** — Specialized agents with clearly defined responsibilities.
- **Session Memory** — Remembers previous reviews within a conversation.
- **Full Observability** — Deep integration with Langfuse for tracing, latency, and token usage.
- **Local-First Architecture** — Runs completely on your machine.
- **Production-Oriented Design** — Single `ReviewState`, clean orchestration, and optimization roadmap.

---

## 🏗 Architecture

### High-Level Flow

```mermaid
flowchart TD
    User[User] --> CLI[CodeTurtle CLI]
    CLI --> Session[Session Manager]
    Session --> Memory[(SQLite Memory)]
    
    CLI --> GitHub[GitHub API]
    GitHub --> PR[Pull Request Data]
    
    CLI --> Repo[Repository Manager]
    Repo --> Scanner[Repository Scanner]
    Scanner --> Chunker[Chunking]
    Chunker --> Embed[Embeddings]
    Embed --> Qdrant[(Qdrant Vector DB)]
    
    PR --> Retrieval[Semantic Retrieval]
    Qdrant --> Retrieval
    Retrieval --> Summarizer[Context Summarizer]
    
    Summarizer --> Swarm[LangGraph Multi-Agent Swarm]
    Memory --> Swarm
    
    Swarm --> Output[Review Output]
    Output --> Memory
    Output --> Langfuse[Langfuse Observability]