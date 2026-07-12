"""Construction du metadata.json par série (avec anonymisation)."""

from __future__ import annotations

from typing import Any, Optional

from pydicom.dataset import FileDataset

from anonymization import safe_value
from dicom_core import WindowSetting
from dicom_series import Series


def _get(ds: FileDataset, attr: str) -> Any:
    value = getattr(ds, attr, None)
    if value is None:
        return None
    # Convertit les types pydicom en types JSON natifs.
    try:
        if hasattr(value, "__iter__") and not isinstance(value, (str, bytes)):
            return [_scalar(v) for v in value]
        return _scalar(value)
    except Exception:  # noqa: BLE001
        return str(value)


def _scalar(v: Any) -> Any:
    if isinstance(v, (int, float, str)):
        return v
    try:
        return float(v)
    except (TypeError, ValueError):
        return str(v)


def build_series_metadata(
    series: Series,
    window: WindowSetting,
    export_format: str,
    bit_depth: int,
    anonymize: bool,
    strict: bool,
    raw_params: Optional[dict[str, float]] = None,
) -> dict[str, Any]:
    """Assemble le dictionnaire de métadonnées d'une série."""
    ds = series.sample_header
    first_pos = series.slices[0].image_position if series.slices else None
    last_pos = series.slices[-1].image_position if series.slices else None

    meta: dict[str, Any] = {
        "StudyDescription": safe_value("StudyDescription", series.study_description, anonymize, strict),
        "SeriesDescription": series.series_description,
        "StudyDate": safe_value("StudyDate", _get(ds, "StudyDate"), anonymize, strict),
        "Modality": series.modality,
        "SeriesNumber": series.series_number,
        "StudyInstanceUID": series.study_uid,
        "SeriesInstanceUID": series.series_uid,
        "SOPClassUID": _get(ds, "SOPClassUID"),
        "image_count": series.count,
        "Rows": series.rows,
        "Columns": series.columns,
        "PixelSpacing": _get(ds, "PixelSpacing"),
        "SliceThickness": _get(ds, "SliceThickness"),
        "SpacingBetweenSlices": _get(ds, "SpacingBetweenSlices"),
        "ImageOrientationPatient": _get(ds, "ImageOrientationPatient"),
        "first_ImagePositionPatient": first_pos,
        "last_ImagePositionPatient": last_pos,
        "WindowCenter": _get(ds, "WindowCenter"),
        "WindowWidth": _get(ds, "WindowWidth"),
        "RescaleSlope": _get(ds, "RescaleSlope"),
        "RescaleIntercept": _get(ds, "RescaleIntercept"),
        "BitsAllocated": _get(ds, "BitsAllocated"),
        "BitsStored": _get(ds, "BitsStored"),
        "HighBit": _get(ds, "HighBit"),
        "PixelRepresentation": _get(ds, "PixelRepresentation"),
        "PhotometricInterpretation": _get(ds, "PhotometricInterpretation"),
        "TransferSyntaxUID": series.transfer_syntax,
        "ConvolutionKernel": _get(ds, "ConvolutionKernel"),
        "ImageType": _get(ds, "ImageType"),
        "category_hint": series.category,
        "sort_order": series.sort_order,
        "export_format": export_format,
        "bit_depth": bit_depth,
        "window_preset": window.preset,
        "window_center_used": window.center,
        "window_width_used": window.width,
        "anonymized": anonymize,
        "strict_anonymization": strict,
    }
    if raw_params is not None:
        meta["png16_reconstruction"] = raw_params
    # Retire les clés None issues de l'anonymisation pour un JSON propre.
    return meta


def build_mapping_entry(source_file: str, exported_file: str, slice_info) -> dict[str, Any]:
    """Une entrée du tableau de correspondance source -> export."""
    return {
        "source_file": source_file,
        "exported_file": exported_file,
        "instance_number": slice_info.instance_number,
        "image_position_patient": slice_info.image_position,
        "sop_instance_uid": slice_info.sop_instance_uid,
    }
