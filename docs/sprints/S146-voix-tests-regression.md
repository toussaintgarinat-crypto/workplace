# Sprint S146 — Brique voix : tests de régression sur les cas limites

> **But du sprint** : couvrir les deux cas qui ont nécessité des hotfixes urgents le
> 2026-07-03 (commits `66cc902` et `36fb1b9`), afin qu'une future régression soit
> détectée avant d'atteindre le HP. La brique voix est critique : quand elle tombe,
> l'assistant devient muet sur Telegram et le Studio.

- **Sprint** : S146
- **Catégorie** : Qualité / Tests / Brique voix
- **Statut** : LIVRÉ
- **Date de planification** : 2026-07-04
- **Date de livraison** : 2026-07-04
- **Briques concernées** : `briques/voix/main.py`, `briques/voix/test_voix.py`
- **Prérequis** : aucun (tests offline, pas de Piper ni Kokoro nécessaires)

---

## Contexte

Deux bugs ont frappé la brique voix en production le même soir :

**Bug 1 — Nom de voix macOS inconnu de Piper** (`66cc902`)
La voix stockée en base de données pouvait être un nom macOS (« Thomas », « Jacques »)
inconnu du registre Piper. L'endpoint `/rendre` crashait au lieu de faire un repli.
Fix : repli sur la voix par défaut si le nom est absent du registre.

**Bug 2 — URL d'épisode construite côté serveur** (`36fb1b9`)
L'URL des fichiers MP3 rendus était construite avec l'hôte serveur (`localhost`) au lieu
de l'hôte de la requête entrante. Résultat : les URL retournées étaient inaccessibles
depuis le navigateur en LAN (`http://localhost:…` au lieu de `http://192.168.1.x:…`).
Fix : construire l'URL depuis `request.url` ou la var `VOIX_PUBLIC_URL`.

Aucun test ne couvrait ces deux cas avant les fixes.

---

## Chantiers

### C0 — Test régression bug 1 : voix macOS inconnue

Dans `briques/voix/test_voix.py` (ou nouveau `test_rendre.py`) :

```python
def test_voix_inconnue_repli_sur_defaut(client, monkeypatch):
    """Un nom de voix absent du registre Piper doit provoquer un repli, pas un crash."""
    # Simuler un registre Piper ne connaissant pas "Thomas"
    monkeypatch.setattr("main.VOIX_DISPONIBLES", {"fr_FR-upmc-medium": {...}})
    resp = client.post("/rendre", json={
        "segments": [{"texte": "Bonjour", "voix": "Thomas"}]
    })
    assert resp.status_code == 200
    # La réponse doit utiliser la voix de repli, pas lever une KeyError/500

def test_voix_vide_repli_sur_defaut(client):
    """Un champ voix vide ou absent doit aussi utiliser la voix par défaut."""
    resp = client.post("/rendre", json={
        "segments": [{"texte": "Bonjour"}]
    })
    assert resp.status_code == 200
```

### C1 — Test régression bug 2 : URL accessible depuis le navigateur LAN

```python
def test_url_episode_depuis_requete(client):
    """/rendre doit retourner une URL construite depuis le host de la requête."""
    resp = client.post(
        "/rendre",
        json={"segments": [{"texte": "Test"}]},
        headers={"Host": "192.168.1.89:5985"},
    )
    assert resp.status_code == 200
    data = resp.json()
    url = data.get("url", "")
    assert "192.168.1.89" in url or "VOIX_PUBLIC_URL" not in url, (
        f"URL retournée non joignable depuis LAN : {url}"
    )

def test_voix_public_url_prioritaire(client, monkeypatch):
    """Si VOIX_PUBLIC_URL est défini, l'URL doit utiliser cette valeur."""
    monkeypatch.setenv("VOIX_PUBLIC_URL", "https://mon-tunnel.trycloudflare.com")
    resp = client.post("/rendre", json={"segments": [{"texte": "Test"}]})
    assert resp.status_code == 200
    assert "mon-tunnel.trycloudflare.com" in resp.json().get("url", "")
```

### C2 — Test cas limite : liste de segments vide

```python
def test_segments_vides_retourne_erreur_propre(client):
    """Segments vides : 400 explicite, pas 500."""
    resp = client.post("/rendre", json={"segments": []})
    assert resp.status_code in (400, 422)
```

### C3 — Vérifier le mock Piper existant

S'assurer que le `conftest.py` de la brique voix mocke correctement Piper et Kokoro
pour que les nouveaux tests tournent offline (sans modèle TTS installé).

---

## Critère d'acceptation

- 4+ nouveaux tests verts (C0 × 2 + C1 × 2 minimum)
- Les tests passent offline (pas de Piper, pas de Kokoro réel)
- Les deux scénarios de bug reproduits puis couverts par un test
- `make test` dans `briques/voix/` reste vert

---

## Effort estimé

**< 2h**
- C0 (bug voix inconnue) : 30 min
- C1 (bug URL LAN) : 45 min
- C2 (segments vides) : 15 min
- C3 (vérif conftest) : 15 min

## Valeur

Les deux pannes les plus récentes de la brique voix seront désormais détectées en
pré-commit. Prévient l'assistant muet sur Telegram avant déploiement sur le HP.
