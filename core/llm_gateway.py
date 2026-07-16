import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.language_models.chat_models import BaseChatModel
from litellm import completion
import structlog

load_dotenv()

logger = structlog.get_logger()

class LLMGateway:
    def __init__(self):
        self.default_model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        self.ollama_base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

    def get_llm(self, model: str = None, temperature: float = 0.3, max_tokens: int = 1024) -> BaseChatModel:
        """Return LLM with support for routing"""
        model = model or self.default_model

        if "ollama" in model.lower():
            return ChatOllama(
                model=model,
                base_url=self.ollama_base_url,
                temperature=temperature,
                num_predict=max_tokens,
                num_ctx=8192,
            )
        else:
            # Future: support other providers via LiteLLM
            logger.info("Using LiteLLM for non-Ollama model", model=model)
            # For now, fallback to Ollama
            return ChatOllama(
                model=self.default_model,
                base_url=self.ollama_base_url,
                temperature=temperature,
                num_predict=max_tokens,
                num_ctx=8192,
            )


# Global instance
llm_gateway = LLMGateway()