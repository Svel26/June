from typing import Literal
from uuid import UUID
from pydantic import BaseModel

class Artifact(BaseModel):
    id: UUID
    type: Literal["code", "markdown", "diff"]
    title: str
    content: str