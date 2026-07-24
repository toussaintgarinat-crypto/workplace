"""Historique des images RÉELLEMENT produites par cette brique.

Avant ce module, l'assistant n'avait aucun moyen de retrouver une image déjà générée :
`/generer`/`/portrait`/`/couverture` renvoient l'image au moment de l'appel, sans trace
consultable après coup (contrairement à la galerie humaine de `atelier-images-video`, que
l'assistant n'appelle jamais — cf. son manifest `capacites: []`). `/historique` comble ce
trou côté outils : le pont même produit/consulte, sans dépendre d'une autre brique.

Journal JSONL borné, best-effort (ne doit jamais faire échouer une génération). On n'y
consigne QUE les images RÉELLES (`place_holder=False`) : un placeholder n'est pas une image
à retrouver plus tard, ce serait relayer une fausse image (contraire au repli honnête).
"""
import json
import os
import time
from pathlib import Path


def _chemin() -> Path:
    defaut = str(Path(os.getenv("IMAGES_DIR", "/tmp/images_brique")) / "historique.jsonl")
    return Path(os.getenv("IMAGES_HISTORIQUE_PATH", defaut))


def _max() -> int:
    try:
        return max(10, int(os.getenv("IMAGES_HISTORIQUE_MAX", "500")))
    except ValueError:
        return 500


def consigner(*, type_: str, prompt: str, url: str | None, backend: str | None) -> None:
    """Ajoute une entrée (image RÉELLE uniquement — appelant filtre `place_holder`)."""
    if not url:
        return
    ligne = {"ts": time.time(), "type": type_, "prompt": prompt or "", "url": url,
             "backend": backend}
    chemin = _chemin()
    try:
        chemin.parent.mkdir(parents=True, exist_ok=True)
        with chemin.open("a", encoding="utf-8") as f:
            f.write(json.dumps(ligne, ensure_ascii=False) + "\n")
        _borner()
    except Exception:  # noqa: BLE001 — l'historique ne doit jamais casser une génération
        pass


def _lignes() -> list[dict]:
    chemin = _chemin()
    if not chemin.exists():
        return []
    out = []
    try:
        for l in chemin.read_text(encoding="utf-8").splitlines():
            l = l.strip()
            if not l:
                continue
            try:
                out.append(json.loads(l))
            except json.JSONDecodeError:
                continue
    except Exception:  # noqa: BLE001
        return []
    return out


def _borner() -> None:
    mx = _max()
    lignes = _lignes()
    if len(lignes) <= int(mx * 1.2):
        return
    try:
        _chemin().write_text(
            "\n".join(json.dumps(x, ensure_ascii=False) for x in lignes[-mx:]) + "\n",
            encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def chercher(q: str | None = None, limite: int = 5) -> list[dict]:
    """Les dernières images produites (plus récente d'abord), filtrées par sous-chaîne
    (insensible à la casse) sur le prompt d'origine si `q` est fourni."""
    lignes = list(reversed(_lignes()))
    if q:
        q = q.strip().lower()
        lignes = [l for l in lignes if q in (l.get("prompt") or "").lower()]
    return lignes[:max(1, limite)]
