"""Domain models shared by every layer. This module depends on nothing but pydantic.

Times are kept as minutes since midnight (single-day data); `hhmm()` renders them back.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


# --------------------------------------------------------------------------- time
def to_min(hhmm: str) -> int:
    h, m = hhmm.strip().split(":")
    return int(h) * 60 + int(m)


def hhmm(t_min: float) -> str:
    t = int(round(t_min))
    return f"{t // 60:02d}:{t % 60:02d}"


# --------------------------------------------------------------------------- enums
Label = Literal["car", "van", "truck", "bus", "unknown"]
HEAVY_LABELS: frozenset[str] = frozenset({"truck", "bus"})
LABEL_TR: dict[str, str] = {
    "car": "otomobil",
    "van": "panelvan",
    "truck": "kamyon",
    "bus": "otobüs",
    "unknown": "araç",
}


class RiskLevel(StrEnum):
    DUSUK = "DÜŞÜK"
    ORTA = "ORTA"
    YUKSEK = "YÜKSEK"
    KRITIK = "KRİTİK"

    @property
    def rank(self) -> int:
        return _LEVEL_ORDER.index(self)

    @classmethod
    def from_rank(cls, rank: int) -> RiskLevel:
        return _LEVEL_ORDER[max(0, min(rank, len(_LEVEL_ORDER) - 1))]

    @property
    def icon(self) -> str:
        return {"DÜŞÜK": "○", "ORTA": "●", "YÜKSEK": "▲", "KRİTİK": "▲▲"}[self.value]


_LEVEL_ORDER = [RiskLevel.DUSUK, RiskLevel.ORTA, RiskLevel.YUKSEK, RiskLevel.KRITIK]


class ClaimType(StrEnum):
    COUNT = "COUNT"
    PRESENCE = "PRESENCE"
    STATIONARY = "STATIONARY"
    MOVING_TO_BASE = "MOVING_TO_BASE"
    LEAVING = "LEAVING"
    TRANSIT = "TRANSIT"
    NORMAL_BEHAVIOR = "NORMAL_BEHAVIOR"
    FRIENDLY_ID = "FRIENDLY_ID"
    ZONE_NO_HEAVY = "ZONE_NO_HEAVY"
    ZONE_NORMAL = "ZONE_NORMAL"
    DENSITY = "DENSITY"
    NOISE = "NOISE"
    UNKNOWN = "UNKNOWN"


class Verdict(StrEnum):
    DOGRULANDI = "DOĞRULANDI"
    CELISIYOR = "ÇELİŞİYOR"
    DOGRULANAMAZ = "DOĞRULANAMAZ"
    ILGISIZ = "İLGİSİZ"

    @property
    def icon(self) -> str:
        return {"DOĞRULANDI": "✓", "ÇELİŞİYOR": "✗", "DOĞRULANAMAZ": "?", "İLGİSİZ": "—"}[self.value]


# --------------------------------------------------------------------------- raw data
class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True)


class Corners(_Frozen):
    top_left: tuple[float, float]
    top_right: tuple[float, float]
    bottom_left: tuple[float, float]
    bottom_right: tuple[float, float]


class ImageMeta(_Frozen):
    image_id: str
    width_px: int
    height_px: int
    capture_time: str
    corner_coordinates: Corners

    @property
    def capture_min(self) -> int:
        return to_min(self.capture_time)


class Base(_Frozen):
    name: str
    lat: float
    lon: float


class Zone(_Frozen):
    name: str
    center: tuple[float, float]


class TrackPoint(_Frozen):
    t_min: int
    lat: float
    lon: float


class Track(_Frozen):
    track_id: str
    points: tuple[TrackPoint, ...]

    @property
    def t_start(self) -> int:
        return self.points[0].t_min

    @property
    def t_end(self) -> int:
        return self.points[-1].t_min


class FieldReport(_Frozen):
    report_id: str
    time: str
    source: Literal["official", "third_party"]
    text: str

    @property
    def t_min(self) -> int:
        return to_min(self.time)


# --------------------------------------------------------------------------- perception
class Detection(BaseModel):
    """Kaggle submission format: label conf x y w h (px, top-left)."""

    det_id: str
    label: Label
    conf: float
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2


class GeoDetection(BaseModel):
    detection: Detection
    lat: float
    lon: float
    d_base_m: float
    bearing_deg: float
    direction: str
    zone: str


# --------------------------------------------------------------------------- tracking
class Match(BaseModel):
    det_id: str
    track_id: str
    dist_m: float
    margin_m: float | None = Field(None, description="2. en yakın track − en yakın (m)")
    second_track_id: str | None = None


class StopSegment(BaseModel):
    start: str
    end: str
    minutes: int


class Kinematics(BaseModel):
    track_id: str
    t_now: str
    d_now_m: float
    d_start_m: float
    d_change_m: float = Field(description="pencere başı − şimdi (+ yaklaştı)")
    closing_mps: float = Field(description="son N dk üsse yaklaşma hızı (+ yaklaşıyor)")
    align_cos: float
    speed_now_mps: float
    speed_mean_mps: float
    speed_max_mps: float
    path_m: float
    heading_deg: float | None
    heading_dir: str | None
    stops: list[StopSegment]
    stop_total_min: int
    stop_and_go: bool
    approaching: bool
    leaving: bool
    eta_min: float | None
    zones_passed: list[str]
    window: tuple[str, str]
    d_series: list[tuple[str, float]]


class TrackSnapshot(BaseModel):
    track_id: str
    time: str
    lat: float
    lon: float
    dist_m: float | None = None
    d_base_m: float | None = None


# --------------------------------------------------------------------------- reports
class Claim(BaseModel):
    report_id: str
    types: list[ClaimType]
    lat: float | None = None
    lon: float | None = None
    zone: str | None = None
    vehicle_labels: list[str] = Field(default_factory=list, description="boş = herhangi araç")
    vehicle_word: str | None = None
    count: int | None = None
    color: str | None = None
    stationary_min: int | None = None
    usual_count: int | None = None
    parsed_by: Literal["regex", "llm"] = "regex"

    @property
    def is_noise(self) -> bool:
        return ClaimType.NOISE in self.types

    @property
    def has_point(self) -> bool:
        return self.lat is not None and self.lon is not None


class ReportVerification(BaseModel):
    report_id: str
    time: str
    source: str
    text: str
    claim: Claim
    verdict: Verdict
    reason: str
    relevance: str = ""
    evidence_refs: list[str] = Field(default_factory=list)
    related_tracks: list[str] = Field(default_factory=list)
    identity_claim: bool = False
    dist_to_frame_m: float | None = None


# --------------------------------------------------------------------------- risk + evidence
class RiskFactor(BaseModel):
    code: str
    label: str
    points: int
    vehicle_ref: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)


class VehicleEvidence(BaseModel):
    ref: str
    det_id: str
    label: Label
    conf: float
    bbox: tuple[float, float, float, float]
    lat: float
    lon: float
    d_base_m: float
    direction: str
    promoted: bool = Field(False, description="τ_op altındaydı, track eşleşmesiyle terfi etti")
    track_id: str | None = None
    match_m: float | None = None
    margin_m: float | None = None
    second_track_id: str | None = None
    kinematics: Kinematics | None = None
    score: int = 0
    factors: list[RiskFactor] = Field(default_factory=list)


class RiskAssessment(BaseModel):
    score: int
    score_level: RiskLevel
    floor_level: RiskLevel | None = None
    floor_reasons: list[str] = Field(default_factory=list)
    level: RiskLevel
    factors: list[RiskFactor] = Field(default_factory=list, description="kare düzeyi faktörler")
    top_vehicle: str | None = None


class FrameInfo(BaseModel):
    image_id: str
    capture_time: str
    zone: str
    center_lat: float
    center_lon: float
    d_base_m: float
    direction: str
    width_m: float
    height_m: float
    width_px: int
    height_px: int
    corners: Corners


class EvidencePacket(BaseModel):
    image_id: str
    frame: FrameInfo
    detector: str
    vehicles: list[VehicleEvidence]
    untracked: list[str] = Field(default_factory=list, description="track'siz tespit ref'leri")
    undetected_tracks: list[str] = Field(default_factory=list)
    low_conf: list[Detection] = Field(default_factory=list)
    reports: list[ReportVerification] = Field(default_factory=list)
    risk: RiskAssessment
    uncertainties: list[str] = Field(default_factory=list)

    def vehicle(self, ref: str) -> VehicleEvidence | None:
        return next((v for v in self.vehicles if v.ref == ref), None)


# --------------------------------------------------------------------------- brief
class KeyFinding(BaseModel):
    vehicle_ref: str | None = None
    statement: str
    evidence_refs: list[str] = Field(default_factory=list)


class ReportAssessment(BaseModel):
    report_id: str
    verdict: Verdict
    reason: str


class RiskBrief(BaseModel):
    image_id: str
    risk_level: RiskLevel
    risk_score: int
    headline: str
    key_findings: list[KeyFinding]
    report_assessment: list[ReportAssessment] = Field(default_factory=list)
    recommended_action: str
    confidence: Literal["düşük", "orta", "orta-yüksek", "yüksek"] = "orta"
    uncertainties: list[str] = Field(default_factory=list)
    level_rationale: str | None = None


class GroundingResult(BaseModel):
    checked: int = 0
    failed: list[str] = Field(default_factory=list)
    unknown_refs: list[str] = Field(default_factory=list)
    level_ok: bool = True
    level_issue: str | None = None

    @computed_field  # serialised so the UI badge does not re-derive it
    @property
    def passed(self) -> bool:
        return not self.failed and not self.unknown_refs and self.level_ok


class EvaluationResult(BaseModel):
    run_id: str
    packet: EvidencePacket
    brief: RiskBrief
    brief_source: Literal["llm", "llm_cache", "template"]
    grounding: GroundingResult
    llm_note: str | None = None
    timings_ms: dict[str, float] = Field(default_factory=dict)


class OperatorDecision(BaseModel):
    decision_id: str
    run_id: str
    image_id: str
    action: Literal["approve", "override", "escalate", "undo"]
    level: RiskLevel | None = None
    reason: str = ""
    at: str


class TriageRow(BaseModel):
    image_id: str
    zone: str
    capture_time: str
    level: RiskLevel
    score: int
    d_base_m: float
    headline: str
    n_vehicles: int
    reports_contradicted: int
    reports_confirmed: int
    # Queue scanability (added for the operator row; all from the packet, nothing new is computed)
    min_eta_min: float | None = Field(None, description="yaklaşan araçlar arasında en kısa ETA")
    n_approaching: int = 0
    n_heavy: int = Field(0, description="kamyon/otobüs sayısı")
    decision: OperatorDecision | None = Field(
        None, description="operatörün geçerli kararı (geri alınanlar düşülür)"
    )
