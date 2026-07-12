"""Gestionnaire extensible de segmentations (multi-classes, import/export).

Architecture prévue pour accueillir plus tard : DICOM SEG, NIfTI, masques de
radiologue, modèles MONAI, correction manuelle. Pour l'instant : conteneur de
masques nommés, colorés, avec opacité/visibilité, superposables sur MPR et 3D.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("dicom_to_images")


@dataclass
class Segmentation:
    """Une segmentation nommée = un masque binaire + apparence."""

    name: str
    mask: np.ndarray                       # bool [z, y, x]
    color: tuple[float, float, float] = (1.0, 0.3, 0.3)
    opacity: float = 0.5
    visible: bool = True

    def voxel_count(self) -> int:
        return int(self.mask.sum())

    def volume_ml(self, voxel_volume_mm3: float) -> float:
        return self.voxel_count() * voxel_volume_mm3 / 1000.0


class SegmentationManager:
    """Collection de segmentations superposables."""

    def __init__(self, reference_shape: Optional[tuple[int, int, int]] = None) -> None:
        self._segs: dict[str, Segmentation] = {}
        self.reference_shape = reference_shape

    def __len__(self) -> int:
        return len(self._segs)

    def names(self) -> list[str]:
        return list(self._segs)

    def get(self, name: str) -> Optional[Segmentation]:
        return self._segs.get(name)

    def add(self, seg: Segmentation, overwrite: bool = True) -> None:
        if self.reference_shape and seg.mask.shape != self.reference_shape:
            raise ValueError(
                f"Masque {seg.mask.shape} incompatible avec le volume "
                f"{self.reference_shape}."
            )
        if not overwrite and seg.name in self._segs:
            raise KeyError(f"Segmentation déjà existante : {seg.name}")
        self._segs[seg.name] = seg

    def add_mask(self, name: str, mask: np.ndarray, **kwargs) -> Segmentation:
        seg = Segmentation(name=name, mask=mask.astype(bool), **kwargs)
        self.add(seg)
        return seg

    def remove(self, name: str) -> None:
        self._segs.pop(name, None)

    def set_visible(self, name: str, visible: bool) -> None:
        if name in self._segs:
            self._segs[name].visible = visible

    def set_opacity(self, name: str, opacity: float) -> None:
        if name in self._segs:
            self._segs[name].opacity = float(np.clip(opacity, 0.0, 1.0))

    def set_color(self, name: str, color: tuple[float, float, float]) -> None:
        if name in self._segs:
            self._segs[name].color = color

    def import_nifti(self, name: str, path: Path, **kwargs) -> Segmentation:
        """Importe un masque depuis un fichier NIfTI (via SimpleITK)."""
        import SimpleITK as sitk

        img = sitk.ReadImage(str(path))
        arr = sitk.GetArrayFromImage(img) > 0  # [z, y, x]
        return self.add_mask(name, arr, **kwargs)

    def export_nifti(self, name: str, path: Path,
                     spacing: Optional[tuple[float, float, float]] = None) -> Path:
        """Exporte un masque en NIfTI (sans donnée nominative)."""
        import SimpleITK as sitk

        seg = self._segs[name]
        img = sitk.GetImageFromArray(seg.mask.astype(np.uint8))
        if spacing:
            img.SetSpacing(spacing)
        sitk.WriteImage(img, str(path))
        return path
