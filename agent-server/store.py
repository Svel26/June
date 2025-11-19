# Simple in-memory task store
TASK_STORE = {}

def create_task(task_id):
    """Create a new task entry if it doesn't exist."""
    if task_id in TASK_STORE:
        return TASK_STORE[task_id]
    TASK_STORE[task_id] = {"id": task_id, "state": None}
    return TASK_STORE[task_id]

def update_task_state(task_id, state):
    """Update the state of an existing task. Create if missing."""
    task = TASK_STORE.get(task_id)
    if not task:
        task = create_task(task_id)
    task["state"] = state
    return task

def get_task(task_id):
    """Return the task dict or None if not found."""
    return TASK_STORE.get(task_id)