from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class PersonCreate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None


class PersonUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None


class PersonOut(BaseModel):
    person_id: int
    first_name: Optional[str] = None
    last_name: Optional[str] = None
    middle_name: Optional[str] = None
    embeddings_count: int = 0
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
