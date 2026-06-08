"""Packager de déploiement (S4) — transforme une app générée en un bundle Docker
reproductible, livrable à une entreprise.

Au lieu d'un simple fichier HTML, le bundle est un dossier autonome qu'on lance d'un
seul `docker compose up` : il embarque l'app (servie par nginx) **et sa propre instance
de persistance** (la brique « donnees », bâtie sur place → multi-tenant par déploiement),
pré-remplie avec les données d'exemple de l'entreprise.

La config réseau de l'app est externalisée dans `web/config.js` (window.WP_CONFIG) :
on déploie le même HTML n'importe où en éditant un seul fichier, sans régénérer l'app.
"""
import json
import os
import re
import secrets
import shutil

from gabarit import entites_du_plan

# Version de Keycloak embarquée dans les bundles livrés (alignée sur le stack workspace).
KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:26.2.5"


def _slug(nom: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", (nom or "app").lower()).strip("-")
    return s or "app"


def _mdp(n: int = 14) -> str:
    """Mot de passe aléatoire lisible (sans caractères ambigus)."""
    alpha = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnpqrstuvwxyz23456789"
    return "".join(secrets.choice(alpha) for _ in range(n))


def _realm_json(slug: str, nom: str, port_app: int, admin_mdp: str) -> dict:
    """Realm Keycloak pré-provisionné, propre à l'entreprise (annuaire de comptes isolé).

    • registrationAllowed=false → seul l'admin du client crée les comptes (choix retenu).
    • client public `app` en PKCE S256 (le tableau de bord livré s'y authentifie).
    • 1 utilisateur `admin` avec le rôle realm-management:realm-admin → il gère les
      utilisateurs de SON realm via la console Keycloak. Mot de passe temporaire (à changer
      à la première connexion).
    """
    realm = f"client-{slug}"
    app_url = f"http://localhost:{port_app}"
    return {
        "realm": realm,
        "enabled": True,
        "registrationAllowed": False,
        "loginWithEmailAllowed": True,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": True,
        "sslRequired": "none",
        "clients": [
            {
                "clientId": "app",
                "name": f"Application {nom}",
                "enabled": True,
                "publicClient": True,
                "standardFlowEnabled": True,
                "directAccessGrantsEnabled": False,
                "rootUrl": app_url,
                "baseUrl": "/",
                "redirectUris": [f"{app_url}/*"],
                "webOrigins": ["+"],
                "attributes": {"pkce.code.challenge.method": "S256", "post.logout.redirect.uris": "+"},
                # Mapper d'audience : inscrit « app » dans le claim `aud` des access tokens.
                # Sans ça, Keycloak n'y met que `account` et la brique donnees (qui valide
                # désormais aud=app, cf. KEYCLOAK_AUDIENCE dans le compose) rejetterait tout.
                "protocolMappers": [
                    {
                        "name": "audience-app",
                        "protocol": "openid-connect",
                        "protocolMapper": "oidc-audience-mapper",
                        "consentRequired": False,
                        "config": {
                            "included.client.audience": "app",
                            "id.token.claim": "false",
                            "access.token.claim": "true",
                            "introspection.token.claim": "true",
                        },
                    }
                ],
            }
        ],
        "users": [
            {
                "username": "admin",
                "enabled": True,
                "emailVerified": True,
                "firstName": "Administrateur",
                "lastName": nom,
                "credentials": [{"type": "password", "value": admin_mdp, "temporary": True}],
                "clientRoles": {"realm-management": ["realm-admin"]},
            }
        ],
    }


def _injecter_config_js(html: str) -> str:
    """Ajoute <script src="config.js"> dans le <head> du HTML livré (avant tout le reste)
    pour que window.WP_CONFIG soit défini quand le script de l'app s'évalue."""
    tag = '  <script src="config.js"></script>\n</head>'
    if "</head>" in html:
        return html.replace("</head>", tag, 1)
    # Repli : HTML sans </head> explicite → injecte juste après <body>.
    return html.replace("<body", '<script src="config.js"></script>\n<body', 1)


def _seed_json(app_id: str, plan: dict) -> dict:
    """{app_id: {entite_id: [exemples]}} — consommé par SEED_FILE de la brique donnees."""
    entites = {}
    for ent in entites_du_plan(plan):
        exemples = [e for e in ent.get("exemples", []) if isinstance(e, dict)]
        if exemples:
            entites[ent["id"]] = exemples
    return {app_id: entites}


_DOCKER_COMPOSE = """# Déploiement autonome de l'application « {nom} »
# Généré par Workplace — un seul `docker compose up -d --build` suffit.
# 3 services : identite (Keycloak, comptes), donnees (persistance), web (l'app).
services:
  identite:
    image: {keycloak_image}
    container_name: {slug}_identite
    command: ["start-dev", "--import-realm"]
    environment:
      - KC_BOOTSTRAP_ADMIN_USERNAME=superadmin
      - KC_BOOTSTRAP_ADMIN_PASSWORD={kc_super_mdp}
      - KC_HTTP_PORT=8080
      - KC_HTTP_ENABLED=true
    volumes:
      - ./keycloak/realm.json:/opt/keycloak/data/import/realm.json:ro
      - identite_data:/opt/keycloak/data
    ports:
      - "${{PORT_KEYCLOAK:-{port_keycloak}}}:8080"
    restart: unless-stopped

  donnees:
    build: ./donnees
    container_name: {slug}_donnees
    depends_on:
      - identite
    environment:
      - DB_PATH=/data/donnees.db
      - SEED_FILE=/seed/seed.json
      # Authentification : chaque écriture/lecture exige un jeton du Keycloak du bundle.
      # KEYCLOAK_URL pointe le service interne (réseau Docker), pas localhost — la
      # signature est validée contre les clés du realm. KEYCLOAK_AUDIENCE=app active
      # en plus la validation d'audience (verify_aud) : un jeton émis pour un autre
      # client/realm est rejeté, même s'il est correctement signé.
      - AUTH_ENABLED=true
      - KEYCLOAK_URL=http://identite:8080
      - KEYCLOAK_REALM={realm}
      - KEYCLOAK_AUDIENCE=app
      - CORS_ORIGINS=http://localhost:${{PORT_APP:-{port_app}}}
    volumes:
      - donnees_data:/data
      - ./donnees/seed.json:/seed/seed.json:ro
    ports:
      - "${{PORT_DONNEES:-{port_donnees}}}:5500"
    restart: unless-stopped

  web:
    image: nginx:alpine
    container_name: {slug}_web
    depends_on:
      - donnees
      - identite
    volumes:
      - ./web:/usr/share/nginx/html:ro
    ports:
      - "${{PORT_APP:-{port_app}}}:80"
    restart: unless-stopped

volumes:
  donnees_data:
  identite_data:
"""


_ENV = """# Ports publiés sur la machine hôte. Modifiables librement.
# ⚠ Si vous changez PORT_DONNEES, mettez à jour l'URL apiBase dans web/config.js.
# ⚠ Si vous changez PORT_KEYCLOAK, mettez à jour auth.url dans web/config.js ET les
#    « redirect URIs » du client « app » dans la console Keycloak.
PORT_APP={port_app}
PORT_DONNEES={port_donnees}
PORT_KEYCLOAK={port_keycloak}
"""


_LISEZMOI = """Application « {nom} » — bundle de déploiement Workplace
========================================================

Ce dossier est une livraison AUTONOME et REPRODUCTIBLE. Il contient tout le
nécessaire pour faire tourner l'application sur n'importe quelle machine équipée
de Docker, sans dépendre de l'environnement de développement.

CONTENU
-------
  docker-compose.yml   Orchestration des 3 services (identité + persistance + app web).
  .env                 Ports publiés (modifiables).
  web/index.html       L'application.
  web/config.js        Config de l'app (URL du serveur de données + du serveur d'identité).
  donnees/             La brique de persistance (bâtie sur place), avec seed.json
                       = les données d'exemple de l'entreprise.
  keycloak/realm.json  L'annuaire de comptes de VOTRE entreprise (realm pré-configuré).

DÉMARRAGE (une seule commande)
------------------------------
  docker compose up -d --build

Le service d'identité (Keycloak) met ~30 à 60 s à démarrer la première fois.
Puis ouvrez :  http://localhost:{port_app}
L'application est protégée : un écran de connexion s'affiche avant tout accès.

AUTHENTIFICATION — VOS COMPTES (annuaire isolé, propre à votre entreprise)
--------------------------------------------------------------------------
Chaque déploiement a SON PROPRE serveur d'identité (Keycloak) et son propre
annuaire de comptes — totalement isolé des autres clients et de l'éditeur.

  • Console d'administration des comptes :
      http://localhost:{port_keycloak}/admin/   (realm « {realm} »)
  • Compte ADMINISTRATEUR de votre entreprise (créé d'office) :
      identifiant : admin
      mot de passe : {admin_mdp}   ← À CHANGER à la première connexion (demandé).
  • Compte super-admin du serveur Keycloak (réglages techniques avancés) :
      identifiant : superadmin   /   mot de passe : voir KC_BOOTSTRAP_ADMIN_PASSWORD
      dans docker-compose.yml.

CRÉER LES COMPTES DE VOS EMPLOYÉS
---------------------------------
L'inscription libre est désactivée : c'est l'admin qui crée les comptes.
  1. Connectez-vous à la console ci-dessus avec « admin ».
  2. Menu « Users » → « Add user » → renseignez identifiant/e-mail.
  3. Onglet « Credentials » → définissez un mot de passe.
L'employé peut alors se connecter à l'application avec ces identifiants.

DONNÉES
-------
La toute première fois, la base est pré-remplie avec les données d'exemple
(seed.json). Les saisies suivantes sont conservées dans le volume Docker
« donnees_data » (elles survivent aux redémarrages). Les comptes utilisateurs
sont conservés dans le volume « identite_data ».

ARRÊT / REDÉMARRAGE
-------------------
  docker compose down          (garde données ET comptes)
  docker compose down -v       (efface TOUT — données et comptes — remise à zéro)

CHANGER LES PORTS
-----------------
Éditez .env (PORT_APP / PORT_DONNEES / PORT_KEYCLOAK). Si vous changez PORT_DONNEES
ou PORT_KEYCLOAK, ajustez « apiBase » / « auth.url » dans web/config.js en conséquence
(et, pour Keycloak, les « redirect URIs » du client « app » dans la console).

MESSAGERIE (le cas échéant)
---------------------------
Si l'application embarque l'onglet « Messagerie », il réutilise le compte avec lequel
vous êtes connecté à l'application (même serveur d'identité). Le serveur de
collaboration Oria doit faire confiance à ce realm — voir l'éditeur pour l'activer.

Mode : hébergé (multi-utilisateur, authentifié).  Généré le {date}.
"""


def packager_bundle(*, app_id: str, nom: str, html: str, plan: dict, date: str,
                    export_dir: str, donnees_src: str,
                    port_app: int = 8090, port_donnees: int = 5510,
                    port_keycloak: int = 8095) -> dict:
    """Écrit le bundle de déploiement sur disque. Retourne un récapitulatif.

    Le bundle embarque SON PROPRE Keycloak (annuaire de comptes isolé par client) :
    realm pré-provisionné, 1 admin, inscription libre désactivée. Toute l'app est servie
    derrière ce login (cf. la garde d'auth du gabarit, activée par le bloc `auth` de config.js).
    """
    if not html:
        raise ValueError("HTML de l'app manquant")
    if not os.path.isdir(donnees_src):
        raise FileNotFoundError(
            f"Source de la brique « donnees » introuvable ({donnees_src}). "
            "Vérifiez que le dossier briques/donnees est monté dans le générateur."
        )

    slug = _slug(nom)
    realm = f"client-{slug}"
    admin_mdp = _mdp()        # mot de passe initial de l'admin du client (temporaire)
    kc_super_mdp = _mdp()     # mot de passe du super-admin du serveur Keycloak
    dossier = os.path.join(export_dir, f"{slug}-deploiement")
    web = os.path.join(dossier, "web")
    donnees = os.path.join(dossier, "donnees")
    keycloak = os.path.join(dossier, "keycloak")
    os.makedirs(web, exist_ok=True)
    os.makedirs(donnees, exist_ok=True)
    os.makedirs(keycloak, exist_ok=True)

    # 1. App + config (réseau données + serveur d'identité). Le bloc `auth` active la
    #    garde de connexion : l'app entière exige un login contre le Keycloak du bundle.
    with open(os.path.join(web, "index.html"), "w", encoding="utf-8") as f:
        f.write(_injecter_config_js(html))
    config_js = (
        "// Configuration de l'application livrée. Éditable sans régénérer l'app.\n"
        "// apiBase  → serveur de données (service « donnees »).\n"
        "// auth     → serveur d'identité Keycloak du bundle (login de TOUTE l'app).\n"
        "window.WP_CONFIG = " + json.dumps(
            {
                "apiBase": f"http://localhost:{port_donnees}",
                "appId": app_id,
                "auth": {
                    "url": f"http://localhost:{port_keycloak}",
                    "realm": realm,
                    "clientId": "app",
                },
            },
            ensure_ascii=False, indent=2,
        ) + ";\n"
    )
    with open(os.path.join(web, "config.js"), "w", encoding="utf-8") as f:
        f.write(config_js)

    # 2. Brique « donnees » embarquée (build reproductible) + seed.
    #    auth.py : garde JWT activée par AUTH_ENABLED (cf. compose) → les écritures
    #    exigent un jeton du Keycloak du bundle, l'API n'est plus contournable en direct.
    for nom_fichier in ("Dockerfile", "main.py", "auth.py", "requirements.txt"):
        src = os.path.join(donnees_src, nom_fichier)
        if os.path.exists(src):
            shutil.copy2(src, os.path.join(donnees, nom_fichier))
    with open(os.path.join(donnees, "seed.json"), "w", encoding="utf-8") as f:
        json.dump(_seed_json(app_id, plan), f, ensure_ascii=False, indent=2)

    # 3. Keycloak — realm pré-provisionné de l'entreprise (annuaire de comptes isolé)
    with open(os.path.join(keycloak, "realm.json"), "w", encoding="utf-8") as f:
        json.dump(_realm_json(slug, nom, port_app, admin_mdp), f, ensure_ascii=False, indent=2)

    # 4. Orchestration + doc
    with open(os.path.join(dossier, "docker-compose.yml"), "w", encoding="utf-8") as f:
        f.write(_DOCKER_COMPOSE.format(nom=nom, slug=slug, keycloak_image=KEYCLOAK_IMAGE,
                                       kc_super_mdp=kc_super_mdp, realm=realm, port_app=port_app,
                                       port_donnees=port_donnees, port_keycloak=port_keycloak))
    with open(os.path.join(dossier, ".env"), "w", encoding="utf-8") as f:
        f.write(_ENV.format(port_app=port_app, port_donnees=port_donnees, port_keycloak=port_keycloak))
    with open(os.path.join(dossier, "LISEZMOI.txt"), "w", encoding="utf-8") as f:
        f.write(_LISEZMOI.format(nom=nom, port_app=port_app, port_keycloak=port_keycloak,
                                 realm=realm, admin_mdp=admin_mdp, date=date))

    return {
        "dossier_conteneur": dossier,
        "port_app": port_app,
        "port_donnees": port_donnees,
        "port_keycloak": port_keycloak,
        "auth": {"realm": realm, "admin_utilisateur": "admin", "admin_mot_de_passe": admin_mdp},
        "fichiers": ["docker-compose.yml", ".env", "web/index.html", "web/config.js",
                     "donnees/Dockerfile", "donnees/main.py", "donnees/auth.py",
                     "donnees/requirements.txt", "donnees/seed.json",
                     "keycloak/realm.json", "LISEZMOI.txt"],
    }
