"""Fonctions utilitaires partagées : nettoyage de noms, logging, formatage."""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger("dicom_to_images")

# Caractères interdits sous Windows + contrôle, plus ceux gênants sous macOS.
_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED_WIN = {
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}


def setup_logging(verbose: bool = False) -> None:
    """Configure le logging standard vers stderr."""
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    # Silence le bavardage DEBUG des bibliothèques tierces (matplotlib, PIL…),
    # même en mode --verbose : ce ne sont pas des messages de l'application.
    for noisy in ("matplotlib", "matplotlib.font_manager", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def sanitize_filename(name: str, fallback: str = "UNKNOWN", max_len: int = 80) -> str:
    """Nettoie une chaîne pour en faire un composant de chemin compatible macOS/Windows.

    - Remplace les caractères interdits par ``_``.
    - Retire espaces/points en début et fin (interdits sous Windows).
    - Évite les noms réservés Windows.
    - Tronque à ``max_len`` caractères.
    """
    if name is None:
        name = ""
    cleaned = _INVALID_CHARS.sub("_", str(name))
    cleaned = cleaned.strip().strip(".").strip()
    cleaned = re.sub(r"\s+", "_", cleaned)
    cleaned = re.sub(r"_+", "_", cleaned).strip("_")
    if not cleaned:
        cleaned = fallback
    if cleaned.upper() in _RESERVED_WIN:
        cleaned = f"_{cleaned}"
    return cleaned[:max_len].rstrip("_. ") or fallback


def human_size(num_bytes: int) -> str:
    """Formate une taille en octets de façon lisible."""
    size = float(num_bytes)
    for unit in ("o", "Ko", "Mo", "Go", "To"):
        if size < 1024.0:
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} Po"


def unique_path(base: Path, taken: set[str]) -> Path:
    """Retourne un chemin dont le nom n'entre pas en collision avec ``taken``.

    Ajoute un suffixe ``_2``, ``_3``... si nécessaire. Met à jour ``taken``.
    """
    name = base.name
    candidate = name
    counter = 2
    while candidate.lower() in taken:
        candidate = f"{name}_{counter}"
        counter += 1
    taken.add(candidate.lower())
    return base.with_name(candidate)


class ProgressPrinter:
    """Affiche une progression simple sur une seule ligne (stderr)."""

    def __init__(self, total: int, prefix: str = "Progression") -> None:
        self.total = max(total, 1)
        self.prefix = prefix
        self.count = 0

    def update(self, increment: int = 1) -> None:
        self.count += increment
        pct = min(100.0, 100.0 * self.count / self.total)
        sys.stderr.write(f"\r{self.prefix}: {self.count}/{self.total} ({pct:5.1f}%)")
        sys.stderr.flush()

    def done(self) -> None:
        sys.stderr.write("\n")
        sys.stderr.flush()
