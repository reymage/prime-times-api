"""
LLM provider abstraction.
Switch providers by setting LLM_PROVIDER in env: groq | openai | anthropic
"""
from abc import ABC, abstractmethod

from langchain_core.language_models import BaseChatModel

from app.config import settings


class BaseLLMProvider(ABC):
    @abstractmethod
    def get_client(self, temperature: float) -> BaseChatModel: ...


class GroqLLM(BaseLLMProvider):
    def get_client(self, temperature: float = 0.1) -> BaseChatModel:
        from langchain_groq import ChatGroq

        kwargs: dict = {
            "model": settings.GROQ_MODEL,
            "temperature": temperature,
            "groq_api_key": settings.GROQ_API_KEY,
        }
        # Only override the base URL when using a non-default endpoint (e.g. proxy).
        # langchain-groq already knows the standard Groq API URL; passing the
        # default value causes the path to be appended twice.
        base = settings.GROQ_BASE_URL or ""
        if base and "api.groq.com" not in base:
            kwargs["base_url"] = base
        return ChatGroq(**kwargs)


class OpenAILLM(BaseLLMProvider):
    def get_client(self, temperature: float = 0.1) -> BaseChatModel:
        from langchain_openai import ChatOpenAI

        return ChatOpenAI(
            model=settings.OPENAI_MODEL,
            temperature=temperature,
            openai_api_key=settings.OPENAI_API_KEY,
        )


class AnthropicLLM(BaseLLMProvider):
    def get_client(self, temperature: float = 0.1) -> BaseChatModel:
        from langchain_anthropic import ChatAnthropic

        return ChatAnthropic(
            model=settings.ANTHROPIC_MODEL,
            temperature=temperature,
            anthropic_api_key=settings.ANTHROPIC_API_KEY,
        )


_PROVIDERS: dict[str, BaseLLMProvider] = {
    "groq": GroqLLM(),
    "openai": OpenAILLM(),
    "anthropic": AnthropicLLM(),
}

# Per-provider approximate token costs (USD per token)
COST_PER_TOKEN: dict[str, dict[str, float]] = {
    "groq": {"input": 0.59e-6, "output": 0.79e-6},
    "openai": {"input": 0.15e-6, "output": 0.60e-6},
    "anthropic": {"input": 0.25e-6, "output": 1.25e-6},
}

TAVILY_COST_PER_SEARCH: float = 0.001


def get_llm(temperature: float = 0.1) -> BaseChatModel:
    provider = settings.LLM_PROVIDER.lower()
    if provider not in _PROVIDERS:
        raise ValueError(
            f"Unknown LLM_PROVIDER '{provider}'. Supported: {list(_PROVIDERS)}"
        )
    return _PROVIDERS[provider].get_client(temperature)


def estimate_llm_cost(input_tokens: int, output_tokens: int) -> float:
    provider = settings.LLM_PROVIDER.lower()
    costs = COST_PER_TOKEN.get(provider, COST_PER_TOKEN["groq"])
    return input_tokens * costs["input"] + output_tokens * costs["output"]
