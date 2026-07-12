"""Tests de la classification densitométrique HU (non diagnostique)."""

from __future__ import annotations

import numpy as np

from lung_analysis import (
    DENSITY_DISCLAIMER,
    DEFAULT_CLASSES,
    classify_lung_tissue,
)
from segmentation import LungSegmentation
from volume_builder import Volume


def _volume_with_regions() -> tuple[Volume, LungSegmentation]:
    """Volume où l'intérieur du poumon a 4 bandes HU distinctes."""
    nz, ny, nx = 8, 20, 40
    hu = np.full((nz, ny, nx), -1000, dtype=np.int16)  # air de fond
    lung = np.zeros((nz, ny, nx), dtype=bool)
    lung[2:6, 4:16, 4:36] = True
    # 4 bandes de densité dans le poumon.
    hu[2:6, 4:16, 4:12] = -1000   # bronches/air
    hu[2:6, 4:16, 12:20] = -800   # parenchyme normal
    hu[2:6, 4:16, 20:28] = -500   # verre dépoli (approx)
    hu[2:6, 4:16, 28:36] = -100   # fibrose/dense (approx)
    vol = Volume(array=hu, spacing=(1.0, 1.0, 1.0), origin=(0, 0, 0),
                 direction=np.identity(3), series_uid="t", modality="CT")
    seg = LungSegmentation(combined=lung, right=lung.copy(), left=np.zeros_like(lung),
                           voxel_volume_mm3=1.0, warnings=[])
    return vol, seg


def test_classes_present_and_nonempty():
    vol, seg = _volume_with_regions()
    tmap = classify_lung_tissue(vol, seg, include_traction_heuristic=False)
    for c in DEFAULT_CLASSES:
        assert c.name in tmap.classes
    assert tmap.classes["Bronches / air"].sum() > 0
    assert tmap.classes["Verre dépoli (approx.)"].sum() > 0
    assert tmap.classes["Fibrose / dense (approx.)"].sum() > 0


def test_overlay_restricted_to_lung():
    vol, seg = _volume_with_regions()
    tmap = classify_lung_tissue(vol, seg)
    # Aucune classe ne doit sortir du masque pulmonaire.
    for mask in tmap.classes.values():
        assert not np.any(mask & ~seg.combined)


def test_label_volume_and_colors():
    vol, seg = _volume_with_regions()
    tmap = classify_lung_tissue(vol, seg, include_traction_heuristic=False)
    names = list(tmap.classes)
    labels = tmap.label_volume(order=names)
    assert labels.max() <= len(names)
    assert labels.shape == vol.array.shape
    for n in names:
        assert n in tmap.colors


def test_volumes_and_disclaimer():
    vol, seg = _volume_with_regions()
    tmap = classify_lung_tissue(vol, seg)
    m = tmap.metrics()
    assert m["disclaimer"] == DENSITY_DISCLAIMER
    assert tmap.volume_ml("Verre dépoli (approx.)") > 0


def test_traction_heuristic_present():
    vol, seg = _volume_with_regions()
    tmap = classify_lung_tissue(vol, seg, include_traction_heuristic=True)
    assert "Bronchectasie traction (heuristique)" in tmap.classes
    # air au contact du dense -> quelques voxels attendus à la frontière
    assert tmap.classes["Bronchectasie traction (heuristique)"].dtype == bool
