"""Universal LLM factory.

Provides get_llm(capability) which returns a configured chat model instance
based on agent-server config.
"""
from typing import Literal

import os

from langchain_openai import ChatOpenAI
from langchain_anthropic import ChatAnthropic
from langchain_ollama import ChatOllama

from config import get_settings

Settings = get_settings()


def _ensure_env(key: str, value: str | None) -> None:
    if value:
        os.environ[key] = value


def get_llm(capability: Literal["reasoning", "coding"]):
    """
    Factory that returns a configured chat model for the requested capability.

    Supported providers (from config):
      - "openai": returns ChatOpenAI
      - "anthropic": returns ChatAnthropic
      - "ollama": returns ChatOllama
      - "vscode_lm": placeholder (NotImplementedError)

    Behavior:
      - Reads provider and model id from config for the requested capability.
      - Uses API keys / base URLs from config where applicable.
      - Sets temperature: coding -> 0, reasoning -> 0.6
    """
    if capability not in ("reasoning", "coding"):
        raise ValueError("capability must be 'reasoning' or 'coding'")

    if capability == "reasoning":
        provider = Settings.REASONING_PROVIDER or "ollama"
        model_id = Settings.REASONING_MODEL_ID
        temperature = 0.6
    else:
        provider = Settings.CODING_PROVIDER or "ollama"
        model_id = Settings.CODING_MODEL_ID
        temperature = 0.0

    provider = provider.lower()

    if provider == "openai":
        # Allow overriding OpenAI base url
        _ensure_env("OPENAI_API_KEY", Settings.OPENAI_API_KEY or "")
        if Settings.OPENAI_BASE_URL:
            # LangChain / OpenAI clients pick up OPENAI_API_BASE or OPENAI_BASE_URL depending on env.
            _ensure_env("OPENAI_API_BASE", Settings.OPENAI_BASE_URL)
            _ensure_env("OPENAI_BASE_URL", Settings.OPENAI_BASE_URL)
        try:
            return ChatOpenAI(model_name=model_id, temperature=temperature, openai_api_key=Settings.OPENAI_API_KEY)
        except Exception as e:
            raise ConnectionError(f"OpenAI client initialization failed: {e}")

    if provider == "anthropic":
        # Ensure env for Anthropic client if key present
        _ensure_env("ANTHROPIC_API_KEY", Settings.ANTHROPIC_API_KEY or "")
        try:
            return ChatAnthropic(model=model_id, temperature=temperature)
        except Exception as e:
            raise ConnectionError(f"Anthropic client initialization failed: {e}")

    if provider == "ollama":
        try:
            client = ChatOllama(model=model_id, temperature=temperature)
            # access attribute to ensure initialization
            _ = getattr(client, "model", None)
            return client
        except Exception as e:
            raise ConnectionError(f"Ollama unreachable: {e}")

    if provider == "vscode_lm":
        raise NotImplementedError("vscode_lm provider is a placeholder for future integration")

    raise ValueError(f"Unsupported provider: {provider}")