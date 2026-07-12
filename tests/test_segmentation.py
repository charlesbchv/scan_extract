"""Tests de segmentation pulmonaire sur volume synthétique."""

from __future__ import annotations

import numpy as np

from segmentation import SEG_DISCLAIMER, segment_lungs
from segmentation_manager import Segmentation, SegmentationManager
from tests.conftest_3d import make_synthetic_volume


def test_segment_finds_two_lungs():
    vol = make_synthetic_volume()
    seg = segment_lungs(vol)
    assert seg.combined.sum() > 0
    assert seg.right.sum() > 0
    assert seg.left.sum() > 0
    # Les deux poumons ne se recouvrent pas.
    assert not np.any(seg.right & seg.left)


def test_left_right_separation_sides():
    vol = make_synthetic_volume()
    seg = segment_lungs(vol)
    # direction identité -> poumon droit = x bas.
    cx_right = np.mean(np.where(seg.right)[2])
    cx_left = np.mean(np.where(seg.left)[2])
    assert cx_right < cx_left


def test_volume_ml_positive_and_ordered():
    vol = make_synthetic_volume()
    seg = segment_lungs(vol)
    m = seg.metrics()
    assert m["volume_total_ml"] > 0
    assert m["disclaimer"] == SEG_DISCLAIMER
    # Comparaison sur les valeurs brutes (les métriques sont arrondies à 0.1 ml).
    assert abs(seg.volume_total_ml - (seg.volume_right_ml + seg.volume_left_ml)) < 1e-6


def test_air_not_confused_with_lungs():
    vol = make_synthetic_volume()
    seg = segment_lungs(vol)
    # L'air extérieur (bords) ne doit pas être segmenté.
    assert not seg.combined[:, 0, 0].any()


def test_segmentation_manager_add_toggle():
    vol = make_synthetic_volume()
    seg = segment_lungs(vol)
    mgr = SegmentationManager(reference_shape=vol.array.shape)
    mgr.add_mask("Poumon droit", seg.right, color=(1, 0, 0))
    mgr.add_mask("Poumon gauche", seg.left, color=(0, 0, 1))
    assert len(mgr) == 2
    mgr.set_visible("Poumon droit", False)
    assert mgr.get("Poumon droit").visible is False
    mgr.set_opacity("Poumon gauche", 0.3)
    assert mgr.get("Poumon gauche").opacity == 0.3
    ml = mgr.get("Poumon droit").volume_ml(vol.voxel_volume_mm3)
    assert ml > 0


def test_manager_rejects_wrong_shape():
    mgr = SegmentationManager(reference_shape=(20, 40, 40))
    import pytest
    with pytest.raises(ValueError):
        mgr.add_mask("bad", np.ones((5, 5, 5), dtype=bool))
