# Standard vocal IVR + répondeur générique — design

Fondation commune pour tous les usages téléphoniques envisagés à terme (rendez-vous,
agent d'écoute réunions, support produit, journal vocal, rappel prospect, assistant
collaborateurs, autre) — construite en partant du pont SIP↔LiveKit déjà prouvé
techniquement en S197 (`docs/superpowers/plans/2026-07-25-s197-pont-telephonie-sip-oria.md`).

## But

Un numéro (test LAN pour l'instant, vrai numéro OVH = décision séparée non prise) répond
avec un menu vocal à 7 options. Aujourd'hui, **toutes** les options tombent sur un
répondeur générique : message d'accueil, enregistrement, transcription automatique,
notification Telegram. Chaque usage réel viendra ensuite se brancher sur ce squelette
sans le reconstruire.

## Contexte technique constaté (S197)

- `sip-stack/roomkit-visio/` (Kamailio + rtpengine + `livekit-sip:local`, vendoré et
  buildé) est déjà en place et prouvé : un appel SIP entre dans une room LiveKit avec
  audio bidirectionnel réel, à condition qu'un participant publie de l'audio dans la
  room (`pkg/sip/room.go:340-356` — `livekit-sip` ne décroche/200 OK qu'après avoir
  lui-même souscrit à une piste audio d'un autre participant).
- Le LiveKit+redis utilisés pour le test S197 sont **jetables** (clés de test en dur
  dans `compose.override.yml`) — ce chantier les remplace par une paire **permanente**,
  toujours découplée d'`oria-stack/` (aucun besoin : ce cas d'usage n'a rien à voir avec
  la visio familiale d'Oria).
- `briques/transcription` (port 5980) a déjà `transcription_fichier` (diarisation,
  résumé, points d'action) — rien à construire côté transcription, juste l'appeler.
- `briques/voix` (port 5985) a déjà la synthèse TTS souveraine (Piper) — utilisée pour
  le message de menu et l'accueil du répondeur.
- `briques/connexion` (port 5870) expose déjà `POST /envoyer`
  (`{reseau: "telegram", id_externe, texte}`, capacité `envoyer_message`,
  `briques/connexion/manifest.json:42`) — mécanisme de notification réutilisé tel quel,
  rien à construire côté Telegram non plus.
- Dernier port de brique attribué : 6180 (`briques/transferts`, S196) → **6190** pour la
  nouvelle brique de ce chantier.

## Architecture

```
Softphone/téléphone
   │ SIP (5060/udp)
   ▼
Kamailio (network_mode: host) ── whitelist LAN, dispatcher
   │
   ▼
rtpengine (network_mode: host) ── relais RTP
   │
   ▼
livekit-sip:local ── traduit SIP↔LiveKit, publie une piste MICROPHONE
   │
   ▼
LiveKit server dédié (permanent, PAS Oria) + redis dédié
   │
   ▼
briques/standard-telephonique (NOUVEAU, port 6190)
   worker livekit-agents (Python) qui auto-rejoint chaque room d'appel
   │
   ├─→ briques/voix (5985)          — TTS menu + accueil répondeur
   ├─→ briques/transcription (5980) — transcrire l'enregistrement
   └─→ briques/connexion (5870)     — notifier Telegram
```

## Composants

### 1. `sip-stack/roomkit-visio/` (existant, retouché)

- `compose.override.yml` : le LiveKit+redis passent de « jetables » (clés de test en
  dur) à une paire **permanente** — nouvelles clés générées, service toujours interne
  au compose (pas de dépendance `oria-stack/`), pas de port publié vers Internet.
- Aucune autre modification du stack SIP lui-même (Kamailio/rtpengine/livekit-sip
  restent tels que prouvés en S197).
- Dispatch rule LiveKit : une seule room générique par appel (`tel-<uuid>`), pas de
  dispatch rule différente par option de menu — le menu est géré **dans l'agent**, pas
  dans le routage SIP (plus simple, tout le comportement futur reste en code Python
  plutôt qu'éclaté entre config Kamailio et config LiveKit).

### 2. `briques/standard-telephonique/` (nouvelle brique, port 6190)

- Process worker utilisant le SDK officiel `livekit-agents` (Python) : auto-dispatch
  sur chaque nouvelle room créée par le trunk SIP.
- Séquence par appel :
  1. Rejoint la room (ce qui, en publiant sa propre piste, permet à `livekit-sip` de
     décrocher — comportement déjà observé en S197).
  2. Appelle `briques/voix` pour synthétiser et jouer le menu : *« 1 pour la famille, 2
     rendez-vous, 3 réunion, 4 support produit, 5 journal vocal, 6 rappel prospect, 7
     autre — laissez un message après le bip »*.
  3. Écoute les événements DTMF forwardés par `livekit-sip` (canal déjà utilisé en
     interne par le fork, cf. `pkg/sip/inbound.go` `c.dtmf`) pendant une fenêtre
     d'attente (ex. 8s). Timeout → répète le menu une fois, puis bascule répondeur
     générique par défaut si toujours rien.
  4. Pour **toutes** les options aujourd'hui (aucune branche métier construite) : joue
     un bip, enregistre l'audio entrant jusqu'à raccroché ou touche `#`, avec l'option
     choisie (1-7 ou « aucune ») en métadonnée.
  5. Sauvegarde l'enregistrement (fichier + métadonnées : option, horodatage, durée).
  6. Appelle `briques/transcription` (`transcription_fichier`) sur l'enregistrement.
  7. Appelle `briques/connexion` (`POST /envoyer`, réseau `telegram`) avec le texte
     transcrit + l'option choisie.
- `manifest.json` : capacité de lecture `standard_telephonique_messages_lister`
  (liste des messages reçus : option, date, statut transcription, lien audio) — pas de
  capacité d'action pour cette première version (rien à déclencher depuis l'assistant
  tant qu'aucun usage réel n'est branché).

## Flux de données

```
Appel entrant → room tel-<uuid> → agent rejoint → décroché (200 OK)
   → TTS menu → DTMF (option 1-7 ou timeout)
   → bip + enregistrement → fichier audio + métadonnées
   → transcription (Whisper, briques/transcription)
   → notification Telegram (texte + option, briques/connexion)
```

## Gestion des erreurs

- **Pas de DTMF reçu** : répète le menu une fois, puis répondeur générique par défaut
  (pas d'échec bloquant — un appelant qui ne fait rien laisse quand même un message).
- **Échec de transcription** : notification Telegram envoyée quand même, avec mention
  explicite « transcription indisponible » plutôt qu'un silence — jamais de faux
  contenu (cohérent avec le principe déjà appliqué dans `briques/transcription`
  : repli honnête).
- **Agent qui plante en cours d'appel** : le softphone/téléphone raccroche
  naturellement côté SIP (déjà géré par le stack S197 existant — media timeout,
  CANCEL/BYE) ; rien de nouveau à construire ici.
- **Enregistrement vide** (raccroché immédiat après le bip) : pas de transcription
  déclenchée, pas de notification Telegram — évite le bruit pour des appels vides.

## Test

Même méthode qu'en S197 : softphone LAN (Linphone), appel vers le numéro de test,
essai de plusieurs touches (1 à 7, et aucune touche = timeout), vérification que
chaque cas tombe bien sur le répondeur avec la bonne métadonnée d'option, et que la
notification Telegram arrive avec le texte transcrit.

## Hors périmètre (explicitement)

- Les 7 usages réels eux-mêmes (rendez-vous, écoute réunion + diarisation multi-
  locuteurs, support produit, journal vocal → mémoire, rappel prospect, assistant
  collaborateurs, standard familial) — chacun sera une spec séparée qui vient se
  brancher sur ce squelette (remplacer la branche « répondeur générique » de l'option
  correspondante par la vraie logique).
- Vrai numéro de téléphone (abonnement OVH ou Twilio SIP trunking) et ouverture réseau
  — décision produit/coût séparée, non prise dans ce chantier.
- Branchement sur le LiveKit réel d'Oria — non pertinent pour ce cas d'usage
  (répondeur, pas de visio Oria).
