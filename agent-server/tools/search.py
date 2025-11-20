"""Search tool using glob to find files containing a query."""
import os
import glob
from typing import List
from langchain_core.tools import tool

ROOT = os.getcwd()

@tool
def search_code(query: str) -> List[str]:
    """
    Search workspace files for occurrences of `query`.
    Skips common virtual env and dependency directories.
    Returns list of relative file paths where `query` is found.
    """
    if not query:
        return []

    pattern = os.path.join(ROOT, "**", "*")
    found: List[str] = []
    excluded_dirs = {".git", "node_modules", "venv", "__pycache__"}

    for path in glob.iglob(pattern, recursive=True):
        if os.path.isdir(path):
            continue
        rel = os.path.relpath(path, ROOT)
        parts = rel.split(os.sep)
        if any(p in excluded_dirs for p in parts):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                content = f.read()
        except Exception:
            # skip unreadable/binary files
            continue
        if query in content:
            found.append(rel.replace(os.sep, "/"))

    return found