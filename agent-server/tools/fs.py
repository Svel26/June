"""Filesystem tools for the agent server, restricted to the current working directory sandbox."""
import os
from typing import List
from langchain_core.tools import tool

ROOT = os.getcwd()

def validate_path(path: str) -> str:
    """
    Validate a user-supplied path and return an absolute path within the sandbox ROOT.
    Raises ValueError if the path attempts to escape the sandbox or is absolute.
    """
    if path is None:
        raise ValueError("Path must be provided")
    # Disallow absolute paths to force usage of sandbox-relative paths
    if os.path.isabs(path):
        raise ValueError("Absolute paths are not allowed. Use a path relative to the working directory.")
    normalized = os.path.normpath(path)
    # Prevent path components that escape the sandbox
    parts = normalized.split(os.sep)
    if any(p == ".." for p in parts):
        raise ValueError("Access outside the sandbox is forbidden")
    # Construct full path and ensure it still resides under ROOT
    full = os.path.join(ROOT, normalized)
    full = os.path.normpath(full)
    if not full.startswith(os.path.normpath(ROOT) + os.sep) and full != os.path.normpath(ROOT):
        raise ValueError("Resolved path is outside the sandbox")
    return full

@tool
def list_files(path: str = ".") -> List[str]:
    """
    List files and directories directly under the given directory (relative to sandbox).
    Returns a list of names (not full paths).
    """
    full = validate_path(path)
    if not os.path.exists(full):
        raise ValueError(f"Path does not exist: {path}")
    if not os.path.isdir(full):
        raise ValueError(f"Not a directory: {path}")
    try:
        return sorted(os.listdir(full))
    except OSError as e:
        raise ValueError(f"Error listing directory {path}: {e}")

@tool
def read_file(path: str) -> str:
    """
    Read a file from the sandbox and return its contents as a string.
    """
    full = validate_path(path)
    if not os.path.exists(full):
        raise ValueError(f"Path does not exist: {path}")
    if not os.path.isfile(full):
        raise ValueError(f"Not a file: {path}")
    try:
        with open(full, "r", encoding="utf-8") as f:
            return f.read()
    except OSError as e:
        raise ValueError(f"Error reading file {path}: {e}")

@tool
def write_file(path: str, content: str) -> str:
    """
    Write content to a file inside the sandbox. Creates parent directories as needed.
    Returns a short confirmation message.
    """
    full = validate_path(path)
    parent = os.path.dirname(full)
    if parent and not os.path.exists(parent):
        os.makedirs(parent, exist_ok=True)
    try:
        with open(full, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Wrote {len(content)} bytes to {path}"
    except OSError as e:
        raise ValueError(f"Error writing file {path}: {e}")