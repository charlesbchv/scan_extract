"""Génère assets/demo.gif : une démo animée (fenêtre + dépôt + progression).

Utilise uniquement Pillow. Sert de démo par défaut jusqu'à ce que vous
enregistriez un vrai screencast de dicom_drop.py.

    python assets/make_demo_gif.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

W, H = 720, 400
OUT = Path(__file__).with_name("demo.gif")


def _font(size: int, bold: bool = False):
    candidates = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    ]
    for c in candidates:
        if Path(c).exists():
            try:
                return ImageFont.truetype(c, size)
            except OSError:
                pass
    return ImageFont.load_default()


F_TITLE = _font(15, bold=True)
F = _font(13)
F_SMALL = _font(11)
F_FOLDER = _font(11, bold=True)


def _round(draw, box, radius, **kw):
    draw.rounded_rectangle(box, radius=radius, **kw)


def _ctext(draw, cx, y, text, font, fill):
    w = draw.textlength(text, font=font)
    draw.text((cx - w / 2, y), text, font=font, fill=fill)


def frame(t: float) -> Image.Image:
    """t dans [0,1] : un cycle complet de la démo."""
    img = Image.new("RGB", (W, H), "#eef3fb")
    d = ImageDraw.Draw(img)

    # Fenêtre
    _round(d, (0, 0, W - 1, H - 1), 14, fill="#f2f6fb", outline="#c7d5e6", width=2)
    d.rectangle((2, 14, W - 2, 40), fill="#dbe4f0")
    _round(d, (0, 0, W - 1, 40), 14, outline="#c7d5e6", width=2)
    for cx, col in ((24, "#ff5f57"), (44, "#febc2e"), (64, "#28c840")):
        d.ellipse((cx - 6, 14, cx + 6, 26), fill=col)
    _ctext(d, W / 2, 12, "DICOM → images : deposez le dossier IMAGES", F_TITLE, "#3a4a63")

    # Réglages
    d.text((60, 58), "Format:", font=F, fill="#42597a")
    _round(d, (118, 56, 170, 74), 4, fill="#ffffff", outline="#c7d5e6")
    d.text((126, 58), "PNG", font=F, fill="#2a3a55")
    d.text((188, 58), "Bits:", font=F, fill="#42597a")
    _round(d, (226, 56, 266, 74), 4, fill="#ffffff", outline="#c7d5e6")
    d.text((240, 58), "8", font=F, fill="#2a3a55")
    d.text((286, 58), "Fenetre:", font=F, fill="#42597a")
    _round(d, (350, 56, 430, 74), 4, fill="#ffffff", outline="#c7d5e6")
    d.text((358, 58), "poumon", font=F, fill="#2a3a55")

    # Zone de dépôt
    dashed = "#4f9fe0" if int(t * 8) % 2 == 0 else "#a9cdf0"
    _round(d, (60, 92, 660, 272), 12, fill="#e8f0fb", outline=dashed, width=3)

    # Phases : 0-0.35 le dossier tombe ; 0.4-0.95 progression ; sinon idle
    if t < 0.38:
        p = min(1.0, t / 0.32)
        y = int(60 + (150 - 60) * p)  # de haut vers la zone
        alpha_drop = p
        fx = 324
        # dossier
        d.polygon(
            [(fx, y + 10), (fx + 26, y + 10), (fx + 32, y + 2), (fx + 66, y + 2),
             (fx + 72, y + 8), (fx + 72, y + 64), (fx, y + 64)],
            fill="#ffcf6b", outline="#e0a83c",
        )
        _ctext(d, fx + 36, y + 40, "IMAGES", F_FOLDER, "#8a5a12")
        _ctext(d, W / 2, 244, "Deposez ici le dossier IMAGES", F, "#5a7699")
    else:
        _ctext(d, W / 2, 150, "Analyse : 3 series, 480 images", F, "#42597a")
        _ctext(d, W / 2, 244, "Conversion en cours...", F, "#5a7699")

    # Barre de progression
    _round(d, (60, 300, 660, 318), 9, fill="#dfe7f1")
    if t >= 0.4:
        p = min(1.0, (t - 0.4) / 0.5)
        fillw = int(600 * p)
        if fillw > 4:
            _round(d, (60, 300, 60 + fillw, 318), 9, fill="#2ea6e0")
        if p >= 1.0:
            _ctext(d, W / 2, 345, "✅  ZIP cree : dicom_export_2026....zip", F, "#1f8f4d")
        else:
            _ctext(d, W / 2, 345, f"Conversion  {int(p*480)}/480", F, "#42597a")

    _ctext(d, W / 2, 376, "Apercu genere par Pillow — remplacez par votre vrai screencast",
           F_SMALL, "#9fb0c6")
    return img


def main() -> None:
    n = 48
    frames = [frame(i / n) for i in range(n)]
    frames[0].save(
        OUT, save_all=True, append_images=frames[1:],
        duration=90, loop=0, optimize=True, disposal=2,
    )
    print(f"Ecrit {OUT} ({OUT.stat().st_size // 1024} Ko, {n} images)")


if __name__ == "__main__":
    main()
