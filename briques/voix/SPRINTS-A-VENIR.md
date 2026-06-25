# Brique voix — sprints à venir (préparés, à lancer plus tard)

Suite directe du travail voix v0.5.0 (lecture vocale propre, Kokoro installé, bascule en un
clic, **voix par usage** conversation/lecture). Numérotation : le dernier sprint du fil
principal est **S105** (synopsis) → ces deux-là sont **S106** puis **S107**.
S107 **dépend** de S106 (le clonage exige le moteur XTTS actif).

> ✅ **S106 LIVRÉ (voix v0.6.0)** — Coqui XTTS activé pour de vrai (`INSTALL_COQUI=1` +
> `VOIX_COQUI=1`), **out of the box** (locuteur intégré par défaut, aucun WAV requis),
> comparateur « voix de lecture » dans la page de réglage (même résumé sur chaque moteur),
> licence CPML dite honnêtement. 74 tests verts. **Reste à prouver LIVE** (rebuild image +
> écoute Coqui vs hébergé). Commit `78a1a0c`.
>
> ✅ **S107 LIVRÉ (voix v0.7.0)** — bibliothèque de **voix clonées** réutilisables : `clones.py`
> (CRUD pur : `VOIX_DIR/voix-clonees/<slug>.wav` + index, validation WAV/durée) ; endpoints
> `GET/POST/DELETE /voix/clones` + `POST /voix/clones/{nom}/tester` ; convention
> `voix:"clone:<nom>"` dans `/synthetiser` → `moteur` **force Coqui** + résout le `speaker_wav` ;
> section « 🎭 Mes voix clonées » dans la tuile Voix (enregistrer/écouter/supprimer) ; capacités
> manifest pour la **réutilisation Studio** (`GET /voix/clones`) ; consentement + licence CPML
> dits dans l'UI. 91 tests verts. **Reste à prouver LIVE** (rebuild + cloner un vrai timbre et
> l'utiliser dans une série du Studio). → **fil voix S106→S107 CODE-COMPLET**.

---

## S106 — Voix de LECTURE au choix (Coqui local **et** hébergé) — ✅ LIVRÉ

**Objectif.** Donner au rôle « lecture » (résumés, longs textes — cf. routage par usage v0.5.0)
un moteur vraiment haut de gamme, AU CHOIX : soit **Coqui XTTS en local** (souverain), soit un
**hébergé** (OpenAI / ElevenLabs). Avec **écoute d'échantillons** pour comparer avant de choisir.

**Pourquoi.** La latence ne gêne pas la lecture → on peut s'offrir une belle voix. Deux familles
ont chacune leur intérêt : Coqui = local/gratuit/clonable mais lourd ; hébergé = superbe et
rapide sans GPU, mais payant et le texte sort de la maison. L'utilisateur veut les DEUX possibles.

**Ce qui existe déjà (à réutiliser).**
- Le rôle « lecture » + le routage par longueur/`usage` (`moteur.py`, `reglages.py`, v0.5.0).
- `Coqui` est **au registre mais inerte** (`fournisseurs.py`, opt-in `VOIX_COQUI`, import paresseux).
- `OpenAI` / `ElevenLabs` déjà supportés (clé `OPENAI_API_KEY` / `ELEVENLABS_API_KEY`).
- `requirements-voix-naturelle.txt` (deps Coqui commentées), Dockerfile `ARG INSTALL_KOKORO`.

**Périmètre.**
1. **Activer Coqui pour de vrai** : Dockerfile `ARG INSTALL_COQUI=0` (sur le modèle de Kokoro) →
   `pip install coqui-tts` + torch CPU-only (espeak-ng déjà présent). Compose : `build.args` +
   `VOIX_COQUI=1`. ⚠ Modèle XTTS ~1,8 Go (téléchargé au 1er appel), CPU lent (OK en lecture),
   **licence non commerciale (CPML)** — à signaler honnêtement dans l'UI/README.
