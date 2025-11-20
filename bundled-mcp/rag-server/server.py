#!/usr/bin/env python3
"""
MCP RAG server

Exposes two MCP tools:
- index_codebase(root_path: str)
- search_knowledge(query: str, n_results: int = 5)

Persistant Chroma DB is stored under .cache
Embeddings produced via ollama.embeddings(model='nomic-embed-text')
"""

import os
import re
import uuid
import json
from typing import List, Dict, Any, Optional
from pathlib import Path

# MCP server framework (expected to be available in the environment)
try:
    from modelcontextprotocol.server import MCPServer
except Exception:
    # Fallback minimal shim so module can be imported in environments
    # without the MCP framework while still exposing the functions.
    class MCPServer:  # type: ignore
        def __init__(self):
            self._tools = {}

        def tool(self, fn=None, **kwargs):
            def decorator(f):
                self._tools[f.__name__] = f
                return f
            if fn is None:
                return decorator
            return decorator(fn)

        def serve(self):
            print("MCPServer.serve() called - running in shim mode; no network exposed.")
            print("Registered tools:", list(self._tools.keys()))

server = MCPServer()

# Chromadb persistent client
try:
    import chromadb
    from chromadb.config import Settings
    CHROMA_SETTINGS = Settings(persist_directory=".cache")
    chroma_client = chromadb.Client(CHROMA_SETTINGS)
except Exception:
    chroma_client = None

# Ollama embeddings
try:
    import ollama
except Exception:
    ollama = None

# Helper: safe read file
def _read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        # Try binary decode fallback
        try:
            with open(path, "rb") as f:
                return f.read().decode("utf-8", errors="ignore")
        except Exception:
            return ""

# Helper: basic language detection from extension
def _lang_from_path(path: Path) -> str:
    return path.suffix.lstrip(".").lower() or "text"

# Chunking logic:
# - Try to chunk by top-level function/class definitions (for common languages)
# - Fallback to fixed-size blocks (500 lines)
MAX_LINES_PER_CHUNK = 500

def chunk_file_by_defs(text: str) -> List[Dict[str, Any]]:
    """
    Attempt to split source file into logical chunks using regex for common
    function/class definitions. Returns list of dicts: {'start': int, 'end': int, 'text': str}
    If detection fails or produces too large chunks, fallback to line-block chunking.
    """
    lines = text.splitlines()
    if len(lines) <= MAX_LINES_PER_CHUNK:
        return [{"start": 1, "end": len(lines), "text": text}]

    # Regex patterns to detect top-level defs for various languages
    patterns = [
        r'^\s*def\s+\w+\s*\(',      # python
        r'^\s*class\s+\w+\s*[:\(]', # python, java, etc
        r'^\s*function\s+\w+\s*\(', # javascript
        r'^\s*(?:public|private|protected)\s+.+\s+\w+\s*\(', # java/c#
        r'^\s*#pragma',             # c/c++
    ]
    combined = re.compile("|".join(patterns), re.MULTILINE)

    indices = []
    for i, line in enumerate(lines):
        if combined.match(line):
            indices.append(i)

    chunks = []
    if not indices:
        # fallback to fixed-size chunking by lines
        for i in range(0, len(lines), MAX_LINES_PER_CHUNK):
            start = i + 1
            end = min(i + MAX_LINES_PER_CHUNK, len(lines))
            chunks.append({"start": start, "end": end, "text": "\n".join(lines[i:end])})
        return chunks

    # Build chunks from indices, ensuring none exceed MAX_LINES_PER_CHUNK
    indices.append(len(lines))  # sentinel
    for i in range(len(indices) - 1):
        start_idx = indices[i]
        end_idx = indices[i + 1]
        # Expand end_idx if chunk too small; ensure chunk sizes are within limits
        if (end_idx - start_idx) > MAX_LINES_PER_CHUNK:
            # split this range further
            for j in range(start_idx, end_idx, MAX_LINES_PER_CHUNK):
                s = j
                e = min(j + MAX_LINES_PER_CHUNK, end_idx)
                chunks.append({"start": s + 1, "end": e, "text": "\n".join(lines[s:e])})
        else:
            chunks.append({"start": start_idx + 1, "end": end_idx, "text": "\n".join(lines[start_idx:end_idx])})

    # If first chunk doesn't include header lines before first def, include them
    first_def_line = indices[0] if indices else 0
    if first_def_line > 0:
        header_text = "\n".join(lines[0:first_def_line])
        if header_text.strip():
            chunks.insert(0, {"start": 1, "end": first_def_line, "text": header_text})

    return chunks

def chunk_text_generic(text: str) -> List[Dict[str, Any]]:
    lines = text.splitlines()
    chunks = []
    for i in range(0, len(lines), MAX_LINES_PER_CHUNK):
        start = i + 1
        end = min(i + MAX_LINES_PER_CHUNK, len(lines))
        chunks.append({"start": start, "end": end, "text": "\n".join(lines[i:end])})
    return chunks

