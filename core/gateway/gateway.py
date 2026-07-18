from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import time
import random

from core.gateway.providers import ollama_provider, openai_provider


class GatewayResponse(BaseModel):
    content: str
    model: str
    provider: str
    usage: Dict[str, Any]
    latency: float


class AIGateway:
    """
    Production-grade AI Gateway.
    """

    def __init__(self):
        self.providers = {
            "ollama": ollama_provider,
            "openai": openai_provider,
        }
        self.default_provider = "ollama"
        self.model_registry = {
            "reasoning": {"provider": "openai", "model": "gpt-4o"},
            "fast": {"provider": "ollama", "model": "qwen2.5:7b"},
            "summarization": {"provider": "ollama", "model": "qwen2.5:7b"},
            "code_quality_review": {"provider": "openai", "model": "gpt-4o-mini"},
            "correctness_review": {"provider": "openai", "model": "gpt-4o"},
            "final_recommendation": {"provider": "openai", "model": "gpt-4o-mini"},
        }

    def _get_provider(self, capability: str):
        config = self.model_registry.get(capability, {"provider": self.default_provider})
        return self.providers[config["provider"]], config["model"]

    def generate(
        self,
        prompt: str,
        capability: str = "reasoning",
        temperature: float = 0.2,
        max_tokens: int = 1500,
        structured_output: Optional[BaseModel] = None,
        retries: int = 3,
    ) -> GatewayResponse:
        """
        Main entry point for all agents with retry logic.
        """
        provider, model = self._get_provider(capability)

        for attempt in range(retries):
            try:
                start_time = time.time()

                if structured_output:
                    response = provider.structured_generate(
                        prompt=prompt,
                        schema=structured_output,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=model
                    )
                else:
                    response = provider.generate(
                        prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=model
                    )

                latency = time.time() - start_time

                return GatewayResponse(
                    content=response.content,
                    model=model,
                    provider=provider.__name__.split('.')[-1],
                    usage=response.usage,
                    latency=latency,
                )
            except Exception as e:
                if attempt == retries - 1:
                    raise e
                time.sleep(2 ** attempt + random.random())  # Exponential backoff

    def generate_structured(
        self,
        prompt: str,
        schema: BaseModel,
        capability: str = "reasoning",
        temperature: float = 0.2,
    ) -> Any:
        """Convenience method for structured output."""
        response = self.generate(
            prompt=prompt,
            capability=capability,
            temperature=temperature,
            structured_output=schema
        )
        return response.content