"""Fenêtre principale PySide6 : panneau latéral + MPR + vue 3D VTK.

Disposition :
    [ MPR axiale/coronale/sagittale ] | [ Vue 3D VTK ]
    avec un panneau latéral de contrôle à gauche.

Réutilise entièrement le cœur existant (scan_directory, build_volume,
segment_lungs, mesh_export, viewer_state).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGroupBox, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QProgressBar,
    QPushButton, QSlider, QSplitter, QTextEdit, QVBoxLayout, QWidget,
)

from dicomkit.dicomio.dicom_series import Series, scan_directory
from dicomkit.volume.mesh_export import export_mask_surface
from dicomkit.viewer.multiplanar_viewer import MultiplanarViewer
from dicomkit.volume.segmentation import LungSegmentation
from dicomkit.volume.segmentation_manager import SegmentationManager
from dicomkit.viewer.viewer_state import ViewerState, save_session, series_fingerprint
from dicomkit.volume.volume_builder import Volume, to_vtk_image_data
from dicomkit.viewer.vtk_volume import PRESETS, build_volume_actor
from dicomkit.viewer.workers import SegmentationWorker, VolumeWorker

logger = logging.getLogger("dicom_to_images")

DISCLAIMER = (
    "Visualisation fondée sur les données DICOM originales. La fidélité dépend "
    "du protocole d'acquisition, de la résolution, du tri des coupes et de la "
    "segmentation.\nCet outil n'est pas un dispositif médical certifié et ne "
    "doit pas être utilisé seul pour établir un diagnostic."
)


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("DICOM 3D — reconstruction & navigation (local)")
        self.resize(1400, 900)

        self.series_list: list[Series] = []
        self.volume: Optional[Volume] = None
        self.segmentation: Optional[LungSegmentation] = None
        self.seg_manager: Optional[SegmentationManager] = None
        self.volume_worker: Optional[VolumeWorker] = None

        self._build_ui()

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_side_panel())

        self.mpr = MultiplanarViewer()
        splitter.addWidget(self.mpr)

        splitter.addWidget(self._build_vtk_panel())
        splitter.setSizes([320, 560, 560])
        self.setCentralWidget(splitter)

        self.status = self.statusBar()
        self.status.showMessage("Choisissez un dossier DICOM pour commencer.")

    def _build_side_panel(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)

        v.addWidget(QPushButton("Choisir un dossier DICOM…", clicked=self._choose_dir))
        self.series_widget = QListWidget()
        self.series_widget.itemSelectionChanged.connect(self._on_series_selected)
        v.addWidget(QLabel("Séries détectées :"))
        v.addWidget(self.series_widget)

        self.info_label = QLabel("—")
        self.info_label.setWordWrap(True)
        self.info_label.setStyleSheet("font-size:11px;")
        v.addWidget(self.info_label)

        self.build_btn = QPushButton("Construire le volume 3D", clicked=self._build_volume)
        self.build_btn.setEnabled(False)
        v.addWidget(self.build_btn)
        self.progress = QProgressBar()
        v.addWidget(self.progress)

        # Preset + fenêtre.
        box = QGroupBox("Affichage")
        bl = QVBoxLayout(box)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems([*PRESETS.keys(), "custom"])
        self.preset_combo.currentTextChanged.connect(self._apply_preset)
        bl.addWidget(QLabel("Preset :"))
        bl.addWidget(self.preset_combo)
        self.wc_slider = self._slider(-1000, 1000, -600, self._on_window)
        self.ww_slider = self._slider(1, 4000, 1500, self._on_window)
        bl.addWidget(QLabel("Window Center")); bl.addWidget(self.wc_slider)
        bl.addWidget(QLabel("Window Width")); bl.addWidget(self.ww_slider)
        v.addWidget(box)

        # Segmentation.
        seg_box = QGroupBox("Poumons")
        sl = QVBoxLayout(seg_box)
        thr_row = QHBoxLayout()
        thr_row.addWidget(QLabel("Seuil air (HU) :"))
        self.air_thr = QSlider(Qt.Horizontal)
        self.air_thr.setRange(-1000, -200)
        self.air_thr.setValue(-320)
        self.air_thr_label = QLabel("-320")
        self.air_thr.valueChanged.connect(lambda v: self.air_thr_label.setText(str(v)))
        thr_row.addWidget(self.air_thr)
        thr_row.addWidget(self.air_thr_label)
        sl.addLayout(thr_row)

        self.seg_btn = QPushButton("Segmenter les poumons", clicked=self._segment)
        self.seg_btn.setEnabled(False)
        sl.addWidget(self.seg_btn)
        self.seg_metrics = QLabel("—")
        self.seg_metrics.setWordWrap(True)
        sl.addWidget(self.seg_metrics)
        self.export_right = QPushButton("Exporter poumon droit (STL)…", clicked=lambda: self._export("right"))
        self.export_left = QPushButton("Exporter poumon gauche (STL)…", clicked=lambda: self._export("left"))
        for b in (self.export_right, self.export_left):
            b.setEnabled(False)
            sl.addWidget(b)
        v.addWidget(seg_box)

        # Coloration densitométrique des tissus (heuristique, non diagnostique).
        tissue_box = QGroupBox("Tissus (densitométrie HU)")
        tl = QVBoxLayout(tissue_box)
        self.tissue_btn = QPushButton("Colorer les tissus (bronches, verre dépoli, fibrose…)",
                                      clicked=self._color_tissues)
        self.tissue_btn.setEnabled(False)
        tl.addWidget(self.tissue_btn)
        self.tree_btn = QPushButton("Voir les branches (vaisseaux / bronches)",
                                    clicked=self._extract_tree)
        self.tree_btn.setEnabled(False)
        tl.addWidget(self.tree_btn)
        self.tissue_toggle = QPushButton("Masquer/afficher l'overlay", clicked=self._toggle_overlay)
        self.tissue_toggle.setEnabled(False)
        tl.addWidget(self.tissue_toggle)
        self.tissue_legend = QLabel("—")
        self.tissue_legend.setWordWrap(True)
        self.tissue_legend.setStyleSheet("font-size:10px;")
        tl.addWidget(self.tissue_legend)
        v.addWidget(tissue_box)

        v.addWidget(QPushButton("Capture PNG de la vue 3D…", clicked=self._screenshot))
        v.addWidget(QPushButton("Sauvegarder la session…", clicked=self._save_session))

        disclaimer = QTextEdit(DISCLAIMER)
        disclaimer.setReadOnly(True)
        disclaimer.setMaximumHeight(90)
        disclaimer.setStyleSheet("font-size:10px; color:#c9a94a;")
        v.addWidget(disclaimer)
        return panel

    def _build_vtk_panel(self) -> QWidget:
        """Panneau de la vue 3D.

        Sur macOS, l'embarquement VTK+PySide6 est instable : la vue 3D est donc
        ouverte dans une fenêtre VTK native séparée (processus indépendant, son
        propre contexte OpenGL), ce qui est robuste multiplateforme.
        """
        panel = QWidget()
        layout = QVBoxLayout(panel)
        title = QLabel("Vue 3D volumique")
        title.setStyleSheet("font-weight:bold; font-size:13px;")
        layout.addWidget(title)
        layout.addWidget(QLabel(
            "La vue 3D s'ouvre dans une fenêtre VTK dédiée (rotation, zoom, pan).\n"
            "Construisez d'abord le volume, puis cliquez ci-dessous."
        ))
        self.lungs_only_check = QCheckBox("Poumons uniquement (masque le corps, les côtes, la table)")
        self.lungs_only_check.setChecked(True)
        layout.addWidget(self.lungs_only_check)
        self.open3d_btn = QPushButton("Ouvrir la vue 3D (fenêtre séparée)",
                                      clicked=self._open_3d_view)
        self.open3d_btn.setEnabled(False)
        layout.addWidget(self.open3d_btn)
        hint = QLabel(
            "Astuce : segmentez les poumons avant d'ouvrir la vue 3D pour les "
            "superposer en surface."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("font-size:10px; color:#8fa6c4;")
        layout.addWidget(hint)
        layout.addStretch(1)
        return panel

    def _slider(self, lo, hi, val, cb) -> QSlider:
        s = QSlider(Qt.Horizontal)
        s.setRange(lo, hi)
        s.setValue(val)
        s.valueChanged.connect(cb)
        return s

    # -------------------------------------------------------------- actions
    def _choose_dir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "Dossier DICOM (IMAGES)")
        if not d:
            return
        self.status.showMessage(f"Analyse de {d} …")
        self.series_list, stats = scan_directory(Path(d), show_progress=False)
        self.series_widget.clear()
        for i, s in enumerate(self.series_list, 1):
            item = QListWidgetItem(
                f"{i}. {s.series_description} — {s.count} coupes — "
                f"{s.rows}×{s.columns} — [{s.category}]"
            )
            self.series_widget.addItem(item)
        self.status.showMessage(
            f"{stats['dicom_detected']} DICOM, {len(self.series_list)} séries."
        )

    def _on_series_selected(self) -> None:
        idx = self.series_widget.currentRow()
        if idx < 0:
            return
        s = self.series_list[idx]
        ds = s.sample_header
        self.info_label.setText(
            f"<b>{s.series_description}</b> [{s.category}]<br>"
            f"Coupes : {s.count}<br>Dimensions : {s.rows}×{s.columns}<br>"
            f"PixelSpacing : {getattr(ds,'PixelSpacing',None)}<br>"
            f"SliceThickness : {getattr(ds,'SliceThickness',None)}<br>"
            f"Orientation : {getattr(ds,'ImageOrientationPatient',None)}<br>"
            f"Tri : {s.sort_order}"
        )
        self.build_btn.setEnabled(True)

    def _build_volume(self) -> None:
        idx = self.series_widget.currentRow()
        if idx < 0:
            return
        self.build_btn.setEnabled(False)
        self.progress.setValue(0)
        self.volume_worker = VolumeWorker(self.series_list[idx])
        self.volume_worker.progressed.connect(
            lambda d, t: self.progress.setValue(int(100 * d / max(t, 1)))
        )
        self.volume_worker.finished_ok.connect(self._on_volume_ready)
        self.volume_worker.failed.connect(self._on_worker_error)
        self.volume_worker.start()

    def _on_volume_ready(self, volume: Volume) -> None:
        self.volume = volume
        self.seg_manager = SegmentationManager(reference_shape=volume.array.shape)
        self.mpr.set_volume(volume)
        self.seg_btn.setEnabled(True)
        self.build_btn.setEnabled(True)
        self.open3d_btn.setEnabled(True)
        if volume.warnings:
            QMessageBox.warning(self, "Anomalies géométriques", "\n".join(volume.warnings))
        sz = volume.physical_size_mm
        self.status.showMessage(
            f"Volume {volume.shape_zyx} — voxel {volume.spacing} mm — "
            f"taille {sz[0]:.0f}×{sz[1]:.0f}×{sz[2]:.0f} mm"
        )

    def _open_3d_view(self) -> None:
        """Écrit le volume (et les surfaces) en fichiers temporaires puis lance
        le visualiseur VTK autonome dans un processus séparé (non bloquant)."""
        if not self.volume:
            return
        import subprocess
        import sys
        import tempfile

        import vtk

        if not hasattr(self, "_tempdir"):
            self._tempdir = tempfile.mkdtemp(prefix="dicom3d_")
        tmp = Path(self._tempdir)

        # Volume à rendre : masqué aux poumons si demandé et segmentation dispo.
        render_volume = self.volume
        if self.lungs_only_check.isChecked() and self.segmentation is not None:
            from dicomkit.volume.segmentation import apply_lung_mask
            render_volume = apply_lung_mask(self.volume, self.segmentation, margin_voxels=2)
        elif self.lungs_only_check.isChecked() and self.segmentation is None:
            QMessageBox.information(
                self, "Poumons uniquement",
                "Segmentez d'abord les poumons pour n'afficher qu'eux en 3D. "
                "La vue va s'ouvrir avec le thorax complet."
            )

        # Volume -> .vti
        img = to_vtk_image_data(render_volume)
        vti = tmp / "volume.vti"
        writer = vtk.vtkXMLImageDataWriter()
        writer.SetFileName(str(vti))
        writer.SetInputData(img)
        writer.Write()

        cmd = [sys.executable, str(Path(__file__).with_name("vtk_view.py")),
               str(vti), "--preset", self.preset_combo.currentText()]

        # Arbre vaisseaux/bronches en surface OPAQUE (priorité d'affichage).
        tree = getattr(self, "tree_mask", None)
        if tree is not None and tree.any():
            vtp = tmp / "tree.vtp"
            try:
                export_mask_surface(tree, self.volume.spacing, vtp, self.volume.origin,
                                    smooth_iterations=0, remove_small=False)
                cmd += ["--surface", f"{vtp}:1.0,0.35,0.55,1.0"]  # opaque rose
            except Exception as exc:  # noqa: BLE001
                logger.warning("Surface arbre non générée : %s", exc)

        # Surfaces colorées : classes densitométriques si disponibles, sinon poumons.
        tmap = getattr(self, "tissue_map", None)
        if tmap is not None:
            for i, (name, mask) in enumerate(tmap.classes.items()):
                if not mask.any() or name == "Parenchyme normal":
                    continue  # on n'englobe pas le parenchyme normal (masque le reste)
                r, g, b = tmap.colors[name]
                vtp = tmp / f"tissue_{i}.vtp"
                try:
                    export_mask_surface(mask, self.volume.spacing, vtp, self.volume.origin)
                    cmd += ["--surface", f"{vtp}:{r:.3f},{g:.3f},{b:.3f}"]
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Surface tissu %s non générée : %s", name, exc)
        elif self.segmentation is not None:
            for side, color in (("right", "0.9,0.3,0.3"), ("left", "0.3,0.5,0.9")):
                mask = getattr(self.segmentation, side)
                if mask.any():
                    vtp = tmp / f"{side}_lung.vtp"
                    try:
                        export_mask_surface(mask, self.volume.spacing, vtp, self.volume.origin)
                        cmd += ["--surface", f"{vtp}:{color}"]
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("Surface %s non générée : %s", side, exc)

        try:
            subprocess.Popen(cmd)
            self.status.showMessage("Vue 3D ouverte dans une fenêtre séparée.")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Vue 3D", f"Lancement impossible : {exc}")

    def _apply_preset(self, name: str) -> None:
        presets_wc = {"lung": (-600, 1500), "bone": (400, 1800), "mediastinum": (40, 400)}
        if name in presets_wc:
            wc, ww = presets_wc[name]
            self.wc_slider.setValue(wc)
            self.ww_slider.setValue(ww)

    def _on_window(self) -> None:
        self.mpr.set_window(self.wc_slider.value(), self.ww_slider.value())

    def _segment(self) -> None:
        if not self.volume:
            return
        self.seg_btn.setEnabled(False)
        self.status.showMessage("Segmentation des poumons…")
        self._seg_worker = SegmentationWorker(self.volume, air_threshold_hu=float(self.air_thr.value()))
        self._seg_worker.finished_ok.connect(self._on_seg_ready)
        self._seg_worker.failed.connect(self._on_worker_error)
        self._seg_worker.start()

    def _on_seg_ready(self, seg: LungSegmentation) -> None:
        self.segmentation = seg
        self.seg_manager.add_mask("Poumon droit", seg.right, color=(0.9, 0.3, 0.3))
        self.seg_manager.add_mask("Poumon gauche", seg.left, color=(0.3, 0.5, 0.9))
        m = seg.metrics()

        # Superpose le masque sur les vues MPR pour vérification visuelle.
        labels = np.where(seg.right, 1, np.where(seg.left, 2, 0)).astype(np.uint8)
        self.mpr.set_overlay(labels, [(0.9, 0.3, 0.3), (0.3, 0.5, 0.9)], alpha=0.4)

        # Contrôle de plausibilité : un poumon adulte fait ~1500–4000 ml/côté.
        plausible = self._check_lung_plausibility(seg)
        warn_html = "" if plausible else (
            "<br><b style='color:#e05555'>⚠ Résultat peu plausible pour des "
            "poumons</b> (volume/position atypique). Vérifiez sur les coupes MPR "
            "et ajustez le seuil, ou la série n'est pas un thorax."
        )
        self.seg_metrics.setText(
            f"Total : {m['volume_total_ml']} ml<br>"
            f"Droit : {m['volume_right_ml']} ml<br>"
            f"Gauche : {m['volume_left_ml']} ml{warn_html}<br>"
            f"<i>{m['disclaimer']}</i>"
        )
        self.export_right.setEnabled(True)
        self.export_left.setEnabled(True)
        self.tissue_btn.setEnabled(True)
        self.tree_btn.setEnabled(True)
        self.seg_btn.setEnabled(True)
        self.status.showMessage(
            "Segmentation affichée sur les coupes MPR — vérifiez qu'elle suit "
            "bien les poumons."
        )

    def _extract_tree(self) -> None:
        """Extrait l'arbre vaisseaux/bronches et l'affiche (MPR + 3D opaque)."""
        if not (self.volume and self.segmentation):
            return
        from dicomkit.volume.lung_analysis import extract_lung_tree

        tree = extract_lung_tree(self.volume, self.segmentation, hu_threshold=-500.0)
        self.tree_mask = tree
        ml = float(tree.sum()) * self.volume.voxel_volume_mm3 / 1000.0
        # Overlay MPR : arbre en rose vif sur fond poumon.
        self.mpr.set_overlay(tree.astype("uint8"), [(1.0, 0.35, 0.55)], alpha=0.8)
        self.tissue_toggle.setEnabled(True)
        self._overlay_on = True
        self.status.showMessage(
            f"Arbre vaisseaux/bronches : {ml:.0f} ml. "
            "Ouvrez la vue 3D pour le voir en relief (opaque dans le poumon)."
        )

    def _check_lung_plausibility(self, seg: LungSegmentation) -> bool:
        """Heuristique : volume total et position verticale compatibles poumons."""
        total_ml = seg.volume_total_ml
        if not (500 <= total_ml <= 12000):
            return False
        # Les poumons occupent surtout la moitié supérieure (petit z = apex si
        # tri céphalo-caudal). On tolère, on vérifie juste l'étalement.
        zs = np.where(seg.combined.any(axis=(1, 2)))[0]
        if len(zs) == 0:
            return False
        span = (zs.max() - zs.min() + 1) / seg.combined.shape[0]
        return span >= 0.25  # les poumons s'étalent sur une bonne hauteur

    def _color_tissues(self) -> None:
        """Classification densitométrique HU dans les poumons + overlay MPR."""
        if not (self.volume and self.segmentation):
            return
        from dicomkit.volume.lung_analysis import DENSITY_DISCLAIMER, classify_lung_tissue

        tmap = classify_lung_tissue(self.volume, self.segmentation)
        self.tissue_map = tmap
        names = list(tmap.classes)
        colors = [tmap.colors[n] for n in names]
        labels = tmap.label_volume(order=names)
        self.mpr.set_overlay(labels, colors)

        # Légende colorée + volumes (avertissement bien visible).
        rows = []
        for n in names:
            r, g, b = tmap.colors[n]
            hexc = f"#{int(r*255):02x}{int(g*255):02x}{int(b*255):02x}"
            rows.append(f"<span style='color:{hexc}'>■</span> {n} : {tmap.volume_ml(n):.0f} ml")
        self.tissue_legend.setText(
            "<br>".join(rows) + f"<br><i style='color:#c9a94a'>{DENSITY_DISCLAIMER}</i>"
        )
        self.tissue_toggle.setEnabled(True)
        self._overlay_on = True
        self.status.showMessage("Coloration densitométrique appliquée (non diagnostique).")

    def _toggle_overlay(self) -> None:
        if not getattr(self, "tissue_map", None):
            return
        self._overlay_on = not getattr(self, "_overlay_on", True)
        if self._overlay_on:
            names = list(self.tissue_map.classes)
            self.mpr.set_overlay(self.tissue_map.label_volume(order=names),
                                 [self.tissue_map.colors[n] for n in names])
        else:
            self.mpr.set_overlay(None, None)

    def _export(self, side: str) -> None:
        if not self.segmentation:
            return
        mask = self.segmentation.right if side == "right" else self.segmentation.left
        default = "Right_Lung.stl" if side == "right" else "Left_Lung.stl"
        path, _ = QFileDialog.getSaveFileName(self, "Exporter la surface", default,
                                              "STL (*.stl);;PLY (*.ply);;OBJ (*.obj);;VTP (*.vtp)")
        if not path:
            return
        try:
            export_mask_surface(mask, self.volume.spacing, Path(path), self.volume.origin)
            self.status.showMessage(f"Exporté : {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Export", str(exc))

    def _screenshot(self) -> None:
        """Rendu 3D hors-écran vers un PNG (n'ouvre pas de fenêtre)."""
        if not self.volume:
            QMessageBox.information(self, "Capture", "Construisez d'abord le volume.")
            return
        path, _ = QFileDialog.getSaveFileName(self, "Capture PNG", "vue_3d.png", "PNG (*.png)")
        if not path:
            return
        try:
            import vtk

            render_volume = self.volume
            if self.lungs_only_check.isChecked() and self.segmentation is not None:
                from dicomkit.volume.segmentation import apply_lung_mask
                render_volume = apply_lung_mask(self.volume, self.segmentation, margin_voxels=2)
            img = to_vtk_image_data(render_volume)
            actor, _ = build_volume_actor(img, self.preset_combo.currentText())
            renderer = vtk.vtkRenderer()
            renderer.SetBackground(0.05, 0.08, 0.15)
            renderer.AddVolume(actor)
            rw = vtk.vtkRenderWindow()
            rw.SetOffScreenRendering(1)
            rw.SetSize(900, 800)
            rw.AddRenderer(renderer)
            renderer.ResetCamera()
            rw.Render()
            w2i = vtk.vtkWindowToImageFilter()
            w2i.SetInput(rw)
            w2i.Update()
            writer = vtk.vtkPNGWriter()
            writer.SetFileName(path)
            writer.SetInputConnection(w2i.GetOutputPort())
            writer.Write()
            self.status.showMessage(f"Capture enregistrée : {path}")
        except Exception as exc:  # noqa: BLE001
            QMessageBox.critical(self, "Capture", f"Rendu hors-écran impossible : {exc}")

    def _save_session(self) -> None:
        if not self.volume:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Sauvegarder la session", "session.json", "JSON (*.json)")
        if not path:
            return
        state = ViewerState(
            series_uid=self.volume.series_uid,
            series_fingerprint=series_fingerprint(self.volume.series_uid, self.volume.shape_zyx[0]),
            preset=self.preset_combo.currentText(),
            window_center=self.wc_slider.value(),
            window_width=self.ww_slider.value(),
            slice_axial=self.mpr.z, slice_coronal=self.mpr.y, slice_sagittal=self.mpr.x,
        )
        save_session(state, Path(path))
        self.status.showMessage(f"Session sauvegardée : {path}")

    def _on_worker_error(self, msg: str) -> None:
        self.build_btn.setEnabled(True)
        self.seg_btn.setEnabled(True)
        QMessageBox.critical(self, "Erreur", msg)
        self.status.showMessage(msg)
