"""Tests du réglage runtime du moteur de voix (bascule « en un clic », persisté)."""
import fournisseurs as F
import reglages


def test_aucun_choix_par_defaut(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    assert reglages.moteur_choisi() is None


def test_definir_et_relire(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    assert reglages.definir_moteur("kokoro") == "kokoro"
    assert reglages.moteur_choisi() == "kokoro"


def test_effacer_choix(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    reglages.definir_moteur("openai")
    assert reglages.definir_moteur("auto") is None       # « auto » = retour au défaut
    assert reglages.moteur_choisi() is None


def test_lecture_robuste_si_fichier_corrompu(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    (tmp_path / "moteur.json").write_text("pas du json", encoding="utf-8")
    assert reglages.moteur_choisi() is None              # repli honnête, pas d'exception


def test_choix_passe_en_tete_de_lordre(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    reglages.definir_moteur("openai")                    # connu du registre
    assert F.ordre()[0] == "openai"                      # bascule immédiate, sans redémarrage
    # Le souverain reste présent comme repli, juste plus en tête.
    assert "piper" in F.ordre()


def test_choix_inconnu_ignore(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    reglages.definir_moteur("inexistant")
    assert F.ordre()[0] == "piper"                       # moteur inconnu → ignoré, défaut tenu


# ── Deux rôles : conversation (rapide) vs lecture (belle) ─────────────────────

def test_roles_independants(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    reglages.definir_moteur("piper", "conversation")
    reglages.definir_moteur("kokoro", "lecture")
    assert reglages.moteur_choisi() == "piper"           # les deux rôles coexistent
    assert reglages.moteur_lecture() == "kokoro"


def test_effacer_un_role_garde_lautre(monkeypatch, tmp_path):
    monkeypatch.setenv("VOIX_DIR", str(tmp_path))
    reglages.definir_moteur("piper", "conversation")
    reglages.definir_moteur("kokoro", "lecture")
    reglages.definir_moteur("auto", "lecture")           # efface la lecture
    assert reglages.moteur_lecture() is None
    assert reglages.moteur_choisi() == "piper"           # la conversation reste


def test_seuil_lecture_defaut_et_env(monkeypatch):
    monkeypatch.delenv("VOIX_SEUIL_LECTURE", raising=False)
    assert reglages.seuil_lecture() == 280
    monkeypatch.setenv("VOIX_SEUIL_LECTURE", "120")
    assert reglages.seuil_lecture() == 120
    monkeypatch.setenv("VOIX_SEUIL_LECTURE", "n-importe-quoi")
    assert reglages.seuil_lecture() == 280               # valeur invalide → défaut honnête
