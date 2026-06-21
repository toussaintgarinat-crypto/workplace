"""S91 — atelier de skills : validation, (dé)composition SKILL.md, personas BMAD, I/O fichier.

Autonome (tmpdir via conftest n'est pas requis ici : on écrit dans un dossier temporaire local).
Prouve que la fabrique de skills façon Claude Code est honnête (refus d'un descripteur invalide
ou d'un doublon) et que le SKILL.md écrit se relit fidèlement (frontmatter + corps + MCP).
"""
import os
import tempfile

import skills_atelier as sk


def _racine():
    return tempfile.mkdtemp(prefix="skills-test-")


def test_valider_refuse_descripteur_bancal():
    assert sk.valider({"name": "", "description": "x"})                      # name vide
    assert sk.valider({"name": "Pas Un Slug", "description": "x"})           # pas un slug
    assert sk.valider({"name": "ok", "description": ""})                     # description vide
    assert sk.valider({"name": "ok", "description": "x", "mcp": "github"})   # mcp pas une liste
    assert sk.valider({"name": "revue-securite", "description": "audit"}) == []  # valide


def test_compose_et_parse_roundtrip():
    meta = {"name": "revue-securite", "description": "Audite un diff.",
            "allowed-tools": ["Read", "Grep"], "mcp": ["github"]}
    texte = sk.composer_skill_md(meta, "# Étapes\n1. Cherche des secrets.")
    relu = sk.parser_skill_md(texte)
    assert relu["name"] == "revue-securite"
    assert relu["description"] == "Audite un diff."
    assert relu["allowed-tools"] == ["Read", "Grep"]
    assert relu["mcp"] == ["github"]
    assert "Cherche des secrets" in relu["corps"]


def test_creer_puis_lire_et_lister():
    racine = _racine()
    meta = {"name": "deployer", "description": "Déploie une brique.", "mcp": ["github"]}
    skill = sk.creer(meta, "1. build\n2. push", racine=racine)
    assert skill["name"] == "deployer" and skill["mcp"] == ["github"]
    assert "build" in skill["corps"]
    # Le fichier existe vraiment, façon Claude Code.
    assert os.path.exists(os.path.join(racine, "deployer", "SKILL.md"))
    descr = sk.lister(racine)
    assert [d["name"] for d in descr] == ["deployer"]
    assert "corps" not in descr[0]                      # niveau-0 : pas de corps (bon marché)


def test_creer_refuse_doublon_et_invalide():
    racine = _racine()
    sk.creer({"name": "x", "description": "d"}, "corps", racine=racine)
    try:
        sk.creer({"name": "x", "description": "d"}, "corps", racine=racine)
        assert False, "doublon non refusé"
    except sk.ErreurSkill as e:
        assert "existe déjà" in str(e)
    try:
        sk.creer({"name": "Bad Name", "description": "d"}, "c", racine=racine)
        assert False, "descripteur invalide non refusé"
    except sk.ErreurSkill as e:
        assert "invalide" in str(e)


def test_supprimer():
    racine = _racine()
    sk.creer({"name": "jetable", "description": "d"}, "c", racine=racine)
    assert sk.supprimer("jetable", racine=racine) is True
    assert sk.lire("jetable", racine=racine) is None
    assert sk.supprimer("jetable", racine=racine) is False   # déjà partie


def test_persona_bmad_fabricable():
    meta, corps = sk.persona_bmad("architect")
    assert meta["name"] == "persona-architect"
    assert "domaine" in (meta["description"] + corps).lower()
    racine = _racine()
    skill = sk.creer(meta, corps, racine=racine)
    assert skill["name"] == "persona-architect"
    # rôle inconnu → erreur honnête
    try:
        sk.persona_bmad("inconnu")
        assert False
    except ValueError as e:
        assert "persona inconnue" in str(e)


if __name__ == "__main__":
    for nom, fn in list(globals().items()):
        if nom.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {nom}")
    print("\n✅ TOUS LES TESTS PASSENT")
