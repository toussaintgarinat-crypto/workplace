# Oria — Cahier des Charges
> Bureau digital spatial et collaboratif
> Version 1.0 — Mars 2026

---

## 1. Vision du produit

**Oria** est un bureau digital personnel et partageable. Chaque utilisateur construit son propre "monde" — un espace composé de bâtiments (maison, site, immeuble) contenant des pièces de texte, de voix et de documents. Ces mondes peuvent être partagés via lien d'invitation, créant ainsi un réseau de bureaux interconnectés.

**Positionnement :** à mi-chemin entre Discord (temps réel), Notion (documents), et Gather.town (spatial). Mais plus simple, plus personnel, plus instinctif.

**Phrase clé :** *"Ton bureau sur internet. Tu choisis qui entre."*

---

## 2. Utilisateurs cibles

| Profil | Usage principal |
|--------|----------------|
| Freelance / indépendant | Espace client partagé, dossiers par projet |
| Petite équipe (2–10 pers.) | Remplacement de Slack + Notion + Meet |
| Créateur de contenu | Espace communauté avec fans proches |
| Étudiant | Groupe de travail avec pièces dédiées |
| Particulier | Espace personnel, cercle d'amis |

---

## 3. Fonctionnalités — État actuel (V1)

### 3.1 Authentification légère
- Connexion par **prénom/pseudo + avatar emoji** (pas de mot de passe)
- Identifiant local persisté en `localStorage`
- Pas de compte email requis pour démarrer

### 3.2 Les Mondes
- Chaque utilisateur peut créer **plusieurs mondes**
- Un monde = un "serveur" personnel (comme Discord) avec nom, emoji, couleur
- Le créateur est automatiquement membre du monde
- Un utilisateur peut rejoindre les mondes d'autres personnes via **lien d'invitation**

### 3.3 Les Bâtiments (3 types)

#### 🏠 Maison
- Espace personnel ou privé
- Pièces par défaut : Salon (mixte), Cuisine (texte), Bureau (vocal)
- Usage : espace personnel, bureau à domicile

#### 🌐 Site
- Vitrine publique ou portfolio
- Pièces par défaut : Accueil (mixte), Blog (texte), Contact (vocal)
- Usage : présence web avec canal de contact en temps réel

#### 🏢 Immeuble
- Structure multi-étages (rez-de-chaussée + étages)
- Pièces par défaut sur 3 étages avec activités différentes
- Usage : agence, entreprise, multi-activités

### 3.4 Les Pièces (3 types)

| Type | Icône | Description |
|------|-------|-------------|
| **Texte** | 💬 | Chat textuel en temps réel (WebSocket) |
| **Vocal** | 🔊 | Appel voix/vidéo (LiveKit WebRTC) |
| **Mixte** | ⚡ | Les deux dans la même pièce, onglets switcher |

### 3.5 Chat temps réel
- Messages texte avec nom + avatar de l'auteur
- Connexion WebSocket maintenue en temps réel
- Historique chargé à l'ouverture de la pièce

### 3.6 Voix & Vidéo
- Intégration **LiveKit** (WebRTC open-source)
- Token JWT généré par le backend pour chaque pièce
- Contrôles micro / caméra / partage d'écran

### 3.7 Présence
- Indication des membres connectés dans un monde
- WebSocket dédié à la présence (join/leave)

---

## 4. Fonctionnalités — À développer (V2)

### 4.1 Système d'invitation
- **Lien d'invitation unique** par monde (ex: `oria.app/invite/abc123`)
- Lien expirant ou permanent (choix du créateur)
- Partage par email ou copier-coller
- QR code généré automatiquement

### 4.2 Gestion des rôles
- **Propriétaire** : droits complets
- **Admin** : gérer membres et bâtiments
- **Membre** : accès aux pièces autorisées
- **Invité** : accès limité (lecture seule ou pièces spécifiques)

### 4.3 Documents & Fichiers
- Upload de fichiers dans une pièce (PDF, images, vidéos)
- Stockage organisé par pièce/bâtiment
- Aperçu intégré sans téléchargement
- Dossiers imbriqués dans une pièce

### 4.4 Navigation spatiale
- Vue "entrée" d'un bâtiment (animation d'entrée style Pokémon)
- Minimap du monde avec position des membres en temps réel
- Transition animée entre les pièces

### 4.5 Notifications
- Badge non-lu sur les pièces avec nouveaux messages
- Notification push (navigateur) pour mentions ou messages directs
- Résumé quotidien par email (optionnel)

