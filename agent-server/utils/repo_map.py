import os
from typing import List, Optional

IGNORED_DIRS = {'.git', 'node_modules', 'venv', '__pycache__'}


def _is_ignored(name: str) -> bool:
    return name in IGNORED_DIRS


def _count_files(root_path: str) -> int:
    total = 0
    for dirpath, dirnames, filenames in os.walk(root_path):
        # skip ignored directories during counting
        dirnames[:] = [d for d in dirnames if not _is_ignored(d)]
        total += len(filenames)
    return total


def generate_repo_map(root_path: str) -> str:
    """
    Generate a tree-style map of the repository starting at root_path.
    Skips common large/irrelevant directories and truncates deep trees when file count is large.
    """
    if not os.path.exists(root_path):
        return f"Path not found: {root_path}"

    total_files = _count_files(root_path)
    # If repository is large, limit depth to keep output compact
    max_depth = 3 if total_files > 200 else 1000
    max_lines = 1000

    lines: List[str] = []
    root_name = os.path.basename(os.path.abspath(root_path)) or root_path
    lines.append(root_name + '/')

    def walk_dir(path: str, prefix: str, depth: int):
        nonlocal lines
        if len(lines) >= max_lines:
            return

        try:
            entries = sorted(os.listdir(path))
        except PermissionError:
            lines.append(prefix + '└── [permission denied]')
            return

        # filter ignored
        entries = [e for e in entries if not _is_ignored(e)]
        # sort directories first
        dirs = [e for e in entries if os.path.isdir(os.path.join(path, e))]
        files = [e for e in entries if not os.path.isdir(os.path.join(path, e))]
        ordered = dirs + files

        for idx, name in enumerate(ordered):
            is_last = idx == len(ordered) - 1
            connector = '└── ' if is_last else '├── '
            full = os.path.join(path, name)

            if os.path.isdir(full):
                lines.append(prefix + connector + name + '/')
                if depth + 1 >= max_depth:
                    # indicate truncated contents if there are children
                    try:
                        child_entries = [c for c in os.listdir(full) if not _is_ignored(c)]
                    except PermissionError:
                        child_entries = []
                    if child_entries:
                        lines.append(prefix + ('    ' if is_last else '│   ') + '└── ... (truncated)')
                    continue
                new_prefix = prefix + ('    ' if is_last else '│   ')
                walk_dir(full, new_prefix, depth + 1)
            else:
                lines.append(prefix + connector + name)

            if len(lines) >= max_lines:
                return

    walk_dir(root_path, '', 0)

    return '\n'.join(lines)