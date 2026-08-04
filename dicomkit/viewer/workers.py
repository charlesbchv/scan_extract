"""Workers Qt : construction du volume et segmentation hors du thread UI.

L'import de PySide6 est local pour ne pas gêner les tests non-GUI.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import QObject, QThread, Signal

from dicomkit.dicomio.dicom_series import Series
from dicomkit.volume.segmentation import LungSegmentation, segment_lungs
from dicomkit.volume.volume_builder import Volume, VolumeBuildError, build_volume


class VolumeWorker(QThread):
    """Construit un Volume dans un thread séparé, avec progression annulable."""

    progressed = Signal(int, int)         # (done, total)
    finished_ok = Signal(object)          # Volume
    failed = Signal(str)

    def __init__(self, series: Series, parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._series = series
        self._cancel = False

    def cancel(self) -> None:
        self._cancel = True

    def run(self) -> None:  # noqa: D401
        try:
            vol = build_volume(
                self._series,
                progress=lambda d, t: self.progressed.emit(d, t),
                cancel=lambda: self._cancel,
            )
            self.finished_ok.emit(vol)
        except VolumeBuildError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Erreur inattendue : {exc}")


class SegmentationWorker(QThread):
    """Segmente les poumons dans un thread séparé."""

    finished_ok = Signal(object)          # LungSegmentation
    failed = Signal(str)

    def __init__(self, volume: Volume, air_threshold_hu: float = -320.0,
                 parent: Optional[QObject] = None) -> None:
        super().__init__(parent)
        self._volume = volume
        self._air_threshold_hu = air_threshold_hu

    def run(self) -> None:
        try:
            seg = segment_lungs(self._volume, air_threshold_hu=self._air_threshold_hu)
            self.finished_ok.emit(seg)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(f"Segmentation échouée : {exc}")
