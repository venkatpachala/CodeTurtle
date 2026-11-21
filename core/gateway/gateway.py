from typing import List, Dict, Any, Optional
from pydantic import BaseModel
import time
import random
from datetime import datetime
import hashlib
import json
from rich.console import Console

console = Console()


def _load_provider(name: str):
    try:
        if name == "ollama":
            from core.gateway.providers import ollama_provider as mod

            return mod
        if name == "openai":
            from core.gateway.providers import openai_provider as mod

            return mod
    except ImportError as exc:
        raise RuntimeError(
            f"LLM backend '{name}' is not installed. "
            f"Install with: pip install 'codeturtle-review[{name}]'"
        ) from exc
    raise KeyError(name)


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
    finish_reason: Optional[str] = None
    output_truncated: bool = False
    max_output_tokens: Optional[int] = None
    context_tokens: Optional[int] = None
    response_format: str = "text"
    schema_sha256: Optional[str] = None
    prompt_characters: int = 0


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
        self.default_provider = "ollama"
        default_model = "qwen2.5-coder:7b"
        try:
            from config import settings
            if getattr(settings, "ollama_model", None):
                default_model = str(settings.ollama_model).strip()
        except Exception:
            pass

        self.model_registry = {
            "reasoning": {"provider": "ollama", "model": default_model},
            "correctness_review": {"provider": "ollama", "model": default_model},
            "final_recommendation": {"provider": "ollama", "model": default_model},
            "fast": {"provider": "ollama", "model": default_model},
            "summarization": {"provider": "ollama", "model": default_model},
            "code_quality_review": {"provider": "ollama", "model": default_model},
            "security_review": {"provider": "ollama", "model": default_model},
            "testing_review": {"provider": "ollama", "model": default_model},
            "documentation_review": {"provider": "ollama", "model": default_model},
            "performance_review": {"provider": "ollama", "model": default_model},
            "api_compatibility_review": {"provider": "ollama", "model": default_model},
            "context_gathering": {"provider": "ollama", "model": default_model},   # ← Added
            "default": {"provider": "ollama", "model": default_model},
        }
        from config import settings
        backend = str(settings.llm_backend).lower()
        if backend not in {"ollama", "openai"}:
            raise ValueError(f"Unsupported LLM backend: {backend}")
        if backend == "openai":
            import os
            model = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
            for entry in self.model_registry.values():
                entry.update(provider="openai", model=model)

    def _get_provider(self, capability: str):
        config = self.model_registry.get(capability, {"provider": self.default_provider})
        return _load_provider(config["provider"]), config["model"]

    def generate(
        self,
        prompt: str,
        capability: str = "reasoning",
        temperature: float = 0.2,
        max_tokens: int = 1500,
        structured_output: Optional[BaseModel] = None,
        retries: int = 3,
        agent_name: str = "unknown",
        response_schema: type[BaseModel] | None = None,
    ) -> GatewayResponse:
        """
        Main entry point for all agents with full observability.

        For compatibility, positive ``retries`` values bound total attempts.
        Zero means one request with no retry; it must never skip generation.
        """
        if retries < 0:
            raise ValueError("retries must be nonnegative")
        attempt_limit = max(1, retries)
        if structured_output is not None and response_schema is not None:
            raise ValueError("choose parsed structured_output or raw response_schema")
        provider, model = self._get_provider(capability)
        start_time = time.time()
        last_error = None

        for attempt in range(attempt_limit):
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
                    schema_options = {"response_schema": response_schema} if response_schema is not None else {}
                    response = provider.generate(
                        prompt=prompt,
                        temperature=temperature,
                        max_tokens=max_tokens,
                        model=model,
                        **schema_options,
                    )

                latency = time.time() - start_time
                metadata = getattr(response, "metadata", {}) or {}

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
                    finish_reason=metadata.get("finish_reason"),
                    output_truncated=metadata.get("finish_reason") == "length",
                    max_output_tokens=max_tokens,
                    context_tokens=metadata.get("context_tokens"),
                    response_format=metadata.get("response_format", "text"),
                    schema_sha256=(hashlib.sha256(json.dumps(response_schema.model_json_schema(), sort_keys=True).encode()).hexdigest()
                                   if response_schema is not None else None),
                    prompt_characters=len(prompt),
                )

                try:
                    console.print(f"[bold green][OK] LLM Call[/bold green] {agent_name} | {capability} | {model} | {latency:.2f}s | Tokens: {telemetry.total_tokens}")
                except Exception:
                    pass

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
                if attempt == attempt_limit - 1:
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
            retries=attempt_limit - 1,
            estimated_cost=0.0,
            success=False,
            error=last_error,
        )

        try:
            console.print(f"[bold red][FAIL] LLM Call Failed[/bold red] {agent_name} | {capability} | {model} | {latency:.2f}s | Attempts: {attempt_limit}")
        except Exception:
            pass

        raise RuntimeError(f"Gateway failed after {attempt_limit} attempt(s): {last_error}")


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
