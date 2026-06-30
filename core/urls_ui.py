"""URLs publiques (vues du NAVIGATEUR) des briques embarquées en iframe et clé
du compte Studio. Partagé par le router dashboard (toutes) et usine
(GENERATEUR_URL_PUBLIQUE, pour les liens aperçu/téléchargement).
"""
import os

# URL publique du Générateur (vue depuis le NAVIGATEUR de l'utilisateur), pour les
# liens « aperçu / télécharger » du tableau des entreprises livrées.
GENERATEUR_URL_PUBLIQUE = os.environ.get("GENERATEUR_URL_PUBLIQUE", "http://localhost:5400")

# URL publique de la SPA Forge (vue depuis le NAVIGATEUR), reprise par l'onglet
# « Forge » du dashboard dans une iframe (S19). Servie par la brique forge (service
# `frontend`, port hôte FORGE_FRONTEND_PORT, défaut 3000). Le SSO se fait dans la SPA
# elle-même (realm `oria`), pas dans le Cœur.
FORGE_UI_URL = os.environ.get("FORGE_UI_URL", "http://localhost:3000")

# URLs publiques des briques créatives (vues depuis le NAVIGATEUR), reprises par l'onglet
# « Créations » du dashboard dans des iframes. Le Hub Créations a migré d'Oria vers le Cœur :
# le Studio (brique autonome, port 6060) et l'atelier Personnages (port 5900) sont désormais
# embarqués ici. Port 6060 et pas 6000 : 6000 = X11, banni par Chrome (ERR_UNSAFE_PORT).
STUDIO_UI_URL = os.environ.get("STUDIO_UI_URL", "http://localhost:6060/atelier")
PERSONNAGES_UI_URL = os.environ.get("PERSONNAGES_UI_URL", "http://localhost:5900/atelier")
TRANSCRIPTION_UI_URL = os.environ.get("TRANSCRIPTION_UI_URL", "http://localhost:5980/atelier")
# Brique « restaurant » (port 6010) : back-office restaurateur (commande & paiement à table
# par QR, multi-tenant). Embarquée dans l'onglet « Atelier » comme les autres briques.
RESTAURANT_UI_URL = os.environ.get("RESTAURANT_UI_URL", "http://localhost:6010/")
# Brique « mail » (port 6030) : client mail (boîtes de réception unifiées + réponse sur
# validation). Embarquée dans son propre onglet « Mail » (entre Agenda et Profil).
MAIL_UI_URL = os.environ.get("MAIL_UI_URL", "http://localhost:6030/")
# Brique « synopsis » (port 6090) : résumé de n'importe quelle vidéo (YouTube, URL, fichier)
# par IA. Embarquée comme TUILE du hub « Atelier » (ouvrirCreation).
SYNOPSIS_UI_URL = os.environ.get("SYNOPSIS_UI_URL", "http://localhost:6090/")
# Brique « voix » (port 5985) : page de réglage du moteur de synthèse vocale — choisir la
# voix de l'assistant EN UN CLIC (Piper souverain par défaut, Kokoro naturel local…) +
# bouton « Tester ». Embarquée comme TUILE du hub « Atelier » (ouvrirCreation).
VOIX_UI_URL = os.environ.get("VOIX_UI_URL", "http://localhost:5985/")
# Brique « memoire » (port 5600) : le vrai front du projet Memory (graphe IPCRA, recherche
# hybride). L'adaptateur sert le front buildé + reverse-proxy /api/v1 (S108). Embarquée
# comme TUILE du hub « Atelier » (ouvrirCreation). Route SPA → /memory.
MEMOIRE_UI_URL = os.environ.get("MEMOIRE_UI_URL", "http://localhost:5600/memory")
# Brique « dev » (auto-atelier, port 5955) : IDE web code-server monté sur le dépôt (S92),
# embarqué dans l'onglet « Atelier dev » du dashboard. On relit/édite le code et les diffs des
# chantiers dans le navigateur, à côté du pilotage à la voix (outil Cœur `dev_demander`).
DEV_IDE_URL = os.environ.get("DEV_IDE_URL", "http://localhost:8744/")
# Console d'admin native de la Gateway (LiteLLM UI), reprise par l'onglet « Gateway »
# du dashboard dans une iframe. URL vue depuis le NAVIGATEUR (port publié 4001), pas
# l'URL interne GATEWAY_URL (host.docker.internal) qui sert aux appels du Cœur.
GATEWAY_UI_URL = os.environ.get("GATEWAY_UI_URL", "http://localhost:4001/ui")
# Brique « peertube » (port 6100) : hébergement vidéo souverain. Interface publique pour
# archive, recherche, upload et live RTMP. Embarquée comme TUILE du hub « Atelier ».
PEERTUBE_UI_URL = os.environ.get("PEERTUBE_UI_URL", "http://localhost:9000")
# « Compte Studio » = clé de service partagée avec la brique (auth X-API-Key). Quand elle est
# définie, l'assistant l'envoie (cf. outils.py) ET l'iframe du dashboard la transporte en
# ?api_key= (le front Studio la lit). Vide = brique en mode ouvert.
STUDIO_KEY = os.environ.get("STUDIO_KEY", "")
