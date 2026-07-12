"""Vues MPR (axiale/coronale/sagittale) synchronisées, en Qt + matplotlib.

Choix d'implémentation : matplotlib pour les 2D (robuste, léger, sans widget
VTK 2D supplémentaire). La vue 3D VTK est gérée dans main_window. Les trois vues
partagent un curseur croisé : cliquer dans l'une recale les deux autres.
"""

from __future__ import annotations

from typing import Callable, Optional

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QGridLayout, QLabel, QVBoxLayout, QWidget

from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
from matplotlib.figure import Figure

from volume_builder import Volume


def _window(arr: np.ndarray, wc: float, ww: float) -> np.ndarray:
    lo, hi = wc - ww / 2.0, wc + ww / 2.0
    return np.clip((arr - lo) / max(hi - lo, 1.0), 0.0, 1.0)


class _SliceView(QWidget):
    """Une vue de coupe (axiale, coronale ou sagittale)."""

    clicked = Signal(int, int)  # coordonnées (a, b) dans le plan de la coupe

    def __init__(self, title: str) -> None:
        super().__init__()
        self.title = title
        layout = QVBoxLayout(self)
        layout.setContentsMargins(2, 2, 2, 2)
        self.info = QLabel(title)
        self.info.setStyleSheet("color:#cfe4ff; font-size:11px;")
        self.fig = Figure(figsize=(3, 3), facecolor="#0c1526")
        self.canvas = FigureCanvasQTAgg(self.fig)
        self.ax = self.fig.add_axes([0, 0, 1, 1])
        self.ax.set_axis_off()
        self._im = None
        self._overlay_im = None
        self._hline = None
        self._vline = None
        layout.addWidget(self.info)
        layout.addWidget(self.canvas)
        self.canvas.mpl_connect("button_press_event", self._on_click)

    def show_image(self, img2d: np.ndarray, cross=None, label: str = "",
                   overlay_rgba: np.ndarray | None = None) -> None:
        norm = img2d
        if self._im is None:
            self._im = self.ax.imshow(norm, cmap="gray", vmin=0, vmax=1, origin="upper", aspect="equal")
        else:
            self._im.set_data(norm)
        # Overlay coloré (RGBA) au-dessus du niveau de gris.
        if overlay_rgba is not None:
            if self._overlay_im is None:
                self._overlay_im = self.ax.imshow(overlay_rgba, origin="upper",
                                                  aspect="equal", interpolation="nearest")
            else:
                self._overlay_im.set_data(overlay_rgba)
            self._overlay_im.set_visible(True)
        elif self._overlay_im is not None:
            self._overlay_im.set_visible(False)
        if cross is not None:
            a, b = cross
            if self._hline is None:
                self._hline = self.ax.axhline(a, color="#5ff0e6", lw=0.6)
                self._vline = self.ax.axvline(b, color="#5ff0e6", lw=0.6)
            else:
                self._hline.set_ydata([a, a])
                self._vline.set_xdata([b, b])
        self.info.setText(f"{self.title}  {label}")
        self.canvas.draw_idle()

    def _on_click(self, event) -> None:
        if event.inaxes is self.ax and event.xdata is not None:
            self.clicked.emit(int(round(event.ydata)), int(round(event.xdata)))


