"""Détection récursive, regroupement par série et tri spatial des coupes."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np
from pydicom.dataset import FileDataset

from dicomkit.dicomio.dicom_core import (
    get_transfer_syntax,
    is_valid_dicom_image,
    read_header,
)
from dicomkit.utils import ProgressPrinter

logger = logging.getLogger("dicom_to_images")


@dataclass
class SliceInfo:
    """Une coupe (un fichier) au sein d'une série."""

    path: Path
    instance_number: Optional[int]
    slice_location: Optional[float]
    image_position: Optional[list[float]]
    image_orientation: Optional[list[float]]
    sop_instance_uid: str
    sort_key: float = 0.0


@dataclass
class Series:
    """Une série DICOM regroupée par SeriesInstanceUID."""

    series_uid: str
    study_uid: str
    modality: str
    series_number: Optional[int]
    series_description: str
    study_description: str
    rows: int
    columns: int
    transfer_syntax: str
    slices: list[SliceInfo] = field(default_factory=list)
    # Métadonnées représentatives (premier fichier).
    sample_header: Optional[FileDataset] = None
    sort_order: str = "unsorted"
    category: str = "UNKNOWN"

    @property
    def count(self) -> int:
        return len(self.slices)


def _to_float_list(value) -> Optional[list[float]]:
    if value is None:
        return None
    try:
        return [float(x) for x in value]
    except (TypeError, ValueError):
        return None


def _to_float(value) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _to_int(value) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def classify_series(ds: FileDataset) -> str:
    """Heuristique de classification (aide utilisateur, ne modifie rien)."""
    parts = " ".join(
        str(getattr(ds, attr, "") or "")
        for attr in ("SeriesDescription", "ProtocolName", "ConvolutionKernel")
    )
    image_type = " ".join(str(x) for x in (getattr(ds, "ImageType", []) or []))
    text = f"{parts} {image_type}".upper()

    if "LOCALIZER" in text or "SCOUT" in text or "TOPOGRAM" in text:
        return "SCOUT/LOCALIZER"
    if "LUNG" in text or "PARANCHYME" in text or "PARENCHYM" in text or "POUMON" in text:
        return "LUNG/PARANCHYME"
    if "MEDIAST" in text:
        return "MEDIASTINUM"
    if "BONE" in text or "OS " in text or "OSSEUX" in text:
        return "BONE"
    if "COR" in text:
        return "CORONAL"
    if "SAG" in text:
        return "SAGITTAL"
    return "UNKNOWN"


def scan_directory(root: Path, show_progress: bool = True) -> tuple[list[Series], dict[str, int]]:
    """Parcourt récursivement ``root`` et regroupe les DICOM par série.

    Retourne (liste de séries triées, statistiques de scan).
    """
    all_files = [p for p in root.rglob("*") if p.is_file()]
    stats = {"files_scanned": len(all_files), "dicom_detected": 0, "ignored": 0}
    progress = ProgressPrinter(len(all_files), "Analyse") if show_progress else None

    series_map: dict[str, Series] = {}
    for path in all_files:
        if progress:
            progress.update()
        ds = read_header(path)
        if not is_valid_dicom_image(ds):
            stats["ignored"] += 1
            continue
        stats["dicom_detected"] += 1
        _add_slice(series_map, path, ds)

    if progress:
        progress.done()

    series_list = list(series_map.values())
    for s in series_list:
        _sort_series(s)
    # Tri des séries par SeriesNumber puis description.
    series_list.sort(key=lambda s: (s.series_number if s.series_number is not None else 1_000_000, s.series_description))
    stats["series_detected"] = len(series_list)
    return series_list, stats


def _add_slice(series_map: dict[str, Series], path: Path, ds: FileDataset) -> None:
    uid = str(ds.SeriesInstanceUID)
    if uid not in series_map:
        series_map[uid] = Series(
            series_uid=uid,
            study_uid=str(getattr(ds, "StudyInstanceUID", "")),
            modality=str(getattr(ds, "Modality", "") or ""),
            series_number=_to_int(getattr(ds, "SeriesNumber", None)),
            series_description=str(getattr(ds, "SeriesDescription", "") or "SERIES"),
            study_description=str(getattr(ds, "StudyDescription", "") or ""),
            rows=int(ds.Rows),
            columns=int(ds.Columns),
            transfer_syntax=get_transfer_syntax(ds),
            sample_header=ds,
            category=classify_series(ds),
        )
    series = series_map[uid]
    series.slices.append(
        SliceInfo(
            path=path,
            instance_number=_to_int(getattr(ds, "InstanceNumber", None)),
            slice_location=_to_float(getattr(ds, "SliceLocation", None)),
            image_position=_to_float_list(getattr(ds, "ImagePositionPatient", None)),
            image_orientation=_to_float_list(getattr(ds, "ImageOrientationPatient", None)),
            sop_instance_uid=str(getattr(ds, "SOPInstanceUID", "") or ""),
        )
    )


def _sort_series(series: Series) -> None:
    """Trie les coupes selon la meilleure information spatiale disponible.

    Priorité : projection de ImagePositionPatient sur la normale au plan
    (via ImageOrientationPatient), puis SliceLocation, puis InstanceNumber,
    puis nom de fichier.
    """
    slices = series.slices
    orientation = None
    for s in slices:
        if s.image_orientation and len(s.image_orientation) == 6:
            orientation = s.image_orientation
            break

    if orientation and all(s.image_position for s in slices):
        row = np.array(orientation[0:3], dtype=float)
        col = np.array(orientation[3:6], dtype=float)
        normal = np.cross(row, col)
        for s in slices:
            pos = np.array(s.image_position, dtype=float)
            s.sort_key = float(np.dot(pos, normal))
        slices.sort(key=lambda s: s.sort_key)
        series.sort_order = "ImagePositionPatient projeté sur la normale (croissant)"
        return

    if any(s.slice_location is not None for s in slices):
        slices.sort(key=lambda s: (s.slice_location if s.slice_location is not None else 0.0))
        for s in slices:
            s.sort_key = s.slice_location if s.slice_location is not None else 0.0
        series.sort_order = "SliceLocation (croissant)"
        return

    if any(s.instance_number is not None for s in slices):
        slices.sort(key=lambda s: (s.instance_number if s.instance_number is not None else 0))
        for s in slices:
            s.sort_key = float(s.instance_number) if s.instance_number is not None else 0.0
        series.sort_order = "InstanceNumber (croissant)"
        return

    slices.sort(key=lambda s: s.path.name)
    series.sort_order = "Nom de fichier (croissant)"


def select_indices(count: int, start: Optional[int], end: Optional[int],
                   step: int, parity: Optional[str]) -> list[int]:
    """Calcule les indices (0-based) à exporter après tri spatial.

    ``start``/``end`` sont 1-based inclusifs (comme présentés à l'utilisateur).
    ``parity`` : "odd", "even" ou None. ``step`` : une image sur N.
    """
    lo = (start - 1) if start else 0
    hi = end if end else count
    lo = max(0, lo)
    hi = min(count, hi)
    step = max(1, step)
    indices = list(range(lo, hi, step))
    if parity == "odd":
        indices = [i for i in indices if (i + 1) % 2 == 1]
    elif parity == "even":
        indices = [i for i in indices if (i + 1) % 2 == 0]
    return indices
