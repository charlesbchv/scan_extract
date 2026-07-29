#!/usr/bin/env python3
"""Outil local de conversion DICOM -> PNG/JPEG avec export ZIP.

Usage minimal :
    python dicom_to_images.py --input "/Volumes/SCANNER/IMAGES" --list-series
    python dicom_to_images.py --input "IMAGES" --series "PARANCHYME" \
        --format png --bit-depth 8 --window lung --zip
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from anonymization import anonymization_warning
from dicom_core import DicomDecodeError, WindowSetting, resolve_window
from dicom_series import Series, scan_directory, select_indices
from image_export import export_slice_jpeg, export_slice_png8, export_slice_png16
from metadata_export import build_mapping_entry, build_series_metadata
from utils import (
    ProgressPrinter,
    human_size,
    sanitize_filename,
    setup_logging,
    unique_path,
)

logger = logging.getLogger("dicom_to_images")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Convertit un dossier IMAGES DICOM en PNG/JPEG + ZIP.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--input", required=True, type=Path, help="Dossier IMAGES source")
    p.add_argument("--output", type=Path, default=Path("./export"), help="Dossier de sortie")
    p.add_argument("--list-series", action="store_true", help="Liste les séries et quitte")

    sel = p.add_argument_group("Sélection de séries")
    sel.add_argument("--series", type=str, help="Filtre par SeriesDescription (sous-chaîne)")
    sel.add_argument("--series-index", type=int, action="append", help="Index de série (répétable)")
    sel.add_argument("--all-series", action="store_true", help="Exporte toutes les séries")

    rng = p.add_argument_group("Sélection d'images")
    rng.add_argument("--start", type=int, help="Première image (1-based, inclus)")
    rng.add_argument("--end", type=int, help="Dernière image (1-based, inclus)")
    rng.add_argument("--step", type=int, default=1, help="Une image sur N")
    rng.add_argument("--parity", choices=["odd", "even"], help="Images impaires/paires")

    fmt = p.add_argument_group("Format")
    fmt.add_argument("--format", choices=["png", "jpeg"], default="png")
    fmt.add_argument("--bit-depth", type=int, choices=[8, 16], default=8)
    fmt.add_argument(
        "--window",
        choices=["auto", "lung", "mediastinum", "bone", "dicom", "custom"],
        default="auto",
        help="auto = fenêtre choisie par catégorie de série (médiastin/poumon/os)",
    )
    fmt.add_argument("--wc", type=float, help="Window Center (mode custom)")
    fmt.add_argument("--ww", type=float, help="Window Width (mode custom)")
    fmt.add_argument("--jpeg-quality", type=int, default=95)

    anon = p.add_argument_group("Anonymisation")
    anon.add_argument("--anonymize", dest="anonymize", action="store_true", default=True)
    anon.add_argument("--keep-identifiers", dest="anonymize", action="store_false",
                      help="Conserve les identifiants patient (avec avertissement)")
    anon.add_argument("--strict-anon", action="store_true", help="Retire aussi établissement/dates")

    out = p.add_argument_group("Sortie")
    out.add_argument("--zip", dest="zip", action="store_true", default=True)
    out.add_argument("--no-zip", dest="zip", action="store_false")
    out.add_argument("--overwrite", action="store_true", help="Écrase le dossier de sortie existant")
    out.add_argument("--verbose", action="store_true")
    return p


def select_series(all_series: list[Series], args: argparse.Namespace) -> list[Series]:
    """Résout la sélection de séries selon les arguments."""
    if args.all_series:
        return all_series
    chosen: list[Series] = []
    if args.series_index:
        for idx in args.series_index:
            if 1 <= idx <= len(all_series):
                chosen.append(all_series[idx - 1])
            else:
                logger.warning("Index de série hors limites : %d", idx)
    if args.series:
        needle = args.series.lower()
        for s in all_series:
            if needle in s.series_description.lower() and s not in chosen:
                chosen.append(s)
    return chosen


def print_series_table(all_series: list[Series]) -> None:
    print(f"\n{len(all_series)} série(s) détectée(s) :\n")
    for i, s in enumerate(all_series, 1):
        thick = getattr(s.sample_header, "SliceThickness", None)
        print(
            f"{i}. {s.series_description} — {s.count} images — "
            f"{s.rows} × {s.columns} — SeriesNumber={s.series_number} — "
            f"Modality={s.modality} — [{s.category}]"
        )
        print(
            f"    TransferSyntax={s.transfer_syntax}  SliceThickness={thick}  "
            f"Kernel={getattr(s.sample_header, 'ConvolutionKernel', None)}  "
            f"tri={s.sort_order}"
        )
    print()


def export_series(
    series: Series,
    study_dir: Path,
    series_folder: str,
    args: argparse.Namespace,
    errors: list[str],
) -> Optional[dict]:
    """Exporte une série. Retourne un résumé, ou None si aucune image exportée."""
    series_dir = study_dir / series_folder
    series_dir.mkdir(parents=True, exist_ok=True)

    indices = select_indices(series.count, args.start, args.end, args.step, args.parity)
    if not indices:
        logger.warning("Aucune image sélectionnée pour %s", series.series_description)
        return None

    # Fenêtre commune à toute la série (cohérence inter-coupes). En mode auto,
    # elle dépend de la catégorie de la série (médiastin != poumon).
    window: WindowSetting = resolve_window(
        series.sample_header, args.window, args.wc, args.ww, series.category
    )

    progress = ProgressPrinter(len(indices), f"Export {series_folder}")
    mapping: list[dict] = []
    raw_params: Optional[dict] = None
    converted = 0

    for out_index, src_index in enumerate(indices, 1):
        slice_info = series.slices[src_index]
        ext = "jpg" if args.format == "jpeg" else "png"
        exported_name = f"Slice_{out_index:06d}.{ext}"
        dst = series_dir / exported_name
        try:
            if args.format == "jpeg":
                export_slice_jpeg(slice_info.path, dst, window, args.jpeg_quality)
            elif args.bit_depth == 16:
                params = export_slice_png16(slice_info.path, dst)
                raw_params = raw_params or params
            else:
                export_slice_png8(slice_info.path, dst, window)
            converted += 1
            mapping.append(build_mapping_entry(slice_info.path.name, exported_name, slice_info))
        except (DicomDecodeError, Exception) as exc:  # noqa: BLE001
            msg = f"{series.series_description} / {slice_info.path.name} : {exc}"
            errors.append(msg)
            logger.error(msg)
        progress.update()
    progress.done()

    if converted == 0:
        return None

    meta = build_series_metadata(
        series, window, args.format, args.bit_depth,
        args.anonymize, args.strict_anon, raw_params,
    )
    meta["mapping"] = mapping
    (series_dir / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    return {
        "series_description": series.series_description,
        "folder": series_folder,
        "converted": converted,
        "window": str(window),
    }


def create_zip(output_dir: Path, zip_path: Path) -> int:
    """Crée le ZIP à partir du dossier de sortie. Retourne la taille en octets."""
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(output_dir.rglob("*")):
            if path.is_file() and path.resolve() != zip_path.resolve():
                zf.write(path, path.relative_to(output_dir))
    return zip_path.stat().st_size


def run(args: argparse.Namespace) -> int:
    setup_logging(args.verbose)

    if not args.anonymize:
        logger.warning(anonymization_warning())

    input_dir: Path = args.input
    if not input_dir.is_dir():
        logger.error("Dossier introuvable : %s", input_dir)
        return 2

    logger.info("Analyse récursive de %s ...", input_dir)
    all_series, stats = scan_directory(input_dir)

    if not all_series:
        logger.error("Aucune image DICOM exploitable trouvée.")
        return 1

    if args.list_series:
        print_series_table(all_series)
        return 0

    selected = select_series(all_series, args)
    if not selected:
        logger.error(
            "Aucune série sélectionnée. Utilisez --list-series, --series, "
            "--series-index ou --all-series."
        )
        print_series_table(all_series)
        return 1

    output_dir: Path = args.output
    if output_dir.exists() and args.overwrite:
        import shutil
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    study_dir = output_dir / "Study_001"
    study_dir.mkdir(exist_ok=True)

    errors: list[str] = []
    summaries: list[dict] = []
    taken_folders: set[str] = set()

    try:
        for i, series in enumerate(selected, 1):
            base = f"Series_{(series.series_number or i):03d}_{sanitize_filename(series.series_description)}"
            folder = unique_path(study_dir / base, taken_folders).name
            summary = export_series(series, study_dir, folder, args, errors)
            if summary:
                summaries.append(summary)
    except KeyboardInterrupt:
        logger.error("\nInterruption utilisateur (Ctrl+C). Nettoyage...")
        return 130

    total_converted = sum(s["converted"] for s in summaries)

    export_summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "input": str(input_dir),
        "files_scanned": stats["files_scanned"],
        "dicom_detected": stats["dicom_detected"],
        "series_detected": stats["series_detected"],
        "series_exported": len(summaries),
        "images_converted": total_converted,
        "ignored": stats["ignored"],
        "errors": len(errors),
        "format": args.format,
        "bit_depth": args.bit_depth,
        "window": args.window,
        "anonymized": args.anonymize,
        "series": summaries,
    }
    (output_dir / "export_summary.json").write_text(
        json.dumps(export_summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    if errors:
        (output_dir / "conversion_errors.txt").write_text(
            "\n".join(errors), encoding="utf-8"
        )

    zip_path: Optional[Path] = None
    zip_size = 0
    if args.zip and total_converted > 0:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        zip_path = output_dir / f"dicom_export_{ts}.zip"
        try:
            zip_size = create_zip(output_dir, zip_path)
        except Exception as exc:  # noqa: BLE001
            logger.error("Échec de création du ZIP : %s", exc)
            if zip_path.exists():
                zip_path.unlink()  # supprime le ZIP incomplet
            zip_path = None

    _print_report(export_summary, output_dir, zip_path, zip_size)
    return 0 if total_converted > 0 else 1


def _print_report(summary: dict, output_dir: Path, zip_path: Optional[Path], zip_size: int) -> None:
    print("\n===== RÉSUMÉ DE CONVERSION =====")
    print(f"Fichiers analysés    : {summary['files_scanned']}")
    print(f"DICOM détectés       : {summary['dicom_detected']}")
    print(f"Séries détectées     : {summary['series_detected']}")
    print(f"Séries exportées     : {summary['series_exported']}")
    print(f"Images converties    : {summary['images_converted']}")
    print(f"Fichiers ignorés     : {summary['ignored']}")
    print(f"Erreurs              : {summary['errors']}")
    print(f"Dossier exporté      : {output_dir.resolve()}")
    if zip_path:
        print(f"ZIP                  : {zip_path.resolve()}")
        print(f"Taille du ZIP        : {human_size(zip_size)}")
    if summary["errors"]:
        print(f"Détails des erreurs  : {(output_dir / 'conversion_errors.txt').resolve()}")
    print("================================\n")


def main(argv: Optional[list[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return run(args)
    except KeyboardInterrupt:
        print("\nInterrompu.", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
