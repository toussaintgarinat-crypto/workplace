"""Composition du digest (S178) : texte court (push) + HTML riche (email). PUR — reçoit
les events déjà chargés, ne fait pas d'I/O. Gabarit déterministe, aucun LLM."""
from __future__ import annotations

import html as _h


def _heure(iso: str) -> str:
    return iso[11:16] if len(iso) >= 16 else iso


def composer(nom: str, events: list[dict], cadence: str) -> dict:
    quand = "du jour" if cadence == "quotidien" else "de la semaine"
    sujet = f"Ton agenda {quand}"
    if not events:
        texte = f"{sujet} : Rien de prévu. Bonne journée !"
        html = f"<h2>Bonjour {_h.escape(nom)}</h2><p>Rien de prévu {quand}. 🌤️</p>"
        return {"texte": texte, "html": html, "sujet": sujet}

    lignes = [f"• {_heure(e['debut'])} {e['titre']}" for e in events]
    texte = f"{sujet} ({len(events)}) :\n" + "\n".join(lignes)

    items = "".join(
        f"<li><strong>{_h.escape(_heure(e['debut']))}</strong> — {_h.escape(e['titre'])}"
        f" <em style='color:#9a8f80'>({_h.escape(e.get('calendrier',''))})</em></li>"
        for e in events)
    html = (f"<div style='font-family:sans-serif;color:#1A1612'>"
            f"<h2>Bonjour {_h.escape(nom)}</h2>"
            f"<p>Voici ton agenda {quand} — {len(events)} événement(s) :</p>"
            f"<ul>{items}</ul></div>")
    return {"texte": texte, "html": html, "sujet": sujet}
