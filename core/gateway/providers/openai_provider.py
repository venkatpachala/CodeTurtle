from langchain_openai import ChatOpenAI
from pydantic import BaseModel


class OpenAIResponse:
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
    model: str = "gpt-4o",
) -> OpenAIResponse:
    response = generate(prompt, temperature, max_tokens, model, response_schema=schema)
    response.content = schema.model_validate_json(response.content)
    return response


def generate(prompt: str, temperature: float = 0.2, max_tokens: int = 1500,
             model: str = "gpt-4o-mini", response_schema: type[BaseModel] | None = None) -> OpenAIResponse:
    llm = ChatOpenAI(model=model, temperature=temperature, max_tokens=max_tokens,
                    timeout=120.0, max_retries=0)
    if response_schema is not None:
        llm = llm.bind(response_format={"type": "json_schema", "json_schema": {
            "name": response_schema.__name__, "schema": response_schema.model_json_schema(), "strict": True}})
    response = llm.invoke(prompt)
    usage = dict(getattr(response, "usage_metadata", None) or {})
    return OpenAIResponse(response.content, model, {
        "prompt_tokens": int(usage.get("input_tokens") or 0),
        "completion_tokens": int(usage.get("output_tokens") or 0)},
        {"finish_reason": (response.response_metadata or {}).get("finish_reason"),
         "response_format": "json_schema" if response_schema is not None else "text"})
