#!/usr/bin/env python3
"""Interface « glisser-déposer » ultra-simple.

Déposez le dossier `IMAGES` (ou un fichier qu'il contient) sur la fenêtre :
l'outil analyse, convertit TOUTES les séries et crée le ZIP automatiquement.

- Glisser-déposer réel si `tkinterdnd2` est installé (`pip install tkinterdnd2`).
- Sinon, repli sur un gros bouton « Choisir un dossier… ».

Réglages par défaut (modifiables en haut de la fenêtre) :
    Format PNG · 8 bits · fenêtre poumon (lung) · anonymisation activée · ZIP.
"""

from __future__ import annotations

import json
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk

# Glisser-déposer optionnel.
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD  # type: ignore

    _DND = True
except Exception:  # noqa: BLE001
    _DND = False

from dicomkit.dicomio.dicom_core import resolve_window
from dicomkit.dicomio.dicom_series import scan_directory
from dicomkit.export.archive import create_zip
from dicomkit.export.image_export import export_slice_jpeg, export_slice_png8, export_slice_png16
from dicomkit.export.metadata_export import build_mapping_entry, build_series_metadata
from dicomkit.utils import sanitize_filename, setup_logging, unique_path


def _resolve_images_dir(path: Path) -> Path:
    """Si on dépose un fichier, remonte à son dossier parent."""
    return path if path.is_dir() else path.parent


