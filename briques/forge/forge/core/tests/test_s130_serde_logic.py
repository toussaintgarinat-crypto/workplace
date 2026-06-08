"""S130 — sérialiseurs (parité Drizzle), helpers de formatage FR, rapport markdown, parser RSS."""

import datetime
import types

from app import serde
from app.fmt import fr_date, fr_date_long, fr_datetime, fr_number
from app.routers.audit import _build_report_markdown
from app.routers.veille import _parse_rss_items


def _ns(**kw):
    return types.SimpleNamespace(**kw)


# ── Sérialiseurs ───────────────────────────────────────────────────────
def test_venture_keys():
    r = _ns(id="11111111-1111-1111-1111-111111111111", owner_id="u1", org_id=None,
            nom="Acme", description="d", emoji="🚀", couleur="#fff", type="own", statut="actif",
            created_at=datetime.datetime(2026, 1, 1), updated_at=datetime.datetime(2026, 1, 2))
    out = serde.venture(r)
    assert set(out) == {"id", "ownerId", "orgId", "nom", "description", "emoji",
                        "couleur", "type", "statut", "createdAt", "updatedAt"}
    assert out["ownerId"] == "u1" and out["createdAt"].endswith("Z")


def test_pole_venture_id_is_raw_text():
    # poles.venture_id est une colonne TEXT côté Drizzle → sortie brute, pas castée UUID.
    r = _ns(id="aaaaaaaa-0000-0000-0000-000000000001", nom="Dev", description="", emoji="💻",
            couleur="#000", type="dev", owner_id="u1", org_id=None, venture_id="venture-text-id",
            created_at=datetime.datetime(2026, 1, 1))
    out = serde.pole(r)
    assert out["ventureId"] == "venture-text-id"
    assert out["type"] == "dev"


def test_rapport_and_brief_keys():
    rp = _ns(id="1", user_id="u", org_id=None, mission_id=None, titre="T", contenu="C",
             type="weekly", periode="P", created_at=None)
    assert set(serde.rapport(rp)) == {"id", "userId", "orgId", "missionId", "titre",
                                      "contenu", "type", "periode", "createdAt"}
    br = _ns(id="1", user_id="u", org_id=None, titre="T", contenu="C", type="morning",
             lu=False, created_at=None)
    out = serde.brief(br)
    assert out["lu"] is False and out["type"] == "morning"


def test_pole_dev_request_camel_keys():
    r = _ns(id="1", source_pole_id="2", source_pole_name="Finance", source_pole_emoji="📊",
            title="Auto", description="d", frequency="daily", priority="high", status="pending",
            analysis=None, proposed_solution=None, automation_rule_id=None, rejection_reason=None,
            user_id="u", created_at=None, updated_at=None)
    out = serde.pole_dev_request(r)
    assert out["sourcePoleName"] == "Finance" and out["status"] == "pending"
    assert "proposedSolution" in out and "automationRuleId" in out


def test_veille_article_keys():
    r = _ns(id="1", user_id="u", source_id=None, titre="T", url="http://x", resume="",
            lu=False, published_at="2026", created_at=None)
    out = serde.veille_article(r)
    assert out["publishedAt"] == "2026" and out["url"] == "http://x"


# ── Formatage FR ───────────────────────────────────────────────────────
def test_fr_formatters():
    dt = datetime.datetime(2026, 5, 30, 14, 5, 9)  # samedi 30 mai 2026
    assert fr_date(dt) == "30/05/2026"
    assert fr_datetime(dt) == "30/05/2026 14:05:09"
    assert fr_date_long(dt) == "samedi 30 mai 2026"
    assert fr_date_long(dt, with_year=False) == "samedi 30 mai"
    # séparateur de milliers = NARROW NO-BREAK SPACE (U+202F), comme Node/ICU fr-FR
    assert fr_number(1234567) == "1 234 567"
    assert fr_number(-500) == "-500"


# ── Rapport markdown ───────────────────────────────────────────────────
def test_build_report_markdown_groups_and_icons():
    findings = [
        _ns(categorie="Sécurité", severite="critique", description="Faille", source="doc1"),
        _ns(categorie="Sécurité", severite="faible", description="Mineur", source=""),
        _ns(categorie="Finance", severite="moyen", description="Écart", source="doc2"),
    ]
    recos = [_ns(priorite="haute", action="Patcher"), _ns(priorite="faible", action="Documenter")]
    md = _build_report_markdown("Mission X", {"resume_executif": "RE"}, findings, recos)
    assert "# Rapport d'audit — Mission X" in md
    assert "## 🔍 Constats (3)" in md
    assert "### Sécurité" in md and "### Finance" in md
    assert "🔴 **[CRITIQUE]** Faille *(doc1)*" in md
    assert "1. 🔴 **[HAUTE]** Patcher" in md
    assert "RE" in md


def test_build_report_markdown_empty():
    md = _build_report_markdown("Vide", {"resume_executif": ""}, [], [])
    assert "*Aucun constat*" in md and "*Aucune recommandation*" in md


# ── Parser RSS ─────────────────────────────────────────────────────────
def test_parse_rss_items():
    feed = """<?xml version="1.0"?><rss><channel>
      <item><title><![CDATA[Premier article]]></title><link>https://ex.com/1</link>
        <pubDate>Mon, 01 Jan 2026 10:00:00 GMT</pubDate></item>
      <item><title>Sans lien valide</title></item>
      <item><title>Via guid</title><guid>https://ex.com/2</guid></item>
    </channel></rss>"""
    items = _parse_rss_items(feed)
    urls = [i["url"] for i in items]
    assert "https://ex.com/1" in urls
    assert "https://ex.com/2" in urls  # fallback guid quand pas de <link>
    assert len(items) == 2  # l'item sans lien est ignoré
    assert items[0]["titre"] == "Premier article"
    assert items[0]["publishedAt"].startswith("Mon, 01 Jan")
