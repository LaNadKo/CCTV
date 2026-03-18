from typing import List, Optional
from pydantic import BaseModel


class AppearanceItem(BaseModel):
    event_id: int
    event_ts: str
    camera_id: int
    camera_name: Optional[str] = None
    person_id: Optional[int] = None
    person_label: Optional[str] = None
    confidence: Optional[float] = None


class AppearanceReport(BaseModel):
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    person_id: Optional[int] = None
    total: int = 0
    items: List[AppearanceItem] = []
