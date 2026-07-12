from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from config import settings

def get_llm(temperature: float = 0.2, streaming: bool = False) -> BaseChatModel:
    """
    Returns Ollama LLM (we can later add support for other local models)
    """
    return ChatOllama(
        model=settings.ollama_model,
        base_url=settings.ollama_base_url,
        temperature=temperature,
        streaming=streaming,
        num_ctx=8192,           # Increase context window
        num_predict=2048,       # Max tokens to generate
    )