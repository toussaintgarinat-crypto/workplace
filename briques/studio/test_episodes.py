"""Tests — Épisodes d'écoute (~12 min) : découpage des chapitres + cliffhanger de fin.

Fonctions pures de la brique (pas de DB ni de Gateway). Reprises hors Oria (S51)."""
import studio as A


def _serie(durees, **extra):
    """Série minimale : `durees` = liste des durées audio (None = pas sonorisé)."""
    eps = []
    for i, d in enumerate(durees, 1):
        ep = {"n": i}
        if d is not None:
            ep["duree"] = d
        eps.append(ep)
    return {"titre": "T", "episodes": eps, **extra}


# ── Cible (durée d'un épisode) ───────────────────────────────────
def test_cible_defaut_12_min():
    assert A._cible_episode_secondes({}) == 12 * 60


def test_cible_personnalisee():
    assert A._cible_episode_secondes({"cible_episode_secondes": 600}) == 600
    assert A._cible_episode_secondes({"cible_episode_secondes": 0}) == 12 * 60
    assert A._cible_episode_secondes({"cible_episode_secondes": "x"}) == 12 * 60


# ── Durée moyenne d'un chapitre (audio réel uniquement) ──────────
def test_moyenne_aucun_audio_none():
    assert A._duree_moyenne_chapitre(_serie([None, None])) is None
    assert A._duree_moyenne_chapitre({}) is None


def test_moyenne_ignore_les_non_sonorises():
    assert A._duree_moyenne_chapitre(_serie([180, None, 220])) == 200


# ── « 12 min ≈ combien de chapitres ? » ──────────────────────────
def test_chapitres_par_episode_repli_defaut():
    assert A._chapitres_par_episode(_serie([None])) == A.CHAPITRES_PAR_EPISODE_DEFAUT


def test_chapitres_par_episode_depuis_audio_reel():
    assert A._chapitres_par_episode(_serie([180, 180])) == 4
    assert A._chapitres_par_episode(_serie([240, 240])) == 3
    assert A._chapitres_par_episode(_serie([10_000])) == 1


def test_chapitres_par_episode_suit_la_cible():
    s = _serie([120, 120], cible_episode_secondes=600)  # 10 min / 2 min = 5
    assert A._chapitres_par_episode(s) == 5


# ── Quel chapitre clôt un épisode ? ──────────────────────────────
def test_fin_episode_par_defaut_tous_les_4():
    s = _serie([None, None, None])
    assert A._est_fin_episode(s, 3) is False
    assert A._est_fin_episode(s, 4) is True


def test_fin_episode_recompte_apres_un_cliffhanger():
    eps = [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4, "fin_episode": True},
           {"n": 5}, {"n": 6}, {"n": 7}]
    s = {"episodes": eps}
    assert A._est_fin_episode(s, 7) is False
    assert A._est_fin_episode(s, 8) is True


# ── Découpage complet (vue frontend) ─────────────────────────────
def test_decoupage_sans_audio_groupe_par_defaut():
    d = A._decoupage_episodes(_serie([None] * 5))
    assert d["base_estimation"] == "defaut"
    assert d["chapitres_par_episode"] == 4
    assert [e["chapitres"] for e in d["episodes"]] == [[1, 2, 3, 4], [5]]
    assert d["episodes"][0]["tout_sonorise"] is False


def test_decoupage_cumule_la_duree_reelle():
    d = A._decoupage_episodes(_serie([180, 180, 180, 180, 180]))
    assert d["base_estimation"] == "audio_reel"
    assert d["chapitres_par_episode"] == 4
    ep1 = d["episodes"][0]
    assert ep1["chapitres"] == [1, 2, 3, 4]
    assert ep1["duree_reelle"] == 720
    assert ep1["tout_sonorise"] is True


def test_decoupage_ferme_sur_un_cliffhanger_explicite():
    eps = [{"n": 1}, {"n": 2, "fin_episode": True}, {"n": 3}]
    d = A._decoupage_episodes({"episodes": eps})
    assert d["episodes"][0]["chapitres"] == [1, 2]
    assert d["episodes"][0]["fin_explicite"] is True
    assert d["episodes"][1]["chapitres"] == [3]


# ── Cliffhanger injecté dans le prompt du scénariste ─────────────
def test_consigne_cliffhanger_explicite():
    txt = A._consigne_cliffhanger({})
    assert "cliffhanger" in txt.lower()
    assert "12 min" in txt


def test_tache_scenariste_ajoute_le_cliffhanger_si_finale():
    serie = {"titre": "T", "bible": {}, "episodes": []}
    sans = A._tache_scenariste(serie, 1, "ouverture", "", finale=False)
    avec = A._tache_scenariste(serie, 4, "suite", "", finale=True)
    assert "cliffhanger" not in sans.lower()
    assert "cliffhanger" in avec.lower()