class DropApp:
    """Fenêtre unique de dépôt."""

    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("DICOM → images : déposez le dossier IMAGES")
        self.root.geometry("620x520")
        self.busy = False

        self.format_var = tk.StringVar(value="png")
        self.depth_var = tk.IntVar(value=8)
        self.window_var = tk.StringVar(value="lung")
        self.output_var = tk.StringVar(value=str(Path("./export").resolve()))

        self._build()

    def _build(self) -> None:
        opts = ttk.Frame(self.root, padding=10)
        opts.pack(fill="x")
        ttk.Label(opts, text="Format :").grid(row=0, column=0, sticky="w")
        ttk.Combobox(opts, textvariable=self.format_var, values=["png", "jpeg"],
                     width=7, state="readonly").grid(row=0, column=1)
        ttk.Label(opts, text="Bits :").grid(row=0, column=2, padx=(10, 0))
        ttk.Combobox(opts, textvariable=self.depth_var, values=[8, 16],
                     width=5, state="readonly").grid(row=0, column=3)
        ttk.Label(opts, text="Fenêtre :").grid(row=0, column=4, padx=(10, 0))
        ttk.Combobox(opts, textvariable=self.window_var,
                     values=["lung", "mediastinum", "bone", "dicom"],
                     width=12, state="readonly").grid(row=0, column=5)

        out = ttk.Frame(self.root, padding=(10, 0))
        out.pack(fill="x")
        ttk.Label(out, text="Sortie :").pack(side="left")
        ttk.Entry(out, textvariable=self.output_var).pack(side="left", fill="x", expand=True, padx=4)
        ttk.Button(out, text="…", width=3, command=self._choose_output).pack(side="left")

        # Zone de dépôt.
        self.drop = tk.Label(
            self.root,
            text=self._drop_text(),
            relief="ridge", borderwidth=3,
            font=("Helvetica", 14), justify="center",
            bg="#eef3fb", fg="#1a3b6b",
        )
        self.drop.pack(fill="both", expand=True, padx=14, pady=14)
        self.drop.bind("<Button-1>", lambda _e: self._browse())

        if _DND:
            self.drop.drop_target_register(DND_FILES)  # type: ignore[attr-defined]
            self.drop.dnd_bind("<<Drop>>", self._on_drop)  # type: ignore[attr-defined]

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill="x", padx=14)
        self.status = tk.StringVar(value="En attente d'un dossier IMAGES…")
        ttk.Label(self.root, textvariable=self.status, wraplength=590,
                  justify="left", padding=8).pack(fill="x")

    def _drop_text(self) -> str:
        if _DND:
            return "⬇\n\nDéposez ici le dossier IMAGES\n(ou cliquez pour choisir)"
        return "📂\n\nCliquez pour choisir le dossier IMAGES\n(glisser-déposer : pip install tkinterdnd2)"

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Dossier de sortie")
        if path:
            self.output_var.set(path)

    def _browse(self) -> None:
        if self.busy:
            return
        path = filedialog.askdirectory(title="Choisir le dossier IMAGES")
        if path:
            self._start(Path(path))

    def _on_drop(self, event) -> None:  # noqa: ANN001
        if self.busy:
            return
        # tkinterdnd2 renvoie une liste possiblement entre accolades.
        raw = event.data.strip()
        if raw.startswith("{") and raw.endswith("}"):
            raw = raw[1:-1]
        first = raw.split("} {")[0].strip("{}")
        self._start(Path(first))

    def _start(self, dropped: Path) -> None:
        images_dir = _resolve_images_dir(dropped)
        if not images_dir.is_dir():
            self.status.set(f"Chemin invalide : {dropped}")
            return
        self.busy = True
        self.drop.config(text="⏳ Traitement en cours…", bg="#fff3d6")
        threading.Thread(target=self._process, args=(images_dir,), daemon=True).start()

    # ------------------------------------------------------------------ #

    def _process(self, images_dir: Path) -> None:
        try:
            self._set_status(f"Analyse de {images_dir} …")
            series_list, stats = scan_directory(images_dir, show_progress=False)
            if not series_list:
                self._finish("Aucune image DICOM exploitable trouvée.", ok=False)
                return

            fmt = self.format_var.get()
            depth = int(self.depth_var.get())
            win = self.window_var.get()
            output_dir = Path(self.output_var.get())
            study_dir = output_dir / "Study_001"
            study_dir.mkdir(parents=True, exist_ok=True)

            total = sum(s.count for s in series_list)
            self.progress["maximum"] = max(total, 1)
            done = 0
            taken: set[str] = set()
            errors: list[str] = []
            summaries: list[dict] = []

            for idx, series in enumerate(series_list, 1):
                base = f"Series_{(series.series_number or idx):03d}_{sanitize_filename(series.series_description)}"
                folder = unique_path(study_dir / base, taken).name
                series_dir = study_dir / folder
                series_dir.mkdir(parents=True, exist_ok=True)
                window = resolve_window(series.sample_header, win, None, None)
                mapping: list[dict] = []
                raw_params = None
                converted = 0
                for out_i, slice_info in enumerate(series.slices, 1):
                    ext = "jpg" if fmt == "jpeg" else "png"
                    name = f"Slice_{out_i:06d}.{ext}"
                    dst = series_dir / name
                    try:
                        if fmt == "jpeg":
                            export_slice_jpeg(slice_info.path, dst, window)
                        elif depth == 16:
                            raw_params = raw_params or export_slice_png16(slice_info.path, dst)
                        else:
                            export_slice_png8(slice_info.path, dst, window)
                        converted += 1
                        mapping.append(build_mapping_entry(slice_info.path.name, name, slice_info))
                    except Exception as exc:  # noqa: BLE001
                        errors.append(f"{series.series_description}/{slice_info.path.name}: {exc}")
                    done += 1
                    self._tick(done, total, series.series_description)

                meta = build_series_metadata(series, window, fmt, depth, True, False, raw_params)
                meta["mapping"] = mapping
                (series_dir / "metadata.json").write_text(
                    json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
                )
                summaries.append({"folder": folder, "converted": converted})

            export_summary = {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "input": str(images_dir),
                "files_scanned": stats["files_scanned"],
                "dicom_detected": stats["dicom_detected"],
                "series_detected": stats["series_detected"],
                "series_exported": len(summaries),
                "images_converted": sum(s["converted"] for s in summaries),
                "errors": len(errors),
                "series": summaries,
            }
            (output_dir / "export_summary.json").write_text(
                json.dumps(export_summary, indent=2, ensure_ascii=False), encoding="utf-8"
            )
            if errors:
                (output_dir / "conversion_errors.txt").write_text("\n".join(errors), encoding="utf-8")

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            zip_path = output_dir / f"dicom_export_{ts}.zip"
            try:
                create_zip(output_dir, zip_path)
            except Exception as exc:  # noqa: BLE001
                if zip_path.exists():
                    zip_path.unlink()
                self._finish(f"Conversion faite mais ZIP échoué : {exc}", ok=False)
                return

            self._finish(
                f"Terminé ✅  {export_summary['images_converted']} images, "
                f"{len(summaries)} séries, {len(errors)} erreurs.\nZIP : {zip_path.resolve()}",
                ok=True,
            )
        except Exception as exc:  # noqa: BLE001
            self._finish(f"Erreur : {exc}", ok=False)

    # ---- Mises à jour thread-safe de l'UI ---------------------------- #

    def _set_status(self, text: str) -> None:
        self.root.after(0, lambda: self.status.set(text))

    def _tick(self, done: int, total: int, name: str) -> None:
        def upd() -> None:
            self.progress["value"] = done
            self.status.set(f"Conversion {name} … {done}/{total}")
        self.root.after(0, upd)

    def _finish(self, message: str, ok: bool) -> None:
        def upd() -> None:
            self.busy = False
            self.status.set(message)
            self.drop.config(
                text="✅  Glissez un autre dossier" if ok else "⚠️  " + self._drop_text(),
                bg="#e6f5ea" if ok else "#fbe6e6",
            )
        self.root.after(0, upd)


def main() -> None:
    setup_logging(False)
    root = TkinterDnD.Tk() if _DND else tk.Tk()
    DropApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
