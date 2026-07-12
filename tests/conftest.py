"""Fixtures : génération de fichiers DICOM synthétiques pour les tests."""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

# Permet d'importer les modules du projet (répertoire parent).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pydicom
from pydicom.dataset import Dataset, FileMetaDataset
from pydicom.uid import ExplicitVRLittleEndian, generate_uid


def _base_ct(rows: int = 16, cols: int = 16, instance: int = 1,
             position: list[float] | None = None,
             photometric: str = "MONOCHROME2",
             series_uid: str | None = None) -> Dataset:
    ds = Dataset()
    ds.file_meta = FileMetaDataset()
    ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
    ds.file_meta.MediaStorageSOPClassUID = "1.2.840.10008.5.1.4.1.1.2"  # CT Image
    ds.file_meta.MediaStorageSOPInstanceUID = generate_uid()

    ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
    ds.SOPInstanceUID = generate_uid()
    ds.StudyInstanceUID = "1.2.3.4.5"
    ds.SeriesInstanceUID = series_uid or "1.2.3.4.5.6"
    ds.Modality = "CT"
    ds.SeriesDescription = "PARANCHYME"
    ds.StudyDescription = "THORAX"
    ds.SeriesNumber = 2
    ds.InstanceNumber = instance
    ds.Rows = rows
    ds.Columns = cols
    ds.BitsAllocated = 16
    ds.BitsStored = 16
    ds.HighBit = 15
    ds.PixelRepresentation = 1  # signed
    ds.SamplesPerPixel = 1
    ds.PhotometricInterpretation = photometric
    ds.RescaleSlope = 1.0
    ds.RescaleIntercept = -1024.0
    ds.WindowCenter = 40
    ds.WindowWidth = 400
    ds.ImageOrientationPatient = [1, 0, 0, 0, 1, 0]
    if position is not None:
        ds.ImagePositionPatient = position
    ds.PatientName = "DUPONT^JEAN"
    ds.PatientID = "SECRET123"
    ds.PatientBirthDate = "19700101"

    # Pixels signés (int16). Valeurs modérées.
    arr = (np.arange(rows * cols, dtype=np.int16).reshape(rows, cols) % 2000) - 500
    ds.PixelData = arr.astype("<i2").tobytes()
    ds.is_little_endian = True
    ds.is_implicit_VR = False
    return ds


@pytest.fixture
def dicom_no_ext(tmp_path: Path) -> Path:
    """Un DICOM valide sans extension (nom type CT000001)."""
    ds = _base_ct(instance=1, position=[0, 0, 10.0])
    path = tmp_path / "CT000001"
    ds.save_as(str(path), enforce_file_format=True)
    return path


@pytest.fixture
def series_dir(tmp_path: Path) -> Path:
    """Un dossier IMAGES avec 3 coupes désordonnées + 1 non-DICOM."""
    positions = [[0, 0, 30.0], [0, 0, 10.0], [0, 0, 20.0]]
    instances = [3, 1, 2]
    for i, (pos, inst) in enumerate(zip(positions, instances)):
        ds = _base_ct(instance=inst, position=pos)
        ds.save_as(str(tmp_path / f"CT{i:06d}"), enforce_file_format=True)
    # Fichier parasite non-DICOM.
    (tmp_path / "README.txt").write_text("pas un dicom")
    return tmp_path


@pytest.fixture
def mono1_file(tmp_path: Path) -> Path:
    ds = _base_ct(instance=1, position=[0, 0, 0.0], photometric="MONOCHROME1")
    path = tmp_path / "CT_MONO1"
    ds.save_as(str(path), enforce_file_format=True)
    return path
