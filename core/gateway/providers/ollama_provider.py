from langchain_ollama import ChatOllama
from pydantic import BaseModel


class OllamaResponse:
    def __init__(self, content: str, model: str, usage: dict):
        self.content = content
        self.model = model
        self.usage = usage


def structured_generate(
    prompt: str,
    schema: BaseModel,
    temperature: float = 0.2,
    max_tokens: int = 1500,
) -> OllamaResponse:
    llm = ChatOllama(
        model="qwen2.5:7b",
        temperature=temperature,
        max_tokens=max_tokens
    )
    structured_llm = gateway.generate_structured(schema)
    response = structured_llm.invoke(prompt)

    return OllamaResponse(
        content=response,
        model="qwen2.5:7b",
        usage={}
    )