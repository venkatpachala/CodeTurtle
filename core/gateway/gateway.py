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
    estimated_cost: float = 0.0   # New: cost tracking


class AIGateway:
    """
    Production-grade AI Gateway with cost tracking.
    """

    def __init__(self):
        self.providers = {
            "ollama": ollama_provider,
            "openai": openai_provider,
        }
        self.default_provider = "ollama"
        self.model_registry = {
            "reasoning": {"provider": "openai", "model": "gpt-4o"},
            "correctness_review": {"provider": "openai", "model": "gpt-4o"},
            "final_recommendation": {"provider": "openai", "model": "gpt-4o-mini"},
            "fast": {"provider": "ollama", "model": "qwen2.5:7b"},
            "summarization": {"provider": "ollama", "model": "qwen2.5:7b"},
            "code_quality_review": {"provider": "openai", "model": "gpt-4o-mini"},
            "security_review": {"provider": "openai", "model": "gpt-4o"},
            "documentation_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "performance_review": {"provider": "openai", "model": "gpt-4o-mini"},
            "api_compatibility_review": {"provider": "openai", "model": "gpt-4o-mini"},
            "default": {"provider": "ollama", "model": "qwen2.5:7b"},
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

                # Simple cost estimation (you can make this more accurate)
                estimated_cost = 0.0
                if "gpt-4o" in model:
                    estimated_cost = 0.01  # placeholder

                return GatewayResponse(
                    content=response.content,
                    model=model,
                    provider=provider.__name__.split('.')[-1],
                    usage=response.usage,
                    latency=latency,
                    estimated_cost=estimated_cost,
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