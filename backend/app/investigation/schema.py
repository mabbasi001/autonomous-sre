from pydantic import BaseModel, Field


class ProposedAction(BaseModel):
    action: str
    unit: str | None = None
    pool: str | None = None
    url: str | None = None
    name: str | None = None
    max_lines: int | None = None


class Diagnosis(BaseModel):
    summary: str
    probable_cause: str
    confidence: float = Field(ge=0, le=1)
    evidence_event_ids: list[str] = Field(default_factory=list)
    proposed_actions: list[ProposedAction] = Field(default_factory=list)
