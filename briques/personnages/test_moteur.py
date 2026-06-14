"""Tests du moteur de distribution & casting (fonctions pures, TTS-agnostique).

Les « voix » sont des identifiants opaques (ex. v_alice) — ce que passerait un client
ElevenLabs/Azure/OpenAI. On vérifie surtout la STABILITÉ du casting (le différenciateur)
et la non-mutation des entrées."""
import moteur as M


POOL = ["v_alice", "v_bob", "v_cara"]


def _persos():
    return [{"id": "p1", "nom": "Aria"}, {"id": "p2", "nom": "Vorn"}]


# ── Clé / texte de distribution ──────────────────────────────────
def test_cle_perso_normalise():
    assert M.cle_perso("Aria") == "ARIA"
    assert M.cle_perso("  le  GARDIEN ") == "LE GARDIEN"
    assert M.cle_perso(None) == ""


def test_distribution_texte():
    assert M.distribution_texte([]) == ""
    txt = M.distribution_texte([{"nom": "Aria", "role": "héroïne", "description": "brave"}])
    assert "Aria — héroïne : brave" in txt and "EXACTEMENT" in txt


# ── Affectation de voix ──────────────────────────────────────────
def test_assigner_voix_distinctes_et_deterministe():
    persos, modifie = M.assigner_voix(_persos(), "fr", POOL)
    assert modifie is True
    assert [p["voix"]["fr"] for p in persos] == ["v_alice", "v_bob"]


def test_assigner_voix_idempotent_et_non_mutant():
    src = _persos()
    persos, _ = M.assigner_voix(src, "fr", POOL)
    persos2, modifie = M.assigner_voix(persos, "fr", POOL)
    assert modifie is False
    assert src[0].get("voix", {}) == {}          # l'entrée d'origine n'a pas bougé


def test_assigner_voix_respecte_choix_manuel():
    persos = [{"id": "p1", "nom": "A", "voix": {"fr": "v_bob"}}, {"id": "p2", "nom": "B"}]
    out, _ = M.assigner_voix(persos, "fr", POOL)
    assert out[0]["voix"]["fr"] == "v_bob"        # non écrasé
    assert out[1]["voix"]["fr"] == "v_alice"      # évite v_bob déjà pris


def test_assigner_voix_round_robin_si_pool_petit():
    persos = [{"nom": "A"}, {"nom": "B"}, {"nom": "C"}]
    out, _ = M.assigner_voix(persos, "fr", ["v_alice", "v_bob"])
    assert [p["voix"]["fr"] for p in out] == ["v_alice", "v_bob", "v_alice"]


def test_assigner_voix_par_langue_independante():
    persos = [{"nom": "A", "voix": {"fr": "v_alice"}}]
    out, _ = M.assigner_voix(persos, "en", ["v_en1", "v_en2"])
    assert out[0]["voix"] == {"fr": "v_alice", "en": "v_en1"}


# ── Casting d'un script ──────────────────────────────────────────
def test_caster_voix_figee_pour_les_connus():
    r = M.caster(_persos(), "fr", ["ARIA", "VORN", "ARIA"], POOL)
    assert r["casting"]["ARIA"] == "v_alice"
    assert r["casting"]["VORN"] == "v_bob"


def test_caster_stable_entre_deux_scripts():
    """Le cœur du produit : un perso garde SA voix d'un script à l'autre."""
    persos = _persos()
    r1 = M.caster(persos, "fr", ["VORN"], POOL)
    # on re-persiste l'état enrichi, comme le ferait l'appelant
    r2 = M.caster(r1["personnages"], "fr", ["ARIA", "VORN"], POOL)
    assert r2["casting"]["VORN"] == "v_bob"       # inchangé
    assert r2["casting"]["ARIA"] == "v_alice"


def test_caster_inconnu_recoit_voix_libre():
    r = M.caster([{"nom": "Aria"}], "fr", ["ARIA", "NARRATEUR"], POOL)
    assert r["casting"]["ARIA"] == "v_alice"
    assert r["casting"]["NARRATEUR"] != "v_alice"
    assert r["casting"]["NARRATEUR"] in POOL


def test_caster_sans_distribution_pur_round_robin():
    r = M.caster([], "fr", ["A", "B", "C"], ["v_alice", "v_bob"])
    assert r["casting"] == {"A": "v_alice", "B": "v_bob", "C": "v_alice"}


def test_caster_match_insensible_casse():
    r = M.caster([{"nom": "Le Gardien"}], "fr", ["LE GARDIEN"], POOL)
    assert r["casting"]["LE GARDIEN"] == "v_alice"


def test_caster_accepte_repliques_objets():
    reps = [{"perso": "ARIA", "texte": "salut"}, {"perso": "VORN", "texte": "grr"}]
    inter = M.intervenants_depuis_repliques(reps)
    r = M.caster(_persos(), "fr", inter, POOL)
    assert set(r["casting"]) == {"ARIA", "VORN"}


def test_intervenants_depuis_repliques_tolerant():
    assert M.intervenants_depuis_repliques(["A", {"perso": "B"}, {"x": 1}]) == ["A", "B"]
