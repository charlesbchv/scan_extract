"""Tests de sérialisation de session et d'absence de données patient."""

from __future__ import annotations

import json

from dicomkit.viewer.viewer_state import (
    SegmentationState,
    ViewerState,
    load_session,
    save_session,
    series_fingerprint,
)


def test_roundtrip(tmp_path):
    state = ViewerState(
        series_uid="1.2.3", preset="lung", window_center=-600, window_width=1500,
        camera_position=[0, 0, 500], slice_axial=12, clipping_enabled=True,
    )
    state.series_fingerprint = series_fingerprint("1.2.3", 200)
    state.segmentations.append(SegmentationState("Poumon droit", [1, 0, 0], 0.5, True))
    path = save_session(state, tmp_path / "session.json")
    loaded = load_session(path)
    assert loaded.preset == "lung"
    assert loaded.window_center == -600
    assert loaded.slice_axial == 12
    assert loaded.clipping_enabled is True
    assert loaded.segmentations[0].name == "Poumon droit"
    assert loaded.segmentations[0].color == [1, 0, 0]


def test_no_patient_identifiers(tmp_path):
    state = ViewerState(series_uid="1.2.3.4.5")
    path = save_session(state, tmp_path / "s.json")
    blob = path.read_text()
    for banned in ("PatientName", "PatientID", "BirthDate", "SECRET"):
        assert banned not in blob


def test_fingerprint_stable():
    a = series_fingerprint("1.2.3", 100)
    b = series_fingerprint("1.2.3", 100)
    c = series_fingerprint("1.2.3", 101)
    assert a == b and a != c and len(a) == 16
