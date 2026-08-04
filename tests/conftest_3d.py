"""Fabriques de volumes synthétiques pour les tests 3D (aucune vraie donnée)."""

from __future__ import annotations

import numpy as np

from dicomkit.dicomio.dicom_series import Series, SliceInfo
from dicomkit.volume.volume_builder import Volume


def make_synthetic_volume(nz: int = 20, ny: int = 40, nx: int = 40,
                          spacing=(1.0, 1.0, 2.0)) -> Volume:
    """Volume CT synthétique : fond -1000 HU (air), deux 'poumons' à -800 HU,
    entourés de tissu mou (40 HU) et d'un liseré 'os' (600 HU)."""
    hu = np.full((nz, ny, nx), 40, dtype=np.int16)  # tissu mou
    # Air extérieur (bords).
    hu[:, :3, :] = -1000
    hu[:, -3:, :] = -1000
    hu[:, :, :3] = -1000
    hu[:, :, -3:] = -1000
    # Deux poumons (deux blocs séparés selon x).
    hu[4:16, 10:30, 6:18] = -800   # côté x bas
    hu[4:16, 10:30, 22:34] = -800  # côté x haut
    # Liseré os sur une coupe.
    hu[2, 5:35, 5:35] = 600
    return Volume(
        array=hu,
        spacing=spacing,
        origin=(0.0, 0.0, 0.0),
        direction=np.identity(3),
        series_uid="1.2.3.synthetic",
        modality="CT",
    )


def make_series_from_arrays(tmp_path, arrays, spacing=(1.0, 1.0), z_step=2.0,
                            orientation=(1, 0, 0, 0, 1, 0), rescale_intercept=-1024.0):
    """Écrit des coupes DICOM synthétiques et renvoie une Series triée.

    Réutilise le pipeline réel de scan pour rester fidèle à l'existant.
    """
    import pydicom
    from pydicom.dataset import Dataset, FileMetaDataset
    from pydicom.uid import ExplicitVRLittleEndian, generate_uid
    from dicomkit.dicomio.dicom_series import scan_directory

    series_uid = generate_uid()
    for i, arr in enumerate(arrays):
        ds = Dataset()
        ds.file_meta = FileMetaDataset()
        ds.file_meta.TransferSyntaxUID = ExplicitVRLittleEndian
        ds.SOPClassUID = "1.2.840.10008.5.1.4.1.1.2"
        ds.SOPInstanceUID = generate_uid()
        ds.StudyInstanceUID = "1.2.3.4"
        ds.SeriesInstanceUID = series_uid
        ds.Modality = "CT"
        ds.SeriesDescription = "PARANCHYME"
        ds.SeriesNumber = 2
        ds.InstanceNumber = i + 1
        ds.Rows, ds.Columns = arr.shape
        ds.BitsAllocated = 16
        ds.BitsStored = 16
        ds.HighBit = 15
        ds.PixelRepresentation = 1
        ds.SamplesPerPixel = 1
        ds.PhotometricInterpretation = "MONOCHROME2"
        ds.RescaleSlope = 1.0
        ds.RescaleIntercept = rescale_intercept
        ds.PixelSpacing = [spacing[1], spacing[0]]  # [row, col]
        ds.SpacingBetweenSlices = z_step
        ds.SliceThickness = z_step
        ds.ImageOrientationPatient = list(orientation)
        ds.ImagePositionPatient = [0.0, 0.0, i * z_step]
        ds.PatientName = "SECRET^PATIENT"
        ds.PatientID = "ID999"
        ds.PixelData = arr.astype("<i2").tobytes()
        ds.save_as(str(tmp_path / f"CT{i:06d}"), enforce_file_format=True)

    series_list, _ = scan_directory(tmp_path, show_progress=False)
    return series_list[0]
