from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from config import settings

def get_llm(temperature: float = 0.3, max_tokens: int = 1024) -> BaseChatModel:
    """Returns Ollama LLM with output length control"""
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        num_predict=max_tokens,      # This controls max output length
        num_ctx=8192,
    )