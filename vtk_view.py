#!/usr/bin/env python3
"""Visualiseur 3D VTK autonome (processus séparé, stable sur macOS).

Ouvre une fenêtre VTK native avec son propre contexte OpenGL et sa propre
boucle d'interaction — totalement découplé de Qt, ce qui évite les plantages
d'embarquement VTK+PySide6 sur certaines configurations macOS.

    python vtk_view.py <volume.vti> [--preset lung|bone|mediastinum]
        [--surface masque.vtp[:R,G,B] ...]

Navigation : rotation (clic gauche), zoom (molette/clic droit), pan (Maj+clic).
Touches VTK usuelles : 'r' recentre la caméra, 'q' quitte.
"""

from __future__ import annotations

import argparse
import sys

from vtk_volume import build_volume_actor


def _parse_surface(spec: str):
    """Analyse 'fichier.vtp[:r,g,b[,opacité]]'.

    Retourne (chemin, couleur|None, opacité). Opacité par défaut 0.5.
    """
    if ":" in spec:
        path, rest = spec.rsplit(":", 1)
        try:
            vals = [float(x) for x in rest.split(",")]
            color = tuple(vals[:3])
            opacity = vals[3] if len(vals) >= 4 else 0.5
            return path, color, opacity
        except ValueError:
            return spec, None, 0.5
    return spec, None, 0.5


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Visualiseur 3D VTK autonome.")
    parser.add_argument("volume", help="Fichier vtkImageData (.vti)")
    parser.add_argument("--preset", default="lung",
                        choices=["lung", "bone", "mediastinum"])
    parser.add_argument("--surface", action="append", default=[],
                        help="Surface .vtp[:r,g,b] à superposer (répétable)")
    parser.add_argument("--title", default="Vue 3D — DICOM (local)")
    args = parser.parse_args(argv)

    import vtk

    reader = vtk.vtkXMLImageDataReader()
    reader.SetFileName(args.volume)
    reader.Update()
    image = reader.GetOutput()

    renderer = vtk.vtkRenderer()
    renderer.SetBackground(0.05, 0.08, 0.15)

    volume_actor, _ = build_volume_actor(image, args.preset)
    renderer.AddVolume(volume_actor)

    # Surfaces optionnelles (poumons segmentés, etc.).
    for spec in args.surface:
        path, color, opacity = _parse_surface(spec)
        s_reader = vtk.vtkXMLPolyDataReader()
        s_reader.SetFileName(path)
        s_reader.Update()
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputConnection(s_reader.GetOutputPort())
        mapper.ScalarVisibilityOff()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*(color or (0.9, 0.3, 0.3)))
        actor.GetProperty().SetOpacity(opacity)
        renderer.AddActor(actor)

    render_window = vtk.vtkRenderWindow()
    render_window.SetWindowName(args.title)
    render_window.SetSize(900, 800)
    render_window.AddRenderer(renderer)

    interactor = vtk.vtkRenderWindowInteractor()
    interactor.SetRenderWindow(render_window)
    interactor.SetInteractorStyle(vtk.vtkInteractorStyleTrackballCamera())

    # Repères anatomiques (axes) dans un coin.
    axes = vtk.vtkAxesActor()
    marker = vtk.vtkOrientationMarkerWidget()
    marker.SetOrientationMarker(axes)
    marker.SetInteractor(interactor)
    marker.SetViewport(0.0, 0.0, 0.2, 0.2)

    renderer.ResetCamera()
    render_window.Render()
    marker.EnabledOn()
    marker.InteractiveOff()
    interactor.Initialize()
    interactor.Start()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