### 4.6 Messages privés
- Canal privé entre deux membres d'un même monde
- Accessible depuis la liste des membres

---

## 5. Fonctionnalités — Vision long terme (V3+)

| Fonctionnalité | Description |
|----------------|-------------|
| **Profil public** | Page publique de ton monde, accessible sans invitation |
| **Recherche** | Trouver des mondes publics par thème |
| **Marketplace de templates** | Acheter/vendre des templates de mondes |
| **IA intégrée** | Résumé de réunion, transcription, assistant par pièce |
| **Monétisation** | Accès payant à une pièce ou un bâtiment (ex: cours en ligne) |
| **Mobile** | App iOS/Android native |
| **Domaine custom** | `monagence.oria.app` |
| **Fédération Matrix** | Protocole Matrix sous le capot : mondes hébergeables, fédérés entre serveurs |
| **Chiffrement E2E** | Chiffrement de bout en bout via Olm/Megolm (standard Matrix) |
| **Inbox universelle** | Toutes tes messageries centralisées dans Oria (voir section 5.7) |
| **Marketplace de bridges** | Activer / désactiver des bridges en un clic depuis les paramètres |
| **Self-hosting** | N'importe qui peut héberger son propre serveur Oria interopérable |

### 5.7 Inbox universelle — "Toutes tes messageries dans un seul endroit"

Oria devient le point central de toute ta vie numérique. Via le protocole Matrix et son système de **bridges**, chaque réseau social ou messagerie est accessible directement depuis une pièce Oria.

#### Bridges disponibles (via mautrix / bridges Matrix communautaires)

| Plateforme | Bridge | Statut |
|------------|--------|--------|
| **WhatsApp** | mautrix-whatsapp | ✅ Mature |
| **Instagram** (DMs) | mautrix-instagram | ✅ Mature |
| **Facebook Messenger** | mautrix-facebook | ✅ Mature |
| **Telegram** | mautrix-telegram | ✅ Mature |
| **Signal** | mautrix-signal | ✅ Mature |
| **LinkedIn** (DMs) | beeper-linkedin | 🟡 Beta |
| **Twitter / X** (DMs) | mx-puppet-twitter | 🟡 Beta |
| **iMessage / SMS** | mautrix-imessage | ✅ (macOS/iOS) |
| **Discord** | mautrix-discord | ✅ Mature |
| **Slack** | mautrix-slack | ✅ Mature |
| **Autres** | API Bridge ouverte | 🔜 Marketplace |

#### Fonctionnement

- Chaque bridge connecté génère une **pièce dédiée** dans ton monde Oria (ex: "WhatsApp — Marie", "Instagram — Équipe")
- Tu lis et réponds à tous tes messages **sans quitter Oria**
- Les messages sont **chiffrés E2E** de bout en bout (si la plateforme source le permet)
- Un bridge peut être activé en quelques clics depuis les **paramètres du monde**

#### Marketplace de bridges (V4+)

- Catalogue de bridges officiels et communautaires
- Activation en un clic (sans configuration technique)
- API ouverte pour que des développeurs tiers créent de nouveaux bridges
- Oria devient extensible à tout réseau de communication existant ou futur

> **Vision** : Oria est le seul endroit où tu dois aller pour communiquer — quelle que soit la plateforme de ton interlocuteur.

---

## 6. Stack technique

| Composant | Technologie |
|-----------|-------------|
| Frontend | React 18 + Vite |
| Backend | FastAPI (Python) |
| Base de données | SQLite (dev) → PostgreSQL (prod) |
| Temps réel | WebSocket natif (FastAPI) → Matrix protocol (V3) |
| Voix/Vidéo | LiveKit (WebRTC open-source) |
| Auth | Identifiant léger (V1) → Auth JWT (V2) → Matrix MXID (V3) |
| Stockage fichiers | Local (V1) → S3/Cloudflare R2 (V2) |
| Déploiement | Docker Compose → Railway/Render (prod) |
| Protocole réseau | Propriétaire (V1/V2) → Matrix (V3, fédération) |

### 6.1 Convergence avec le protocole Matrix