# Embedding function
def get_embedding(text: str) -> List[float]:
    """
    Obtain embedding for given text using ollama.embeddings(model='nomic-embed-text')
    Returns embedding vector as list[float].
    """
    if ollama is None:
        raise RuntimeError("ollama package not available in environment")
    # Ollama python API may accept single string or list input; handle both defensively
    try:
        resp = ollama.embeddings(model="nomic-embed-text", input=text)
        # resp may be dict with 'embedding' or list of embeddings
        if isinstance(resp, dict) and "embedding" in resp:
            return resp["embedding"]
        if isinstance(resp, (list, tuple)) and len(resp) > 0:
            # If each item is a dict
            first = resp[0]
            if isinstance(first, dict) and "embedding" in first:
                return first["embedding"]
            # else assume resp is embedding vector
            if all(isinstance(x, (int, float)) for x in resp):
                return list(resp)
    except TypeError:
        # fallback calling with list input
        try:
            resp = ollama.embeddings(model="nomic-embed-text", input=[text])
            if isinstance(resp, list) and resp and isinstance(resp[0], dict) and "embedding" in resp[0]:
                return resp[0]["embedding"]
        except Exception as e:
            raise
    except Exception as e:
        raise

    raise RuntimeError("Unexpected response from ollama.embeddings")

# Ensure collection exists
def _get_collection(name: str = "codebase"):
    if chroma_client is None:
        raise RuntimeError("chromadb client not configured")
    try:
        return chroma_client.get_collection(name)
    except Exception:
        return chroma_client.create_collection(name)

@server.tool
def index_codebase(root_path: str) -> Dict[str, Any]:
    """
    Walks directory at root_path, chunks files (by function or 500-line blocks),
    generates embeddings via ollama, and stores them in ChromaDB (.cache).
    """
    if chroma_client is None:
        return {"ok": False, "error": "chromadb client not available"}

    root = Path(root_path)
    if not root.exists():
        return {"ok": False, "error": f"path not found: {root_path}"}

    coll = _get_collection("codebase")
    added = 0
    skipped = 0
    for dirpath, dirnames, filenames in os.walk(root):
        # skip common large or irrelevant directories
        skip_dirs = {".git", ".cache", "__pycache__", "node_modules", ".venv", "venv"}
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for fname in filenames:
            fpath = Path(dirpath) / fname
            # skip binary-ish by extension heuristics
            if fpath.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".exe", ".dll", ".so", ".bin"}:
                skipped += 1
                continue

            text = _read_text_file(fpath)
            if not text.strip():
                skipped += 1
                continue

            # Try chunk by defs first, else generic chunking
            chunks = chunk_file_by_defs(text)
            if not chunks:
                chunks = chunk_text_generic(text)

            lang = _lang_from_path(fpath)
            for chunk in chunks:
                doc_id = str(uuid.uuid4())
                doc_text = chunk["text"].strip()
                if not doc_text:
                    continue
                try:
                    emb = get_embedding(doc_text)
                except Exception as e:
                    # Skip embedding failures for individual chunks but continue overall
                    skipped += 1
                    continue

                metadata = {
                    "path": str(fpath.relative_to(root)) if fpath.is_relative_to(root) else str(fpath),
                    "full_path": str(fpath),
                    "start_line": int(chunk["start"]),
                    "end_line": int(chunk["end"]),
                    "language": lang,
                }
                try:
                    coll.add(
                        ids=[doc_id],
                        metadatas=[metadata],
                        documents=[doc_text],
                        embeddings=[emb],
                    )
                    added += 1
                except Exception:
                    # Some chroma client versions may not accept embeddings param; try without
                    try:
                        coll.add(ids=[doc_id], metadatas=[metadata], documents=[doc_text])
                        added += 1
                    except Exception:
                        skipped += 1
    # Persist if client supports persist
    try:
        chroma_client.persist()
    except Exception:
        pass

    return {"ok": True, "added": added, "skipped": skipped}

@server.tool
def search_knowledge(query: str, n_results: int = 5) -> Dict[str, Any]:
    """
    Embeds query, searches Chroma, returns top-n matched code snippets with metadata.
    """
    if chroma_client is None:
        return {"ok": False, "error": "chromadb client not available"}

    try:
        q_emb = get_embedding(query)
    except Exception as e:
        return {"ok": False, "error": f"embedding error: {e}"}

    coll = _get_collection("codebase")
    try:
        results = coll.query(
            query_embeddings=[q_emb],
            n_results=n_results,
            include=["documents", "metadatas", "distances"],
        )
    except Exception:
        # adapt to different chroma APIs
        try:
            results = coll.query(q_emb, n_results=n_results)
        except Exception as e:
            return {"ok": False, "error": f"query error: {e}"}

    # Normalize output
    out = []
    docs = results.get("documents") if isinstance(results, dict) else None
    metadatas = results.get("metadatas") if isinstance(results, dict) else None
    distances = results.get("distances") if isinstance(results, dict) else None

    # chroma may return nested lists per query; normalize first element
    if isinstance(docs, list) and docs and isinstance(docs[0], list):
        docs = docs[0]
    if isinstance(metadatas, list) and metadatas and isinstance(metadatas[0], list):
        metadatas = metadatas[0]
    if isinstance(distances, list) and distances and isinstance(distances[0], list):
        distances = distances[0]

    count = max(len(docs or []), len(metadatas or []))
    for i in range(count):
        entry = {
            "document": (docs[i] if docs and i < len(docs) else None),
            "metadata": (metadatas[i] if metadatas and i < len(metadatas) else None),
            "distance": (distances[i] if distances and i < len(distances) else None),
        }
        out.append(entry)

    return {"ok": True, "results": out}

if __name__ == "__main__":
    # When run directly, start the server (or print registered tools in shim)
    server.serve()