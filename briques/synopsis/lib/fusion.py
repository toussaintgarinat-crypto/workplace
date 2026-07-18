"""Fusion — chapter/insight extraction from LLM markdown output.

L'extraction est volontairement tolérante : le LLM ne respecte pas toujours
le gabarit du prompt à la lettre (emoji omis, titre de section traduit quand
la langue de sortie n'est pas le français, horodatage en HH:MM:SS pour les
vidéos longues, crochets absents…). Le sommaire ne doit pas disparaître pour
ces variations bénignes.
"""

import re

# MM:SS, H:MM:SS ou HH:MM:SS (les vidéos > 1 h produisent la forme longue).
_TS = r'\d{1,3}:\d{2}(?::\d{2})?'

# Une ligne de tableau dont la 1re cellule commence par un horodatage.
# La cellule peut contenir des crochets et/ou une plage (« 00:12 – 03:45 ») :
# on ne capture que le 1er horodatage, le reste de la cellule est ignoré.
_CHAPTER_ROW = re.compile(
    rf'\|\s*\[?({_TS})\]?[^|]*\|\s*(.+?)\s*\|\s*(.+?)\s*\|')

# Titres de section « points clés » (moments forts / highlights / Höhepunkte…).
# Niveau ##..#### uniquement : le titre H1 « # ANALYSE VIDÉO : … » ne doit
# JAMAIS être pris pour une section — le nom de la vidéo contient parfois un de
# ces mots-clés (« Deep learning chapter 1 »), ce qui empoisonnait la détection.
_INSIGHT_HEADING = re.compile(
    r'^#{2,4}\s.*(moments?\s*forts?|insight|highlight|key\s*moment|'
    r'moment[oi]s?|momente|h[oö]hepunkt|destaque|saliente)',
    re.IGNORECASE | re.MULTILINE)

_INSIGHT_ITEM = re.compile(
    rf'^\s*\d+[.)]\s*\*{{0,2}}(.+?)\*{{0,2}}\s*\[?({_TS})\]?\s*[:\-–]\s*(.+)',
    re.MULTILINE)


def _ts_to_seconds(ts: str) -> int:
    parts = [int(p) for p in ts.split(':')]
    if len(parts) == 3:
        return parts[0] * 3600 + parts[1] * 60 + parts[2]
    return parts[0] * 60 + parts[1]


def _clean(text: str) -> str:
    return text.strip().strip('*').strip()


def _section_after(heading: re.Pattern, analysis: str) -> str | None:
    """Contenu de la section (jusqu'au prochain titre) ou None si absente."""
    m = heading.search(analysis)
    if not m:
        return None
    rest = analysis[m.end():]
    nxt = re.search(r'^#{2,4}\s', rest, re.MULTILINE)
    return rest[:nxt.start()] if nxt else rest


def _extract_chapters(analysis: str) -> list[dict]:
    chapters: list[dict] = []
    if not analysis:
        return chapters
    # Le chapitrage est le SEUL tableau horodaté produit par le pipeline : on le
    # repère par ses lignes (1re cellule = horodatage) sur tout le document, sans
    # dépendre du titre de section — ni de son emoji, ni de sa langue, ni d'une
    # collision avec le titre de la vidéo. C'est le repli le plus sûr.
    for m in _CHAPTER_ROW.finditer(analysis):
        subject = _clean(m.group(2))
        desc = _clean(m.group(3))
        # Ligne de séparation du tableau (| :--- | :--- | :--- |).
        if set(subject) <= {':', '-', ' '} and set(desc) <= {':', '-', ' '}:
            continue
        ts_raw = m.group(1)
        chapters.append({'timestamp': ts_raw, 'ts_seconds': _ts_to_seconds(ts_raw),
                         'subject': subject, 'description': desc})
    return chapters


def _extract_insights(analysis: str) -> list[dict]:
    insights: list[dict] = []
    if not analysis:
        return insights
    scope = _section_after(_INSIGHT_HEADING, analysis)
    if scope is None:
        return insights
    for m in _INSIGHT_ITEM.finditer(scope):
        insights.append({'title': _clean(m.group(1)), 'timestamp': m.group(2),
                         'description': m.group(3).strip()})
    return insights


def merge_chapter_tables(chapters_lists: list[list[dict]]) -> list[dict]:
    all_chapters = []
    for cl in chapters_lists:
        all_chapters.extend(cl)
    all_chapters.sort(key=lambda x: x.get('ts_seconds', 0))
    seen_ts = set()
    unique = []
    for c in all_chapters:
        ts = c.get('ts_seconds', 0)
        if ts not in seen_ts:
            seen_ts.add(ts)
            unique.append(c)
    return unique


def select_top_insights(insights_lists: list[list[dict]], max_insights: int = 3) -> list[dict]:
    all_insights = []
    seen = set()
    for il in insights_lists:
        for ins in il:
            key = ins.get('title', '').lower()
            if key and key not in seen:
                seen.add(key)
                all_insights.append(ins)
    return all_insights[:max_insights]


def _build_chapter_table(chapters: list[dict]) -> str:
    if not chapters:
        return ""
    lines = ["## 📍 Chapitrage Temporel", "| Time | Sujet | Description |", "| :--- | :--- | :--- |"]
    for c in chapters:
        lines.append(f"| {c.get('timestamp', '')} | *{c.get('subject', '')}* | {c.get('description', '')} |")
    return "\n".join(lines)


def _build_insights_list(insights: list[dict]) -> str:
    if not insights:
        return ""
    lines = ["## 💡 Top 3 Moments Forts (Insights)"]
    for i, ins in enumerate(insights, 1):
        lines.append(f"{i}. *{ins.get('title', '')}* [{ins.get('timestamp', '')}] : {ins.get('description', '')}")
    return "\n".join(lines)