[Matrix.org](https://matrix.org) est un standard ouvert et décentralisé pour la messagerie temps réel. Oria et Matrix partagent la même structure conceptuelle :

| Concept Oria | Équivalent Matrix |
|--------------|-------------------|
| Monde | Matrix Space |
| Pièce texte | Matrix Room |
| Pièce vocale | Element Call Room (basé sur LiveKit) |
| Invitation par lien | Matrix Room alias / invite link |
| Présence | Matrix Presence API |
| Fédération entre mondes | Matrix Federation (homeservers) |

**Avantages d'une intégration Matrix à terme :**
- **Chiffrement E2E natif** via le protocole Olm/Megolm (Double Ratchet)
- **Fédération** : un monde Oria sur `oria.app` peut communiquer avec un monde hébergé en self-hosted
- **Bridges** : connecter les pièces Oria à Discord, Slack, IRC sans effort via les bridges Matrix existants
- **Interopérabilité** : les utilisateurs d'Element ou d'autres clients Matrix peuvent rejoindre un espace Oria
- **LiveKit déjà dans l'écosystème** : Element Call (client voix officiel de Matrix) utilise exactement la même stack LiveKit — aucune migration requise

---

## 7. Architecture des données

```
Monde
  └── Bâtiment (maison / site / immeuble)
        └── Pièce (texte / vocal / mixte / étage)
              ├── Messages (chat temps réel)
              ├── Membres présents
              └── Fichiers (V2)

Utilisateur
  ├── Profil (nom, avatar, id)
  ├── Membres de plusieurs mondes
  └── Messages privés (V2)
```

---

## 8. Métriques de succès (KPIs)

| Métrique | Cible V1 | Cible V2 |
|----------|----------|----------|
| Mondes créés | 10 | 500 |
| Sessions actives / jour | — | 50 |
| Durée moyenne session | — | > 20 min |
| Taux de rétention J7 | — | > 40% |
| Invitations acceptées | — | > 60% |

---

## 9. Différenciation concurrentielle

| | Oria | Discord | Slack | Notion | Gather | Element (Matrix) |
|--|------|---------|-------|--------|--------|-----------------|
| Espace visuel/spatial | ✅ | ❌ | ❌ | ❌ | ✅ | ❌ |
| Voix/Vidéo | ✅ | ✅ | ✅ | ❌ | ✅ | ✅ |
| Documents | 🔜 | ❌ | ✅ | ✅ | ❌ | ❌ |
| Monde personnel | ✅ | ❌ | ❌ | ✅ | ❌ | ❌ |
| Invitation par lien | ✅ | ✅ | ✅ | ✅ | ✅ | ✅ |
| Sans compte email | ✅ | ❌ | ❌ | ❌ | ❌ | ❌ |
| Open-source | ✅ | ❌ | ❌ | ❌ | ❌ | ✅ |
| Fédéré / décentralisé | 🔜 V3 | ❌ | ❌ | ❌ | ❌ | ✅ |
| Chiffrement E2E natif | 🔜 V3 | ❌ | ❌ | ❌ | ❌ | ✅ |
| Bridges vers autres apps | 🔜 V3 | ❌ | ✅ | ❌ | ❌ | ✅ |

**Positionnement par rapport à Matrix/Element :**
Element est puissant mais complexe et peu intuitif. Oria apporte la dimension spatiale, l'expérience visuelle et la simplicité d'onboarding qui manquent à l'écosystème Matrix. À terme, Oria peut devenir **le client Matrix grand public** : simple en surface, fédéré en dessous.

---

## 10. Roadmap

```
V1 — Fondation (actuel)
  ✅ Login léger
  ✅ Création de mondes
  ✅ 3 types de bâtiments
  ✅ Chat texte temps réel
  ✅ Voix/vidéo par pièce
  ✅ Présence en temps réel

V2 — Collaboration (prochain sprint)
  🔜 Liens d'invitation
  🔜 Gestion des rôles
  🔜 Upload de fichiers
  🔜 Navigation animée
  🔜 Notifications

V3 — Réseau (6–12 mois)
  🔜 Profils publics
  🔜 IA (transcription, résumé)
  🔜 Monétisation
  🔜 App mobile

V4 — Fédération & Inbox universelle (12–24 mois)
  🔜 Protocole Matrix sous le capot (homeserver Oria)
  🔜 Chiffrement E2E natif (Olm/Megolm)
  🔜 Inbox unifiée : toutes tes messageries dans Oria
      → WhatsApp, Instagram, Facebook Messenger
      → LinkedIn, Telegram, Signal
      → Twitter/X DMs, iMessage, SMS
      → Discord, Slack (pro)
  🔜 Marketplace de bridges : installer / activer en un clic
  🔜 Interopérabilité avec Element et autres clients Matrix
  🔜 Self-hosting avec fédération inter-mondes
```
