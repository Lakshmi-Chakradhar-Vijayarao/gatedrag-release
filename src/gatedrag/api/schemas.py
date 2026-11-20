"""Request/response models (Pydantic) and the authenticated principal."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Principal:
    user: str
    groups: frozenset[str]


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)


class AskResponse(BaseModel):
    request_id: str
    answer: str
    decision: str
    support: float
    regenerated: bool
    citations: list[str]
    timings_ms: dict
