"""Classification densitométrique (Hounsfield) des tissus pulmonaires.

⚠️ AVERTISSEMENT MÉDICAL IMPORTANT
Ce module NE détecte PAS de pathologie. Il colore des plages de densité (HU) à
l'intérieur du masque pulmonaire. La correspondance entre une plage HU et un
terme radiologique (verre dépoli, fibrose, bronchectasie de traction…) est une
APPROXIMATION densitométrique, non validée médicalement, qui ne constitue en
aucun cas un diagnostic. La bronchectasie de traction et le honeycombing sont
des diagnostics morphologiques qui ne peuvent pas être établis de façon fiable
par un seuil de densité.

Pour un usage clinique, importez un masque réalisé/validé par un radiologue
(voir segmentation_manager : import NIfTI / futur DICOM SEG).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import ndimage

from segmentation import LungSegmentation
from volume_builder import Volume

logger = logging.getLogger("dicom_to_images")

DENSITY_DISCLAIMER = (
    "Coloration densitométrique (Hounsfield) approximative — NON validée "
    "médicalement, ne constitue pas un diagnostic. Les étiquettes (verre dépoli, "
    "fibrose, bronchectasie de traction…) sont des correspondances de densité "
    "indicatives, pas une détection de pathologie."
)


@dataclass(frozen=True)
class TissueClass:
    """Une classe densitométrique : plage HU, couleur, libellé."""

    name: str
    hu_low: float
    hu_high: float
    color: tuple[float, float, float]   # RGB 0..1


# Plages HU indicatives (littérature de densitométrie CT thoracique). Ce sont
# des repères approximatifs ; ils se recouvrent en pratique clinique.
DEFAULT_CLASSES: tuple[TissueClass, ...] = (
    # Lumière aérienne / bronches / emphysème (très hypodense).
    TissueClass("Bronches / air", -1024.0, -950.0, (0.20, 0.85, 0.95)),   # cyan
    # Parenchyme normalement aéré (non coloré par défaut, informatif).
    TissueClass("Parenchyme normal", -950.0, -700.0, (0.30, 0.75, 0.40)),  # vert
    # Densité augmentée type « verre dépoli ».
    TissueClass("Verre dépoli (approx.)", -700.0, -350.0, (0.95, 0.85, 0.20)),  # jaune
    # Réticulations / fibrose / consolidation (dense).
    TissueClass("Fibrose / dense (approx.)", -350.0, 50.0, (0.90, 0.25, 0.15)),  # rouge
)

# Couleur dédiée à l'heuristique géométrique de bronchectasie de traction.
TRACTION_COLOR = (0.85, 0.30, 0.90)  # magenta


@dataclass
class TissueMap:
    """Résultat : masques colorés par classe densitométrique."""

    classes: dict[str, np.ndarray]              # nom -> masque bool [z,y,x]
    colors: dict[str, tuple[float, float, float]]
    voxel_volume_mm3: float
    warnings: list[str]

    def volume_ml(self, name: str) -> float:
        m = self.classes.get(name)
        if m is None:
            return 0.0
        return float(m.sum()) * self.voxel_volume_mm3 / 1000.0

    def label_volume(self, order: Optional[list[str]] = None) -> np.ndarray:
        """Volume d'étiquettes entières (0 = fond), pour un overlay unique.

        En cas de recouvrement, l'ordre (dernier gagnant) suit ``order``.
        """
        names = order or list(self.classes)
        out = np.zeros(next(iter(self.classes.values())).shape, dtype=np.uint8)
        for i, name in enumerate(names, 1):
            out[self.classes[name]] = i
        return out

    def metrics(self) -> dict:
        return {
            "disclaimer": DENSITY_DISCLAIMER,
            "classes": {n: round(self.volume_ml(n), 1) for n in self.classes},
        }


def extract_lung_tree(
    volume: Volume,
    seg: LungSegmentation,
    hu_threshold: float = -500.0,
    min_component_ml: float = 0.3,
) -> np.ndarray:
    """Extrait l'arbre vaisseaux + parois bronchiques à l'intérieur des poumons.

    Ce sont les structures « branchantes » denses (vaisseaux pulmonaires,
    parois des bronches) visibles au sein du parenchyme. On seuille au-dessus de
    ``hu_threshold`` DANS le masque pulmonaire, puis on retire les petits amas
    pour ne garder que le réseau connecté.

    ⚠️ Représentation anatomique indicative (densitométrie), non validée ;
    ne distingue pas artères/veines/bronches et ne constitue pas un diagnostic.
    """
    lung = seg.combined
    tree = lung & (volume.array > hu_threshold)
    labels, n = ndimage.label(tree)
    if n == 0:
        return tree
    voxel_ml = volume.voxel_volume_mm3 / 1000.0
    min_voxels = max(1, int(min_component_ml / max(voxel_ml, 1e-9)))
    sizes = ndimage.sum(np.ones_like(labels), labels, index=range(1, n + 1))
    keep = [i + 1 for i, s in enumerate(sizes) if s >= min_voxels]
    return np.isin(labels, keep)


def classify_lung_tissue(
    volume: Volume,
    seg: LungSegmentation,
    classes: tuple[TissueClass, ...] = DEFAULT_CLASSES,
    include_traction_heuristic: bool = True,
) -> TissueMap:
    """Colore les tissus par plage HU à l'intérieur du masque pulmonaire.

    Ne s'applique QU'À l'intérieur des poumons segmentés (``seg.combined``),
    pour ne pas colorer l'air extérieur ni la paroi thoracique.
    """
    lung = seg.combined
    hu = volume.array
    result: dict[str, np.ndarray] = {}
    colors: dict[str, tuple[float, float, float]] = {}
    warnings = [DENSITY_DISCLAIMER]

    for c in classes:
        mask = lung & (hu >= c.hu_low) & (hu < c.hu_high)
        result[c.name] = mask
        colors[c.name] = c.color

    if include_traction_heuristic:
        traction = _traction_heuristic(volume, seg, result, warnings)
        result["Bronchectasie traction (heuristique)"] = traction
        colors["Bronchectasie traction (heuristique)"] = TRACTION_COLOR

    logger.warning("Analyse densitométrique poumons : %s", DENSITY_DISCLAIMER)
    return TissueMap(result, colors, volume.voxel_volume_mm3, warnings)


def _traction_heuristic(
    volume: Volume,
    seg: LungSegmentation,
    classes: dict[str, np.ndarray],
    warnings: list[str],
) -> np.ndarray:
    """Heuristique géométrique GROSSIÈRE de bronchectasie de traction.

    NON fiable : approxime des lumières aériennes (air) entourées de tissu
    dense (fibrose) — signe indirect de traction. À interpréter avec prudence.
    """
    warnings.append(
        "Bronchectasie de traction : heuristique géométrique non fiable "
        "(air au contact de tissu dense). Ne pas utiliser pour un diagnostic."
    )
    air = classes.get("Bronches / air")
    dense = classes.get("Fibrose / dense (approx.)")
    if air is None or dense is None or not dense.any():
        return np.zeros_like(seg.combined)
    # Air adjacent (dilatation 1 voxel) à du tissu dense.
    dense_dilated = ndimage.binary_dilation(dense, iterations=1)
    return air & dense_dilated
