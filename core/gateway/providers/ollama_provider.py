from langchain_ollama import ChatOllama
from pydantic import BaseModel
from config import settings


def _usage(response) -> dict:
    usage = dict(getattr(response, "usage_metadata", None) or {})
    meta = dict(getattr(response, "response_metadata", None) or {})
    prompt = int(usage.get("input_tokens") or meta.get("prompt_eval_count") or 0)
    completion = int(usage.get("output_tokens") or meta.get("eval_count") or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion}


class OllamaResponse:
    def __init__(self, content, model: str, usage: dict, metadata: dict | None = None):
        self.content = content
        self.model = model
        self.usage = usage
        self.metadata = metadata or {}


def structured_generate(
    prompt: str,
    schema: type[BaseModel],
    temperature: float = 0.2,
    max_tokens: int = 1500,
    model: str = "qwen2.5-coder:7b",
) -> OllamaResponse:
    response = generate(prompt, temperature, max_tokens, model, response_schema=schema)
    response.content = schema.model_validate_json(response.content)
    return response


def generate(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    model: str = "qwen2.5-coder:7b",
    response_schema: type[BaseModel] | None = None,
) -> OllamaResponse:
    """Plain text generation for non-structured calls."""
    llm = ChatOllama(
        model=model,
        temperature=temperature,
        num_predict=max_tokens,
        num_ctx=settings.ollama_context_tokens,
        format=response_schema.model_json_schema() if response_schema is not None else None,
        base_url=settings.ollama_base_url,
        client_kwargs={"timeout": 120.0},
    )
    response = llm.invoke(prompt)

    return OllamaResponse(
        content=response.content,
        model=model,
        usage=_usage(response),
        metadata={"finish_reason": (response.response_metadata or {}).get("done_reason"),
                  "context_tokens": settings.ollama_context_tokens,
                  "response_format": "json_schema" if response_schema is not None else "text"},
    )
