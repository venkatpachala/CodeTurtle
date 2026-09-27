from langchain_openai import ChatOpenAI
from pydantic import BaseModel
import time
import random


class OpenAIResponse:
    def __init__(self, content: str, model: str, usage: dict):
        self.content = content
        self.model = model
        self.usage = usage


def structured_generate(
    prompt: str,
    schema: BaseModel,
    temperature: float = 0.2,
    max_tokens: int = 1500,
    model: str = "gpt-4o",
    retries: int = 3,
) -> OpenAIResponse:
    for attempt in range(retries):
        try:
            llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                timeout=120.0,
                max_retries=0,
            )
            structured_llm = llm.with_structured_output(schema)
            response = structured_llm.invoke(prompt)

            return OpenAIResponse(
                content=response,
                model=model,
                usage={}
            )
        except Exception as e:
            if attempt == retries - 1:
                raise e
            time.sleep(2 ** attempt + random.random())  # Exponential backoff


def generate(prompt: str, temperature: float = 0.2, max_tokens: int = 1500,
             model: str = "gpt-4o-mini") -> OpenAIResponse:
    llm = ChatOpenAI(model=model, temperature=temperature, max_tokens=max_tokens,
                    timeout=120.0, max_retries=0)
    response = llm.invoke(prompt)
    usage = dict(getattr(response, "usage_metadata", None) or {})
    return OpenAIResponse(response.content, model, {
        "prompt_tokens": int(usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("output_tokens") or 0)})
