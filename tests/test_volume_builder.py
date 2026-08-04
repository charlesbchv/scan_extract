"""Tests de reconstruction volumique : géométrie, HU, anomalies, vtkImageData."""

from __future__ import annotations

import numpy as np
import pytest

from tests.conftest_3d import make_series_from_arrays
from dicomkit.volume.volume_builder import (
    Volume,
    VolumeBuildError,
    analyze_geometry,
    build_volume,
    to_vtk_image_data,
)


def _pixel_arrays(n=6, size=16, value=1000):
    # valeur brute 1000 -> HU 1000 + intercept(-1024) = -24
    return [np.full((size, size), value, dtype=np.int16) for _ in range(n)]


def test_build_volume_shape_and_spacing(tmp_path):
    series = make_series_from_arrays(tmp_path, _pixel_arrays(6, 16), spacing=(0.7, 0.7), z_step=2.0)
    vol = build_volume(series)
    assert vol.array.shape == (6, 16, 16)          # [z, y, x]
    assert vol.spacing == pytest.approx((0.7, 0.7, 2.0))
    assert vol.array.dtype == np.int16


def test_hu_conversion(tmp_path):
    series = make_series_from_arrays(tmp_path, _pixel_arrays(4, 8, value=1024), z_step=1.0)
    vol = build_volume(series)
    # 1024 + (-1024) = 0 HU
    assert int(vol.array[0, 4, 4]) == 0


def test_origin_and_direction_preserved(tmp_path):
    series = make_series_from_arrays(tmp_path, _pixel_arrays(5, 8), z_step=3.0)
    vol = build_volume(series)
    assert vol.origin == pytest.approx((0.0, 0.0, 0.0))
    # orientation axiale standard -> direction identité
    assert np.allclose(vol.direction, np.identity(3))


def test_spatial_sort_used(tmp_path):
    # Positions volontairement dans le désordre : le scan doit trier.
    arrays = _pixel_arrays(5, 8)
    series = make_series_from_arrays(tmp_path, arrays, z_step=2.0)
    zpos = [s.image_position[2] for s in series.slices]
    assert zpos == sorted(zpos)


def test_detect_irregular_spacing(tmp_path):
    series = make_series_from_arrays(tmp_path, _pixel_arrays(5, 8), z_step=2.0)
    # Fausser une position pour créer une irrégularité.
    series.slices[2].image_position[2] = 5.3
    series.slices.sort(key=lambda s: s.image_position[2])
    warns = analyze_geometry(series)
    assert any("irrégulier" in w or "manquante" in w for w in warns)


def test_vtk_image_data(tmp_path):
    series = make_series_from_arrays(tmp_path, _pixel_arrays(4, 8), z_step=2.0)
    vol = build_volume(series)
    img = to_vtk_image_data(vol)
    assert img.GetDimensions() == (8, 8, 4)          # (nx, ny, nz)
    assert img.GetSpacing() == pytest.approx((1.0, 1.0, 2.0))


def test_empty_series_raises():
    from dicomkit.dicomio.dicom_series import Series
    empty = Series(series_uid="x", study_uid="y", modality="CT", series_number=1,
                   series_description="d", study_description="s", rows=8, columns=8,
                   transfer_syntax="1.2.840.10008.1.2.1")
    with pytest.raises(VolumeBuildError):
        build_volume(empty)


def test_progress_and_cancel(tmp_path):
    series = make_series_from_arrays(tmp_path, _pixel_arrays(6, 8), z_step=1.0)
    seen = []
    build_volume(series, progress=lambda d, t: seen.append((d, t)))
    assert seen[-1] == (6, 6)
    # Annulation immédiate.
    with pytest.raises(VolumeBuildError):
        build_volume(series, cancel=lambda: True)
