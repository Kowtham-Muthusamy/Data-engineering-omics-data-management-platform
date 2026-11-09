from datetime import datetime
from typing import Annotated, Any, Optional

from pydantic import BaseModel, ConfigDict, PlainSerializer

# Timestamps are stored as naive UTC; always serialise with a Z so browsers parse them as UTC.
UtcDt = Annotated[datetime, PlainSerializer(lambda d: d.isoformat() + "Z", return_type=str, when_used="json")]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class ErrorOut(BaseModel):
    detail: Any


class Page(BaseModel):
    total: int
    items: list[Any]
