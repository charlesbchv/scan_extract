"""Presets de rendu volumique VTK (transfer functions) et fabrique de volume.

Import de VTK différé pour ne pas alourdir les modules cœur/tests non-3D.
Presets fondés sur les unités de Hounsfield.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable


@dataclass
class TransferPreset:
    """Description d'un preset : points (HU -> couleur) et (HU -> opacité)."""

    name: str
    color_points: list[tuple[float, float, float, float]]   # (HU, r, g, b)
    opacity_points: list[tuple[float, float]]               # (HU, alpha)
    gradient_points: list[tuple[float, float]] | None = None
    ambient: float = 0.2
    diffuse: float = 0.9
    specular: float = 0.2


# Presets HU. Valeurs volontairement sobres et fidèles.
PRESETS: dict[str, TransferPreset] = {
    "lung": TransferPreset(
        name="lung",
        color_points=[
            (-1000, 0.0, 0.0, 0.0),
            (-820, 0.35, 0.20, 0.20),
            (-600, 0.75, 0.55, 0.55),
            (-400, 0.95, 0.85, 0.80),
            (-200, 1.0, 0.95, 0.90),
        ],
        opacity_points=[(-1000, 0.0), (-850, 0.02), (-700, 0.12), (-500, 0.28), (-300, 0.0)],
    ),
    "bone": TransferPreset(
        name="bone",
        color_points=[
            (-200, 0.0, 0.0, 0.0),
            (150, 0.55, 0.35, 0.25),
            (400, 0.9, 0.8, 0.65),
            (1000, 1.0, 1.0, 0.95),
            (2000, 1.0, 1.0, 1.0),
        ],
        opacity_points=[(-200, 0.0), (150, 0.0), (300, 0.4), (700, 0.85), (2000, 0.95)],
    ),
    "mediastinum": TransferPreset(
        name="mediastinum",
        color_points=[
            (-200, 0.0, 0.0, 0.0),
            (-60, 0.45, 0.15, 0.15),
            (40, 0.85, 0.55, 0.5),
            (150, 0.95, 0.85, 0.8),
            (400, 1.0, 0.95, 0.9),
        ],
        opacity_points=[(-200, 0.0), (-100, 0.05), (40, 0.35), (200, 0.6), (500, 0.8)],
    ),
}


def custom_preset(window_center: float, window_width: float) -> TransferPreset:
    """Preset linéaire gris fondé sur une fenêtre WC/WW (mode Custom)."""
    low = window_center - window_width / 2.0
    high = window_center + window_width / 2.0
    return TransferPreset(
        name="custom",
        color_points=[(low, 0.0, 0.0, 0.0), (high, 1.0, 1.0, 1.0)],
        opacity_points=[(low, 0.0), (window_center, 0.2), (high, 0.6)],
    )


def build_transfer_functions(preset: TransferPreset):
    """Construit (vtkColorTransferFunction, vtkPiecewiseFunction[, gradient])."""
    import vtk

    color = vtk.vtkColorTransferFunction()
    for hu, r, g, b in preset.color_points:
        color.AddRGBPoint(hu, r, g, b)

    opacity = vtk.vtkPiecewiseFunction()
    for hu, a in preset.opacity_points:
        opacity.AddPoint(hu, a)

    gradient = None
    if preset.gradient_points:
        gradient = vtk.vtkPiecewiseFunction()
        for mag, a in preset.gradient_points:
            gradient.AddPoint(mag, a)
    return color, opacity, gradient


def build_volume_property(preset: TransferPreset):
    """Assemble un ``vtkVolumeProperty`` prêt à l'emploi."""
    import vtk

    color, opacity, gradient = build_transfer_functions(preset)
    prop = vtk.vtkVolumeProperty()
    prop.SetColor(color)
    prop.SetScalarOpacity(opacity)
    if gradient is not None:
        prop.SetGradientOpacity(gradient)
    prop.ShadeOn()
    prop.SetInterpolationTypeToLinear()
    prop.SetAmbient(preset.ambient)
    prop.SetDiffuse(preset.diffuse)
    prop.SetSpecular(preset.specular)
    return prop


def build_volume_actor(image_data, preset_name: str = "lung",
                       custom_wc: float = -600, custom_ww: float = 1500):
    """Crée un ``vtkVolume`` (acteur) avec mapper GPU + fallback logiciel.

    Retourne (vtkVolume, vtkVolumeProperty).
    """
    import vtk

    preset = PRESETS.get(preset_name) or custom_preset(custom_wc, custom_ww)
    prop = build_volume_property(preset)

    # Mapper GPU ray-cast, avec repli logiciel si indisponible.
    try:
        mapper = vtk.vtkGPUVolumeRayCastMapper()
    except Exception:  # noqa: BLE001
        mapper = vtk.vtkSmartVolumeMapper()
    mapper.SetInputData(image_data)

    volume = vtk.vtkVolume()
    volume.SetMapper(mapper)
    volume.SetProperty(prop)
    return volume, prop
