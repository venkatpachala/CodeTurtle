from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import time
import random
from datetime import datetime
from rich.console import Console

from core.gateway.providers import ollama_provider, openai_provider

console = Console()


class GatewayTelemetry(BaseModel):
    """Telemetry for every LLM call."""
    timestamp: datetime
    agent_name: str
    capability: str
    provider: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency: float
    retries: int
    estimated_cost: float = 0.0
    success: bool
    error: Optional[str] = None


class GatewayResponse(BaseModel):
    content: Any          # The parsed object for structured output
    model: str
    provider: str
    usage: Dict[str, Any]
    latency: float
    telemetry: GatewayTelemetry


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
            "reasoning": {"provider": "ollama", "model": "qwen2.5:7b"},
            "correctness_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "final_recommendation": {"provider": "ollama", "model": "qwen2.5:7b"},
            "fast": {"provider": "ollama", "model": "qwen2.5:7b"},
            "summarization": {"provider": "ollama", "model": "qwen2.5:7b"},
            "code_quality_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "security_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "documentation_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "performance_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "api_compatibility_review": {"provider": "ollama", "model": "qwen2.5:7b"},
            "context_gathering": {"provider": "ollama", "model": "qwen2.5:7b"},   # ← Added
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
        agent_name: str = "unknown",
    ) -> GatewayResponse:
        """
        Main entry point for all agents with full observability.
        """
        provider, model = self._get_provider(capability)
        start_time = time.time()
        last_error = None

        for attempt in range(retries):
            try:
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

                telemetry = GatewayTelemetry(
                    timestamp=datetime.now(),
                    agent_name=agent_name,
                    capability=capability,
                    provider=provider.__name__.split('.')[-1],
                    model=model,
                    prompt_tokens=response.usage.get("prompt_tokens", 0),
                    completion_tokens=response.usage.get("completion_tokens", 0),
                    total_tokens=response.usage.get("prompt_tokens", 0) + response.usage.get("completion_tokens", 0),
                    latency=latency,
                    retries=attempt,
                    estimated_cost=0.0,
                    success=True,
                )

                console.print(f"[bold green]✅ LLM Call[/bold green] {agent_name} | {capability} | {model} | {latency:.2f}s | Tokens: {telemetry.total_tokens}")

                return GatewayResponse(
                    content=response.content,
                    model=model,
                    provider=provider.__name__.split('.')[-1],
                    usage=response.usage,
                    latency=latency,
                    telemetry=telemetry,
                )

            except Exception as e:
                last_error = str(e)
                if attempt == retries - 1:
                    break
                time.sleep(2 ** attempt + random.random())

        # Failure case
        latency = time.time() - start_time
        telemetry = GatewayTelemetry(
            timestamp=datetime.now(),
            agent_name=agent_name,
            capability=capability,
            provider=provider.__name__.split('.')[-1],
            model=model,
            prompt_tokens=0,
            completion_tokens=0,
            total_tokens=0,
            latency=latency,
            retries=retries,
            estimated_cost=0.0,
            success=False,
            error=last_error,
        )

        console.print(f"[bold red] LLM Call Failed[/bold red] {agent_name} | {capability} | {model} | {latency:.2f}s | Retries: {retries}")

        raise Exception(f"Gateway failed after {retries} retries: {last_error}")


    def generate_structured(
        self,
        prompt: str,
        schema: BaseModel,
        capability: str = "reasoning",
        temperature: float = 0.2,
        max_tokens: int = 1500,
        retries: int = 3,
        agent_name: str = "unknown",
    ) -> Any:
        """Convenience method for structured output."""
        response = self.generate(
            prompt=prompt,
            capability=capability,
            temperature=temperature,
            max_tokens=max_tokens,
            structured_output=schema,
            retries=retries,
            agent_name=agent_name,
        )
        return response.content  # Returns the parsed Pydantic object directly