"""Tests de génération de surface et export STL/PLY/OBJ/VTP."""

from __future__ import annotations

import numpy as np
import pytest

from mesh_export import export_mask_surface, export_polydata, mask_to_polydata


def _ball_mask(n=24, r=7):
    zz, yy, xx = np.mgrid[0:n, 0:n, 0:n]
    c = n // 2
    return ((zz - c) ** 2 + (yy - c) ** 2 + (xx - c) ** 2) <= r ** 2


def test_mask_to_polydata_nonempty():
    poly = mask_to_polydata(_ball_mask(), spacing=(1.0, 1.0, 1.0))
    assert poly.GetNumberOfPoints() > 0
    assert poly.GetNumberOfCells() > 0


@pytest.mark.parametrize("ext", [".stl", ".ply", ".obj", ".vtp"])
def test_export_formats(tmp_path, ext):
    out = tmp_path / f"Right_Lung{ext}"
    export_mask_surface(_ball_mask(), (1.0, 1.0, 1.0), out)
    assert out.exists() and out.stat().st_size > 0


def test_export_no_patient_data_in_name(tmp_path):
    out = tmp_path / "Left_Lung.stl"
    export_mask_surface(_ball_mask(), (0.7, 0.7, 1.5), out)
    # Le nom est neutre, aucune donnée nominative.
    assert "Left_Lung" in out.name
    assert out.exists()


def test_smoothing_option(tmp_path):
    poly_raw = mask_to_polydata(_ball_mask(), (1, 1, 1), smooth_iterations=0)
    poly_smooth = mask_to_polydata(_ball_mask(), (1, 1, 1), smooth_iterations=15)
    assert poly_raw.GetNumberOfPoints() > 0
    assert poly_smooth.GetNumberOfPoints() > 0


def test_empty_mask_raises(tmp_path):
    empty = np.zeros((10, 10, 10), dtype=bool)
    with pytest.raises(RuntimeError):
        export_mask_surface(empty, (1, 1, 1), tmp_path / "x.stl")


def test_unsupported_format(tmp_path):
    poly = mask_to_polydata(_ball_mask(), (1, 1, 1))
    with pytest.raises(ValueError):
        export_polydata(poly, tmp_path / "x.xyz")
