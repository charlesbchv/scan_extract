"""Génération et export de surfaces 3D à partir de masques binaires.

Masque binaire -> vtkFlyingEdges3D (repli vtkMarchingCubes) -> nettoyage,
normales, lissage léger optionnel -> export STL / OBJ / PLY / VTP.

Aucune donnée nominative dans les fichiers exportés.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np

logger = logging.getLogger("dicom_to_images")

_EXPORTERS = {
    ".stl": "vtkSTLWriter",
    ".ply": "vtkPLYWriter",
    ".obj": "vtkOBJWriter",
    ".vtp": "vtkXMLPolyDataWriter",
}


def mask_to_polydata(
    mask: np.ndarray,
    spacing: tuple[float, float, float],
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    smooth_iterations: int = 0,
    remove_small: bool = True,
):
    """Convertit un masque binaire [z,y,x] en surface ``vtkPolyData``.

    ``smooth_iterations`` = 0 par défaut : aucun lissage fort imposé.
    """
    import vtk
    from vtk.util import numpy_support

    nz, ny, nx = mask.shape
    img = vtk.vtkImageData()
    img.SetDimensions(nx, ny, nz)
    img.SetSpacing(*spacing)
    img.SetOrigin(*origin)
    flat = np.ascontiguousarray(mask.astype(np.uint8)).ravel(order="C")
    arr = numpy_support.numpy_to_vtk(flat, deep=True, array_type=vtk.VTK_UNSIGNED_CHAR)
    img.GetPointData().SetScalars(arr)

    # Extraction d'iso-surface à 0.5 (frontière du masque).
    if hasattr(vtk, "vtkFlyingEdges3D"):
        surface = vtk.vtkFlyingEdges3D()
    else:  # repli
        surface = vtk.vtkMarchingCubes()
    surface.SetInputData(img)
    surface.SetValue(0, 0.5)
    surface.ComputeNormalsOff()
    surface.Update()

    poly = surface.GetOutput()

    if remove_small and poly.GetNumberOfCells() > 0:
        conn = vtk.vtkPolyDataConnectivityFilter()
        conn.SetInputData(poly)
        conn.SetExtractionModeToLargestRegion()
        conn.Update()
        poly = conn.GetOutput()

    clean = vtk.vtkCleanPolyData()
    clean.SetInputData(poly)
    clean.Update()
    poly = clean.GetOutput()

    if smooth_iterations > 0:
        smoother = vtk.vtkWindowedSincPolyDataFilter()
        smoother.SetInputData(poly)
        smoother.SetNumberOfIterations(int(smooth_iterations))
        smoother.SetPassBand(0.1)
        smoother.NonManifoldSmoothingOn()
        smoother.NormalizeCoordinatesOn()
        smoother.Update()
        poly = smoother.GetOutput()

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SetFeatureAngle(60.0)
    normals.Update()
    return normals.GetOutput()


def export_polydata(poly, path: Path) -> Path:
    """Écrit un ``vtkPolyData`` selon l'extension (.stl/.ply/.obj/.vtp)."""
    import vtk

    ext = path.suffix.lower()
    writer_name = _EXPORTERS.get(ext)
    if writer_name is None:
        raise ValueError(f"Format d'export non supporté : {ext}")
    writer = getattr(vtk, writer_name)()
    writer.SetFileName(str(path))
    writer.SetInputData(poly)
    if ext in (".stl", ".ply"):
        writer.SetFileTypeToBinary()
    if not writer.Write():
        raise RuntimeError(f"Échec de l'écriture de {path}")
    return path


def export_mask_surface(
    mask: np.ndarray,
    spacing: tuple[float, float, float],
    path: Path,
    origin: tuple[float, float, float] = (0.0, 0.0, 0.0),
    smooth_iterations: int = 0,
    remove_small: bool = True,
) -> Path:
    """Raccourci masque -> surface -> fichier.

    ``remove_small=False`` conserve toutes les composantes (utile pour un arbre
    vasculaire dont les branches gauche/droite ne sont pas connectées).
    """
    poly = mask_to_polydata(mask, spacing, origin, smooth_iterations,
                            remove_small=remove_small)
    if poly.GetNumberOfPoints() == 0:
        raise RuntimeError("Surface vide : le masque ne contient aucun voxel.")
    return export_polydata(poly, path)
