# Décision — `app-builder` sort du monorepo : ce n'était pas une brique

- **Date** : 2026-07-28
- **Statut** : ✅ Adopté (S213)
- **Portée** : `briques/app-builder/` (supprimée), le registre du Cœur
  (`core/conscience.py`, `core/catalogue.py`), le bundle du Générateur
  (`briques/generateur/bundle.py`), les filets `tests/test_briques_smoke.py` et
  `core/test_catalogue.py`
- **Dépôt d'accueil** : `~/Desktop/strategic-app-builder` (dépôt Git séparé, commit initial
  `2638c9f`)

> **But de ce document** : consigner *pourquoi* un outil qui marche a été retiré du dépôt,
> *ce qu'on renonce* à faire de lui, et *à quelle condition* on reviendrait sur ce choix.

---

## En bref (l'état retenu)

- `app-builder` était déclarée comme brique depuis S15b mais **ne l'a jamais été à
  l'exécution** : aucun port, aucun service dans les `docker-compose*.yml`, aucune route
  Caddy, aucun lien depuis le dashboard, aucun test — et **aucune brique ne déclarait ses
  offres en `besoin`**.
- Elle est sortie vers son propre dépôt, comme le Calendrier Familial. Elle n'est **plus**
  dans `briques/`, et les six références du monorepo ont été retirées.
- Les clés d'API en `localStorage` sont **assumées** comme le régime normal d'un outil
  mono-poste, et écrites comme telles dans son README.

## Le vrai sujet n'était pas l'hébergement

Servir un fichier HTML statique est trivial : un conteneur nginx, une route, une entrée au
dashboard, une demi-journée. Ce n'est pas ce qui coûtait.

L'outil appelle **seize fournisseurs d'IA directement depuis le navigateur** — Anthropic,
OpenAI, Mistral, Cohere, Perplexity, OpenRouter, DeepSeek, Groq, Together, xAI, Jina, Voyage,
Ollama et LM Studio compris — avec des clés saisies par l'utilisateur et rangées en
`localStorage`. Vérifié : **aucune référence à la Gateway `:5100`** (les cinq occurrences de
`5100` dans le fichier sont la couleur CSS `#e65100`).

Donc, tant qu'il reste ainsi : pas de budget LLM, pas de cache sémantique, pas de journal des
coûts, et des clés en clair dans un navigateur. **Le servir sur le mesh transformait ce défaut
personnel en exposition réelle** ; le corriger imposait de réécrire toute sa couche LLM pour
la faire passer par la Gateway — l'essentiel des ~2 jours de l'option « la servir », et un
couplage définitif au stack.

## Pourquoi sortir plutôt que servir

1. **Rien ne s'appuie dessus.** Ses offres déclarées (`generation_app`, `audit_entreprise`,
   `dashboard`) ne figurent dans le `besoin` d'aucune brique. La retirer ne casse rien —
   vérifié, pas supposé.
2. **Le `generateur` (5400) couvre déjà la fabrication d'apps *dans* le stack**, branchée sur
   la Gateway et le reste. Deux « mains (fabrication d'applications) » dans
   `core/conscience.py` était d'ailleurs le symptôme : la table d'organes en déclarait deux,
   à l'identique.
3. **L'outil n'a besoin de rien.** Un fichier HTML, un navigateur. Le mettre en conteneur pour
   le servir ajoute de l'exploitation sans ajouter de capacité.
4. **« Brique » doit continuer à vouloir dire quelque chose.** Une entrée du registre qui
   n'existe pas à l'exécution use la notion pour toutes les autres.

## Ce qu'on a corrigé au passage

Trois défauts constatés à l'ouverture, indépendants du choix, corrigés dans le dépôt d'accueil :

| Défaut | Effet | Correction |
|---|---|---|
| `<link rel="manifest" href="manifest.json">` pointait sur le manifeste de **brique Workplace** | installation PWA impossible | vrai `manifest.webmanifest` + icône SVG |
| Version incohérente sur trois supports : titre `V3.0`, manifeste `2.8.0`, fichier `v2` | on ne savait pas quelle version tournait | une seule référence, `3.0.0` ; fichier renommé `index.html` |
| `favicon.ico` absent | 404 à chaque chargement | `<link rel="icon">` sur l'icône SVG |

Vérifié au navigateur après extraction : la page démarre, le projet de démo se charge, plus
aucune erreur console hormis l'avertissement Babel ci-dessous.

## Ce qu'on assume et ne corrige pas

- **Les clés d'API restent en `localStorage`.** C'est le régime d'un outil mono-poste, désormais
  écrit noir sur blanc dans son README avec la consigne de ne pas le servir sur un réseau
  partagé. Hors du stack, ce n'est plus une exposition de Workplace.
- **React, Babel, `tesseract.js` et `pdf.js` restent tirés d'unpkg.com**, et Babel transpile
  677 Ko de JSX **dans le navigateur** à chaque ouverture — il émet lui-même
  `code generator deoptimised, exceeds max of 500KB`. Vendorer et précompiler est la suite
  logique, mais c'est le travail du dépôt d'accueil, pas de cette sortie.

## Ce qu'on ne fait pas

- **Pas de conteneur statique, pas de route mesh, pas d'entrée dashboard.** C'était l'option
  (a) ; elle n'est retenue ni en entier, ni en version « locale seulement » — cette dernière
  aurait gardé les clés dans le stack et laissé « brique » vouloir dire deux choses, soit
  exactement l'ambiguïté que ce sprint devait supprimer.
- **Pas de reprise d'historique Git.** Le fichier avait été copié tel quel depuis
  `~/Desktop/application de création d'application/` en S15b : il n'y a pas d'histoire à
  préserver. Le dépôt d'accueil part d'un commit initial.
- **Pas de synchronisation Workplace → standalone**, contrairement au Calendrier Familial. Là,
  la brique `agenda` **restait** dans Workplace comme source de vérité, d'où
  `scripts/export-standalone.sh`. Ici c'est une sortie sèche : le dépôt d'accueil devient la
  seule source.

## À quelle condition on revient là-dessus

Si l'outil devait redevenir une brique, la condition est claire et unique : **qu'il passe par
la Gateway `:5100`** au lieu d'appeler seize fournisseurs en direct. Le jour où c'est fait, le
servir redevient une demi-journée de travail sans dette — et l'ADR sera à réviser.

## Références

- Sprint : `docs/sprints/S210-S215-etl-connecteurs-app-builder.md` (S213)
- Précédent d'extraction : Calendrier Familial (motif différent — duplication, pas sortie)
- Registre d'organes : `core/conscience.py`
