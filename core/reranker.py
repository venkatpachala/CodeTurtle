from typing import List
from langchain_core.documents import Document
from core.llm import get_llm


class Reranker:
    """Simple LLM-based reranker for retrieved documents."""

    def rerank(self, query: str, docs: List[Document], top_k: int = 6) -> List[Document]:
        if not docs:
            return docs

        llm = get_llm(temperature=0.0, max_tokens=800)

        # Create a prompt to score relevance
        prompt = f"""Query: {query}

Documents:
"""
        for i, doc in enumerate(docs):
            prompt += f"\nDocument {i+1}:\n{doc.page_content[:800]}\n---\n"

        prompt += "\nRank the documents by relevance to the query (1 = most relevant). Return only the top {top_k} document numbers in order."

        response = llm.invoke(prompt)

        # Simple parsing (you can improve this)
        try:
            ranked_indices = [int(x) - 1 for x in response.content.split() if x.isdigit()][:top_k]
            ranked_docs = [docs[i] for i in ranked_indices if i < len(docs)]
            return ranked_docs
        except:
            # Fallback to original order
            return docs[:top_k]