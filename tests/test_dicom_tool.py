"""Tests unitaires de l'outil de conversion DICOM."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import numpy as np
import pytest

from anonymization import DIRECT_IDENTIFIERS, is_blocked, safe_value
from dicom_core import (
    WindowSetting,
    apply_modality_lut,
    apply_window,
    decode_pixels,
    is_monochrome1,
    is_valid_dicom_image,
    read_header,
    resolve_window,
    to_uint16_raw,
)
from dicom_series import scan_directory, select_indices
from image_export import export_slice_png8, export_slice_png16
from metadata_export import build_series_metadata
from utils import sanitize_filename, unique_path


# --- Détection DICOM sans extension ---------------------------------------

def test_detect_dicom_without_extension(dicom_no_ext: Path):
    ds = read_header(dicom_no_ext)
    assert is_valid_dicom_image(ds)
    assert dicom_no_ext.suffix == ""  # aucun .dcm


def test_non_dicom_rejected(tmp_path: Path):
    junk = tmp_path / "note"
    junk.write_text("hello")
    assert not is_valid_dicom_image(read_header(junk))


# --- Tri par ImagePositionPatient + fallback ------------------------------

def test_sort_by_image_position(series_dir: Path):
    series_list, stats = scan_directory(series_dir, show_progress=False)
    assert stats["dicom_detected"] == 3
    assert stats["ignored"] == 1  # README.txt
    assert len(series_list) == 1
    s = series_list[0]
    zpos = [sl.image_position[2] for sl in s.slices]
    assert zpos == sorted(zpos)  # trié spatialement croissant
    assert "ImagePositionPatient" in s.sort_order


def test_fallback_instance_number(tmp_path: Path):
    from tests.conftest import _base_ct
    # Coupes sans position ni SliceLocation -> repli sur InstanceNumber.
    for inst in (3, 1, 2):
        ds = _base_ct(instance=inst)
        ds.save_as(str(tmp_path / f"CT{inst}"), enforce_file_format=True)
    series_list, _ = scan_directory(tmp_path, show_progress=False)
    s = series_list[0]
    assert [sl.instance_number for sl in s.slices] == [1, 2, 3]
    assert "InstanceNumber" in s.sort_order


# --- Rescale slope/intercept ----------------------------------------------

def test_apply_rescale(dicom_no_ext: Path):
    arr, ds = decode_pixels(dicom_no_ext)
    values = apply_modality_lut(arr, ds)
    # Intercept -1024 doit décaler les valeurs.
    assert np.min(values) == pytest.approx(float(np.min(arr)) - 1024.0)


# --- Fenêtre pulmonaire ----------------------------------------------------

def test_lung_window_formula():
    window = WindowSetting(-600, 1500, "lung")
    values = np.array([-1350.0, -600.0, 150.0], dtype=np.float32)
    out = apply_window(values, window)
    # -1350 = borne basse -> 0 ; centre -600 -> ~128 ; 150 = borne haute -> 255
    assert out[0] == 0
    assert out[2] == 255
    assert 120 <= out[1] <= 135


def test_window_common_to_series_is_deterministic():
    w = WindowSetting(-600, 1500, "lung")
    a = apply_window(np.array([0.0]), w)
    b = apply_window(np.array([0.0]), w)
    assert a[0] == b[0]


# --- MONOCHROME1 -----------------------------------------------------------

def test_monochrome1_inversion(mono1_file: Path):
    arr, ds = decode_pixels(mono1_file)
    assert is_monochrome1(ds)
    values = apply_modality_lut(arr, ds)
    w = WindowSetting(40, 400, "mediastinum")
    normal = apply_window(values, w, invert=False)
    inverted = apply_window(values, w, invert=True)
    # L'inversion doit produire le complément à 255.
    assert np.all(inverted.astype(int) == 255 - normal.astype(int))


# --- PNG 8 bits et 16 bits -------------------------------------------------

def test_export_png8(dicom_no_ext: Path, tmp_path: Path):
    dst = tmp_path / "out8.png"
    export_slice_png8(dicom_no_ext, dst, WindowSetting(-600, 1500, "lung"))
    assert dst.exists() and dst.stat().st_size > 0
    from PIL import Image
    img = Image.open(dst)
    assert img.mode == "L"
    assert img.size == (16, 16)


def test_export_png16(dicom_no_ext: Path, tmp_path: Path):
    dst = tmp_path / "out16.png"
    params = export_slice_png16(dicom_no_ext, dst)
    assert dst.exists()
    assert set(params) >= {"original_min", "original_max", "scale", "offset"}
    from PIL import Image
    img = Image.open(dst)
    assert img.mode in ("I;16", "I")


def test_to_uint16_reconstruction():
    values = np.array([-1024.0, 0.0, 3000.0], dtype=np.float32)
    out, params = to_uint16_raw(values)
    assert out.dtype == np.uint16
    assert out.min() == 0 and out.max() == 65535
    # Reconstruction approximative.
    recon = out.astype(float) / params["scale"] + params["offset"]
    assert np.allclose(recon, values, atol=1.0)


# --- Sélection d'indices ---------------------------------------------------

def test_select_indices_range_and_step():
    assert select_indices(10, 1, 10, 1, None) == list(range(10))
    assert select_indices(10, 2, 6, 1, None) == [1, 2, 3, 4, 5]
    assert select_indices(10, 1, 10, 2, None) == [0, 2, 4, 6, 8]


def test_select_indices_parity():
    even = select_indices(6, 1, 6, 1, "even")  # 1-based pairs -> index 1,3,5
    assert even == [1, 3, 5]
    odd = select_indices(6, 1, 6, 1, "odd")
    assert odd == [0, 2, 4]


# --- Anonymisation ---------------------------------------------------------

def test_anonymization_blocks_identifiers():
    for field in ("PatientName", "PatientID", "PatientBirthDate", "AccessionNumber"):
        assert is_blocked(field, anonymize=True)
        assert safe_value(field, "SECRET", anonymize=True) is None
    assert safe_value("PatientName", "SECRET", anonymize=False) == "SECRET"


def test_metadata_has_no_patient_data(series_dir: Path):
    series_list, _ = scan_directory(series_dir, show_progress=False)
    meta = build_series_metadata(
        series_list[0], WindowSetting(-600, 1500, "lung"),
        "png", 8, anonymize=True, strict=False,
    )
    blob = json.dumps(meta)
    assert "DUPONT" not in blob
    assert "SECRET123" not in blob
    assert meta["SeriesDescription"] == "PARANCHYME"


# --- Fichier corrompu ------------------------------------------------------

def test_corrupted_file_is_ignored(series_dir: Path):
    corrupt = series_dir / "CT_BAD"
    corrupt.write_bytes(b"DICM" + b"\x00" * 200)
    series_list, stats = scan_directory(series_dir, show_progress=False)
    # Ne doit pas planter ; le fichier corrompu est ignoré.
    assert stats["dicom_detected"] == 3


# --- Nettoyage de noms -----------------------------------------------------

def test_sanitize_filename():
    assert sanitize_filename("LUNG / THIN:1*") == "LUNG_THIN_1"
    assert sanitize_filename("  ..  ") == "UNKNOWN"
    assert sanitize_filename("CON") == "_CON"  # nom réservé Windows
    assert "/" not in sanitize_filename("a/b/c")


def test_unique_path(tmp_path: Path):
    taken: set[str] = set()
    p1 = unique_path(tmp_path / "Series_002_PARANCHYME", taken)
    p2 = unique_path(tmp_path / "Series_002_PARANCHYME", taken)
    assert p1.name != p2.name
    assert p2.name.endswith("_2")


# --- Mapping et ZIP (via CLI end-to-end) -----------------------------------

def test_end_to_end_export_and_zip(series_dir: Path, tmp_path: Path):
    from dicom_to_images import main
    out = tmp_path / "export"
    rc = main([
        "--input", str(series_dir),
        "--output", str(out),
        "--all-series",
        "--format", "png",
        "--bit-depth", "8",
        "--window", "lung",
        "--zip",
    ])
    assert rc == 0
    zips = list(out.glob("dicom_export_*.zip"))
    assert len(zips) == 1
    with zipfile.ZipFile(zips[0]) as zf:
        names = zf.namelist()
    assert any(n.endswith("metadata.json") for n in names)
    assert any(n.endswith("Slice_000001.png") for n in names)
    assert any("export_summary.json" in n for n in names)

    # Vérifie le mapping source -> export.
    meta_path = next(out.rglob("metadata.json"))
    meta = json.loads(meta_path.read_text())
    assert len(meta["mapping"]) == 3
    assert meta["mapping"][0]["exported_file"] == "Slice_000001.png"
    assert "source_file" in meta["mapping"][0]


def test_resolve_window_presets():
    class Dummy:
        WindowCenter = 50
        WindowWidth = 350
    assert resolve_window(Dummy(), "lung", None, None).center == -600
    assert resolve_window(Dummy(), "bone", None, None).width == 1800
    assert resolve_window(Dummy(), "dicom", None, None).center == 50
    assert resolve_window(Dummy(), "custom", -700, 1600).center == -700
