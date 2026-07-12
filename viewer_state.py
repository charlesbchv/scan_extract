"""Sérialisation JSON d'une session de visualisation (locale, anonyme).

Ne contient jamais d'identifiant patient : on référence la série par son
``SeriesInstanceUID`` (pseudonyme technique) et/ou une empreinte, plus les
réglages de vue. Aucun nom, ID ou date nominative.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Optional

SESSION_VERSION = 1


def series_fingerprint(series_uid: str, n_slices: int) -> str:
    """Empreinte stable et non nominative d'une série."""
    h = hashlib.sha256(f"{series_uid}|{n_slices}".encode("utf-8")).hexdigest()
    return h[:16]


@dataclass
class SegmentationState:
    name: str
    color: list[float]              # RGB 0..1
    opacity: float = 1.0
    visible: bool = True
    mask_file: Optional[str] = None  # chemin relatif d'un masque exporté


@dataclass
class ViewerState:
    """État complet d'une session de visualisation."""

    version: int = SESSION_VERSION
    series_uid: str = ""
    series_fingerprint: str = ""
    input_dir: Optional[str] = None     # chemin relatif éventuel
    preset: str = "lung"
    window_center: float = -600.0
    window_width: float = 1500.0
    opacity: float = 1.0
    density_threshold: float = -500.0
    camera_position: Optional[list[float]] = None
    camera_focal_point: Optional[list[float]] = None
    camera_view_up: Optional[list[float]] = None
    camera_zoom: float = 1.0
    parallel_projection: bool = False
    slice_axial: int = 0
    slice_coronal: int = 0
    slice_sagittal: int = 0
    clipping_enabled: bool = False
    clipping_planes: list[dict[str, Any]] = field(default_factory=list)
    visibility: dict[str, bool] = field(default_factory=dict)
    segmentations: list[SegmentationState] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ViewerState":
        segs = [SegmentationState(**s) for s in data.get("segmentations", [])]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        clean = {k: v for k, v in data.items() if k in known and k != "segmentations"}
        state = cls(**clean)
        state.segmentations = segs
        return state


def save_session(state: ViewerState, path: Path) -> Path:
    """Enregistre la session en JSON. Ne stocke aucun identifiant patient."""
    path = Path(path)
    payload = state.to_dict()
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def load_session(path: Path) -> ViewerState:
    """Recharge une session depuis un fichier JSON."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("version") != SESSION_VERSION:
        # Compatibilité ascendante minimale : on tente quand même.
        data.setdefault("version", SESSION_VERSION)
    return ViewerState.from_dict(data)