2. **Voix de référence Coqui** : XTTS exige un locuteur. Fournir un `COQUI_SPEAKER_WAV` par défaut
   (échantillon FR neutre fourni dans l'image, ou speaker intégré) pour que ça marche « out of the box ».
3. **Échantillons comparatifs dans l'UI** : panneau « voix de lecture » dans la tuile Voix → un même
   texte type « résumé » synthétisé par chaque moteur disponible (Coqui, OpenAI, ElevenLabs, Kokoro),
   chacun avec un bouton ▶︎. Réutilise `/synthetiser {fournisseur: …}` (déjà possible) — pas de
   nouvel endpoint indispensable.
4. **Clé hébergée** : documenter `OPENAI_API_KEY` / `ELEVENLABS_API_KEY` au `.env` racine (pas dans
   le compose — piège env-shadow). Sélection « lecture » via le `POST /voix/moteur {role:"lecture"}`
   existant.

**Critères de done.**
- Écouter le MÊME texte de résumé en Coqui **et** en hébergé, côte à côte, depuis la tuile Voix.
- Choisir l'un pour le rôle « lecture » en un clic.
- PROUVÉ LIVE : un résumé long part automatiquement dans le moteur de lecture choisi
  (`x-backend` = coqui ou openai/elevenlabs).

**Risques / pièges.** Image lourde (torch + modèle XTTS) ; CPU lent (acceptable lecture) ;
licence CPML de XTTS (perso OK, commercial à vérifier) ; téléchargement du modèle au 1er run
(prévoir un repli honnête « modèle en cours de chargement »).

---

## S107 — Clonage de voix RÉUTILISABLES (bibliothèque de voix) — ✅ LIVRÉ

**Objectif.** Cloner une voix à partir d'un court échantillon (~10-20 s de WAV), l'**enregistrer
sous un nom**, et la **réutiliser dans plusieurs contextes** : l'assistant, la narration de résumés,
et — surtout — les **personnages des séries du Studio** (brique 6060). « Cloner une fois, rappeler
partout ».

**Pourquoi.** L'utilisateur veut une vraie bibliothèque de voix transverse, comme pour ses séries :
une voix clonée doit pouvoir servir au-delà d'un seul usage.

**Dépend de S106** (le clonage repose sur Coqui XTTS, donc XTTS doit être actif).

**Ce qui existe déjà (à réutiliser).**
- Coqui XTTS **sait cloner** via `speaker_wav` (déjà câblé dans `fournisseurs.Coqui`, env
  `COQUI_SPEAKER_WAV`).
- `VOIX_DIR` (volume persistant) sert déjà au choix de moteur → y ranger aussi les voix clonées.
- Le **Studio** (6060) distribue déjà des voix aux personnages de séries → point d'accroche.

**Périmètre.**
1. **Bibliothèque persistée** : `VOIX_DIR/voix-clonees/<nom>.wav` (+ un index `voix-clonees.json` :
   nom, date, durée, notes). Module `clones.py` (CRUD pur, testable).
2. **Endpoints** : `POST /voix/clones` (upload échantillon + nom), `GET /voix/clones` (lister),
   `DELETE /voix/clones/{nom}`, `POST /voix/clones/{nom}/tester` (écouter).
3. **Synthèse avec une voix clonée** : convention `voix: "clone:<nom>"` dans `/synthetiser` →
   `moteur`/`Coqui` résout le `speaker_wav` correspondant. Marche pour les deux rôles
   (conversation/lecture) et l'usage forcé.
4. **UI** (tuile Voix) : section « Mes voix » — enregistrer (uploader un WAV), écouter, supprimer,
   et « utiliser comme voix de conversation / lecture ».
5. **Réutilisation transverse Studio** : exposer la liste des voix clonées à la brique Studio pour
   qu'un personnage de série puisse pointer une voix clonée (capacité au manifest / appel `/voix/clones`).
6. **Consentement** : note honnête dans l'UI — ne cloner que des voix qu'on a le droit d'utiliser.

**Critères de done.**
- Enregistrer une voix clonée nommée, l'écouter.
- L'utiliser pour un résumé (rôle lecture) ET dans une série du Studio.
- PROUVÉ LIVE : `/synthetiser {voix:"clone:<nom>"}` rend de l'audio avec ce timbre.

**Risques / pièges.** Qualité du clone dépend de l'échantillon (durée/propreté) ; XTTS lent en CPU ;
licence CPML ; **éthique** (consentement de la personne clonée) — à rendre explicite, pas optionnel.

---

*Préparés le 2026-06-25. S106 + S107 LIVRÉS le 2026-06-25 (commits `78a1a0c`, `07f315b`).*

> ⚠ **Preuve LIVE de la voix Coqui (S106) / du timbre cloné (S107) — TENTÉE, bloquée par la RAM.**
> 2026-06-25 : image **0.7.0 rebuildée** (Coqui + clones + python-multipart), conteneur recréé
> *healthy*, modèle **XTTS-v2 téléchargé** (1,8 Go, `TTS_HOME=/data/voix/coqui`). Mais l'inférence
> XTTS **fait redémarrer le conteneur** (process tué) : la VM Docker (~7,8 Go) n'a que ~2,4 Go
> libres avec **44 conteneurs** actifs (Keycloak seul = 2,65 Go) et le **swap saturé**. Ce n'est
> PAS un bug du code (91 tests verts ; CRUD clones, endpoints, routage `clone:<nom>`→Coqui OK) —
> c'est le **risque HW documenté** (XTTS lourd en CPU/RAM). Pour prouver à l'oreille plus tard :
> libérer ~2 Go (arrêter Keycloak/Oria le temps du test) **ou** attendre la machine dédiée
> (Proxmox). La voix de lecture **hébergée** (OpenAI/ElevenLabs) marcherait sans cette charge.
