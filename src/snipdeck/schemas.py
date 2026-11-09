"""Data models: what the model may return (line IDs only) and what is exported (times computed by code)."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

HOOK_TYPES = [
    "physical_violence", "public_humiliation", "betrayal_reveal", "identity_reveal",
    "threat_ultimatum", "shocking_line", "romance_taboo", "rescue_confrontation", "other",
]
CLIFF_TYPES = [
    "unanswered_threat", "reveal_cut_before_reaction", "arrival_of_new_character",
    "choice_or_ultimatum", "betrayal_discovered", "danger_peak", "other",
]


# returned by the model: line IDs only, never timestamps
class RawCandidate(BaseModel):
    episode: int
    start_line: str = Field(description="ID of the first line of the clip, e.g. E07_L012")
    end_line: str = Field(description="ID of the last line of the clip")
    hook_line: str = Field(description="ID of the line that is the scroll-stopping hook (must be within ~3s of start)")
    cliffhanger_line: str = Field(description="ID of the last meaningful line, where tension is left unresolved")
    hook_type: str = "other"
    cliffhanger_type: str = "other"
    open_question: str = Field(default="", description="The question the viewer is left with")
    heur_score: float = 0.0
    answered_at_line: str | None = Field(
        default=None, description="ID of the first line AFTER end_line that resolves the open question, if any")
    why: str = ""


class CandidateBatch(BaseModel):
    candidates: list[RawCandidate] = []


class ScoreItem(BaseModel):
    id: str
    evidence: str = Field(default="", description="Quote the hook line and ending line before scoring")
    hook_3s: int = Field(ge=1, le=5)
    standalone: int = Field(ge=1, le=5)
    cliffhanger: int = Field(ge=1, le=5)
    intensity: int = Field(ge=1, le=5)
    plot_relevance: int = Field(ge=1, le=5)
    trope_fit: int = Field(ge=1, le=5)
    spoiler_risk: bool = False
    ad_policy_risk: bool = False
    needs_context: bool = False
    note: str = ""


class ScoreBatch(BaseModel):
    scores: list[ScoreItem] = []


class RankItem(BaseModel):
    id: str
    reason: str = ""


class RankResult(BaseModel):
    ranking: list[RankItem] = []


class RawSegment(BaseModel):
    start_line: str
    end_line: str


class RawMontage(BaseModel):
    segments: list[RawSegment]
    hook_line: str
    cliffhanger_line: str
    hook_type: str = "other"
    cliffhanger_type: str = "other"
    open_question: str = ""
    why: str = ""


class MontageBatch(BaseModel):
    montages: list[RawMontage] = []


# exported: times computed by code
class Segment(BaseModel):
    episode: int
    start: float
    end: float
    start_ts: str
    end_ts: str
    first_line: str
    last_line: str


class Promo(BaseModel):
    pid: str
    kind: Literal["single", "montage"] = "single"
    source: Literal["llm", "heuristic", "montage"] = "llm"
    segments: list[Segment]
    duration: float
    hook: str
    hook_line_id: str
    hook_type: str = "other"
    cliffhanger: str
    cliffhanger_line_id: str
    cliffhanger_type: str = "other"
    open_question: str = ""
    why: str = ""
    scores: dict[str, float] = {}
    flags: dict[str, bool] = {}
    score_note: str = ""
    heur_score: float = 0.0
    composite: float = 0.0
    final: float = 0.0
    rank: int | None = None
    rank_reason: str = ""
    excerpt: list[str] = []
    attention: dict = {}  # from attention.py: hook_attention, hold, flags


class Rejected(BaseModel):
    source: str
    episode: int | None = None
    start_line: str | None = None
    end_line: str | None = None
    hook_line: str | None = None
    cliffhanger_line: str | None = None
    reason: str
    hint: str = ""        # legal alternatives computed by code (fed back to the model in the repair call)
    repaired: bool = False  # a repair call was made for this rejection
