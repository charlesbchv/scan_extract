#!/usr/bin/env python3
"""Point d'entrée de l'application desktop 3D (PySide6 + VTK), 100 % locale.

    python app_3d.py

Reconstruction volumique fidèle, vues MPR synchronisées, rendu volumique VTK,
segmentation pulmonaire automatique (non-IA, non validée médicalement),
export STL/OBJ/PLY/VTP et sauvegarde de session — sans réseau ni cloud.
"""

from __future__ import annotations

import sys

from dicomkit.utils import setup_logging


def main() -> int:
    setup_logging(verbose="--verbose" in sys.argv)
    from PySide6.QtWidgets import QApplication
    from dicomkit.viewer.main_window import MainWindow

    app = QApplication(sys.argv)
    app.setApplicationName("DICOM 3D Viewer (local)")
    window = MainWindow()
    window.show()
    # macOS : forcer la fenêtre au premier plan (sinon icône Dock sans fenêtre).
    window.raise_()
    window.activateWindow()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
