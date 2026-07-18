from langchain_ollama import ChatOllama
from pydantic import BaseModel


class OllamaResponse:
    def __init__(self, content: str, model: str, usage: dict):
        self.content = content
        self.model = model
        self.usage = usage


def structured_generate(
    prompt: str,
    schema: type[BaseModel],
    temperature: float = 0.2,
    max_tokens: int = 1500,
    model: str = "qwen2.5:7b",
) -> OllamaResponse:
    llm = ChatOllama(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    structured_llm = llm.with_structured_output(schema)
    response = structured_llm.invoke(prompt)

    return OllamaResponse(
        content=response,
        model=model,
        usage={}
    )


def generate(
    prompt: str,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    model: str = "qwen2.5:7b",
) -> OllamaResponse:
    """Plain text generation for non-structured calls."""
    llm = ChatOllama(
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
    )
    response = llm.invoke(prompt)

    return OllamaResponse(
        content=response.content,
        model=model,
        usage={}
    )