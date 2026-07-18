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