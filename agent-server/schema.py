from typing import Literal
from uuid import UUID
from pydantic import BaseModel

class Artifact(BaseModel):
    id: UUID
    # Support code, diff and markdown artifacts to match frontend renderer
    type: Literal["code", "diff", "markdown"]
    title: str
    content: str