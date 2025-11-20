"""
Config manager for agent-server.
Loads .env from the agent-server directory if present.
Prefer pydantic-settings (or pydantic.BaseSettings); fallback to os.environ.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional, Any, Dict
import json

# Load .env from this directory if python-dotenv is available
_env_path = Path(__file__).parent / ".env"
try:
    from dotenv import load_dotenv

    if _env_path.exists():
        load_dotenv(dotenv_path=str(_env_path))
except Exception:
    # python-dotenv not installed or failed to load; continue using os.environ
    pass

# Try to use pydantic settings when available
_BaseSettings = None
try:
    from pydantic_settings import BaseSettings as _BaseSettings  # type: ignore
except Exception:
    try:
        from pydantic import BaseSettings as _BaseSettings  # type: ignore
    except Exception:
        _BaseSettings = None


if _BaseSettings is not None:

    class Settings(_BaseSettings):
        REASONING_PROVIDER: str = "ollama"
        REASONING_MODEL_ID: str = "deepseek-r1:7b"
        CODING_PROVIDER: str = "ollama"
        CODING_MODEL_ID: str = "qwen2.5-coder"
        OPENAI_API_KEY: Optional[str] = None
        OPENAI_BASE_URL: Optional[str] = None
        ANTHROPIC_API_KEY: Optional[str] = None
        MCP_SERVERS: Optional[dict] = None

        class Config:
            env_file = str(_env_path) if _env_path.exists() else None
            env_file_encoding = "utf-8"


else:

    class Settings:
        REASONING_PROVIDER: str
        REASONING_MODEL_ID: str
        CODING_PROVIDER: str
        CODING_MODEL_ID: str
        OPENAI_API_KEY: Optional[str]
        OPENAI_BASE_URL: Optional[str]
        ANTHROPIC_API_KEY: Optional[str]

        def __init__(self) -> None:
            self.REASONING_PROVIDER = os.getenv("REASONING_PROVIDER", "ollama")
            self.REASONING_MODEL_ID = os.getenv("REASONING_MODEL_ID", "deepseek-r1:7b")
            self.CODING_PROVIDER = os.getenv("CODING_PROVIDER", "ollama")
            self.CODING_MODEL_ID = os.getenv("CODING_MODEL_ID", "qwen2.5-coder")
            self.OPENAI_API_KEY = os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_KEY")
            self.OPENAI_BASE_URL = os.getenv("OPENAI_BASE_URL")
            self.ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")


# Instantiate once for module-level import
settings = Settings()

# Enforce Ollama as the default provider/model when no cloud API keys are present.
# If a provider requiring cloud keys is configured but the corresponding key is missing,
# fall back to local Ollama models to avoid misconfiguration.
try:
    if (not getattr(settings, "OPENAI_API_KEY", None)) and (not getattr(settings, "ANTHROPIC_API_KEY", None)):
        # If a cloud provider was set via env but no API key is available, revert to ollama.
        if getattr(settings, "REASONING_PROVIDER", None) in ("openai", "anthropic"):
            settings.REASONING_PROVIDER = "ollama"
            settings.REASONING_MODEL_ID = getattr(settings, "REASONING_MODEL_ID", "deepseek-r1:7b") or "deepseek-r1:7b"
        if getattr(settings, "CODING_PROVIDER", None) in ("openai", "anthropic"):
            settings.CODING_PROVIDER = "ollama"
            settings.CODING_MODEL_ID = getattr(settings, "CODING_MODEL_ID", "qwen2.5-coder") or "qwen2.5-coder"
except Exception:
    # best-effort; don't fail import if fallback logic encounters an issue
    pass

# Auto-include bundled RAG MCP server if present.
# This makes the agent auto-register the bundled RAG MCP server as "rag"
# and spawns it using the server's venv Python: .../rag-server/.venv/bin/python server.py
try:
    _base_dir = Path(__file__).parent.parent
    _bundled_rag = _base_dir / "bundled-mcp" / "rag-server"
    _server_py = _bundled_rag / "server.py"
    _venv_python = _bundled_rag / ".venv" / "bin" / "python"
    if _bundled_rag.exists() and _server_py.exists() and _venv_python.exists():
        rag_entry = {"command": str(_venv_python), "args": [str(_server_py)]}
        try:
            current = getattr(settings, "MCP_SERVERS", None) or {}
            # If user provided a dict form, merge the rag entry unless it already exists.
            if isinstance(current, dict):
                if "rag" not in current:
                    current["rag"] = rag_entry
                settings.MCP_SERVERS = current
            # If user provided a list form, append a named entry if not present.
            elif isinstance(current, list):
                if not any(isinstance(e, dict) and e.get("name") == "rag" for e in current):
                    current.append({"name": "rag", "command": str(_venv_python), "args": [str(_server_py)]})
                settings.MCP_SERVERS = current
            else:
                settings.MCP_SERVERS = {"rag": rag_entry}
        except Exception:
            # best-effort; don't fail import if merging settings fails
            pass
except Exception:
    # swallow any unexpected errors during auto-discovery
    pass


def get_settings() -> Settings:
    """Return the singleton settings instance."""
    return settings


__all__ = ["Settings", "settings", "get_settings"]