#!/usr/bin/env python3
"""Génère le lot 3D `poumons_3d/` (atlas RGBA + maillages GLB + metadata.json)
à partir des DICOM bruts du parenchyme.

Pipeline :
  DICOM -> volume HU -> segmentation poumons D/G -> recadrage sur les poumons
  -> ré-échantillonnage isotrope 1,2 mm -> classification densitométrique en
  6 classes -> encodage RGBA -> atlas de coupes axiales (PNG) + maillages GLB
  + metadata.json.

AVERTISSEMENT : la classification est une APPROXIMATION densitométrique par
seuils Hounsfield. Elle n'est pas un diagnostic. Les classes de « réticulation »
(motif de texture) ne sont pas séparables de façon fiable du verre dépoli par
la seule densité ; elles sont ici approchées par bandes de HU.

    python scripts/build_lung_bundle.py --input export/DICOM \
        --output export/Study_001/poumons_3d --series 302
"""

from __future__ import annotations

import argparse
import json
import logging
import struct
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage
from skimage import measure
from skimage.segmentation import clear_border

# Le script vit dans scripts/ ; on ajoute la racine du dépôt au path.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dicomkit.dicomio.dicom_series import scan_directory  # noqa: E402
from dicomkit.volume.volume_builder import Volume, build_volume  # noqa: E402


def segment_lungs_robust(hu: np.ndarray) -> dict:
    """Segmentation pulmonaire robuste D/G, adaptée aux poumons fibrosants.

    Air interne (nettoyage du bord coupe par coupe) -> 2 plus grandes
    composantes -> remplissage des vaisseaux/fibrose internes -> bornage par le
    torse solide (corps ∪ poumon) pour écarter l'air péri-corporel -> retrait
    des bandes d'air purement basales (creux dos/table) -> séparation D/G.
    Retourne un dict de masques booléens : combined, right, left.
    """
    nz = hu.shape[0]
    air = (hu < -400) & (hu > -1500)

    internal = np.stack([clear_border(air[z]) for z in range(nz)])
    lbl, _ = ndimage.label(internal)
    sizes = ndimage.sum(np.ones_like(lbl), lbl, index=range(1, lbl.max() + 1))
    lung = np.isin(lbl, np.argsort(sizes)[::-1][:2] + 1)
    lung = ndimage.binary_fill_holes(lung)

    # Torse solide : corps (plus grosse composante tissu, table exclue) ∪ poumon.
    tissue = hu > -320
    lb, _ = ndimage.label(tissue)
    st = ndimage.sum(np.ones_like(lb), lb, index=range(1, lb.max() + 1))
    body = lb == (np.argmax(st) + 1)
    solid = np.stack([ndimage.binary_fill_holes(body[z] | lung[z]) for z in range(nz)])

    # Récupère la fibrose sous-pleurale (closing borné par le torse).
    lung = ndimage.binary_closing(lung, iterations=2) & solid

    # Retrait des bandes d'air situées tout en bas (sous le poumon) par coupe.
    for z in range(nz):
        ys = np.where(lung[z].any(axis=1))[0]
        if len(ys) == 0:
            continue
        cutoff = ys.min() + int(0.85 * (ys.max() - ys.min()))
        strip = np.zeros_like(lung[z])
        strip[cutoff:] = True
        band = lung[z] & strip
        # Ne retire que les composantes larges et fines de cette zone basse.
        lab2, m2 = ndimage.label(band)
        for i, sl in enumerate(ndimage.find_objects(lab2), 1):
            if sl is None:
                continue
            w = sl[1].stop - sl[1].start
            h = sl[0].stop - sl[0].start
            if w > 0.5 * lung.shape[2] and h < 0.12 * lung.shape[1]:
                lung[z][sl][lab2[sl] == i] = False

    lf, _ = ndimage.label(lung)
    sf = ndimage.sum(np.ones_like(lf), lf, index=range(1, lf.max() + 1))
    lung = np.isin(lf, np.argsort(sf)[::-1][:2] + 1)

    right, left = _split_left_right(lung)
    return {"combined": lung, "right": right, "left": left}


