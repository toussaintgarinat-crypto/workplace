"""Vecteurs de contrôle Code128 / EAN-13.

1) Logique de référence en Python : fige les invariants d'encodage (checksum mod 103,
   chiffre de contrôle mod 10) — une régression algorithmique devient détectable.
2) Validation Node du VRAI static/barcode.js (skip si node absent) : charge le module et
   vérifie qu'il rend un SVG non vide pour un intrant valide et échoue proprement sinon."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
BARCODE_JS = BACKEND / "static" / "barcode.js"


# ── 1. Code128 jeu B (référence Python) ─────────────────────────────────────────
def code128b_valeurs(texte: str) -> list[int]:
    codes = [104]
    codes.extend(ord(ch) - 32 for ch in texte)
    somme = 104 + sum((ord(ch) - 32) * (i + 1) for i, ch in enumerate(texte))
    codes.append(somme % 103)
    codes.append(106)
    return codes


def test_code128_checksum_connu():
    valeurs = code128b_valeurs("CODE128")
    assert valeurs[0] == 104 and valeurs[-1] == 106
    attendu = (104 + sum((ord(ch) - 32) * (i + 1) for i, ch in enumerate("CODE128"))) % 103
    assert valeurs[-2] == attendu


# ── 2. EAN-13 (référence Python) ────────────────────────────────────────────────
def ean13_checksum(d12: str) -> int:
    s = sum((1 if i % 2 == 0 else 3) * int(d12[i]) for i in range(12))
    return (10 - (s % 10)) % 10


def test_ean13_checksum_reference():
    assert ean13_checksum("978020137962") == 4   # 9780201379624
    assert ean13_checksum("400638133393") == 1   # 4006381333931


# ── 3. Validation Node du fichier réellement embarqué ───────────────────────────
def _node_dessine(texte: str, format_: str):
    node = shutil.which("node")
    if not node:
        import pytest
        pytest.skip("node absent")
    script = (
        "global.window = {};"
        f"require({json.dumps(str(BARCODE_JS))});"
        "let svg = { attrs:{}, innerHTML:'', setAttribute(k,v){this.attrs[k]=v;} };"
        f"let ok = window.dessinerCodeBarres(svg, {json.dumps(texte)}, {json.dumps(format_)});"
        "console.log(JSON.stringify({ok, rects:(svg.innerHTML.match(/<rect/g)||[]).length, "
        "viewBox: svg.attrs.viewBox||''}));"
    )
    out = subprocess.run([node, "-e", script], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip())


def test_js_ean13_rend_des_barres():
    r = _node_dessine("4006381333931", "ean13")
    assert r["ok"] is True and r["rects"] > 20 and r["viewBox"]


def test_js_code128_rend_des_barres():
    r = _node_dessine("CARTE123", "code128")
    assert r["ok"] is True and r["rects"] > 5


def test_js_code128_largeur_modules_stop_complet():
    """Code128 « A » = Start B + 1 donnée + checksum + stop = 4×11 + 2 (barre finale du
    stop) = 46 modules. Verrouille le motif de stop complet « 2331112 » (régression :
    un stop tronqué « 233111 » donnerait 44 → symbole inscannable)."""
    r = _node_dessine("A", "code128")
    total = int(r["viewBox"].split(" ")[2])  # "0 0 TOTAL 100", unité=2, marges 20
    assert (total - 20) // 2 == 46


def test_js_ean13_refuse_longueur_invalide():
    r = _node_dessine("12345", "ean13")   # ni 12 ni 13 chiffres
    assert r["ok"] is False
