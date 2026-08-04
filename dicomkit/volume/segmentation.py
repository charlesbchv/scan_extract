"""Segmentation pulmonaire automatique NON-IA (seuillage + morphologie 3D).

AVERTISSEMENT : segmentation automatique non validée médicalement. Elle ne
constitue pas un diagnostic. Elle sert de point de départ, corrigeable
manuellement, et volontairement conservatrice pour préserver les zones
pathologiques (fibrose, verre dépoli) autant que possible.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np
from scipy import ndimage

from dicomkit.volume.volume_builder import Volume

logger = logging.getLogger("dicom_to_images")

SEG_DISCLAIMER = (
    "Segmentation automatique non validée médicalement — ne pas utiliser seule "
    "pour un diagnostic."
)


@dataclass
class LungSegmentation:
    """Masques pulmonaires binaires + mesures volumétriques."""

    combined: np.ndarray          # bool [z, y, x]
    right: np.ndarray             # bool (poumon droit du patient)
    left: np.ndarray              # bool (poumon gauche du patient)
    voxel_volume_mm3: float
    warnings: list[str]

    def _ml(self, mask: np.ndarray) -> float:
        return float(mask.sum()) * self.voxel_volume_mm3 / 1000.0

    @property
    def volume_total_ml(self) -> float:
        return self._ml(self.combined)

    @property
    def volume_right_ml(self) -> float:
        return self._ml(self.right)

    @property
    def volume_left_ml(self) -> float:
        return self._ml(self.left)

    def metrics(self) -> dict:
        return {
            "disclaimer": SEG_DISCLAIMER,
            "voxel_count_total": int(self.combined.sum()),
            "voxel_count_right": int(self.right.sum()),
            "voxel_count_left": int(self.left.sum()),
            "voxel_volume_mm3": self.voxel_volume_mm3,
            "volume_total_ml": round(self.volume_total_ml, 1),
            "volume_right_ml": round(self.volume_right_ml, 1),
            "volume_left_ml": round(self.volume_left_ml, 1),
            "warnings": self.warnings,
        }


def apply_lung_mask(
    volume: "Volume",
    seg: "LungSegmentation",
    margin_voxels: int = 2,
    outside_hu: int = -1000,
) -> "Volume":
    """Retourne une copie du volume où tout ce qui est hors des poumons est
    remplacé par de l'air (transparent au rendu), pour n'afficher en 3D que
    les poumons et leurs structures internes (vaisseaux, bronches, lésions).

    ``margin_voxels`` dilate légèrement le masque pour conserver la paroi
    bronchique et les vaisseaux périphériques liés aux poumons.
    """
    from dicomkit.volume.volume_builder import Volume

    mask = seg.combined
    if margin_voxels > 0:
        mask = ndimage.binary_dilation(mask, iterations=int(margin_voxels))
    out = np.where(mask, volume.array, np.int16(outside_hu)).astype(np.int16)
    return Volume(
        array=out,
        spacing=volume.spacing,
        origin=volume.origin,
        direction=volume.direction.copy(),
        series_uid=volume.series_uid,
        modality=volume.modality,
        warnings=list(volume.warnings),
    )


def _body_mask(hu: np.ndarray, air_threshold_hu: float, warnings: list[str]) -> np.ndarray:
    """Masque de l'enveloppe corporelle (patient), coupe par coupe.

    Corps = tissu (HU > seuil air) le plus grand, dont on remplit les cavités
    internes (poumons, voies aériennes). L'air à l'intérieur de cette enveloppe
    est de l'air pulmonaire/digestif, jamais l'air ambiant extérieur.
    """
    tissue = hu > air_threshold_hu
    body = np.zeros_like(tissue)
    for z in range(tissue.shape[0]):
        sl = tissue[z]
        if not sl.any():
            continue
        # Plus grande composante de tissu = corps du patient (retire le bruit,
        # la table, le remplissage hors champ de vue circulaire).
        lbl, n = ndimage.label(sl)
        if n == 0:
            continue
        sizes = ndimage.sum(np.ones_like(lbl), lbl, index=range(1, n + 1))
        biggest = int(np.argmax(sizes)) + 1
        patient = lbl == biggest
        # Remplir les cavités internes (poumons) -> enveloppe pleine du corps.
        body[z] = ndimage.binary_fill_holes(patient)
    if not body.any():
        warnings.append("Enveloppe corporelle non détectée : seuil inadapté ?")
    return body


def _select_lung_components(
    labels: np.ndarray, n: int, min_voxels: int, warnings: list[str]
) -> np.ndarray:
    """Sélectionne les composantes d'air ressemblant à des poumons.

    Score = nombre de voxels × (étendue verticale relative). Favorise les
    grandes structures hautes (poumons) plutôt que les poches compactes
    (estomac, anses intestinales). Garde au plus 2 composantes.
    """
    nz = labels.shape[0]
    objects = ndimage.find_objects(labels)
    candidates: list[tuple[float, int]] = []
    for idx, sl in enumerate(objects, 1):
        if sl is None:
            continue
        size = int((labels[sl] == idx).sum())
        if size < min_voxels:
            continue
        zspan = (sl[0].stop - sl[0].start) / max(nz, 1)  # 0..1
        # On exige un minimum d'étalement vertical : un poumon n'est jamais
        # confiné à quelques coupes. L'air digestif l'est souvent.
        if zspan < 0.20:
            continue
        score = size * zspan
        candidates.append((score, idx))

    if not candidates:
        warnings.append(
            "Aucune composante ne ressemble à un poumon (taille/étendue "
            "verticale insuffisantes). Série non thoracique ? Seuil à ajuster ?"
        )
        return _largest_components(labels > 0, 2)

    candidates.sort(reverse=True)
    keep = [idx for _, idx in candidates[:2]]
    if len(candidates) > 2:
        warnings.append(
            f"{len(candidates)} poches d'air candidates ; les 2 plus « pulmonaires » "
            "ont été retenues. Vérifiez sur les coupes MPR."
        )
    return np.isin(labels, keep)


def _largest_components(mask: np.ndarray, keep: int) -> np.ndarray:
    """Conserve les ``keep`` plus grandes composantes connexes 3D."""
    labels, n = ndimage.label(mask)
    if n == 0:
        return mask
    sizes = ndimage.sum(np.ones_like(labels), labels, index=range(1, n + 1))
    order = np.argsort(sizes)[::-1][:keep]
    keep_labels = set((order + 1).tolist())
    return np.isin(labels, list(keep_labels))


def segment_lungs(
    volume: Volume,
    air_threshold_hu: float = -320.0,
    min_component_ml: float = 50.0,
) -> LungSegmentation:
    """Segmente les poumons droit/gauche.

    Étapes : seuillage air (< seuil HU), exclusion de l'air extérieur par
    connexité au bord, sélection des grandes composantes internes, fermeture
    et remplissage de trous 3D, séparation gauche/droite par axe x.
    """
    warnings: list[str] = []
    hu = volume.array
    nz, ny, nx = hu.shape

    # 1. Régions « air/gaz » : poumon + air extérieur + voies aériennes.
    air = hu < air_threshold_hu
    if not air.any():
        warnings.append("Aucune région aérique détectée : seuil inadapté ?")
        empty = np.zeros_like(air)
        return LungSegmentation(empty, empty.copy(), empty.copy(),
                                volume.voxel_volume_mm3, warnings)

    # 2. Air À L'INTÉRIEUR DU CORPS (méthode de l'enveloppe corporelle).
    #    Les poumons se connectent à l'air extérieur par la trachée : exclure
    #    « l'air touchant le bord » supprimerait donc les poumons. On délimite
    #    plutôt le corps du patient et on garde l'air situé dedans.
    body = _body_mask(hu, air_threshold_hu, warnings)
    internal = air & body

    # 3. Sélection des composantes ressemblant à des poumons.
    #    Les poumons sont grands ET s'étendent verticalement sur une bonne
    #    hauteur ; l'air digestif (estomac, côlon) forme des poches compactes.
    #    On classe chaque composante par un score = taille × étendue verticale
    #    et on ne garde que les meilleures (au plus 2, poumons droit + gauche).
    voxel_ml = volume.voxel_volume_mm3 / 1000.0
    min_voxels = max(1, int(min_component_ml / max(voxel_ml, 1e-9)))
    labels2, n2 = ndimage.label(internal)
    if n2 == 0:
        warnings.append("Aucune composante interne : les poumons touchent-ils le bord ?")
        lungs = internal
    else:
        lungs = _select_lung_components(labels2, n2, min_voxels, warnings)

    # 4. Fermeture morphologique + remplissage de trous 3D (vaisseaux, nodules).
    lungs = ndimage.binary_closing(lungs, iterations=1)
    lungs = ndimage.binary_fill_holes(lungs)
    lungs = _largest_components(lungs, 2)

    # 5. Séparation gauche / droite.
    right, left = _split_left_right(lungs, volume, warnings)

    seg = LungSegmentation(
        combined=lungs, right=right, left=left,
        voxel_volume_mm3=volume.voxel_volume_mm3, warnings=warnings,
    )
    logger.warning("Segmentation poumons : %s", SEG_DISCLAIMER)
    return seg


def _split_left_right(
    lungs: np.ndarray, volume: Volume, warnings: list[str]
) -> tuple[np.ndarray, np.ndarray]:
    """Sépare en poumon droit et gauche.

    Tente d'abord deux grandes composantes distinctes (poumons non fusionnés).
    Sinon, sépare par la coordonnée x (côté patient déduit de la direction).
    """
    labels, n = ndimage.label(lungs)
    if n >= 2:
        sizes = ndimage.sum(np.ones_like(labels), labels, index=range(1, n + 1))
        top2 = np.argsort(sizes)[::-1][:2] + 1
        comp_a = labels == top2[0]
        comp_b = labels == top2[1]
        cx_a = np.mean(np.where(comp_a)[2])
        cx_b = np.mean(np.where(comp_b)[2])
        # Poumon droit patient = x monde négatif. Selon direction[0,0] (x row).
        right_is_low_x = volume.direction[0, 0] >= 0
        a_is_right = (cx_a < cx_b) == right_is_low_x
        right, left = (comp_a, comp_b) if a_is_right else (comp_b, comp_a)
        return right, left

    # Fusionnées : coupe médiane par plan x.
    warnings.append("Poumons non séparés par connexité : séparation par plan médian x.")
    right = np.zeros_like(lungs)
    left = np.zeros_like(lungs)
    xs = np.where(lungs.any(axis=(0, 1)))[0]
    if len(xs) == 0:
        return right, left
    mid = int((xs.min() + xs.max()) / 2)
    low = lungs.copy()
    low[:, :, mid:] = False
    high = lungs.copy()
    high[:, :, :mid] = False
    if volume.direction[0, 0] >= 0:
        right, left = low, high  # x bas = droite patient
    else:
        right, left = high, low
    return right, left
