"""Reconstruction d'un volume 3D fidèle à partir d'une série DICOM CT.

Réutilise la détection/tri/décodage existants (dicom_series, dicom_core). Le
volume conserve la géométrie DICOM réelle (spacing, origine physique, direction
cosines). Aucune donnée anatomique n'est inventée.

Pipeline :
    Series triée (dicom_series)
      -> décodage pixel (dicom_core.decode_pixels)
      -> RescaleSlope/Intercept -> Hounsfield (dicom_core.apply_modality_lut)
      -> empilement en volume NumPy int16 [z, y, x]
      -> géométrie (PixelSpacing, espacement inter-coupes, direction cosines)
      -> conversion optionnelle en vtkImageData.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np

from dicomkit.dicomio.dicom_core import apply_modality_lut, decode_pixels
from dicomkit.dicomio.dicom_series import Series

logger = logging.getLogger("dicom_to_images")

# Tolérance relative pour juger l'espacement inter-coupes « régulier ».
_SPACING_TOL = 0.01  # 1 %


class VolumeBuildError(RuntimeError):
    """Erreur empêchant une reconstruction géométriquement valide."""


@dataclass
class Volume:
    """Volume CT reconstruit + géométrie DICOM.

    - ``array`` : HU, dtype int16, indexé [z, y, x] (z = axe des coupes).
    - ``spacing`` : (sx, sy, sz) en mm, ordre VTK/ITK (x, y, z).
    - ``origin`` : position physique du voxel [0,0,0] (mm), depuis la 1re coupe.
    - ``direction`` : matrice 3x3 des cosinus directeurs (colonnes = axes x,y,z).
    """

    array: np.ndarray
    spacing: tuple[float, float, float]
    origin: tuple[float, float, float]
    direction: np.ndarray
    series_uid: str = ""
    modality: str = "CT"
    warnings: list[str] = field(default_factory=list)

    @property
    def shape_zyx(self) -> tuple[int, int, int]:
        return tuple(int(x) for x in self.array.shape)  # type: ignore[return-value]

    @property
    def physical_size_mm(self) -> tuple[float, float, float]:
        nz, ny, nx = self.array.shape
        return (nx * self.spacing[0], ny * self.spacing[1], nz * self.spacing[2])

    @property
    def voxel_volume_mm3(self) -> float:
        return float(self.spacing[0] * self.spacing[1] * self.spacing[2])


def _slice_normal(orientation: list[float]) -> np.ndarray:
    row = np.array(orientation[0:3], dtype=float)
    col = np.array(orientation[3:6], dtype=float)
    return np.cross(row, col)


def analyze_geometry(series: Series) -> list[str]:
    """Détecte les anomalies géométriques. Retourne une liste d'avertissements.

    Ne lève pas : la reconstruction reste possible, mais l'utilisateur doit
    savoir si elle risque d'être imprécise.
    """
    warnings: list[str] = []
    slices = series.slices
    if len(slices) < 2:
        warnings.append("Série avec moins de 2 coupes : volume 3D peu significatif.")
        return warnings

    # Dimensions incompatibles ?
    dims = {(s_rows, s_cols) for s_rows, s_cols in [(series.rows, series.columns)]}
    # (rows/cols proviennent de l'en-tête série ; vérifiées finement au build)

    # Orientations différentes au sein d'une série ?
    orientations = [tuple(np.round(s.image_orientation, 4)) for s in slices if s.image_orientation]
    if orientations and len(set(orientations)) > 1:
        warnings.append("Orientations différentes détectées entre coupes (gantry tilt ?).")

    # Espacement inter-coupes régulier ?
    positions = [s.image_position for s in slices if s.image_position]
    if len(positions) >= 2 and orientations:
        normal = _slice_normal(slices[0].image_orientation)
        projected = [float(np.dot(np.array(p, dtype=float), normal)) for p in positions]
        diffs = np.diff(projected)
        if len(diffs) and np.any(diffs == 0):
            warnings.append("Coupes dupliquées (positions identiques) détectées.")
        nonzero = diffs[diffs != 0]
        if len(nonzero):
            med = float(np.median(np.abs(nonzero)))
            if med > 0 and np.any(np.abs(np.abs(nonzero) - med) > _SPACING_TOL * med):
                warnings.append(
                    f"Espacement inter-coupes irrégulier (médiane {med:.3f} mm) : "
                    "reconstruction possiblement déformée. Coupes manquantes ?"
                )
            # Coupes manquantes : un écart ~ multiple entier du pas médian.
            for gap in np.abs(nonzero):
                ratio = gap / med if med else 1.0
                if ratio > 1.5 and abs(ratio - round(ratio)) < 0.2:
                    warnings.append("Écart compatible avec une ou plusieurs coupes manquantes.")
                    break
    return warnings


def _compute_slice_spacing(series: Series) -> tuple[float, Optional[np.ndarray]]:
    """Espacement inter-coupes (mm) et direction de coupe (normale unitaire)."""
    slices = series.slices
    positions = [s.image_position for s in slices if s.image_position]
    if len(positions) >= 2 and slices[0].image_orientation:
        normal = _slice_normal(slices[0].image_orientation)
        n = np.linalg.norm(normal)
        if n > 0:
            normal = normal / n
            projected = [float(np.dot(np.array(p, dtype=float), normal)) for p in positions]
            diffs = np.abs(np.diff(projected))
            diffs = diffs[diffs > 1e-6]
            if len(diffs):
                return float(np.median(diffs)), normal
    # Repli : SpacingBetweenSlices puis SliceThickness.
    ds = series.sample_header
    for attr in ("SpacingBetweenSlices", "SliceThickness"):
        val = getattr(ds, attr, None)
        if val:
            try:
                return float(val), None
            except (TypeError, ValueError):
                pass
    return 1.0, None


def build_volume(
    series: Series,
    progress: Optional[Callable[[int, int], None]] = None,
    cancel: Optional[Callable[[], bool]] = None,
) -> Volume:
    """Construit le volume HU à partir d'une série triée.

    ``progress(done, total)`` est appelé au fil des coupes. ``cancel()`` peut
    renvoyer True pour interrompre proprement (lève VolumeBuildError).
    """
    slices = series.slices
    if not slices:
        raise VolumeBuildError("Série vide : aucune coupe à reconstruire.")

    warnings = analyze_geometry(series)
    total = len(slices)

    # Première coupe : dimensions de référence + PixelSpacing + orientation.
    first_arr, first_ds = decode_pixels(slices[0].path)
    if first_arr.ndim != 2:
        raise VolumeBuildError(
            "Coupe non 2D (multi-frame ou couleur) : non pris en charge pour "
            "la reconstruction volumique dans cette version."
        )
    ny, nx = first_arr.shape
    pixel_spacing = getattr(first_ds, "PixelSpacing", None)
    if pixel_spacing:
        row_spacing = float(pixel_spacing[0])  # mm entre lignes (axe y)
        col_spacing = float(pixel_spacing[1])  # mm entre colonnes (axe x)
    else:
        row_spacing = col_spacing = 1.0
        warnings.append("PixelSpacing absent : espacement dans le plan supposé 1 mm.")

    slice_spacing, normal = _compute_slice_spacing(series)

    volume = np.empty((total, ny, nx), dtype=np.int16)
    used_positions: list[list[float]] = []

    for z, s in enumerate(slices):
        if cancel and cancel():
            raise VolumeBuildError("Reconstruction annulée par l'utilisateur.")
        arr, ds = decode_pixels(s.path)
        if arr.ndim != 2 or arr.shape != (ny, nx):
            raise VolumeBuildError(
                f"Dimensions incompatibles à la coupe {z} : {arr.shape} vs {(ny, nx)}."
            )
        hu = apply_modality_lut(arr, ds)
        volume[z] = np.clip(np.round(hu), -32768, 32767).astype(np.int16)
        if s.image_position:
            used_positions.append(s.image_position)
        if progress:
            progress(z + 1, total)

    # Origine physique = position de la première coupe (voxel [0,0,0]).
    if used_positions:
        origin = tuple(float(v) for v in used_positions[0])
    else:
        origin = (0.0, 0.0, 0.0)
        warnings.append("ImagePositionPatient absent : origine physique supposée (0,0,0).")

    direction = _direction_matrix(slices[0].image_orientation, normal)

    if warnings:
        for w in warnings:
            logger.warning("Géométrie volume : %s", w)

    return Volume(
        array=volume,
        spacing=(col_spacing, row_spacing, slice_spacing),
        origin=origin,  # type: ignore[arg-type]
        direction=direction,
        series_uid=series.series_uid,
        modality=series.modality,
        warnings=warnings,
    )


def _direction_matrix(orientation: Optional[list[float]], normal: Optional[np.ndarray]) -> np.ndarray:
    """Matrice 3x3 de cosinus directeurs (colonnes = axes x, y, z)."""
    if orientation and len(orientation) == 6:
        row = np.array(orientation[0:3], dtype=float)
        col = np.array(orientation[3:6], dtype=float)
        z = normal if normal is not None else np.cross(row, col)
        z = z / (np.linalg.norm(z) or 1.0)
        return np.column_stack([row, col, z])
    return np.identity(3, dtype=float)


def to_vtk_image_data(volume: Volume):
    """Convertit un Volume en ``vtkImageData`` (import différé de VTK).

    L'orientation cosines est appliquée via SetDirectionMatrix quand disponible.
    """
    import vtk
    from vtk.util import numpy_support

    nz, ny, nx = volume.array.shape
    img = vtk.vtkImageData()
    img.SetDimensions(nx, ny, nz)
    img.SetSpacing(*volume.spacing)
    img.SetOrigin(*volume.origin)

    # VTK attend l'ordre x le plus rapide : aplatir en [z,y,x] -> C order OK.
    flat = np.ascontiguousarray(volume.array).ravel(order="C")
    vtk_arr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_SHORT)
    vtk_arr.SetName("HU")
    img.GetPointData().SetScalars(vtk_arr)

    if hasattr(img, "SetDirectionMatrix"):
        try:
            d = volume.direction
            img.SetDirectionMatrix(
                d[0, 0], d[0, 1], d[0, 2],
                d[1, 0], d[1, 1], d[1, 2],
                d[2, 0], d[2, 1], d[2, 2],
            )
        except Exception:  # noqa: BLE001
            pass
    return img
