#!/usr/bin/env python3
"""Interface minimale tkinter pour la conversion DICOM -> PNG/JPEG.

Ne remplace pas le CLI : sélection dossier, analyse, choix de séries, format,
fenêtre, dossier de sortie, conversion, progression, chemin du ZIP.
"""

from __future__ import annotations

import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from dicom_series import scan_directory
from image_export import export_slice_jpeg, export_slice_png8, export_slice_png16
from dicom_core import resolve_window
from dicom_to_images import create_zip
from metadata_export import build_mapping_entry, build_series_metadata
from utils import sanitize_filename, setup_logging, unique_path

import json
from datetime import datetime


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title("DICOM → PNG / JPEG")
        self.geometry("760x620")
        self.series: list = []
        self._build_widgets()

    def _build_widgets(self) -> None:
        top = ttk.Frame(self, padding=10)
        top.pack(fill="x")

        self.input_var = tk.StringVar()
        self.output_var = tk.StringVar(value=str(Path("./export").resolve()))
        ttk.Label(top, text="Dossier IMAGES :").grid(row=0, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.input_var, width=60).grid(row=0, column=1)
        ttk.Button(top, text="Choisir…", command=self._choose_input).grid(row=0, column=2, padx=4)

        ttk.Label(top, text="Dossier sortie :").grid(row=1, column=0, sticky="w")
        ttk.Entry(top, textvariable=self.output_var, width=60).grid(row=1, column=1)
        ttk.Button(top, text="Choisir…", command=self._choose_output).grid(row=1, column=2, padx=4)

        ttk.Button(top, text="Analyser les séries", command=self._analyze).grid(row=2, column=1, pady=6, sticky="w")

        # Liste des séries (multi-sélection).
        self.listbox = tk.Listbox(self, selectmode="extended", height=12)
        self.listbox.pack(fill="both", expand=True, padx=10)

        opts = ttk.Frame(self, padding=10)
        opts.pack(fill="x")
        self.format_var = tk.StringVar(value="png")
        self.depth_var = tk.IntVar(value=8)
        self.window_var = tk.StringVar(value="lung")

        ttk.Label(opts, text="Format :").grid(row=0, column=0)
        ttk.Combobox(opts, textvariable=self.format_var, values=["png", "jpeg"], width=8, state="readonly").grid(row=0, column=1)
        ttk.Label(opts, text="Bits :").grid(row=0, column=2)
        ttk.Combobox(opts, textvariable=self.depth_var, values=[8, 16], width=5, state="readonly").grid(row=0, column=3)
        ttk.Label(opts, text="Fenêtre :").grid(row=0, column=4)
        ttk.Combobox(opts, textvariable=self.window_var,
                     values=["lung", "mediastinum", "bone", "dicom"], width=12, state="readonly").grid(row=0, column=5)

        ttk.Button(opts, text="Convertir", command=self._convert).grid(row=0, column=6, padx=10)

        self.progress = ttk.Progressbar(self, mode="determinate")
        self.progress.pack(fill="x", padx=10, pady=6)
        self.status = tk.StringVar(value="Prêt.")
        ttk.Label(self, textvariable=self.status, wraplength=740, justify="left").pack(fill="x", padx=10)

    def _choose_input(self) -> None:
        path = filedialog.askdirectory(title="Choisir le dossier IMAGES")
        if path:
            self.input_var.set(path)

    def _choose_output(self) -> None:
        path = filedialog.askdirectory(title="Choisir le dossier de sortie")
        if path:
            self.output_var.set(path)

    def _analyze(self) -> None:
        root = Path(self.input_var.get())
        if not root.is_dir():
            messagebox.showerror("Erreur", "Dossier IMAGES invalide.")
            return
        self.status.set("Analyse en cours…")
        self.update_idletasks()
        self.series, stats = scan_directory(root, show_progress=False)
        self.listbox.delete(0, tk.END)
        for i, s in enumerate(self.series, 1):
            self.listbox.insert(
                tk.END,
                f"{i}. {s.series_description} — {s.count} img — {s.rows}×{s.columns} — [{s.category}]",
            )
        self.status.set(
            f"{stats['dicom_detected']} DICOM, {len(self.series)} séries. "
            f"Sélectionnez une ou plusieurs séries."
        )

    def _convert(self) -> None:
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showwarning("Sélection", "Choisissez au moins une série.")
            return
        chosen = [self.series[i] for i in sel]
        threading.Thread(target=self._run_conversion, args=(chosen,), daemon=True).start()

    def _run_conversion(self, chosen: list) -> None:
        output_dir = Path(self.output_var.get())
        study_dir = output_dir / "Study_001"
        study_dir.mkdir(parents=True, exist_ok=True)
        fmt = self.format_var.get()
        depth = int(self.depth_var.get())
        win = self.window_var.get()
        taken: set[str] = set()
        errors: list[str] = []
        total = sum(s.count for s in chosen)
        self.progress["maximum"] = max(total, 1)
        done = 0
        summaries = []

        for idx, series in enumerate(chosen, 1):
            base = f"Series_{(series.series_number or idx):03d}_{sanitize_filename(series.series_description)}"
            folder = unique_path(study_dir / base, taken).name
            series_dir = study_dir / folder
            series_dir.mkdir(parents=True, exist_ok=True)
            window = resolve_window(series.sample_header, win, None, None)
            mapping = []
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
                self.progress["value"] = done
                self.status.set(f"Conversion… {done}/{total}")
                self.update_idletasks()
            meta = build_series_metadata(series, window, fmt, depth, True, False, raw_params)
            meta["mapping"] = mapping
            (series_dir / "metadata.json").write_text(
                json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
            )
            summaries.append({"folder": folder, "converted": converted})

        if errors:
            (output_dir / "conversion_errors.txt").write_text("\n".join(errors), encoding="utf-8")
        (output_dir / "export_summary.json").write_text(
            json.dumps({"series": summaries, "errors": len(errors)}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = output_dir / f"dicom_export_{ts}.zip"
        try:
            create_zip(output_dir, zip_path)
            self.status.set(f"Terminé. ZIP : {zip_path.resolve()}  ({len(errors)} erreurs)")
        except Exception as exc:  # noqa: BLE001
            if zip_path.exists():
                zip_path.unlink()
            self.status.set(f"Conversion faite mais ZIP échoué : {exc}")


def main() -> None:
    setup_logging(False)
    App().mainloop()


if __name__ == "__main__":
    main()
