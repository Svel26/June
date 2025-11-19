"""LLM helper to create an Ollama Chat client."""

from langchain_ollama import ChatOllama


def get_llm() -> ChatOllama:
    """
    Return a configured ChatOllama instance.

    Raises:
        ConnectionError: If Ollama is unreachable.
    """
    model_name = "qwen2.5-coder"
    temperature = 0
    try:
        client = ChatOllama(model=model_name, temperature=temperature)
        # Access a simple attribute to ensure the client initialized properly
        _ = client.model
        return client
    except Exception as e:
        raise ConnectionError(f"Ollama unreachable: {e}")