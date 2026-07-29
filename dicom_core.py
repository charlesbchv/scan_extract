"""Détection, lecture et décodage des pixels DICOM.

Ce module ne dépend d'aucune interface. Il expose des fonctions courtes et
testables pour :
- détecter un fichier DICOM valide (même sans extension) ;
- extraire les valeurs de pixels en unités correctes (Hounsfield pour CT) ;
- appliquer le fenêtrage et gérer MONOCHROME1/MONOCHROME2.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import numpy as np
import pydicom
from pydicom.dataset import FileDataset

logger = logging.getLogger("dicom_to_images")

# Champs requis pour considérer un fichier comme une image DICOM exploitable.
REQUIRED_FIELDS = (
    "SOPClassUID",
    "StudyInstanceUID",
    "SeriesInstanceUID",
    "Modality",
    "Rows",
    "Columns",
)

# Transfer Syntax -> paquet(s) nécessaire(s), pour messages d'erreur clairs.
DECODER_HINTS: dict[str, str] = {
    "1.2.840.10008.1.2.4.50": "JPEG Baseline nécessite pylibjpeg-libjpeg ou GDCM.",
    "1.2.840.10008.1.2.4.51": "JPEG Extended nécessite pylibjpeg-libjpeg ou GDCM.",
    "1.2.840.10008.1.2.4.57": "JPEG Lossless (Process 14) nécessite pylibjpeg-libjpeg ou GDCM.",
    "1.2.840.10008.1.2.4.70": (
        "JPEG Lossless Process 14 Selection Value 1 nécessite "
        "pylibjpeg-libjpeg ou GDCM."
    ),
    "1.2.840.10008.1.2.4.80": "JPEG-LS Lossless nécessite pylibjpeg-libjpeg ou GDCM.",
    "1.2.840.10008.1.2.4.81": "JPEG-LS Near-Lossless nécessite pylibjpeg-libjpeg ou GDCM.",
    "1.2.840.10008.1.2.4.90": "JPEG 2000 Lossless nécessite pylibjpeg-openjpeg ou GDCM.",
    "1.2.840.10008.1.2.4.91": "JPEG 2000 nécessite pylibjpeg-openjpeg ou GDCM.",
    "1.2.840.10008.1.2.5": "RLE Lossless nécessite pylibjpeg-rle ou pydicom natif.",
}


class DicomDecodeError(RuntimeError):
    """Erreur explicite de décodage, avec indication du paquet manquant."""


@dataclass
class WindowSetting:
    """Fenêtre (center/width) et libellé associé."""

    center: float
    width: float
    preset: str

    def __str__(self) -> str:
        return f"{self.preset}(WC={self.center:g}, WW={self.width:g})"


# Presets de fenêtres CT courants (Hounsfield).
WINDOW_PRESETS: dict[str, tuple[float, float]] = {
    "lung": (-600.0, 1500.0),
    "mediastinum": (40.0, 350.0),
    "bone": (400.0, 1800.0),
}

# Correspondance catégorie de série (voir classify_series) -> preset de fenêtre,
# utilisée par le mode "auto" pour ne pas appliquer une fenêtre pulmonaire aux
# séries médiastin (et inversement).
CATEGORY_WINDOW: dict[str, str] = {
    "LUNG/PARANCHYME": "lung",
    "MEDIASTINUM": "mediastinum",
    "BONE": "bone",
}


def read_header(file_path: Path) -> Optional[FileDataset]:
    """Lit l'en-tête DICOM sans les pixels. Retourne ``None`` si non lisible."""
    try:
        return pydicom.dcmread(
            str(file_path), stop_before_pixels=True, force=True
        )
    except Exception as exc:  # noqa: BLE001 - on veut être robuste
        logger.debug("Lecture en-tête impossible pour %s : %s", file_path, exc)
        return None


def is_valid_dicom_image(ds: Optional[FileDataset]) -> bool:
    """Vrai si le dataset contient les champs cohérents d'une image DICOM.

    Un fichier sans matrice de pixels (Rows/Columns absents ou nuls, ou pas
    de PixelData référencé) n'est pas considéré comme exploitable.
    """
    if ds is None:
        return False
    for field in REQUIRED_FIELDS:
        if not getattr(ds, field, None):
            return False
    try:
        if int(ds.Rows) <= 0 or int(ds.Columns) <= 0:
            return False
    except (TypeError, ValueError):
        return False
    # L'en-tête est lu avec stop_before_pixels=True, donc PixelData n'est pas
    # chargé ici. On exige plutôt les descripteurs de matrice de pixels : un
    # fichier sans image (DICOMDIR, rapport structuré) ne les possède pas.
    if getattr(ds, "BitsAllocated", None) is None:
        return False
    if getattr(ds, "PixelRepresentation", None) is None and \
            getattr(ds, "SamplesPerPixel", None) is None:
        return False
    return True


def get_transfer_syntax(ds: FileDataset) -> str:
    """Retourne le Transfer Syntax UID (défaut Implicit VR LE si absent)."""
    meta = getattr(ds, "file_meta", None)
    if meta is not None and getattr(meta, "TransferSyntaxUID", None):
        return str(meta.TransferSyntaxUID)
    return "1.2.840.10008.1.2"  # Implicit VR Little Endian