class MultiplanarViewer(QWidget):
    """Conteneur des trois vues MPR + curseur croisé synchronisé."""

    position_changed = Signal(int, int, int)  # (z, y, x)

    def __init__(self) -> None:
        super().__init__()
        self.volume: Optional[Volume] = None
        self.wc = -600.0
        self.ww = 1500.0
        self.z = self.y = self.x = 0
        self._labels: Optional[np.ndarray] = None          # [z,y,x] uint8
        self._lut: Optional[np.ndarray] = None             # [n+1, 4] RGBA 0..1
        self._overlay_alpha = 0.45

        self.axial = _SliceView("Axiale")
        self.coronal = _SliceView("Coronale")
        self.sagittal = _SliceView("Sagittale")

        grid = QGridLayout(self)
        grid.addWidget(self.axial, 0, 0)
        grid.addWidget(self.coronal, 1, 0)
        grid.addWidget(self.sagittal, 1, 1)

        self.axial.clicked.connect(lambda a, b: self._set_from_axial(a, b))
        self.coronal.clicked.connect(lambda a, b: self._set_from_coronal(a, b))
        self.sagittal.clicked.connect(lambda a, b: self._set_from_sagittal(a, b))

    def set_volume(self, volume: Volume) -> None:
        self.volume = volume
        nz, ny, nx = volume.array.shape
        self.z, self.y, self.x = nz // 2, ny // 2, nx // 2
        self.refresh()

    def set_window(self, wc: float, ww: float) -> None:
        self.wc, self.ww = wc, ww
        self.refresh()

    def set_overlay(self, labels: Optional[np.ndarray],
                    colors: Optional[list[tuple[float, float, float]]],
                    alpha: float = 0.45) -> None:
        """Définit un overlay coloré par étiquettes (0 = transparent).

        ``labels`` : volume [z,y,x] d'entiers. ``colors`` : couleur RGB de
        chaque étiquette 1..n (dans l'ordre). ``None`` retire l'overlay.
        """
        self._overlay_alpha = alpha
        if labels is None or colors is None:
            self._labels = self._lut = None
            self.refresh()
            return
        self._labels = labels.astype(np.uint8)
        lut = np.zeros((len(colors) + 1, 4), dtype=float)  # 0 = fond transparent
        for i, (r, g, b) in enumerate(colors, 1):
            lut[i] = (r, g, b, alpha)
        self._lut = lut
        self.refresh()

    def _overlay_slice(self, label2d: np.ndarray) -> Optional[np.ndarray]:
        if self._lut is None:
            return None
        return self._lut[np.clip(label2d, 0, len(self._lut) - 1)]

    def set_position(self, z: int, y: int, x: int) -> None:
        if not self.volume:
            return
        nz, ny, nx = self.volume.array.shape
        self.z = int(np.clip(z, 0, nz - 1))
        self.y = int(np.clip(y, 0, ny - 1))
        self.x = int(np.clip(x, 0, nx - 1))
        self.refresh()
        self.position_changed.emit(self.z, self.y, self.x)

    def refresh(self) -> None:
        if not self.volume:
            return
        vol = self.volume.array
        sx, sy, sz = self.volume.spacing
        ox, oy, oz = self.volume.origin
        hu_here = int(vol[self.z, self.y, self.x])
        px = (ox + self.x * sx, oy + self.y * sy, oz + self.z * sz)
        coord = f"HU={hu_here}  patient≈({px[0]:.1f}, {px[1]:.1f}, {px[2]:.1f}) mm"

        lab = self._labels
        ov_ax = self._overlay_slice(lab[self.z]) if lab is not None else None
        ov_cor = self._overlay_slice(lab[:, self.y, :]) if lab is not None else None
        ov_sag = self._overlay_slice(lab[:, :, self.x]) if lab is not None else None

        self.axial.show_image(_window(vol[self.z], self.wc, self.ww),
                              cross=(self.y, self.x), overlay_rgba=ov_ax,
                              label=f"coupe {self.z+1}/{vol.shape[0]}  {coord}")
        self.coronal.show_image(_window(vol[:, self.y, :], self.wc, self.ww),
                                cross=(self.z, self.x), overlay_rgba=ov_cor,
                                label=f"coupe {self.y+1}/{vol.shape[1]}")
        self.sagittal.show_image(_window(vol[:, :, self.x], self.wc, self.ww),
                                 cross=(self.z, self.y), overlay_rgba=ov_sag,
                                 label=f"coupe {self.x+1}/{vol.shape[2]}")

    # Clics -> synchronisation.
    def _set_from_axial(self, a: int, b: int) -> None:
        self.set_position(self.z, a, b)

    def _set_from_coronal(self, a: int, b: int) -> None:
        self.set_position(a, self.y, b)

    def _set_from_sagittal(self, a: int, b: int) -> None:
        self.set_position(a, b, self.x)

    def wheel_slice(self, delta: int) -> None:
        self.set_position(self.z + delta, self.y, self.x)
