"""Outils du domaine « transcription » (dispatch, extrait de outils.py — S115).

brique transcription (audio→texte) : état, sources, résumé, archivage.
"""
import json
import catalogue
from outils_communs import _confirmation, _transcription_appel


async def dispatch(nom: str, args: dict, registre, client) -> str | None:
    """Renvoie le résultat (str) si le nom appartient à ce domaine, sinon None."""
    if nom == "transcription_etat":
        return await _transcription_appel(client, registre, "GET", "/sante", timeout=15)

    if nom == "transcription_destinations":
        return await _transcription_appel(client, registre, "GET", "/destinations",
                                          timeout=15)

    if nom == "transcription_depuis_url":
        charge = {"url": args.get("url", ""), "langue": args.get("langue"),
                  "diarisation": bool(args.get("diarisation"))}
        trans = await _transcription_appel(client, registre, "POST", "/transcrire-url",
                                           charge=charge, timeout=300, brut=True)
        if not isinstance(trans, dict) or trans.get("place_holder"):
            return json.dumps({"transcription": trans}, ensure_ascii=False)
        notes = await _transcription_appel(
            client, registre, "POST", "/resumer",
            charge={"texte": trans.get("texte", ""), "langue": args.get("langue")},
            timeout=120, brut=True)
        return json.dumps({"transcription": trans, "notes": notes}, ensure_ascii=False)

    if nom == "transcription_resumer":
        charge = {"texte": args.get("texte", ""), "langue": args.get("langue")}
        return await _transcription_appel(client, registre, "POST", "/resumer",
                                          charge=charge, timeout=120)

    if nom == "transcription_archiver":
        dest = args.get("destination") or "memoire"
        titre = args.get("titre") or "Notes"
        if not args.get("confirme"):
            return _confirmation(f"ranger les notes ({dest})", titre)
        charge = {
            "notes": {"resume": args.get("resume", ""),
                      "points_action": args.get("points_action") or [],
                      "decisions": args.get("decisions") or [],
                      "themes": args.get("themes") or [], "source": "assistant"},
            "titre": args.get("titre"), "langue": args.get("langue"),
            "destination": dest, "dossier": args.get("dossier"),
        }
        return await _transcription_appel(client, registre, "POST", "/archiver",
                                          charge=charge, timeout=45)

    # — CAPACITÉS DYNAMIQUES (S64) : routées par le catalogue des manifests —
    return None