def decode_pixels(file_path: Path) -> tuple[np.ndarray, FileDataset]:
    """Lit un fichier complet et retourne (pixel_array, dataset).

    Lève ``DicomDecodeError`` avec un message indiquant le paquet manquant si
    le décodage échoue.
    """
    try:
        ds = pydicom.dcmread(str(file_path), force=True)
    except Exception as exc:  # noqa: BLE001
        raise DicomDecodeError(f"Lecture impossible de {file_path.name} : {exc}") from exc

    tsuid = get_transfer_syntax(ds)
    try:
        arr = ds.pixel_array
    except Exception as exc:  # noqa: BLE001
        hint = DECODER_HINTS.get(tsuid)
        detail = f" ({hint})" if hint else ""
        raise DicomDecodeError(
            f"Impossible de décoder cette série : Transfer Syntax {tsuid}"
            f"{detail} Erreur d'origine : {exc}"
        ) from exc
    return np.asarray(arr), ds


def apply_modality_lut(arr: np.ndarray, ds: FileDataset) -> np.ndarray:
    """Applique RescaleSlope / RescaleIntercept (unités Hounsfield pour CT).

    Ne normalise jamais avant ce rescale. Retourne un tableau float32.
    """
    slope = float(getattr(ds, "RescaleSlope", 1.0) or 1.0)
    intercept = float(getattr(ds, "RescaleIntercept", 0.0) or 0.0)
    out = arr.astype(np.float32)
    if slope != 1.0 or intercept != 0.0:
        out = out * slope + intercept
    return out


def is_monochrome1(ds: FileDataset) -> bool:
    return str(getattr(ds, "PhotometricInterpretation", "")).upper() == "MONOCHROME1"


def apply_window(
    values: np.ndarray, window: WindowSetting, invert: bool = False
) -> np.ndarray:
    """Applique une fenêtre (center/width) et retourne un tableau uint8 [0,255].

    Formule DICOM standard (VOI LUT linéaire). ``invert`` gère MONOCHROME1.
    """
    center = float(window.center)
    width = max(float(window.width), 1.0)
    low = center - width / 2.0
    high = center + width / 2.0
    scaled = (values - low) / (high - low)
    scaled = np.clip(scaled, 0.0, 1.0)
    if invert:
        scaled = 1.0 - scaled
    return (scaled * 255.0 + 0.5).astype(np.uint8)


def resolve_window(
    ds: FileDataset,
    preset: str,
    custom_wc: Optional[float],
    custom_ww: Optional[float],
    category: Optional[str] = None,
) -> WindowSetting:
    """Détermine la fenêtre à utiliser selon le preset demandé.

    En mode ``auto``, la fenêtre est choisie d'après la catégorie de la série
    (``category`` issu de ``classify_series``) : les séries médiastin reçoivent
    une fenêtre parties molles, les séries poumon une fenêtre pulmonaire, etc.
    Si la catégorie est inconnue, repli sur la VOI LUT du fichier (``dicom``).
    """
    preset = preset.lower()
    if preset == "auto":
        mapped = CATEGORY_WINDOW.get(category or "")
        if mapped is None:
            logger.info(
                "Fenêtre auto : catégorie '%s' non mappée, repli sur la VOI LUT DICOM.",
                category,
            )
            return resolve_window(ds, "dicom", custom_wc, custom_ww)
        wc, ww = WINDOW_PRESETS[mapped]
        return WindowSetting(wc, ww, f"auto({mapped})")
    if preset in WINDOW_PRESETS:
        wc, ww = WINDOW_PRESETS[preset]
        return WindowSetting(wc, ww, preset)
    if preset == "custom":
        if custom_wc is None or custom_ww is None:
            raise ValueError("Le mode custom exige --wc et --ww.")
        return WindowSetting(float(custom_wc), float(custom_ww), "custom")
    if preset == "dicom":
        wc = _first_value(getattr(ds, "WindowCenter", None))
        ww = _first_value(getattr(ds, "WindowWidth", None))
        if wc is None or ww is None:
            # Repli raisonnable si le fichier n'a pas de VOI LUT.
            logger.warning(
                "WindowCenter/Width absents ; repli sur fenêtre médiastin."
            )
            return WindowSetting(40.0, 400.0, "dicom(fallback=mediastinum)")
        return WindowSetting(float(wc), float(ww), "dicom")
    raise ValueError(f"Preset de fenêtre inconnu : {preset}")


def _first_value(value: Any) -> Optional[float]:
    """WindowCenter/Width peuvent être multivalués (MultiValue). Prend le 1er."""
    if value is None:
        return None
    try:
        if isinstance(value, (list, tuple)) or hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
            seq = list(value)
            return float(seq[0]) if seq else None
        return float(value)
    except (TypeError, ValueError, IndexError):
        return None


def to_uint16_raw(values: np.ndarray) -> tuple[np.ndarray, dict[str, float]]:
    """Transforme des valeurs (après rescale) vers uint16 sans perte de dynamique.

    Retourne (tableau uint16, paramètres de reconstruction). La transformation
    est ``pixel = (value - offset) * scale`` et est documentée dans metadata.
    """
    vmin = float(np.min(values))
    vmax = float(np.max(values))
    if vmax <= vmin:
        scale = 1.0
    else:
        scale = 65535.0 / (vmax - vmin)
    offset = vmin
    out = np.clip((values - offset) * scale + 0.5, 0, 65535).astype(np.uint16)
    params = {
        "original_min": vmin,
        "original_max": vmax,
        "scale": scale,
        "offset": offset,
        "reconstruct": "value = pixel / scale + offset",
    }
    return out, params
