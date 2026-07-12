"""Conversion des pixels DICOM vers PNG (8/16 bits) et JPEG."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image

from dicom_core import (
    WindowSetting,
    apply_modality_lut,
    apply_window,
    decode_pixels,
    is_monochrome1,
    to_uint16_raw,
)

logger = logging.getLogger("dicom_to_images")


def export_slice_png16(
    src: Path, dst: Path
) -> dict[str, float]:
    """Exporte une coupe en PNG 16 bits brut (dynamique préservée).

    Applique RescaleSlope/Intercept puis une mise à l'échelle documentée vers
    uint16. Retourne les paramètres de reconstruction.
    """
    arr, ds = decode_pixels(src)
    values = apply_modality_lut(arr, ds)
    if is_monochrome1(ds):
        # Pour le PNG 16 bits brut on ne fenêtre pas ; on inverse la dynamique
        # afin de rester cohérent visuellement avec MONOCHROME2.
        vmax = float(np.max(values))
        vmin = float(np.min(values))
        values = (vmax + vmin) - values
    out16, params = to_uint16_raw(values)
    _save_gray(out16, dst, mode="I;16")
    return params


def export_slice_png8(
    src: Path, dst: Path, window: WindowSetting
) -> None:
    """Exporte une coupe en PNG 8 bits fenêtré avec une fenêtre commune."""
    arr, ds = decode_pixels(src)
    values = apply_modality_lut(arr, ds)
    out8 = apply_window(values, window, invert=is_monochrome1(ds))
    _save_gray(out8, dst, mode="L")


def export_slice_jpeg(
    src: Path, dst: Path, window: WindowSetting, quality: int = 95
) -> None:
    """Exporte une coupe en JPEG (avec perte) à partir de l'image fenêtrée 8 bits."""
    arr, ds = decode_pixels(src)
    values = apply_modality_lut(arr, ds)
    out8 = apply_window(values, window, invert=is_monochrome1(ds))
    img = Image.fromarray(out8, mode="L")
    img.save(str(dst), format="JPEG", quality=int(quality), optimize=True)


def _save_gray(arr: np.ndarray, dst: Path, mode: str) -> None:
    """Enregistre un tableau 2D en niveaux de gris. Gère la couleur RGB si besoin."""
    if arr.ndim == 3 and arr.shape[-1] == 3:
        Image.fromarray(arr.astype(np.uint8), mode="RGB").save(str(dst))
        return
    if mode == "I;16":
        img = Image.fromarray(arr.astype(np.uint16))
        # Pillow exige le mode I;16 explicite pour un PNG 16 bits.
        img = Image.frombytes("I;16", (arr.shape[1], arr.shape[0]), arr.astype("<u2").tobytes())
    else:
        img = Image.fromarray(arr.astype(np.uint8), mode="L")
    img.save(str(dst), format="PNG")
