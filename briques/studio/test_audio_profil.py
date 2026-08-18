"""Tests — POST /series/{id}/audio avec `profil_id` (S231 P5).

Toute la chaîne réseau (Gateway pour la découpe en répliques, service voix pour le rendu)
est mockée — motif `test_images.py`/`test_langue.py`. On vérifie que `profil_id`, quand
fourni, adapte le script AVANT la découpe en répliques, et que son absence ne régresse pas
le chemin existant."""
import main
import studio as S


class _FauxClientVoix:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, *a, **k):
        class _Rep:
            def raise_for_status(self):
                pass

            def json(self):
                return {"url": "/fichiers/audio.mp3", "duree": 42}
        return _Rep()


def _mocker_chaine_production(monkeypatch, capture_adapter=None):
    """Mocke : découpe en répliques (Gateway), pool de voix, casting, rendu voix."""
    async def fake_repliques(*a, **k):
        return '[{"perso":"NARRATEUR","texte":"Il était une fois."}]'
    monkeypatch.setattr(main.agents, "_gateway_answer", fake_repliques)

    async def fake_pool(langue="fr"):
        return ["Thomas"]
    monkeypatch.setattr(S, "_voix_pool", fake_pool)

    import composition
    async def fake_caster(*a, **k):
        return None  # force le repli interne S._caster (aucun réseau)
    monkeypatch.setattr(composition, "caster", fake_caster)

    monkeypatch.setattr(S, "httpx", type("H", (), {"AsyncClient": _FauxClientVoix}))

    if capture_adapter is not None:
        async def fake_adapter(texte, cible, langue="fr"):
            capture_adapter.append((texte, cible))
            return "Script adapté.", True
        monkeypatch.setattr(S, "_adapter_cible", fake_adapter)


def _serie_avec_episode():
    client = main.app
    from fastapi.testclient import TestClient
    c = TestClient(client)
    sid = c.post("/series", json={"titre": "Sonorisable"}).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Il était une fois.",
                          "script_brut": "Il était une fois."}]
    S._save(serie)
    return c, sid


def test_audio_avec_profil_id_adapte_le_script_avant_les_repliques(monkeypatch):
    appels = []
    _mocker_chaine_production(monkeypatch, capture_adapter=appels)
    c, sid = _serie_avec_episode()
    pid = c.post("/profils", json={"nom": "Fille", "cible": "0-3"}).json()["id"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid})
    assert r.status_code == 200
    assert r.json()["profil_id"] == pid
    assert appels == [("Il était une fois.", "0-3")]


def test_audio_sans_profil_id_non_regression(monkeypatch):
    appels = []
    _mocker_chaine_production(monkeypatch, capture_adapter=appels)
    c, sid = _serie_avec_episode()

    r = c.post(f"/series/{sid}/audio", json={"n": 1})
    assert r.status_code == 200
    assert r.json()["profil_id"] is None
    assert appels == []  # _adapter_cible jamais appelé sans profil_id


class _FauxClientVoixDistinct:
    """Comme `_FauxClientVoix`, mais renvoie une URL DIFFÉRENTE par `episode_id` — pour
    distinguer, côté test, le rendu du profil A de celui du profil B."""
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, **k):
        eid = (json or {}).get("episode_id", "?")

        class _Rep:
            def raise_for_status(self):
                pass

            def json(self):
                return {"url": f"/fichiers/{eid}.mp3", "duree": 42}
        return _Rep()


def test_audio_deux_profils_meme_chapitre_conserve_les_deux_rendus(monkeypatch):
    """S231 revue finale C1 : produire l'audio du profil A PUIS du profil B sur le MÊME
    chapitre ne doit plus écraser le premier rendu — les deux doivent rester récupérables."""
    _mocker_chaine_production(monkeypatch)
    monkeypatch.setattr(S, "httpx", type("H", (), {"AsyncClient": _FauxClientVoixDistinct}))

    async def fake_adapter(texte, cible, langue="fr"):
        return f"Script pour {cible}.", True
    monkeypatch.setattr(S, "_adapter_cible", fake_adapter)

    c, sid = _serie_avec_episode()
    pid_a = c.post("/profils", json={"nom": "Fils", "cible": "7-9"}).json()["id"]
    pid_b = c.post("/profils", json={"nom": "Fille", "cible": "0-3"}).json()["id"]

    r_a = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid_a})
    r_b = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid_b})
    assert r_a.status_code == 200 and r_b.status_code == 200

    serie = S._load(sid)
    audios = serie["episodes"][0]["audios"]
    assert set(audios.keys()) == {pid_a, pid_b}
    assert audios[pid_a]["url"] != audios[pid_b]["url"]
    assert audios[pid_a]["profil_id"] == pid_a
    assert audios[pid_b]["profil_id"] == pid_b


def test_audio_reference_seule_peuple_toujours_les_champs_plats(monkeypatch):
    """Rétrocompat : un rendu SANS profil (référence) doit continuer à peupler les champs
    plats historiques `audio_url`/`duree`/`casting`/... — pour ne pas casser le front
    existant ou une intégration externe qui les lit directement."""
    _mocker_chaine_production(monkeypatch)
    c, sid = _serie_avec_episode()

    r = c.post(f"/series/{sid}/audio", json={"n": 1})
    assert r.status_code == 200

    serie = S._load(sid)
    ep = serie["episodes"][0]
    assert ep["audio_url"] == "/fichiers/audio.mp3"
    assert ep["duree"] == 42
    assert ep["audios"]["reference"]["url"] == "/fichiers/audio.mp3"
    assert ep["audios"]["reference"]["profil_id"] is None


def test_audio_avec_profil_ne_reecrit_jamais_le_script_stocke(monkeypatch):
    """S231 revue finale I2 : l'adaptation cible est utilisée UNIQUEMENT pour construire
    l'audio — le script de référence stocké dans la série ne doit jamais être modifié."""
    _mocker_chaine_production(monkeypatch)

    async def fake_adapter(texte, cible, langue="fr"):
        return "TEXTE COMPLÈTEMENT DIFFÉRENT.", True
    monkeypatch.setattr(S, "_adapter_cible", fake_adapter)

    c, sid = _serie_avec_episode()
    pid = c.post("/profils", json={"nom": "Fils", "cible": "0-3"}).json()["id"]
    avant = S._load(sid)["episodes"][0]
    script_balise_avant = avant["script_balise"]
    script_brut_avant = avant["script_brut"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid})
    assert r.status_code == 200

    apres = S._load(sid)["episodes"][0]
    assert apres["script_balise"] == script_balise_avant
    assert apres["script_brut"] == script_brut_avant


def test_audio_profil_id_dautrui_404(monkeypatch):
    _mocker_chaine_production(monkeypatch)
    monkeypatch.setenv("STUDIO_KEY", "cle-coeur")
    from fastapi.testclient import TestClient
    c = TestClient(main.app)
    entetes_claire = {"X-API-Key": "cle-coeur", "X-User-Id": "claire"}
    entetes_marina = {"X-API-Key": "cle-coeur", "X-User-Id": "marina"}
    sid = c.post("/series", json={"titre": "SérieMarina"}, headers=entetes_marina).json()["id"]
    serie = S._load(sid)
    serie["episodes"] = [{"n": 1, "script_balise": "Texte.", "script_brut": "Texte."}]
    S._save(serie)
    pid = c.post("/profils", json={"nom": "DeClaire", "cible": "7-9"},
                 headers=entetes_claire).json()["id"]

    r = c.post(f"/series/{sid}/audio", json={"n": 1, "profil_id": pid}, headers=entetes_marina)
    assert r.status_code == 404