def _split_left_right(lung: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Sépare D/G par le plan sagittal du médiastin.

    Les lobes fusionnent souvent au médiastin antérieur : une séparation par
    composantes connexes échoue. On coupe plutôt au x où le poumon est le moins
    présent dans la région centrale (le médiastin). Convention LPS : x croissant
    = gauche patient, donc x faible = poumon droit.
    """
    profile = lung.sum(axis=(0, 1)).astype(float)   # voxels poumon par colonne x
    nx = lung.shape[2]
    lo, hi = int(0.30 * nx), int(0.70 * nx)
    mid = lo + int(np.argmin(profile[lo:hi]))
    right = lung.copy()
    right[:, :, mid:] = False
    left = lung.copy()
    left[:, :, :mid] = False
    return right, left


VESSEL_HU = -100.0   # seuil vaisseaux/bronches (dense), classé à pleine résolution


def classify_ids(hu: np.ndarray, lung: np.ndarray) -> np.ndarray:
    """Ids de classe (uint8) par bandes HU, dans le masque poumon."""
    ids = np.zeros(hu.shape, dtype=np.uint8)

    def assign(mask: np.ndarray, cid: int) -> None:
        ids[lung & mask & (ids == 0)] = cid

    assign(hu >= VESSEL_HU, 5)                          # vaisseaux / bronches
    assign((hu >= -350.0) & (hu < VESSEL_HU), 4)        # réticulation / fibrose
    assign((hu >= -600.0) & (hu < -350.0), 3)           # verre dépoli
    assign((hu >= -750.0) & (hu < -600.0), 2)           # réticulation fine
    assign((hu >= -950.0) & (hu < -750.0), 1)           # poumon sain
    assign(hu < -950.0, 6)                              # hypoatténuation
    ids[lung & (ids == 0)] = 1
    return ids

logger = logging.getLogger("build_lung_bundle")

# --- Définition des 6 classes (ids/couleurs figés ; volumes calculés) ---------
# Les bornes HU sont des repères densitométriques indicatifs et se recouvrent
# en pratique clinique. L'ordre d'attribution est du plus dense au moins dense
# pour que les vaisseaux (denses) l'emportent sur la fibrose, etc.
ISO_MM = 1.2  # voxel isotrope cible (mm)
HU_ENCODE_LOW, HU_ENCODE_HIGH = -1000.0, -200.0  # plage encodée sur le canal R
CLASS_STEP = 40  # G = id * CLASS_STEP

CLASSES = [
    # id, nom, couleur hex, opacité de base (fonction de transfert du viewer)
    (1, "Poumon sain", "#3fa34d", 0.10),
    (2, "Réticulation fine sur poumon aéré", "#9ae6b4", 0.55),
    (3, "Verre dépoli", "#f5c542", 0.70),
    (4, "Réticulation / fibrose", "#e8590c", 0.85),
    (5, "Vaisseaux et bronches", "#c0392b", 0.90),
    (6, "Hypoatténuation", "#2b6cb0", 0.60),
]


def crop_to_mask(vol: np.ndarray, masks: dict, margin: int = 4):
    """Recadre le volume et les masques sur la boîte englobante du poumon."""
    zz, yy, xx = np.where(masks["combined"])
    z0, z1 = max(zz.min() - margin, 0), min(zz.max() + margin + 1, vol.shape[0])
    y0, y1 = max(yy.min() - margin, 0), min(yy.max() + margin + 1, vol.shape[1])
    x0, x1 = max(xx.min() - margin, 0), min(xx.max() + margin + 1, vol.shape[2])
    sl = (slice(z0, z1), slice(y0, y1), slice(x0, x1))
    out_masks = {k: m[sl] for k, m in masks.items()}
    return vol[sl], out_masks


def resample_iso(hu: np.ndarray, masks: dict, spacing_xyz, iso: float):
    """Ré-échantillonne à un voxel isotrope `iso` mm. HU linéaire, masques ppv."""
    sx, sy, sz = spacing_xyz
    # array est [z,y,x] ; facteurs de zoom dans le même ordre.
    factors = (sz / iso, sy / iso, sx / iso)
    hu_rs = ndimage.zoom(hu.astype(np.float32), factors, order=1)
    masks_rs = {
        k: ndimage.zoom(m.astype(np.uint8), factors, order=0).astype(bool)
        for k, m in masks.items()
    }
    return hu_rs, masks_rs


def encode_rgba(hu: np.ndarray, ids: np.ndarray, right: np.ndarray,
                left: np.ndarray, lung: np.ndarray) -> np.ndarray:
    """Construit le volume RGBA uint8 [z,y,x,4] selon le contrat d'encodage."""
    nz, ny, nx = hu.shape
    rgba = np.zeros((nz, ny, nx, 4), dtype=np.uint8)
    r = (hu - HU_ENCODE_LOW) / (HU_ENCODE_HIGH - HU_ENCODE_LOW)
    rgba[..., 0] = np.clip(r * 255.0 + 0.5, 0, 255).astype(np.uint8)
    rgba[..., 1] = (ids.astype(np.uint16) * CLASS_STEP).clip(0, 255).astype(np.uint8)
    b = np.zeros((nz, ny, nx), dtype=np.uint8)
    b[right] = 80
    b[left] = 160
    rgba[..., 2] = b
    rgba[..., 3] = np.where(lung, 255, 0).astype(np.uint8)
    return rgba


def build_atlas(rgba: np.ndarray, cols: int = 15):
    """Aplati [z,y,x,4] en atlas de tuiles (une par coupe axiale, ligne par ligne)."""
    nz, ny, nx, _ = rgba.shape
    rows = int(np.ceil(nz / cols))
    atlas = np.zeros((rows * ny, cols * nx, 4), dtype=np.uint8)
    for i in range(nz):
        row, col = divmod(i, cols)
        atlas[row * ny:(row + 1) * ny, col * nx:(col + 1) * nx] = rgba[i]
    return atlas, cols, rows


# --- Export GLB minimal autonome ---------------------------------------------

def _smooth_decimate(mask: np.ndarray, iso: float, target_faces: int):
    """Marching cubes -> lissage laplacien -> décimation VTK. Retourne (verts_mm, faces).

    Verts en mm dans le repère (x, y, z), origine au coin du volume.
    """
    import vtk
    from vtk.util import numpy_support

    # skimage renvoie verts en (z, y, x) avec l'espacement fourni.
    verts, faces, _, _ = measure.marching_cubes(
        mask.astype(np.uint8), level=0.5, spacing=(iso, iso, iso), step_size=1
    )
    # Reordonne (z,y,x) -> (x,y,z).
    verts_xyz = verts[:, [2, 1, 0]].astype(np.float32)

    # Construit un vtkPolyData pour lisser + décimer.
    points = vtk.vtkPoints()
    points.SetData(numpy_support.numpy_to_vtk(verts_xyz, deep=True))
    cells = vtk.vtkCellArray()
    tri = np.hstack([np.full((faces.shape[0], 1), 3, np.int64), faces]).astype(np.int64)
    cells.SetCells(faces.shape[0], numpy_support.numpy_to_vtkIdTypeArray(tri.ravel(), deep=True))
    poly = vtk.vtkPolyData()
    poly.SetPoints(points)
    poly.SetPolys(cells)

    smoother = vtk.vtkWindowedSincPolyDataFilter()
    smoother.SetInputData(poly)
    smoother.SetNumberOfIterations(20)
    smoother.SetPassBand(0.1)
    smoother.NonManifoldSmoothingOn()
    smoother.NormalizeCoordinatesOn()
    smoother.Update()
    poly = smoother.GetOutput()

    n_faces = poly.GetNumberOfPolys()
    if n_faces > target_faces and n_faces > 0:
        deci = vtk.vtkQuadricDecimation()   # atteint la réduction cible de façon fiable
        deci.SetInputData(poly)
        deci.SetTargetReduction(min(0.95, 1.0 - target_faces / n_faces))
        deci.Update()
        poly = deci.GetOutput()

    normals = vtk.vtkPolyDataNormals()
    normals.SetInputData(poly)
    normals.SplittingOff()
    normals.ConsistencyOn()
    normals.Update()
    poly = normals.GetOutput()

    v = numpy_support.vtk_to_numpy(poly.GetPoints().GetData()).astype(np.float32)
    nrm = numpy_support.vtk_to_numpy(poly.GetPointData().GetNormals()).astype(np.float32)
    fp = numpy_support.vtk_to_numpy(poly.GetPolys().GetData()).reshape(-1, 4)[:, 1:]
    return v, nrm, fp.astype(np.uint32)


def write_glb(path: Path, verts: np.ndarray, normals: np.ndarray,
              faces: np.ndarray, color=(0.8, 0.8, 0.8, 1.0)) -> None:
    """Écrit un fichier .glb (glTF binaire) : un mesh, POSITION+NORMAL+indices."""
    verts = np.ascontiguousarray(verts, dtype=np.float32)
    normals = np.ascontiguousarray(normals, dtype=np.float32)
    idx = np.ascontiguousarray(faces.ravel(), dtype=np.uint32)

    bin_parts, views, accessors = [], [], []
    offset = 0

    def add_view(data: bytes, target: int) -> int:
        nonlocal offset
        pad = (4 - len(data) % 4) % 4
        data = data + b"\x00" * pad
        views.append({"buffer": 0, "byteOffset": offset, "byteLength": len(data) - pad,
                      "target": target})
        bin_parts.append(data)
        offset += len(data)
        return len(views) - 1

    ARRAY_BUFFER, ELEMENT_ARRAY = 34962, 34963
    v_view = add_view(verts.tobytes(), ARRAY_BUFFER)
    n_view = add_view(normals.tobytes(), ARRAY_BUFFER)
    i_view = add_view(idx.tobytes(), ELEMENT_ARRAY)

    vmin = verts.min(axis=0).tolist()
    vmax = verts.max(axis=0).tolist()
    accessors.append({"bufferView": v_view, "componentType": 5126, "count": len(verts),
                      "type": "VEC3", "min": vmin, "max": vmax})           # POSITION
    accessors.append({"bufferView": n_view, "componentType": 5126, "count": len(normals),
                      "type": "VEC3"})                                      # NORMAL
    accessors.append({"bufferView": i_view, "componentType": 5125, "count": len(idx),
                      "type": "SCALAR"})                                    # indices

    gltf = {
        "asset": {"version": "2.0", "generator": "build_lung_bundle"},
        "scene": 0,
        "scenes": [{"nodes": [0]}],
        "nodes": [{"mesh": 0}],
        "meshes": [{"primitives": [{"attributes": {"POSITION": 0, "NORMAL": 1},
                                    "indices": 2, "material": 0}]}],
        "materials": [{"pbrMetallicRoughness": {
            "baseColorFactor": list(color), "metallicFactor": 0.0,
            "roughnessFactor": 0.85}, "doubleSided": True}],
        "buffers": [{"byteLength": offset}],
        "bufferViews": views,
        "accessors": accessors,
    }

    json_bytes = json.dumps(gltf, separators=(",", ":")).encode("utf-8")
    json_bytes += b" " * ((4 - len(json_bytes) % 4) % 4)
    bin_blob = b"".join(bin_parts)
    total = 12 + 8 + len(json_bytes) + 8 + len(bin_blob)
    with open(path, "wb") as f:
        f.write(b"glTF")
        f.write(struct.pack("<II", 2, total))
        f.write(struct.pack("<I", len(json_bytes)))
        f.write(b"JSON")
        f.write(json_bytes)
        f.write(struct.pack("<I", len(bin_blob)))
        f.write(b"BIN\x00")
        f.write(bin_blob)


# --- Statistiques par zone ----------------------------------------------------

def zone_stats(ids: np.ndarray, right: np.ndarray, left: np.ndarray,
               voxel_ml: float) -> list[dict]:
    """6 zones (bases/moyennes/sommets, D et G). z croissant = crânial.

    « Atteinte » = classes 3 (verre dépoli) + 4 (fibrose/réticulation).
    """
    zones = []
    involved = np.isin(ids, [3, 4])
    for side_name, side_mask, code in (("Droit", right, "D"), ("Gauche", left, "G")):
        zz = np.where(side_mask.any(axis=(1, 2)))[0]
        if len(zz) == 0:
            continue
        z0, z1 = zz.min(), zz.max() + 1
        thirds = np.linspace(z0, z1, 4).astype(int)
        for label, (a, b) in zip(
            ("Base", "Zone moyenne", "Sommet"),
            ((thirds[0], thirds[1]), (thirds[1], thirds[2]), (thirds[2], thirds[3])),
        ):
            band = np.zeros_like(side_mask)
            band[a:b] = True
            zone_mask = side_mask & band
            total = int(zone_mask.sum())
            inv = int((zone_mask & involved).sum())
            zones.append({
                "name": f"{label} {code}",
                "label": label,
                "side": side_name,
                "volume_ml": round(total * voxel_ml, 1),
                "involved_ml": round(inv * voxel_ml, 1),
                "involved_pct": round(100.0 * inv / total, 1) if total else 0.0,
            })
    return zones


def pick_series(series_list, wanted: int):
    for s in series_list:
        if s.series_number == wanted:
            return s
    # repli : plus grande série de catégorie poumon.
    lungs = [s for s in series_list if "LUNG" in s.category]
    if not lungs:
        raise SystemExit("Aucune série parenchyme trouvée.")
    return max(lungs, key=lambda s: s.count)


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--series", type=int, default=302)
    ap.add_argument("--iso", type=float, default=ISO_MM)
    ap.add_argument("--cols", type=int, default=15)
    args = ap.parse_args(argv)

    logger.info("1/8 Analyse DICOM…")
    series_list, _ = scan_directory(args.input, show_progress=False)
    series = pick_series(series_list, args.series)
    logger.info("    série retenue : n°%s %s (%d coupes)",
                series.series_number, series.series_description, series.count)

    logger.info("2/8 Reconstruction du volume…")
    vol: Volume = build_volume(series)
    logger.info("    volume %s, spacing %s mm", vol.shape_zyx,
                tuple(round(s, 3) for s in vol.spacing))

    logger.info("3/8 Segmentation des poumons D/G…")
    masks = segment_lungs_robust(vol.array)

    logger.info("4/8 Classification densitométrique (6 classes) à pleine résolution…")
    hu_c, masks_c = crop_to_mask(vol.array, masks)
    ids_full = classify_ids(hu_c, masks_c["combined"])

    logger.info("5/8 Recadrage + ré-échantillonnage isotrope %.2f mm…", args.iso)
    hu, masks_rs = resample_iso(hu_c, masks_c, vol.spacing, args.iso)
    lung = masks_rs["combined"]
    right, left = masks_rs["right"], masks_rs["left"]
    # ré-échantillonne les ids (plus proche voisin) puis restreint au poumon
    sx, sy, sz = vol.spacing
    ids = ndimage.zoom(ids_full, (sz / args.iso, sy / args.iso, sx / args.iso),
                       order=0)
    # aligne les formes (arrondis de zoom)
    zt = tuple(min(a, b) for a, b in zip(ids.shape, hu.shape))
    ids = ids[:zt[0], :zt[1], :zt[2]]
    hu = hu[:zt[0], :zt[1], :zt[2]]
    lung = lung[:zt[0], :zt[1], :zt[2]]
    right = right[:zt[0], :zt[1], :zt[2]]
    left = left[:zt[0], :zt[1], :zt[2]]
    ids[~lung] = 0
    ids[lung & (ids == 0)] = 1
    nz, ny, nx = hu.shape
    logger.info("    volume final %d×%d×%d voxels (%.1f×%.1f×%.1f mm)",
                nx, ny, nz, nx * args.iso, ny * args.iso, nz * args.iso)

    voxel_ml = (args.iso ** 3) / 1000.0
    total_ml = float(lung.sum()) * voxel_ml
    class_stats = []
    for cid, name, color, base_op in CLASSES:
        cnt = int((ids == cid).sum())
        class_stats.append({
            "id": cid, "name": name, "color": color, "base_opacity": base_op,
            "voxels": cnt,
            "volume_ml": round(cnt * voxel_ml, 1),
            "percent": round(100.0 * cnt / lung.sum(), 2) if lung.any() else 0.0,
        })

    logger.info("6/8 Encodage RGBA + atlas…")
    rgba = encode_rgba(hu, ids, right, left, lung)
    atlas, cols, rows = build_atlas(rgba, cols=args.cols)
    args.output.mkdir(parents=True, exist_ok=True)
    Image.fromarray(atlas, "RGBA").save(args.output / "volume_atlas.png")
    logger.info("    atlas %d×%d px (%d tuiles, %d×%d)",
                atlas.shape[1], atlas.shape[0], nz, cols, rows)

    logger.info("7/8 Maillages GLB (lissage + décimation)…")
    mesh_specs = [
        ("poumon_droit.glb", right, (0.55, 0.62, 0.72, 1.0), 55000),
        ("poumon_gauche.glb", left, (0.55, 0.62, 0.72, 1.0), 52000),
        ("fibrose.glb", np.isin(ids, [3, 4]), (0.91, 0.35, 0.05, 1.0), 82000),
        ("vaisseaux.glb", ids == 5, (0.75, 0.23, 0.17, 1.0), 33000),
    ]
    mesh_meta = []
    for fname, mask, color, target in mesh_specs:
        if mask.sum() < 10:
            logger.info("    (ignoré, vide) %s", fname)
            continue
        v, n, f = _smooth_decimate(mask, args.iso, target)
        write_glb(args.output / fname, v, n, f, color)
        mesh_meta.append({"file": fname, "vertices": int(len(v)), "faces": int(len(f))})
        logger.info("    %s : %d faces", fname, len(f))

    logger.info("8/8 metadata.json…")
    mean_hu = float(hu[lung].mean()) if lung.any() else 0.0
    involved = np.isin(ids, [3, 4])
    extent_pct = round(100.0 * involved.sum() / lung.sum(), 1) if lung.any() else 0.0
    right_inv = float((involved & right).sum()) / max(right.sum(), 1) * 100
    left_inv = float((involved & left).sum()) / max(left.sum(), 1) * 100

    meta = {
        "disclaimer": (
            "Reconstruction issue d'une segmentation automatique par seuils de "
            "densité (Hounsfield). Approximation à visée pédagogique — ne "
            "constitue pas un compte rendu radiologique ni un diagnostic."
        ),
        "study": {
            "description": series.study_description,
            "series_description": series.series_description,
            "series_number": series.series_number,
            "study_date": str(getattr(series.sample_header, "StudyDate", "")),
            "modality": series.modality,
        },
        "volume": {
            "dims": [nx, ny, nz],
            "voxel_mm": [args.iso, args.iso, args.iso],
            "physical_mm": [round(nx * args.iso, 1), round(ny * args.iso, 1),
                            round(nz * args.iso, 1)],
            "orientation": "LPS (x→gauche patiente, y→postérieur, z→crânial)",
        },
        "atlas": {
            "file": "volume_atlas.png",
            "tile_px": [nx, ny],
            "tiles": nz,
            "cols": cols,
            "rows": rows,
            "atlas_px": [atlas.shape[1], atlas.shape[0]],
            "fill_order": "row-major (ligne = i // cols, colonne = i % cols)",
        },
        "channels": {
            "R": {"meaning": "densité normalisée",
                  "decode_hu": f"HU = R/255*{HU_ENCODE_HIGH - HU_ENCODE_LOW:g}"
                               f" + ({HU_ENCODE_LOW:g})",
                  "hu_range": [HU_ENCODE_LOW, HU_ENCODE_HIGH]},
            "G": {"meaning": "identifiant de classe",
                  "decode_id": f"id = round(G/{CLASS_STEP})"},
            "B": {"meaning": "côté", "right": 80, "left": 160, "outside": 0},
            "A": {"meaning": "masque pulmonaire", "lung": 255, "outside": 0},
        },
        "classes": class_stats,
        "meshes": mesh_meta,
        "stats": {
            "lung_volume_ml": round(total_ml, 0),
            "mean_hu": round(mean_hu, 1),
            "extent_involved_pct": extent_pct,
            "healthy_pct": next(c["percent"] for c in class_stats if c["id"] == 1),
            "right_involved_pct": round(right_inv, 1),
            "left_involved_pct": round(left_inv, 1),
            "zones": zone_stats(ids, right, left, voxel_ml),
        },
        "warnings": vol.warnings,
    }
    (args.output / "metadata.json").write_text(
        json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    logger.info("Terminé → %s", args.output)
    logger.info("  Poumon %.0f mL | HU moyen %.1f | atteinte %.1f%% (D %.1f%% / G %.1f%%)",
                total_ml, mean_hu, extent_pct, right_inv, left_inv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
