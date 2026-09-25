"""Typed configuration loaded from config.yaml (+ env overrides)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parents[2]


class UltralyticsCfg(BaseModel):
    weights: str = "yolov8n.pt"
    imgsz: int = 960
    device: str | None = None
    min_conf: float = 0.05
    agnostic_nms: bool = True  # one box per object even if the model hesitates between car/bus
    class_map: dict[str, str] = Field(
        default_factory=lambda: {"car": "car", "van": "van", "truck": "truck", "bus": "bus"}
    )


class CallableCfg(BaseModel):
    target: str | None = None


class DetectorCfg(BaseModel):
    kind: Literal["oracle", "ultralytics", "callable"] = "oracle"
    cache: bool = True
    cache_dir: Path = Path("cache/detections")
    tau_op: float = 0.4
    oracle_vehicle_m: tuple[float, float] = (4.5, 2.0)
    # longest box side on the ground; None = off (dev frames' pixel scale does not match their corners)
    plausible_size_m: tuple[float, float] | None = None
    ultralytics: UltralyticsCfg = Field(default_factory=UltralyticsCfg)
    callable: CallableCfg = Field(default_factory=CallableCfg)


class TrackingCfg(BaseModel):
    gate_m: float = 10.0
    box_gate_factor: float = 1.5  # big boxes: gate grows to factor × half-diagonal (m)
    gate_max_m: float = 25.0
    frame_margin_m: float = 5.0  # only tracks inside the frame (+margin) can be seen in it
    window_min: int = 120
    closing_window_min: int = 10
    stop_speed_mps: float = 0.5
    stop_min_steps: int = 2
    approach_closing_mps: float = 1.0
    approach_align: float = 0.7
    leaving_closing_mps: float = -1.0
    moving_speed_mps: float = 1.0


class ReportsCfg(BaseModel):
    radius_m: float = 200.0
    window_min: int = 120
    allow_after_capture: bool = False
    time_aware: bool = True
    stationary_default_min: int = 60
    stationary_min_coverage_min: int = 30
    stationary_max_disp_m: float = 50.0


class RiskWeights(BaseModel):
    proximity_near: int = 30
    proximity_mid: int = 15
    approaching: int = 25
    stop_and_go: int = 10
    heavy: int = 10
    convoy: int = 15
    eta_short: int = 10
    eta_mid: int = 5
    identity_contradicted: int = 20
    identity_confirmed: int = -20
    leaving: int = -15
    untracked: int = 5


class RiskCfg(BaseModel):
    weights: RiskWeights = Field(default_factory=RiskWeights)
    near_km: float = 2.0
    mid_km: float = 3.5
    eta_short_min: float = 5.0
    eta_mid_min: float = 10.0
    load_bonus_per_vehicle: int = 3
    load_bonus_cap: int = 10
    levels: dict[str, int] = Field(default_factory=lambda: {"ORTA": 25, "YUKSEK": 50, "KRITIK": 75})
    convoy_min_size: int = 3
    convoy_heading_tol_deg: float = 30.0
    floor_critical_eta_min: float = 10.0
    floor_high_untracked_km: float = 2.0
    floor_high_untracked_min_conf: float = 0.6


class LLMCfg(BaseModel):
    provider: Literal["mock", "openai_compat"] = "mock"
    prompt_version: str = "analyst_v2"
    temperature: float = 0.2
    max_tokens: int = 3000
    # reasoning models (glm-5.3) otherwise spend the whole token budget thinking; null = don't send
    reasoning_effort: str | None = "low"
    timeout_s: float = 30.0
    max_retries: int = 3  # transient gateway errors (503) are retried by the SDK with backoff
    price_in_per_mtok: float = 0.6
    price_out_per_mtok: float = 2.2
    budget_stop_usd: float = 12.0
    cache: bool = True
    cache_dir: Path = Path("cache/llm")
    max_level_deviation: int = 1


class DemoChatQ(BaseModel):
    question: str
    image_id: str | None = None


class DemoCfg(BaseModel):
    """What `make demo-check` guards: the frames, reports and chat questions the live demo relies on."""

    frames: dict[str, str] = Field(default_factory=lambda: {"img_000860": "KRİTİK"})
    contradicted: dict[str, list[str]] = Field(default_factory=dict)  # frame → reports that must be ÇELİŞİYOR
    no_contradiction: list[str] = Field(default_factory=list)  # frames whose reports must not contradict
    chat: list[DemoChatQ] = Field(default_factory=list)
    chat_max_s: float = 45.0


class ImpactCfg(BaseModel):
    """Shift simulation (#/impact, triage replay). Measured handling times win over these assumptions:
    manual ← calibration/stopwatch.csv (mode=manual); system ← opening→decision log, else stopwatch (mode=system)."""

    manual_min_assumed: float = 6.0  # PROJECT_DESIGN §1.2, Varsayım V5
    system_min_assumed: float = 1.0  # §1.4
    min_measurements: int = 3
    stopwatch_file: Path = Path("calibration/stopwatch.csv")


class ObservabilityCfg(BaseModel):
    runs_dir: Path = Path("runs")
    labels_dir: Path = Path("calibration/labels")  # blind gold-set labels (committed to git)


class Settings(BaseModel):
    root: Path = PROJECT_ROOT
    data_dir: Path = Path("../stage2_dev_data")
    images_subdir: str = "images"
    detector: DetectorCfg = Field(default_factory=DetectorCfg)
    tracking: TrackingCfg = Field(default_factory=TrackingCfg)
    reports: ReportsCfg = Field(default_factory=ReportsCfg)
    risk: RiskCfg = Field(default_factory=RiskCfg)
    llm: LLMCfg = Field(default_factory=LLMCfg)
    observability: ObservabilityCfg = Field(default_factory=ObservabilityCfg)
    demo: DemoCfg = Field(default_factory=DemoCfg)
    impact: ImpactCfg = Field(default_factory=ImpactCfg)

    def path(self, p: Path | str) -> Path:
        """Resolve a config-relative path."""
        p = Path(p)
        return p if p.is_absolute() else (self.root / p).resolve()

    @property
    def data_path(self) -> Path:
        return self.path(self.data_dir)

    @property
    def images_path(self) -> Path:
        return self.data_path / self.images_subdir


def load_settings(path: str | Path | None = None) -> Settings:
    """Load settings; env vars SENTINEL_CONFIG / SENTINEL_DETECTOR / SENTINEL_LLM / SENTINEL_DATA_DIR override."""
    cfg_path = Path(path or os.environ.get("SENTINEL_CONFIG") or PROJECT_ROOT / "config.yaml")
    raw: dict = {}
    if cfg_path.exists():
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
    raw["root"] = cfg_path.resolve().parent if cfg_path.exists() else PROJECT_ROOT
    settings = Settings.model_validate(raw)
    if det := os.environ.get("SENTINEL_DETECTOR"):
        settings.detector.kind = det  # type: ignore[assignment]
    if llm := os.environ.get("SENTINEL_LLM"):
        settings.llm.provider = llm  # type: ignore[assignment]
    if data := os.environ.get("SENTINEL_DATA_DIR"):  # e.g. the official package mounted into Docker
        settings.data_dir = Path(data)
    return settings
