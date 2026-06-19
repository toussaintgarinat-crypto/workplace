import asyncio
import os
import uuid
from contextlib import asynccontextmanager

import json

import httpx
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse

import agenda
import assistant
import classer
import config_assistant
import identite
import journal_usage
import langue as langue_mod
import personas
import shadow
import proactif
import horloge
import briefing
import pouls
import proprioception
import amelioration
import curateur
import cycle_de_vie
import orchestrateur
import catalogue
import mcp as mcp_serveur
from registre import Registre

registre = Registre()

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
# « Compte Studio » = clé de service partagée avec la brique (auth X-API-Key). Quand elle est
# définie, l'assistant l'envoie (cf. outils.py) ET l'iframe du dashboard la transporte en
# ?api_key= (le front Studio la lit). Vide = brique en mode ouvert.
STUDIO_KEY = os.environ.get("STUDIO_KEY", "")

DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0, viewport-fit=cover">
<title>Workplace — Cœur</title>
<!-- PWA « télécommande » (S61) : installable sur mobile, plein écran, zéro calcul local. -->
<link rel="manifest" href="/manifest.webmanifest">
<meta name="theme-color" content="#0f1117">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Workplace">
<link rel="apple-touch-icon" href="/icon.svg">
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; background: #0f1117; color: #e2e8f0; min-height: 100vh; }
  header { background: #1a1d27; border-bottom: 1px solid #2d3148; padding: 20px 32px; display: flex; align-items: center; justify-content: space-between; }
  header h1 { font-size: 1.25rem; font-weight: 700; letter-spacing: 0.02em; }
  header h1 span { color: #7c83ff; }
  .badge { background: #1e2535; border: 1px solid #2d3148; border-radius: 20px; padding: 4px 14px; font-size: 0.78rem; color: #94a3b8; }
  .badge b { color: #e2e8f0; }
  main { padding: 32px; max-width: 1200px; margin: 0 auto; }
  .topbar { display: flex; align-items: center; justify-content: space-between; margin-bottom: 24px; }
  .topbar h2 { font-size: 1rem; color: #64748b; font-weight: 500; }
  .btn { background: #7c83ff; color: #fff; border: none; border-radius: 8px; padding: 8px 18px; font-size: 0.85rem; cursor: pointer; display: flex; align-items: center; gap: 8px; transition: background 0.15s; }
  .btn:hover { background: #6366f1; }
  .btn.loading { opacity: 0.6; pointer-events: none; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: 16px; }
  .groupe-couche { margin-bottom: 28px; }
  .groupe-titre { display: flex; align-items: center; gap: 10px; font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.1em; color: #94a3b8; margin: 0 0 14px; padding-bottom: 8px; border-bottom: 1px solid #2a2f44; }
  .groupe-compteur { font-size: 0.72rem; font-weight: 600; color: #7c83ff; background: #1f2433; border: 1px solid #3d4468; border-radius: 20px; padding: 1px 9px; letter-spacing: 0; }
  .card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; position: relative; transition: border-color 0.2s; }
  .card:hover { border-color: #3d4468; }
  .card-header { display: flex; align-items: flex-start; justify-content: space-between; margin-bottom: 12px; }
  .card-title { font-size: 1rem; font-weight: 600; }
  .card-version { font-size: 0.72rem; color: #475569; margin-top: 2px; }
  .role-badge { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; padding: 3px 10px; border-radius: 20px; }
  .role-memoire    { background: #1e3a5f; color: #60a5fa; }
  .role-llm        { background: #3b2a5f; color: #c084fc; }
  .role-collaboration { background: #1f3a2f; color: #4ade80; }
  .role-agents     { background: #3a2a1f; color: #fb923c; }
  .role-etl        { background: #2a2a1f; color: #facc15; }
  .role-generateur { background: #1f3a3a; color: #22d3ee; }
  .card-desc { font-size: 0.82rem; color: #94a3b8; line-height: 1.5; margin-bottom: 14px; }
  .card-footer { display: flex; align-items: center; justify-content: space-between; }
  .statut { display: flex; align-items: center; gap: 6px; font-size: 0.78rem; font-weight: 500; }
  .dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }
  .statut-actif       .dot { background: #22c55e; box-shadow: 0 0 6px #22c55e88; }
  .statut-actif           { color: #22c55e; }
  .statut-setup_requis .dot { background: #f59e0b; box-shadow: 0 0 6px #f59e0b88; }
  .statut-setup_requis     { color: #f59e0b; }
  .statut-a_tester    .dot { background: #64748b; }
  .statut-a_tester        { color: #64748b; }
  .health { font-size: 0.75rem; padding: 3px 10px; border-radius: 20px; font-weight: 500; }
  .health-ok          { background: #14532d55; color: #4ade80; border: 1px solid #16653155; }
  .health-inaccessible{ background: #7f1d1d55; color: #f87171; border: 1px solid #991b1b55; }
  .health-inconnu     { background: #1e293b; color: #475569; border: 1px solid #2d3748; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip { font-size: 0.68rem; background: #1e2535; border: 1px solid #2d3148; border-radius: 6px; padding: 2px 8px; color: #64748b; }
  .section-label { font-size: 0.65rem; color: #475569; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; margin-top: 10px; }
  #last-check { font-size: 0.75rem; color: #475569; }
  /* Onglets */
  .tabs { display: flex; gap: 4px; }
  .tab { background: transparent; border: none; color: #64748b; font-size: 0.85rem; font-weight: 500; padding: 8px 16px; border-radius: 8px; cursor: pointer; }
  .tab:hover { color: #e2e8f0; }
  .tab.active { background: #1e2535; color: #7c83ff; }
  /* Assistant */
  .chat { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; display: flex; flex-direction: column; height: 65vh; overflow: hidden; }
  .chat-fil { flex: 1; overflow-y: auto; padding: 20px; display: flex; flex-direction: column; gap: 12px; }
  .msg { display: flex; }
  .msg.user { justify-content: flex-end; }
  .bulle { max-width: 78%; padding: 10px 14px; border-radius: 12px; font-size: 0.88rem; line-height: 1.5; white-space: pre-wrap; word-wrap: break-word; }
  .msg.assistant .bulle { background: #232838; color: #e2e8f0; border: 1px solid #2d3148; border-bottom-left-radius: 3px; }
  .msg.user .bulle { background: #7c83ff; color: #fff; border-bottom-right-radius: 3px; }
  .outil { align-self: flex-start; font-size: 0.74rem; color: #94a3b8; background: #161922; border: 1px solid #2d3148; border-radius: 8px; padding: 6px 12px; display: flex; align-items: center; gap: 8px; }
  .outil .pic { width: 7px; height: 7px; border-radius: 50%; background: #22d3ee; box-shadow: 0 0 6px #22d3ee88; }
  .outil.action .pic { background: #fb923c; box-shadow: 0 0 6px #fb923c88; }
  .outil.confirm .pic { background: #f59e0b; box-shadow: 0 0 6px #f59e0b88; }
  .chat-saisie { display: flex; gap: 10px; padding: 14px; border-top: 1px solid #2d3148; }
  .chat-saisie input { flex: 1; background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 10px 14px; color: #e2e8f0; font-size: 0.9rem; }
  .chat-saisie input:focus { outline: none; border-color: #7c83ff; }
  .typing { color: #64748b; font-size: 0.8rem; font-style: italic; align-self: flex-start; }
  /* Voix + dépôt de documents */
  .btn.ghost.icone { padding: 8px 12px; font-size: 1rem; }
  #btn-micro.ecoute { background: #ef4444; color: #fff; animation: pulse 1.2s infinite; }
  #btn-micro.reveil { background: #22c55e; color: #fff; animation: pulse 0.7s infinite; }  /* mot-clé détecté : on dicte */
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.55; } }
  .chat { position: relative; }
  .drop-overlay { position: absolute; inset: 0; z-index: 5; display: none; align-items: center; justify-content: center;
    background: rgba(124,131,255,0.12); border: 2px dashed #7c83ff; border-radius: 12px; color: #c7cbff; font-size: 1rem; font-weight: 600; }
  .chat.drag .drop-overlay { display: flex; }
  .carte-classement { align-self: flex-start; max-width: 78%; background: #1f2433; border: 1px solid #3d4468; border-radius: 12px; border-bottom-left-radius: 3px; padding: 12px 14px; font-size: 0.84rem; }
  .carte-classement .cc-tete { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .carte-classement .cc-cat { background: #2a2a1f; color: #facc15; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; padding: 3px 9px; border-radius: 20px; }
  .carte-classement .cc-nom { color: #e2e8f0; font-weight: 600; }
  .carte-classement .cc-ligne { color: #94a3b8; margin: 3px 0; }
  .carte-classement .cc-ligne b { color: #cbd5e1; font-weight: 600; }
  .carte-classement .chips { margin: 6px 0; }
  .carte-classement .cc-actions { display: flex; gap: 8px; margin-top: 10px; }
  .carte-classement .cc-actions .btn { padding: 5px 12px; font-size: 0.78rem; }
  .dossiers-tete { display: flex; align-items: baseline; gap: 10px; margin-bottom: 12px; }
  .dossiers-corps { display: flex; flex-wrap: wrap; gap: 18px; }
  .dossier-groupe { min-width: 160px; }
  .dossier-groupe .dg-titre { font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; margin-bottom: 6px; }
  .dossier-chip { display: inline-flex; align-items: center; gap: 6px; background: #1e2535; border: 1px solid #2d3148; border-radius: 8px; padding: 4px 10px; margin: 0 6px 6px 0; font-size: 0.8rem; color: #cbd5e1; cursor: pointer; }
  .dossier-chip:hover { border-color: #7c83ff; }
  .dossier-chip b { color: #7c83ff; }
  /* Agenda */
  .agenda-corps { display: flex; flex-direction: column; gap: 4px; }
  .agenda-jour { font-size: 0.72rem; color: #7c83ff; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; margin: 14px 0 6px; }
  .agenda-jour:first-child { margin-top: 0; }
  .agenda-evt { display: flex; align-items: center; gap: 12px; padding: 9px 12px; background: #1e2535; border: 1px solid #2d3148; border-radius: 8px; }
  .agenda-heure { font-variant-numeric: tabular-nums; color: #94a3b8; font-size: 0.82rem; min-width: 92px; }
  .agenda-titre { color: #e2e8f0; font-weight: 600; font-size: 0.9rem; flex: 1; }
  .agenda-lieu { color: #64748b; font-size: 0.78rem; }
  /* Rappels proactifs */
  .pastille { background: #ef4444; color: #fff; border-radius: 10px; padding: 0 6px; font-size: 0.68rem; font-weight: 700; margin-left: 4px; }
  .rappel { display: flex; align-items: center; justify-content: space-between; gap: 12px; padding: 10px 12px; border: 1px solid #2d3148; border-radius: 8px; margin-bottom: 8px; background: #1e2535; }
  .rappel.vu { opacity: 0.5; }
  .rappel-actions { display: flex; gap: 6px; flex-shrink: 0; }
  .rappel-actions .btn { padding: 4px 10px; font-size: 0.76rem; }
  /* Carte : bouton Ouvrir + panneau de détail (modal) */
  .card-open { width: 100%; justify-content: center; margin-top: 14px; }
  .modal-fond { position: fixed; inset: 0; z-index: 50; background: rgba(8,10,16,0.7); display: flex; align-items: center; justify-content: center; padding: 20px; }
  .modal-boite { position: relative; background: #1a1d27; border: 1px solid #2d3148; border-radius: 14px; padding: 24px; width: 100%; max-width: 540px; max-height: 85vh; overflow-y: auto; }
  .modal-fermer { position: absolute; top: 12px; right: 14px; background: none; border: none; color: #64748b; font-size: 1.1rem; cursor: pointer; }
  .modal-fermer:hover { color: #e2e8f0; }
  .modal-tete { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .modal-titre { font-size: 1.15rem; font-weight: 700; margin-bottom: 8px; }
  .modal-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
  .modal-actions .btn { text-decoration: none; }
  .view { display: none; }
  .view.active { display: block; }
  /* Usine */
  .panel { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 20px; margin-bottom: 20px; }
  .panel h3 { font-size: 0.92rem; margin-bottom: 14px; }
  .form-row { display: flex; flex-wrap: wrap; gap: 14px; align-items: flex-end; }
  .field { display: flex; flex-direction: column; gap: 5px; }
  .field label { font-size: 0.7rem; color: #64748b; text-transform: uppercase; letter-spacing: 0.05em; }
  .field input[type=text], .field select, .field input[type=file] { background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 8px 10px; color: #e2e8f0; font-size: 0.85rem; min-width: 180px; }
  .check { display: flex; align-items: center; gap: 6px; font-size: 0.82rem; color: #94a3b8; }
  .liv-card { background: #1a1d27; border: 1px solid #2d3148; border-radius: 12px; padding: 18px 20px; margin-bottom: 14px; }
  .liv-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 14px; }
  .liv-title { font-size: 1rem; font-weight: 600; }
  .liv-sub { font-size: 0.72rem; color: #475569; margin-top: 2px; }
  .liv-statut { font-size: 0.75rem; font-weight: 600; padding: 4px 12px; border-radius: 20px; }
  .liv-en_cours { background: #1e293b; color: #facc15; border: 1px solid #3a3a1f; }
  .liv-livree   { background: #14532d55; color: #4ade80; border: 1px solid #16653155; }
  .liv-erreur   { background: #7f1d1d55; color: #f87171; border: 1px solid #991b1b55; }
  .liv-decrochee{ background: #2a2440; color: #c4b5fd; border: 1px solid #4c3f73; }
  .steps { display: flex; gap: 8px; flex-wrap: wrap; }
  .step { flex: 1; min-width: 120px; background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 10px 12px; }
  .step-nom { font-size: 0.72rem; text-transform: uppercase; letter-spacing: 0.05em; color: #64748b; display: flex; align-items: center; gap: 6px; }
  .step-msg { font-size: 0.74rem; color: #94a3b8; margin-top: 4px; min-height: 1em; }
  .step-dot { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; background: #334155; }
  .step.en_cours { border-color: #facc1555; }
  .step.en_cours .step-dot { background: #facc15; box-shadow: 0 0 6px #facc1588; animation: pulse 1.2s infinite; }
  .step.en_cours .step-nom { color: #facc15; }
  .step.termine .step-dot { background: #22c55e; }
  .step.termine .step-nom { color: #4ade80; }
  .step.erreur .step-dot { background: #f87171; }
  .step.erreur .step-nom { color: #f87171; }
  @keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
  .liv-links { margin-top: 14px; display: flex; gap: 10px; align-items: center; }
  .liv-links a { font-size: 0.8rem; color: #7c83ff; text-decoration: none; padding: 6px 12px; border: 1px solid #3d4468; border-radius: 8px; }
  .liv-links a:hover { background: #1e2535; }
  .liv-err-msg { font-size: 0.78rem; color: #f87171; margin-top: 10px; }
  .empty { color: #475569; font-size: 0.85rem; padding: 30px; text-align: center; }
  .btn.ghost { background: transparent; border: 1px solid #3d4468; color: #94a3b8; }
  .btn.ghost:hover { background: #1e2535; color: #e2e8f0; }
  .creations-tuiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(260px, 1fr)); gap: 18px; }
  .creation-tuile { display: flex; flex-direction: column; align-items: flex-start; gap: 10px; text-align: left; padding: 22px; background: #1a1d27; border: 1px solid #2d3148; border-radius: 14px; color: #e2e8f0; cursor: pointer; transition: border-color 0.2s, transform 0.12s; }
  .creation-tuile:hover { border-color: #3d4468; transform: translateY(-2px); }
  .creation-tuile.creation-bientot { opacity: 0.55; cursor: default; }
  .creation-tuile.creation-bientot:hover { border-color: #2d3148; transform: none; }
  .creation-emoji { font-size: 26px; width: 50px; height: 50px; border-radius: 12px; display: flex; align-items: center; justify-content: center; background: #1e2535; }
  .creation-titre { font-size: 1.05rem; font-weight: 600; }
  .creation-desc { font-size: 0.82rem; line-height: 1.5; color: #94a3b8; }
  .creation-badge { font-size: 0.68rem; color: #7c83ff; border: 1px solid #3d4468; border-radius: 999px; padding: 2px 10px; }
  .creation-badge-bientot { color: #94a3b8; }
  /* Cerveau de l'assistant */
  .cerveau { margin-bottom: 16px; }
  .cerveau h3 { display: flex; align-items: center; gap: 10px; }
  .cerveau-row { display: flex; gap: 14px; align-items: flex-end; }
  .cerveau-row select, .cerveau-row input[type=password] { width: 100%; background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 9px 12px; color: #e2e8f0; font-size: 0.88rem; }
  .cerveau-row select:focus, .cerveau-row input:focus { outline: none; border-color: #7c83ff; }
  .cerveau-pill { font-size: 0.68rem; font-weight: 600; padding: 2px 10px; border-radius: 20px; background: #1e293b; color: #475569; border: 1px solid #2d3748; }
  .cerveau-pill.ok { background: #14532d55; color: #4ade80; border-color: #16653155; }
  .cerveau-pill.ko { background: #7f1d1d55; color: #f87171; border-color: #991b1b55; }
  .cerveau-msg { font-size: 0.82rem; margin-top: 12px; min-height: 1em; line-height: 1.5; }
  .cerveau-msg.ok { color: #4ade80; }
  .cerveau-msg.ko { color: #f87171; }
  .cerveau-msg.info { color: #94a3b8; }
  /* ── Télécommande mobile (S61) : le dashboard devient une appli chat plein écran ── */
  @supports (padding: env(safe-area-inset-bottom)) {
    header { padding-top: calc(20px + env(safe-area-inset-top)); }
    body { padding-bottom: env(safe-area-inset-bottom); }
  }
  @media (max-width: 640px) {
    header { padding: 14px 16px; padding-top: calc(14px + env(safe-area-inset-top)); flex-wrap: wrap; gap: 8px; }
    header h1 { font-size: 1.05rem; }
    main { padding: 16px; }
    .topbar { flex-wrap: wrap; gap: 10px; margin-bottom: 16px; }
    .grid { grid-template-columns: 1fr; }      /* tuiles en colonne unique */
    .tabs { width: 100%; overflow-x: auto; -webkit-overflow-scrolling: touch; }
    /* Chat : occupe l'écran (la « télécommande »). dvh = hauteur réelle hors barre mobile. */
    .chat { height: calc(100dvh - 150px); }
    .bulle { max-width: 88%; font-size: 0.95rem; }
    /* Inputs ≥ 16px : empêche le zoom auto d'iOS au focus. */
    .chat-saisie input, .cerveau-row input, .cerveau-row select { font-size: 16px; }
    .chat-saisie { padding: 10px; padding-bottom: calc(10px + env(safe-area-inset-bottom)); gap: 8px; }
    #panel-cerveau { max-height: 70dvh; overflow-y: auto; }
  }
</style>
</head>
<body>
<header>
  <h1>Workplace — <span>Cœur</span></h1>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="tabs">
      <button class="tab active" data-vue="briques" onclick="switchVue('briques')">Registre de briques</button>
      <button class="tab" data-vue="usine" onclick="switchVue('usine')">Usine à apps</button>
      <button class="tab" data-vue="assistant" onclick="switchVue('assistant')">Assistant</button>
      <button class="tab" data-vue="forge" onclick="switchVue('forge')">Forge</button>
      <button class="tab" data-vue="creations" onclick="switchVue('creations')">Créations</button>
      <button class="tab" data-vue="agenda" onclick="switchVue('agenda')">Agenda</button>
      <button class="tab" data-vue="profil" onclick="switchVue('profil')">Profil</button>
    </div>
    <div class="badge">v0.2.0 &nbsp;·&nbsp; <b id="nb-briques">—</b> briques</div>
  </div>
</header>
<main>
  <!-- VUE BRIQUES -->
  <div class="view active" id="vue-briques">
    <div class="topbar">
      <h2>Registre de briques</h2>
      <div style="display:flex;align-items:center;gap:12px">
        <span id="last-check"></span>
        <button class="btn" id="refresh-btn" onclick="charger()">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><polyline points="23 4 23 10 17 10"/><path d="M20.5 15a9 9 0 1 1-2.8-9.4L23 10"/></svg>
          Actualiser
        </button>
      </div>
    </div>
    <div id="groupes-briques"></div>
  </div>

  <!-- VUE USINE -->
  <div class="view" id="vue-usine">
    <div class="topbar">
      <h2>Usine à applications — livrer une entreprise en une commande</h2>
      <span id="usine-check"></span>
    </div>
    <div class="panel">
      <h3>Nouvelle livraison</h3>
      <form id="form-livrer" onsubmit="return lancerLivraison(event)">
        <div class="form-row">
          <div class="field">
            <label>Nom de l'entreprise</label>
            <input type="text" name="nom_entreprise" placeholder="Menuiserie Lefèvre & Fils">
          </div>
          <div class="field">
            <label>Documents (optionnel)</label>
            <input type="file" name="fichiers" multiple>
          </div>
          <div class="field">
            <label>Persistance</label>
            <select name="persistance">
              <option value="hebergee">Hébergée (multi-utilisateur)</option>
              <option value="autonome">Autonome (mono-poste)</option>
            </select>
          </div>
          <div class="field">
            <label>Langue de l'app</label>
            <select name="langue">
              <option value="fr">Français</option>
              <option value="en">English</option>
              <option value="es">Español</option>
            </select>
          </div>
          <div class="field">
            <label>Email du client (compte d'accès)</label>
            <input type="email" name="email_client" placeholder="client@exemple.fr">
          </div>
          <div class="field">
            <label>Contact client (optionnel)</label>
            <input type="text" name="contact_client" placeholder="Jean Dupont">
          </div>
          <label class="check"><input type="checkbox" name="messagerie"> Messagerie Oria</label>
          <label class="check"><input type="checkbox" name="packager"> Bundle Docker</label>
          <button class="btn" type="submit" id="btn-livrer">Livrer</button>
        </div>
        <div class="liv-sub" style="margin-top:10px">Sans documents, l'audit porte sur les fichiers déjà ingérés dans l'ETL. Avec un email client, un compte d'accès Oria est créé et un lien « définis ton mot de passe » lui est envoyé.</div>
      </form>
    </div>
    <div id="livraisons"></div>
  </div>

  <!-- VUE ASSISTANT -->
  <div class="view" id="vue-assistant">
    <div class="topbar">
      <h2>Assistant — parle-lui, dépose-lui des documents, il pilote la solution</h2>
      <div style="display:flex;gap:10px">
        <button class="btn ghost" id="btn-rappels" onclick="basculerRappels()" title="Rappels">🔔<span id="rappels-pastille" class="pastille" style="display:none">0</span></button>
        <button class="btn ghost" id="btn-voix" onclick="basculerLectureVocale()" title="Lire les réponses à voix haute">🔊 Voix : off</button>
        <button class="btn ghost" id="btn-cerveau" onclick="toggleCerveau()">⚙ Cerveau</button>
      </div>
    </div>

    <!-- Panneau des rappels proactifs -->
    <div class="panel" id="panel-rappels" style="display:none">
      <h3>🔔 Rappels</h3>
      <div id="rappels-corps"><span class="liv-sub">—</span></div>
    </div>

    <!-- Panneau de réglages du « cerveau » (modèle + clé) -->
    <div class="panel cerveau" id="panel-cerveau" style="display:none">
      <h3>Cerveau de l'assistant <span id="cerveau-etat" class="cerveau-pill">—</span></h3>
      <div class="cerveau-row">
        <div class="field" style="flex:1">
          <label>Modèle LLM</label>
          <select id="cerveau-model"><option>Chargement…</option></select>
          <div class="liv-sub" style="margin-top:4px">Changement immédiat — l'assistant l'utilise dès le prochain message.</div>
        </div>
        <button class="btn" id="btn-model" onclick="enregistrerModele()">Choisir ce modèle</button>
      </div>
      <div class="cerveau-row" style="margin-top:10px">
        <div class="field" style="flex:1">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="cerveau-cascade" onchange="enregistrerCascade()" style="width:auto;min-width:0">
            Cascade auto — gratuits d'abord, repli payant
          </label>
          <div class="liv-sub" id="cascade-desc" style="margin-top:4px">Essaie les meilleurs modèles gratuits (auto-sélectionnés), puis bascule sur le payant si besoin. Choisir un modèle ci-dessus le met en tête (ex. IA locale, ou payant d'abord).</div>
        </div>
      </div>
      <div class="cerveau-row" style="margin-top:10px">
        <div class="field" style="flex:1">
          <label style="display:flex;align-items:center;gap:8px;cursor:pointer">
            <input type="checkbox" id="cerveau-muscle" onchange="enregistrerMuscle()" style="width:auto;min-width:0">
            Muscle déporté — calcul LLM sur une autre machine (Mac/PC)
          </label>
          <div class="liv-sub" style="margin-top:4px">Si un nœud de calcul est prêt, il passe <b>en tête de la cascade</b> ; sinon il est réveillé en fond et la réponse part en mode dégradé (gratuits). Géré par la brique <b>calcul</b> (port 5990).</div>
          <div class="liv-sub" id="muscle-noeuds" style="margin-top:6px">—</div>
        </div>
      </div>
      <div class="cerveau-row" style="margin-top:14px">
        <div class="field" style="flex:1">
          <label>Personnalité <span id="persona-statut" class="cerveau-pill">—</span></label>
          <select id="cerveau-persona"><option>Chargement…</option></select>
          <div class="liv-sub" id="persona-desc" style="margin-top:4px">Le ton et la façon de répondre de l'assistant.</div>
        </div>
        <button class="btn" id="btn-persona" onclick="enregistrerPersona()">Choisir</button>
      </div>
      <div class="cerveau-row" style="margin-top:14px">
        <div class="field" style="flex:1">
          <label>Langue <span id="langue-statut" class="cerveau-pill">—</span></label>
          <select id="cerveau-langue"><option>Chargement…</option></select>
          <div class="liv-sub" style="margin-top:4px">Langue des réponses du Jarvis et de la voix (reconnaissance + lecture).</div>
        </div>
        <button class="btn" id="btn-langue" onclick="enregistrerLangue()">Choisir</button>
      </div>
      <div class="cerveau-row" style="margin-top:14px">
        <div class="field" style="flex:1">
          <label>Clé OpenRouter <span id="cle-statut" class="cerveau-pill">—</span></label>
          <input type="password" id="cerveau-cle" placeholder="sk-or-..." autocomplete="off">
          <div class="liv-sub" style="margin-top:4px">Enregistrer redémarre la Gateway (~15&nbsp;s) puis teste la clé pour de vrai.</div>
        </div>
        <button class="btn" id="btn-cle" onclick="enregistrerCle()">Enregistrer la clé</button>
      </div>
      <div class="cerveau-row" style="margin-top:14px">
        <div class="field" style="flex:1">
          <label>Voix temps réel <span id="voix-statut" class="cerveau-pill">—</span></label>
          <select id="cerveau-voix" onchange="majVisibiliteUnmute()">
            <option value="webspeech">Navigateur (Web Speech) — gratuit, ici</option>
            <option value="wakeword">Mot-clé « comme Siri » — brique ecoute (openWakeWord, CPU)</option>
            <option value="unmute">Kyutai Unmute — full-duplex (nécessite un GPU)</option>
          </select>
          <input type="text" id="cerveau-unmute-url" placeholder="wss://mon-serveur-unmute/v1/realtime" autocomplete="off" style="margin-top:8px;display:none">
          <input type="text" id="cerveau-wakeword-url" placeholder="ws://localhost:5800/ecoute" autocomplete="off" style="margin-top:8px;display:none">
          <div class="liv-sub" style="margin-top:4px">Mot-clé : micro toujours à l'écoute, réveil par <b>« hey jarvis »</b> via la brique <b>ecoute</b> (S42, ton infra, sans Google). Unmute : serveur Kyutai (GPU). Web Speech marche sur ce Mac.</div>
          <div id="voix-fin-bloc" style="margin-top:10px;display:none">
            <label style="font-size:0.82rem">Fin de ma phrase</label>
            <div style="display:flex;gap:16px;align-items:center;margin-top:4px;flex-wrap:wrap">
              <label class="liv-sub" style="cursor:pointer"><input type="radio" name="voix-fin" value="appui" onchange="majVoixFin()"> J'appuie 🎤 pour terminer</label>
              <label class="liv-sub" style="cursor:pointer"><input type="radio" name="voix-fin" value="silence" onchange="majVoixFin()"> Auto après silence</label>
              <span id="voix-silence-champ" style="display:none" class="liv-sub">de <input type="number" id="cerveau-silence" min="1" max="15" step="0.5" style="width:62px"> s</span>
            </div>
            <div class="liv-sub" style="margin-top:4px">En mode <b>appui</b>, le micro t'écoute à travers tes pauses : ta phrase ne part qu'au prochain clic 🎤 (zéro coupure). En <b>auto</b>, elle part après ce délai de silence. Le mot-clé utilise toujours ce délai.</div>
          </div>
        </div>
        <button class="btn" id="btn-voix-cfg" onclick="enregistrerVoix()">Enregistrer la voix</button>
      </div>
      <div id="cerveau-msg" class="cerveau-msg"></div>
    </div>

    <div class="chat" id="chat-zone">
      <div class="drop-overlay" id="drop-overlay">📎 Déposez le document — je le classe</div>
      <div id="chat-fil" class="chat-fil">
        <div class="msg assistant"><div class="bulle">Bonjour 👋 Je pilote toute la solution. Demandez-moi « où en sont les entreprises ? », déposez un document (je le range), ou cliquez sur 🎤 pour me parler. Pour toute action, je vous demanderai confirmation.</div></div>
      </div>
      <form id="chat-form" class="chat-saisie" onsubmit="return envoyerMessage(event)">
        <button class="btn ghost icone" type="button" id="btn-fichier" title="Déposer un document" onclick="document.getElementById('fichier-input').click()">📎</button>
        <button class="btn ghost icone" type="button" id="btn-micro" title="Parler à l'assistant" onclick="basculerMicro()">🎤</button>
        <input type="text" id="chat-input" placeholder="Écrivez, ou cliquez sur 🎤 pour parler…" autocomplete="off">
        <button class="btn" type="submit" id="chat-btn">Envoyer</button>
      </form>
      <input type="file" id="fichier-input" style="display:none" onchange="deposerFichier(this.files[0])">
    </div>

    <!-- Dossiers : documents rangés par projet et catégorie -->
    <div class="panel dossiers" id="panel-dossiers" style="margin-top:18px">
      <div class="dossiers-tete">
        <h3>📂 Dossiers</h3>
        <span class="liv-sub">Rangés automatiquement par l'assistant</span>
      </div>
      <div id="dossiers-corps" class="dossiers-corps"><span class="liv-sub">—</span></div>
    </div>
  </div>

  <!-- VUE FORGE (SPA intégrée — S19) -->
  <div class="view" id="vue-forge">
    <div class="topbar">
      <h2>Forge — agents IA, RAG, ventures (interface complète intégrée)</h2>
      <div style="display:flex;align-items:center;gap:12px">
        <span class="liv-sub">Connexion unique (realm Oria) — la première fois, l'écran de connexion s'ouvre dans Forge.</span>
        <a class="btn ghost" id="forge-open-tab" href="__FORGE_UI_URL__" target="_blank" rel="noopener">Ouvrir dans un onglet ↗</a>
      </div>
    </div>
    <div class="panel" style="padding:0;overflow:hidden">
      <iframe id="forge-iframe" title="Forge"
        style="width:100%;height:78vh;border:0;display:block;background:#0f1117"
        allow="clipboard-read; clipboard-write"></iframe>
    </div>
    <div class="liv-sub" style="margin-top:8px">
      Si l'écran de connexion ne s'affiche pas dans le cadre (politique anti-iframe de Keycloak),
      utilisez « Ouvrir dans un onglet ↗ » pour la première connexion : la session Oria est ensuite
      partagée, et le cadre se charge connecté.
    </div>
  </div>

  <!-- VUE CRÉATIONS — Hub des briques créatives (Studio 6060, Personnages 5900), migré d'Oria -->
  <div class="view" id="vue-creations">
    <!-- Grille de tuiles (état par défaut) -->
    <div id="creations-grille">
      <div class="topbar">
        <h2>Créations — les outils créatifs de Workplace, réunis ici</h2>
      </div>
      <div class="creations-tuiles">
        <button class="creation-tuile" onclick="ouvrirCreation('__STUDIO_UI_URL__', 'Studio audio-séries')">
          <span class="creation-emoji">🎬</span>
          <span class="creation-titre">Studio audio-séries</span>
          <span class="creation-desc">Écrire des séries, distribuer des voix, produire des épisodes audio.</span>
          <span class="creation-badge">Brique · port 6060</span>
        </button>
        <button class="creation-tuile" onclick="ouvrirCreation('__PERSONNAGES_UI_URL__', 'Atelier de personnages')">
          <span class="creation-emoji">🎭</span>
          <span class="creation-titre">Atelier de personnages</span>
          <span class="creation-desc">Générer un personnage holistique (numérologie, astro, traditions) ou retrouver les signes d'un caractère.</span>
          <span class="creation-badge">Brique · port 5900</span>
        </button>
        <button class="creation-tuile" onclick="ouvrirCreation('__TRANSCRIPTION_UI_URL__', 'Transcription · notes d\'appel')">
          <span class="creation-emoji">🎙️</span>
          <span class="creation-titre">Transcription &amp; notes d'appel</span>
          <span class="creation-desc">Capter un appel (façon Granola, sans bot) ou un mémo, transcrire en local, et ranger les notes en mémoire ou sur un drive.</span>
          <span class="creation-badge">Brique · port 5980</span>
        </button>
        <button class="creation-tuile creation-bientot" disabled>
          <span class="creation-emoji">🖼️</span>
          <span class="creation-titre">Images &amp; Vidéo</span>
          <span class="creation-desc">Génération d'images et de vidéo — brique à venir.</span>
          <span class="creation-badge creation-badge-bientot">Bientôt</span>
        </button>
      </div>
    </div>
    <!-- Cadre plein écran (au clic sur une tuile) -->
    <div id="creations-cadre" style="display:none">
      <div class="topbar">
        <button class="btn ghost" onclick="retourCreations()">← Créations</button>
        <div style="display:flex;align-items:center;gap:12px">
          <span id="creation-cadre-titre" style="font-size:0.85rem;color:#94a3b8"></span>
          <a class="btn ghost" id="creation-open-tab" href="#" target="_blank" rel="noopener">Ouvrir dans un onglet ↗</a>
        </div>
      </div>
      <div class="panel" style="padding:0;overflow:hidden">
        <iframe id="creation-iframe" title="Création"
          style="width:100%;height:78vh;border:0;display:block;background:#fff"
          allow="clipboard-read; clipboard-write; microphone; display-capture"></iframe>
      </div>
    </div>
  </div>

  <div class="view" id="vue-agenda">
    <div class="topbar">
      <h2>Agenda — tes rendez-vous (l'assistant les gère en langage naturel)</h2>
      <button class="btn" id="btn-agenda-add" onclick="nouvelEvenementViaAssistant()">+ Nouveau rendez-vous</button>
    </div>
    <div class="panel">
      <div id="agenda-corps" class="agenda-corps"><span class="liv-sub">Chargement…</span></div>
    </div>
  </div>

  <!-- VUE PROFIL -->
  <div class="view" id="vue-profil">
    <div class="topbar">
      <h2>Profil — ton contexte d'amorçage (sert à personnaliser l'assistant)</h2>
      <div style="display:flex;align-items:center;gap:12px">
        <span id="profil-etat" style="font-size:0.8rem;color:#64748b"></span>
        <button class="btn" id="btn-profil-save" onclick="sauverProfil()">Enregistrer</button>
      </div>
    </div>
    <!-- Fiche d'identité structurée (S48) : 5 champs → dérivations + thème astral -->
    <div class="panel" style="margin-bottom:16px">
      <div style="display:flex;align-items:center;gap:10px;margin-bottom:4px">
        <h3 style="margin:0;font-size:1rem">🪪 Te présenter — fiche d'identité</h3>
        <span style="font-size:0.78rem;color:#64748b">Ces champs nourrissent l'assistant et débloquent ta « fiche cosmique ».</span>
      </div>
      <div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:10px;margin-top:12px">
        <label style="font-size:0.78rem;color:#94a3b8">Prénom(s)
          <input id="id-prenoms" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px" placeholder="Toussaint Michel Rémi"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Nom
          <input id="id-nom" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px" placeholder="Garinat"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Date de naissance
          <input id="id-date" type="date" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Heure de naissance
          <input id="id-heure" type="time" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Lieu de naissance
          <input id="id-lieu" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px" placeholder="Toulouse"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Latitude
          <input id="id-lat" type="number" step="0.0001" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px" placeholder="43.6045"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Longitude (est +)
          <input id="id-lon" type="number" step="0.0001" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px" placeholder="1.4442"></label>
        <label style="font-size:0.78rem;color:#94a3b8">Décalage UTC à la naissance
          <input id="id-utc" type="number" step="0.5" style="width:100%;box-sizing:border-box;margin-top:4px;padding:8px 10px;border-radius:8px;border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px" placeholder="2"></label>
      </div>
      <div style="display:flex;align-items:center;gap:12px;margin-top:12px">
        <button class="btn" id="btn-id-save" onclick="sauverIdentite()">Calculer & enregistrer</button>
        <span id="id-etat" style="font-size:0.8rem;color:#64748b"></span>
      </div>
      <div id="id-derive" style="margin-top:16px"></div>
    </div>

    <div class="panel">
      <div style="font-size:0.82rem;color:#94a3b8;margin-bottom:8px">📝 Notes libres (Markdown) — nuances que les champs ne capturent pas.</div>
      <textarea id="profil-texte" spellcheck="false"
        style="width:100%;min-height:42vh;box-sizing:border-box;padding:16px;border-radius:10px;
               border:1px solid #2d3148;background:#0f1117;color:#e2e8f0;font-size:13px;line-height:1.55;
               font-family:ui-monospace,SFMono-Regular,Menlo,monospace;resize:vertical"
        placeholder="Chargement…"></textarea>
    </div>
  </div>
</main>

<!-- Panneau de détail d'une brique -->
<div class="modal-fond" id="modal-brique" style="display:none" onclick="if(event.target===this)fermerBrique()">
  <div class="modal-boite">
    <button class="modal-fermer" onclick="fermerBrique()">✕</button>
    <div id="modal-brique-corps"></div>
  </div>
</div>
<script>
const ROLES_LABELS = {
  memoire:'Mémoire', llm:'LLM', collaboration:'Collaboration',
  agents:'Agents', etl:'ETL', generateur:'Générateur', persistance:'Persistance',
  agenda:'Agenda'
};
let VUE = 'briques';

function switchVue(v) {
  VUE = v;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.vue === v));
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === 'vue-' + v));
  if (v === 'usine') chargerLivraisons();
  if (v === 'assistant') {
    setTimeout(() => document.getElementById('chat-input').focus(), 50);
    chargerCerveau(); majBoutonVoix(); brancherDragDrop(); chargerDossiers(); rafraichirPastilleRappels();
  }
  if (v === 'agenda') chargerAgenda();
  if (v === 'profil') chargerProfil();
  if (v === 'forge') chargerForge();
}

// ── Créations (Hub des briques créatives, migré d'Oria) ─────────────────────────
// Chargement paresseux : on ne pose le src de l'iframe qu'au clic sur une tuile, pour
// ne pas réveiller les briques tant que l'utilisateur n'ouvre pas un outil.
function ouvrirCreation(url, titre) {
  const f = document.getElementById('creation-iframe');
  if (f) f.src = url;
  document.getElementById('creation-cadre-titre').textContent = titre;
  document.getElementById('creation-open-tab').href = url;
  document.getElementById('creations-grille').style.display = 'none';
  document.getElementById('creations-cadre').style.display = 'block';
}
function retourCreations() {
  // On vide le src pour libérer la brique (et couper micro/audio éventuels).
  const f = document.getElementById('creation-iframe');
  if (f) f.src = 'about:blank';
  document.getElementById('creations-cadre').style.display = 'none';
  document.getElementById('creations-grille').style.display = 'block';
}

// ── Forge (SPA intégrée, S19) ───────────────────────────────────────────────────
// Chargement paresseux : on ne pose le src de l'iframe qu'au 1er affichage de l'onglet,
// pour ne pas déclencher le login Keycloak de Forge tant que l'utilisateur n'y va pas.
const FORGE_UI_URL = '__FORGE_UI_URL__';
let forgeCharge = false;
function chargerForge() {
  if (forgeCharge) return;
  const f = document.getElementById('forge-iframe');
  if (f) { f.src = FORGE_UI_URL; forgeCharge = true; }
}

// ── Profil ────────────────────────────────────────────────────────────────────
async function chargerProfil() {
  const etat = document.getElementById('profil-etat');
  const zone = document.getElementById('profil-texte');
  try {
    const d = await fetch('/profil').then(r => r.json());
    zone.value = d.contenu || '';
    etat.textContent = d.modifie ? 'Profil personnalisé (enregistré)' : 'Profil par défaut — non encore modifié';
  } catch (e) {
    etat.textContent = 'Erreur de chargement';
  }
  chargerIdentite();
}

// ── Fiche d'identité (S48) : 5 champs → dérivations + thème astral ──────────────
async function chargerIdentite() {
  try {
    const d = await fetch('/profil/identite').then(r => r.json());
    const f = d.fiche || {};
    const set = (id, v) => { document.getElementById(id).value = (v ?? ''); };
    set('id-prenoms', f.prenoms); set('id-nom', f.nom); set('id-date', f.date_naissance);
    set('id-heure', f.heure_naissance); set('id-lieu', f.lieu_naissance);
    set('id-lat', f.latitude); set('id-lon', f.longitude); set('id-utc', f.utc_offset);
    document.getElementById('id-etat').textContent =
      d.modifie ? 'Fiche enregistrée' : 'Fiche par défaut — modifie et enregistre';
    rendreDerive(d.derive || {});
  } catch (e) { /* silencieux */ }
}

async function sauverIdentite() {
  const btn = document.getElementById('btn-id-save');
  const etat = document.getElementById('id-etat');
  const val = id => document.getElementById(id).value.trim();
  const corps = {
    prenoms: val('id-prenoms'), nom: val('id-nom'), date_naissance: val('id-date'),
    heure_naissance: val('id-heure'), lieu_naissance: val('id-lieu'),
    latitude: val('id-lat'), longitude: val('id-lon'), utc_offset: val('id-utc'),
  };
  btn.classList.add('loading'); etat.textContent = 'Calcul…';
  try {
    const r = await fetch('/profil/identite', {
      method: 'PATCH', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(corps)
    }).then(r => r.json());
    etat.textContent = r.ok ? '✔ Enregistré — l\\'assistant te connaît mieux' : 'Échec';
    rendreDerive(r.derive || {});
  } catch (e) {
    etat.textContent = 'Erreur réseau';
  } finally {
    btn.classList.remove('loading');
  }
}

function rendreDerive(d) {
  const zone = document.getElementById('id-derive');
  if (!d || !Object.keys(d).length) { zone.innerHTML = ''; return; }
  const carte = (titre, corps) =>
    '<div style="background:#0f1117;border:1px solid #2d3148;border-radius:10px;padding:12px">' +
    '<div style="font-size:0.72rem;text-transform:uppercase;letter-spacing:.04em;color:#64748b;margin-bottom:6px">' +
    titre + '</div>' + corps + '</div>';
  const cards = [];

  if (d.age) cards.push(carte('Âge', '<b style="font-size:1.2rem">' + d.age.ans + ' ans</b>' +
    '<div style="font-size:0.8rem;color:#94a3b8">' + d.age.mois + ' mois, ' + d.age.jours + ' j' +
    (d.jour_naissance ? ' · né(e) un ' + d.jour_naissance : '') + '</div>'));
  if (d.anniversaire) cards.push(carte('Prochain anniversaire',
    (d.anniversaire.dans_jours === 0 ? '<b>Aujourd\\'hui 🎉</b>' :
      '<b>dans ' + d.anniversaire.dans_jours + ' j</b>') +
    '<div style="font-size:0.8rem;color:#94a3b8">' + d.anniversaire.date + ' · ' + d.anniversaire.ages + ' ans</div>'));
  if (d.signe_solaire) cards.push(carte('Signe solaire',
    '<b style="font-size:1.1rem">' + d.signe_solaire.symbole + ' ' + d.signe_solaire.nom + '</b>' +
    '<div style="font-size:0.8rem;color:#94a3b8">élément ' + d.signe_solaire.element + '</div>'));
  if (d.signe_chinois) cards.push(carte('Astrologie chinoise',
    '<b style="font-size:1.1rem">' + d.signe_chinois.emoji + ' ' + d.signe_chinois.animal + '</b>' +
    '<div style="font-size:0.8rem;color:#94a3b8">' + d.signe_chinois.element + ' · ' + d.signe_chinois.polarite + '</div>'));
  if (d.theme_astral) { const t = d.theme_astral; cards.push(carte('Thème astral (calculé)',
    '<div style="font-size:0.85rem;line-height:1.7">' +
    '☉ Soleil : <b>' + t.soleil.signe + '</b> ' + t.soleil.degre + '°<br>' +
    'AC Ascendant : <b>' + t.ascendant.signe + '</b> ' + t.ascendant.degre + '°<br>' +
    'MC Milieu du Ciel : <b>' + t.milieu_du_ciel.signe + '</b></div>')); }
  if (d.chemin_de_vie != null) cards.push(carte('Numérologie',
    '<b style="font-size:1.2rem">chemin de vie ' + d.chemin_de_vie + '</b>' +
    (d.numerologie_nom ? '<div style="font-size:0.8rem;color:#94a3b8">expression ' + d.numerologie_nom.expression +
      ' · âme ' + d.numerologie_nom.ame + ' · personnalité ' + d.numerologie_nom.personnalite + '</div>' : '')));
  if (d.biorythmes) { const b = d.biorythmes; const bar = (lbl, v) =>
    '<div style="display:flex;align-items:center;gap:6px;font-size:0.78rem"><span style="width:74px;color:#94a3b8">' + lbl +
    '</span><span style="flex:1;height:6px;background:#1e2336;border-radius:3px;overflow:hidden">' +
    '<span style="display:block;height:100%;width:' + Math.abs(v) + '%;background:' + (v >= 0 ? '#34d399' : '#f87171') + '"></span></span>' +
    '<span style="width:38px;text-align:right">' + v + '%</span></div>';
    cards.push(carte('Biorythmes du jour', bar('Physique', b.physique) + bar('Émotionnel', b.emotionnel) + bar('Intellectuel', b.intellectuel))); }
  if (d.jours_vecus) cards.push(carte('Jours vécus',
    '<b style="font-size:1.2rem">' + d.jours_vecus.jours.toLocaleString('fr-FR') + ' j</b>' +
    '<div style="font-size:0.8rem;color:#94a3b8">cap des ' + d.jours_vecus.prochain_jalon.toLocaleString('fr-FR') +
    ' j dans ' + d.jours_vecus.dans_jours + ' j</div>'));
  if (d.pierre_du_mois || d.generation) cards.push(carte('Repères',
    '<div style="font-size:0.82rem;line-height:1.7">' +
    (d.pierre_du_mois ? '💎 ' + d.pierre_du_mois + '<br>' : '') +
    (d.fleur_du_mois ? '🌸 ' + d.fleur_du_mois + '<br>' : '') +
    (d.saison ? '🍂 né(e) en ' + d.saison + '<br>' : '') +
    (d.generation ? '👥 ' + d.generation : '') + '</div>'));

  zone.innerHTML =
    '<div style="display:grid;grid-template-columns:repeat(auto-fill,minmax(190px,1fr));gap:10px">' +
    cards.join('') + '</div>' +
    '<div style="font-size:0.72rem;color:#64748b;margin-top:10px">' +
    'Astrologie & numérologie = divertissement (pas un fait). Lune et planètes à venir (calcul éphéméride).</div>';
}
async function sauverProfil() {
  const btn = document.getElementById('btn-profil-save');
  const etat = document.getElementById('profil-etat');
  const contenu = document.getElementById('profil-texte').value;
  btn.classList.add('loading'); etat.textContent = 'Enregistrement…';
  try {
    const r = await fetch('/profil', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ contenu })
    }).then(r => r.json());
    etat.textContent = r.ok ? '✔ Enregistré (' + r.taille + ' caractères)' : 'Échec de l\\'enregistrement';
  } catch (e) {
    etat.textContent = 'Erreur réseau';
  } finally {
    btn.classList.remove('loading');
  }
}

// ── Agenda ──────────────────────────────────────────────────────────────────
const JOURS = ['dimanche','lundi','mardi','mercredi','jeudi','vendredi','samedi'];
const MOIS = ['janv.','févr.','mars','avr.','mai','juin','juil.','août','sept.','oct.','nov.','déc.'];
function fmtHeure(iso) { const d = new Date(iso); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'); }
function cleJour(iso) { const d = new Date(iso); return JOURS[d.getDay()]+' '+d.getDate()+' '+MOIS[d.getMonth()]; }
async function chargerAgenda() {
  const corps = document.getElementById('agenda-corps');
  if (!corps) return;
  const debut = new Date().toISOString();
  try {
    const r = await fetch('/agenda/evenements?debut=' + encodeURIComponent(debut));
    const evts = (await r.json()).evenements || [];
    if (!evts.length) { corps.innerHTML = '<span class="liv-sub">Aucun rendez-vous à venir. Demandez à l\\'assistant « ajoute un rendez-vous demain 14h ».</span>'; return; }
    evts.sort((a,b) => new Date(a.start_at) - new Date(b.start_at));
    let html = '', jourCourant = null;
    for (const e of evts) {
      const j = cleJour(e.start_at);
      if (j !== jourCourant) { jourCourant = j; html += `<div class="agenda-jour">${j}</div>`; }
      html += `<div class="agenda-evt">
        <span class="agenda-heure">${fmtHeure(e.start_at)}–${fmtHeure(e.end_at)}</span>
        <span class="agenda-titre">${escHtml(e.title)}</span>
        ${e.location ? `<span class="agenda-lieu">📍 ${escHtml(e.location)}</span>` : ''}
      </div>`;
    }
    corps.innerHTML = html;
  } catch(e) { corps.innerHTML = '<span class="liv-sub">Agenda indisponible : ' + e.message + '</span>'; }
}
function nouvelEvenementViaAssistant() {
  switchVue('assistant');
  const input = document.getElementById('chat-input');
  input.value = 'Ajoute un rendez-vous '; input.focus();
}

// ── Rappels proactifs ───────────────────────────────────────────────────────
async function rafraichirPastilleRappels() {
  try {
    const d = await fetch('/assistant/rappels?non_lus=true').then(r => r.json());
    const p = document.getElementById('rappels-pastille');
    if (!p) return;
    if (d.non_lus > 0) { p.textContent = d.non_lus; p.style.display = 'inline-block'; }
    else p.style.display = 'none';
  } catch(e) {}
}
function basculerRappels() {
  const p = document.getElementById('panel-rappels');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') chargerRappels();
}
async function chargerRappels() {
  const corps = document.getElementById('rappels-corps');
  try {
    const d = await fetch('/assistant/rappels').then(r => r.json());
    const rs = d.rappels || [];
    if (!rs.length) { corps.innerHTML = '<span class="liv-sub">Aucun rappel pour le moment.</span>'; return; }
    corps.innerHTML = rs.map(r => `
      <div class="rappel ${r.vu ? 'vu' : ''}">
        <div class="rappel-txt"><b>${escHtml(r.titre)}</b>${r.corps ? '<br><span class="liv-sub" style="white-space:pre-wrap">'+escHtml(r.corps)+'</span>' : ''}</div>
        <div class="rappel-actions">
          <button class="btn ghost" onclick='parlerRappel(${JSON.stringify(r.titre)})'>En parler</button>
          ${r.vu ? '' : `<button class="btn ghost" onclick="marquerRappelVu('${r.id}')">Vu</button>`}
        </div>
      </div>`).join('');
  } catch(e) { corps.innerHTML = '<span class="liv-sub">Rappels indisponibles.</span>'; }
}
async function marquerRappelVu(id) {
  await fetch('/assistant/rappels/' + id + '/vu', { method:'POST' });
  chargerRappels(); rafraichirPastilleRappels();
}
function parlerRappel(titre) {
  basculerRappels(); switchVue('assistant');
  const input = document.getElementById('chat-input');
  input.value = titre; input.focus();
}

// ── Cerveau de l'assistant (modèle + clé OpenRouter) ────────────────────────
let CERVEAU_CHARGE = false;
function toggleCerveau() {
  const p = document.getElementById('panel-cerveau');
  p.style.display = p.style.display === 'none' ? 'block' : 'none';
  if (p.style.display === 'block') chargerCerveau(true);
}
function pill(el, ok, texte) {
  el.textContent = texte;
  el.classList.remove('ok','ko');
  if (ok === true) el.classList.add('ok'); else if (ok === false) el.classList.add('ko');
}
function cerveauMsg(texte, type) {
  const m = document.getElementById('cerveau-msg');
  m.className = 'cerveau-msg ' + (type || 'info');
  m.textContent = texte || '';
}
async function chargerCerveau(force) {
  if (CERVEAU_CHARGE && !force) return;
  try {
    const c = await fetch('/assistant/config').then(r => r.json());
    const sel = document.getElementById('cerveau-model');
    const dispo = c.modeles_disponibles || [];
    const liste = dispo.length ? dispo : (c.model ? [c.model] : []);
    // Option « cascade pure » (aucune tête) en haut, puis les modèles servis.
    const optCascade = `<option value=""${!c.model?' selected':''}>⚡ Cascade auto (gratuits → repli payant)</option>`;
    sel.innerHTML = optCascade + liste.map(m => `<option value="${m}"${m===c.model?' selected':''}>${m}</option>`).join('');
    // Case cascade + description de la chaîne réellement essayée.
    const cb = document.getElementById('cerveau-cascade');
    if (cb) cb.checked = !!c.cascade_auto;
    // Muscle déporté (brique calcul) : toggle + état live des nœuds.
    const cbM = document.getElementById('cerveau-muscle');
    if (cbM) cbM.checked = !!c.muscle_actif;
    majMuscleNoeuds();
    const chaine = c.chaine_effective || [];
    const desc = document.getElementById('cascade-desc');
    if (desc && chaine.length) desc.textContent = 'Ordre essayé : ' + chaine.join('  →  ');
    pill(document.getElementById('cerveau-etat'), null,
         c.cascade_auto ? 'cascade : ' + (chaine[0] || '—') : 'modèle : ' + (c.model || '—'));
    // Persona : peupler le sélecteur + statut.
    const selP = document.getElementById('cerveau-persona');
    if (selP) {
      const ps = c.personas || [];
      selP.innerHTML = ps.map(p => `<option value="${p.cle}"${p.cle===c.persona?' selected':''}>${p.emoji||''} ${p.label}</option>`).join('');
      majDescPersona(ps);
      selP.onchange = () => majDescPersona(ps);
      const actuel = ps.find(p => p.cle === c.persona);
      pill(document.getElementById('persona-statut'), c.persona !== 'default' ? null : true,
           (actuel ? (actuel.emoji + ' ' + actuel.label) : c.persona));
    }
    // Langue (S39) : peupler le sélecteur + régler la locale de la voix.
    const selL = document.getElementById('cerveau-langue');
    if (selL) {
      const ls = c.langues || [];
      selL.innerHTML = ls.map(l => `<option value="${l.code}"${l.code===c.langue?' selected':''}>${l.label}</option>`).join('');
      const actuelle = ls.find(l => l.code === c.langue);
      if (actuelle) VOIX_LOCALE = actuelle.locale_voix;
      pill(document.getElementById('langue-statut'), c.langue !== 'fr' ? null : true,
           actuelle ? actuelle.label : (c.langue || 'fr'));
    }
    pill(document.getElementById('cle-statut'),
         c.cle_openrouter_definie ? true : false,
         c.cle_openrouter_definie ? '● définie' : '● absente');
    // Voix : provider + URL Unmute, puis (re)construction du fournisseur.
    const selV = document.getElementById('cerveau-voix');
    if (selV) {
      selV.value = c.voix_provider || 'webspeech';
      document.getElementById('cerveau-unmute-url').value = c.unmute_url || '';
      document.getElementById('cerveau-wakeword-url').value = c.wakeword_url || '';
      // Fin de parole : globals + contrôles (radio mode + délai de silence en secondes).
      VOIX_FIN_MODE = c.voix_fin_mode === 'appui' ? 'appui' : 'silence';
      VOIX_SILENCE_MS = c.voix_silence_ms || 5000;
      const rFin = document.querySelector('input[name="voix-fin"][value="' + VOIX_FIN_MODE + '"]');
      if (rFin) rFin.checked = true;
      document.getElementById('cerveau-silence').value = (VOIX_SILENCE_MS / 1000);
      majVoixFin();
      majVisibiliteUnmute();
      pill(document.getElementById('voix-statut'),
           c.voix_provider === 'webspeech' ? true : null,
           c.voix_provider === 'unmute' ? '● Unmute'
             : c.voix_provider === 'wakeword' ? '● mot-clé' : '● navigateur');
      construireVoix(c.voix_provider, c.unmute_url, c.wakeword_url);
    }
    CERVEAU_CHARGE = true;
  } catch(e) { cerveauMsg('Impossible de charger la config : ' + e.message, 'ko'); }
}
function majVisibiliteUnmute() {
  const sel = document.getElementById('cerveau-voix');
  const u = document.getElementById('cerveau-unmute-url');
  const w = document.getElementById('cerveau-wakeword-url');
  if (sel && u) u.style.display = sel.value === 'unmute' ? 'block' : 'none';
  if (sel && w) w.style.display = sel.value === 'wakeword' ? 'block' : 'none';
  // Fin de parole : pertinente pour le navigateur et le mot-clé (qui utilisent la reco
  // navigateur) ; Unmute gère son propre full-duplex.
  const fin = document.getElementById('voix-fin-bloc');
  if (sel && fin) fin.style.display = sel.value === 'unmute' ? 'none' : 'block';
}
// Fin de parole : applique le mode choisi (effet immédiat) + montre le champ délai en 'silence'.
function majVoixFin() {
  const r = document.querySelector('input[name="voix-fin"]:checked');
  VOIX_FIN_MODE = r ? r.value : 'silence';
  const champ = document.getElementById('voix-silence-champ');
  if (champ) champ.style.display = VOIX_FIN_MODE === 'silence' ? 'inline' : 'none';
  const s = parseFloat(document.getElementById('cerveau-silence').value);
  if (!isNaN(s)) VOIX_SILENCE_MS = Math.round(s * 1000);
}
async function enregistrerVoix() {
  const btn = document.getElementById('btn-voix-cfg');
  const provider = document.getElementById('cerveau-voix').value;
  const unmute_url = document.getElementById('cerveau-unmute-url').value.trim();
  const wakeword_url = document.getElementById('cerveau-wakeword-url').value.trim();
  if (provider === 'unmute' && !unmute_url) { cerveauMsg('Donne l\\'URL du serveur Unmute (wss://…/v1/realtime).', 'ko'); return; }
  if (provider === 'wakeword' && !wakeword_url) { cerveauMsg('Donne l\\'URL de la brique ecoute (ws://…/ecoute).', 'ko'); return; }
  const finR = document.querySelector('input[name="voix-fin"]:checked');
  const voix_fin_mode = finR ? finR.value : 'silence';
  const sSil = parseFloat(document.getElementById('cerveau-silence').value);
  const voix_silence_ms = isNaN(sSil) ? 5000 : Math.round(sSil * 1000);
  btn.classList.add('loading');
  try {
    const r = await fetch('/assistant/voix', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ voix_provider: provider, unmute_url, wakeword_url, voix_fin_mode, voix_silence_ms })
    }).then(r => r.json());
    VOIX_FIN_MODE = r.voix_fin_mode || 'silence';
    VOIX_SILENCE_MS = r.voix_silence_ms || 5000;
    construireVoix(r.voix_provider, r.unmute_url, r.wakeword_url);
    pill(document.getElementById('voix-statut'),
         r.voix_provider === 'webspeech' ? true : null,
         r.voix_provider === 'unmute' ? '● Unmute'
           : r.voix_provider === 'wakeword' ? '● mot-clé' : '● navigateur');
    const fin = r.voix_fin_mode === 'silence'
      ? 'fin auto après ' + (r.voix_silence_ms/1000) + ' s de silence'
      : 'tu termines en recliquant 🎤';
    const msg = { unmute: '✔ Voix réglée sur Unmute (' + (r.unmute_url||'') + '). Lance la stack outils/unmute/ côté GPU.',
                  wakeword: '✔ Mot-clé activé (' + (r.wakeword_url||'') + ', ' + fin + '). Lance la brique ecoute, puis 🎙 pour mettre le micro en veille.',
                  webspeech: '✔ Voix réglée sur le navigateur (Web Speech, ' + fin + ').' };
    cerveauMsg(msg[r.voix_provider] || msg.webspeech, 'ok');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}
function majDescPersona(ps) {
  const sel = document.getElementById('cerveau-persona');
  const p = (ps || []).find(x => x.cle === sel.value);
  document.getElementById('persona-desc').textContent = p ? p.description : 'Le ton et la façon de répondre de l\\'assistant.';
}
async function enregistrerPersona() {
  const btn = document.getElementById('btn-persona');
  const persona = document.getElementById('cerveau-persona').value;
  btn.classList.add('loading');
  try {
    const r = await fetch('/assistant/persona', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ persona })
    }).then(r => r.json());
    pill(document.getElementById('persona-statut'), r.persona !== 'default' ? null : true, r.persona);
    cerveauMsg('✔ Personnalité « ' + r.persona + ' » active dès le prochain message.', 'ok');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}
async function enregistrerLangue() {
  const btn = document.getElementById('btn-langue');
  const langue = document.getElementById('cerveau-langue').value;
  btn.classList.add('loading');
  try {
    const r = await fetch('/assistant/langue', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ langue })
    }).then(r => r.json());
    VOIX_LOCALE = r.locale_voix || 'fr-FR';  // la voix suit immédiatement (sans recharger)
    const opt = document.querySelector('#cerveau-langue option[value="' + r.langue + '"]');
    pill(document.getElementById('langue-statut'), r.langue !== 'fr' ? null : true,
         opt ? opt.textContent : r.langue);
    cerveauMsg('✔ Langue « ' + (opt ? opt.textContent : r.langue) + ' » active : réponses et voix.', 'ok');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}
async function enregistrerModele() {
  const btn = document.getElementById('btn-model');
  const model = document.getElementById('cerveau-model').value;  // "" = cascade pure
  const label = model || 'cascade auto';
  btn.classList.add('loading'); cerveauMsg('Test de « ' + label + ' »…', 'info');
  try {
    const r = await fetch('/assistant/config', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ model })
    }).then(r => r.json());
    await chargerCerveau(true);
    if (r.ok) cerveauMsg('✔ Tête « ' + (r.tete||label) + ' » active : ' + r.detail, 'ok');
    else cerveauMsg('⚠ Enregistré mais la tête ne répond pas : ' + r.detail, 'ko');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}
async function enregistrerCascade() {
  const actif = document.getElementById('cerveau-cascade').checked;
  cerveauMsg('Mise à jour de la cascade…', 'info');
  try {
    const r = await fetch('/assistant/config', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ cascade_auto: actif })
    }).then(r => r.json());
    await chargerCerveau(true);
    cerveauMsg(actif ? '✔ Cascade auto activée (gratuits d\\'abord).' : '✔ Cascade désactivée (modèle + repli manuel).', 'ok');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
}
async function majMuscleNoeuds() {
  const el = document.getElementById('muscle-noeuds');
  if (!el) return;
  try {
    const m = await fetch('/assistant/muscle').then(r => r.json());
    if (!m.brique_joignable) { el.textContent = '◌ Brique calcul injoignable (port 5990).'; return; }
    const ns = m.noeuds || [];
    if (!ns.length) { el.textContent = 'Aucun nœud déclaré (variable CALCUL_NOEUDS).'; return; }
    const icone = e => e === 'eveille' ? '🟢' : e === 'endormi' ? '🌙' : e === 'injoignable' ? '🔴' : '⚪';
    el.innerHTML = ns.map(n => icone(n.etat) + ' ' + (n.nom || n.id) + ' — ' + n.etat
      + (n.modele_gateway ? ' <span style="opacity:.7">(' + n.modele_gateway + ')</span>' : '')).join('<br>');
  } catch(e) { el.textContent = 'État des nœuds indisponible.'; }
}
async function enregistrerMuscle() {
  const actif = document.getElementById('cerveau-muscle').checked;
  cerveauMsg('Mise à jour du muscle déporté…', 'info');
  try {
    const r = await fetch('/assistant/muscle', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ actif })
    }).then(r => r.json());
    await majMuscleNoeuds();
    cerveauMsg(r.muscle_actif ? '✔ Muscle déporté activé : un nœud prêt passe en tête de cascade.'
                              : '✔ Muscle déporté désactivé (cascade habituelle).', 'ok');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
}
async function enregistrerCle() {
  const btn = document.getElementById('btn-cle');
  const cle = document.getElementById('cerveau-cle').value.trim();
  if (!cle) { cerveauMsg('Saisis une clé OpenRouter (sk-or-…).', 'ko'); return; }
  btn.classList.add('loading');
  cerveauMsg('Enregistrement, redémarrage de la Gateway puis test… (~15 s)', 'info');
  try {
    const r = await fetch('/assistant/cle-openrouter', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ cle })
    }).then(r => r.json());
    pill(document.getElementById('cle-statut'),
         r.cle_openrouter_definie ? true : false,
         r.cle_openrouter_definie ? '● définie' : '● absente');
    if (r.ok) { cerveauMsg('✔ Clé valide, la Gateway a redémarré : ' + r.detail, 'ok');
                document.getElementById('cerveau-cle').value = ''; }
    else cerveauMsg('⚠ Échec à l\\'étape « ' + r.etape + ' » : ' + r.detail, 'ko');
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
  btn.classList.remove('loading');
}

async function charger() {
  const btn = document.getElementById('refresh-btn');
  btn.classList.add('loading');
  try {
    const [bData, sData] = await Promise.all([
      fetch('/briques').then(r => r.json()),
      fetch('/sante-globale').then(r => r.json()).catch(() => ({briques:{}}))
    ]);
    document.getElementById('nb-briques').textContent = bData.total;
    document.getElementById('last-check').textContent =
      'Mis à jour ' + new Date().toLocaleTimeString('fr-FR');
    const groupes = document.getElementById('groupes-briques');
    groupes.innerHTML = '';
    BRIQUES_MAP = {};
    // On répartit les briques par couche : frontend (interface utilisateur) /
    // backend (service API pur). Toute couche inconnue retombe sur « backend ».
    const parCouche = { frontend: [], backend: [] };
    (bData.briques || []).forEach(b => {
      const h = (sData.briques || {})[b.nom] || {};
      BRIQUES_MAP[b.nom] = { b, h };   // mémorisé pour le panneau de détail
      const couche = b.couche === 'frontend' ? 'frontend' : 'backend';
      parCouche[couche].push({ b, h });
    });
    [['frontend', 'Frontend'], ['backend', 'Backend']].forEach(([cle, titre]) => {
      const items = parCouche[cle];
      if (!items.length) return;
      const cartes = items.map(({ b, h }) => carteHTML(b, h)).join('');
      groupes.insertAdjacentHTML('beforeend',
        `<div class="groupe-couche"><h3 class="groupe-titre">${titre}` +
        `<span class="groupe-compteur">${items.length}</span></h3>` +
        `<div class="grid">${cartes}</div></div>`);
    });
  } catch(e) {
    console.error(e);
  }
  btn.classList.remove('loading');
}

// ── Usine ──────────────────────────────────────────────────────────────────
const ETAPES_LABELS = { ingestion:'Ingestion', audit:'Audit', generation:'Génération', packaging:'Packaging' };

async function lancerLivraison(e) {
  e.preventDefault();
  const form = document.getElementById('form-livrer');
  const btn = document.getElementById('btn-livrer');
  const fd = new FormData(form);
  // Les cases non cochées sont absentes du FormData → on force false.
  fd.set('messagerie', form.messagerie.checked ? 'true' : 'false');
  fd.set('packager', form.packager.checked ? 'true' : 'false');
  if (!form.fichiers.files.length) fd.delete('fichiers');
  btn.classList.add('loading'); btn.textContent = 'Livraison lancée…';
  try {
    const r = await fetch('/usine/livrer', { method: 'POST', body: fd });
    if (!r.ok) throw new Error(await r.text());
    form.reset();
    await chargerLivraisons();
  } catch(err) {
    alert('Échec : ' + err.message);
  }
  btn.classList.remove('loading'); btn.textContent = 'Livrer';
  return false;
}

async function chargerLivraisons() {
  try {
    const data = await fetch('/usine/livraisons').then(r => r.json());
    document.getElementById('usine-check').textContent =
      'Mis à jour ' + new Date().toLocaleTimeString('fr-FR');
    const box = document.getElementById('livraisons');
    if (!data.livraisons.length) {
      box.innerHTML = '<div class="empty">Aucune livraison pour l\\'instant. Lancez-en une ci-dessus.</div>';
      return;
    }
    box.innerHTML = data.livraisons.map(livraisonHTML).join('');
  } catch(e) { console.error(e); }
}

function livraisonHTML(l) {
  const etapes = (l.etapes || []).map(e => {
    const cls = e.statut || 'en_attente';
    return `<div class="step ${cls}">
      <div class="step-nom"><span class="step-dot"></span>${ETAPES_LABELS[e.etape] || e.etape}</div>
      <div class="step-msg">${e.message || ''}</div>
    </div>`;
  }).join('');
  let links = '';
  if (l.statut === 'livree' && l.url_apercu) {
    links = `<div class="liv-links">
      <a href="${l.url_apercu}" target="_blank">Aperçu de l'app ↗</a>
      <a href="${l.url_html}" target="_blank">Télécharger le HTML</a>
      <button class="btn ghost" onclick="decrocher('${l.id}')">Décrocher · mettre de côté</button>
    </div>`;
  } else if (l.statut === 'decrochee') {
    links = `<div class="liv-links">
      <span class="liv-sub" style="margin:0">📦 ${l.dossier || 'dossier portable'}</span>
      <button class="btn" onclick="reprendre('${l.id}')">Reprendre pour modifier</button>
    </div>`;
  }
  const err = l.statut === 'erreur' && l.erreur ? `<div class="liv-err-msg">⚠ ${l.erreur}</div>` : '';
  const modeChip = l.mode === 'hebergee' ? 'hébergée' : 'autonome';
  const extra = [modeChip, l.messagerie ? 'messagerie' : null, l.packager ? 'bundle' : null]
    .filter(Boolean).join(' · ');
  // Une entreprise « de côté » n'affiche pas les pastilles d'étapes (elle n'est plus en pipeline).
  const steps = l.statut === 'decrochee' ? '' : `<div class="steps">${etapes}</div>`;
  return `<div class="liv-card">
    <div class="liv-head">
      <div>
        <div class="liv-title">${l.nom_entreprise || 'Entreprise'}</div>
        <div class="liv-sub">${extra} · ${new Date(l.date_creation).toLocaleString('fr-FR')}</div>
      </div>
      <span class="liv-statut liv-${l.statut}">${ {en_cours:'En cours', livree:'Livrée', erreur:'Erreur', decrochee:'De côté'}[l.statut] || l.statut }</span>
    </div>
    ${steps}
    ${err}${links}
  </div>`;
}

async function decrocher(id) {
  if (!confirm('Décrocher cette entreprise ? Son état est rassemblé dans un dossier portable, puis retiré de la solution principale.')) return;
  try {
    const r = await fetch('/usine/livraisons/' + id + '/decrocher', { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    await chargerLivraisons();
  } catch(err) { alert('Échec du décrochage : ' + err.message); }
}

async function reprendre(id) {
  try {
    const r = await fetch('/usine/livraisons/' + id + '/reprendre', { method: 'POST' });
    if (!r.ok) throw new Error(await r.text());
    await chargerLivraisons();
  } catch(err) { alert('Échec de la reprise : ' + err.message); }
}

// ── Assistant ───────────────────────────────────────────────────────────────
const CHAT_HIST = [];
const LABELS_OUTILS = {
  lister_entreprises:'consulte les entreprises', details_entreprise:'consulte le détail',
  etat_briques:'vérifie les briques', livrer_entreprise:'lance une livraison',
  decrocher_entreprise:'décroche une entreprise', reprendre_entreprise:'reprend une entreprise',
  chercher_documents:'cherche dans les documents', lire_document:'lit un document',
  lister_dossiers:'consulte les dossiers', classer_document:'range un document',
  ingerer_document:'ingère un document', memoire_rappeler:'consulte la mémoire',
  memoire_retenir:'mémorise', lister_apps:'consulte les apps', consulter_donnees:'consulte les données'
};
function chatEcho(t) { const el = document.getElementById('chat-fil'); el.scrollTop = el.scrollHeight; return t; }
function ajouterBulle(role, texte) {
  const fil = document.getElementById('chat-fil');
  const d = document.createElement('div');
  d.className = 'msg ' + role;
  d.innerHTML = '<div class="bulle"></div>';
  d.querySelector('.bulle').textContent = texte;
  fil.appendChild(d); chatEcho();
  return d.querySelector('.bulle');
}
function ajouterOutil(nom, action, confirmation) {
  const fil = document.getElementById('chat-fil');
  const d = document.createElement('div');
  d.className = 'outil' + (confirmation ? ' confirm' : action ? ' action' : '');
  d.innerHTML = '<span class="pic"></span>';
  const span = document.createElement('span');
  span.textContent = (LABELS_OUTILS[nom] || nom) + (confirmation ? ' — confirmation requise' : '');
  d.appendChild(span);
  fil.appendChild(d); chatEcho();
}
async function envoyerMessage(e) {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const texte = input.value.trim();
  if (!texte) return false;
  input.value = '';
  document.getElementById('chat-btn').classList.add('loading');
  ajouterBulle('user', texte);
  CHAT_HIST.push({ role:'user', content: texte });

  const fil = document.getElementById('chat-fil');
  const tip = document.createElement('div');
  tip.className = 'typing'; tip.textContent = 'L\\'assistant réfléchit…';
  fil.appendChild(tip); chatEcho();

  let bulleAssist = null, texteFinal = '';
  try {
    const r = await fetch('/assistant/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ messages: CHAT_HIST })
    });
    const reader = r.body.getReader();
    const dec = new TextDecoder();
    let tampon = '';
    while (true) {
      const { value, done } = await reader.read();
      if (done) break;
      tampon += dec.decode(value, { stream:true });
      const lignes = tampon.split('\\n\\n');
      tampon = lignes.pop();
      for (const ligne of lignes) {
        const m = ligne.match(/^data: (.*)$/s);
        if (!m) continue;
        const evt = JSON.parse(m[1]);
        if (evt.type === 'outil') { ajouterOutil(evt.nom, evt.action, false); }
        else if (evt.type === 'resultat_outil') { if (evt.confirmation) ajouterOutil(evt.nom, true, true); }
        else if (evt.type === 'texte_delta' && evt.contenu) {   // S60 : tokens au fil de l'eau
          if (!bulleAssist) { tip.remove(); bulleAssist = ajouterBulle('assistant', ''); }
          texteFinal += evt.contenu; bulleAssist.textContent = texteFinal; chatEcho();
        }
        else if (evt.type === 'texte' && evt.contenu) {
          if (!bulleAssist) { tip.remove(); bulleAssist = ajouterBulle('assistant', ''); }
          texteFinal = evt.contenu; bulleAssist.textContent = evt.contenu; chatEcho();
        }
        else if (evt.type === 'erreur') {
          tip.remove(); ajouterBulle('assistant', '⚠ ' + evt.contenu);
        }
      }
    }
  } catch(err) {
    ajouterBulle('assistant', '⚠ Erreur de connexion : ' + err.message);
  } finally {
    if (document.body.contains(tip)) tip.remove();
    document.getElementById('chat-btn').classList.remove('loading');
    if (texteFinal) {
      CHAT_HIST.push({ role:'assistant', content: texteFinal });
      if (LECTURE_VOCALE) VOIX.parler(texteFinal);   // lit la réponse à voix haute
    }
    // Une action a pu changer l'état → rafraîchir tableau usine + dossiers en arrière-plan.
    chargerLivraisons().catch(()=>{});
    chargerDossiers().catch(()=>{});
  }
  return false;
}

// ── Voix temps réel (fournisseur abstrait : navigateur aujourd'hui, Kyutai Unmute demain) ──
// Une seule UI, deux fournisseurs. Le choix vient de la CONFIG (panneau ⚙ Cerveau,
// persistée côté serveur) : passer de 'webspeech' à 'unmute' est une simple config.
let VOIX_PROVIDER = 'webspeech';
let UNMUTE_URL = '';
let WAKEWORD_URL = '';
// Langue de la voix (S39) : locale BCP-47 pour reco.lang/utt.lang + choix de la voix.
// Pilotée par la config (⚙ Cerveau) ; défaut français. 'fr-FR' → préfixe 'fr'.
let VOIX_LOCALE = 'fr-FR';
let LECTURE_VOCALE = localStorage.getItem('wp_lecture_vocale') === '1';
let MICRO_ACTIF = false;
// Fin du tour de parole en voix navigateur (réglés depuis ⚙ Cerveau, persistés serveur) :
// 'silence' = envoi auto après VOIX_SILENCE_MS de silence (mains-libres, défaut 5 s) ;
// 'appui' = micro à l'écoute à travers les pauses, envoi au prochain clic 🎤.
let VOIX_FIN_MODE = 'silence';
let VOIX_SILENCE_MS = 5000;

// Fournisseur navigateur : reconnaissance (SpeechRecognition) + synthèse (speechSynthesis).
// opts.silenceForce = toujours finir au silence (capture du mot-clé, pas de second clic).
function creerWebSpeech(opts) {
  opts = opts || {};
  const Reco = window.SpeechRecognition || window.webkitSpeechRecognition;
  let reco = null, cbTexte = null, minuteur = null, texteCourant = '', fini = false;
  const mode = () => opts.silenceForce ? 'silence' : VOIX_FIN_MODE;
  const delaiMs = () => Math.max(800, VOIX_SILENCE_MS || 5000);
  // Livre le texte accumulé une seule fois (anti double-envoi : silence + arrêt + onend).
  function livrer() {
    clearTimeout(minuteur);
    if (fini) return;
    fini = true;
    if (cbTexte) cbTexte(texteCourant.trim());
  }
  return {
    supporteEcoute: !!Reco,
    supporteParole: 'speechSynthesis' in window,
    demarrer() {
      if (!Reco) { alert("La reconnaissance vocale n'est pas supportée par ce navigateur (essayez Chrome, Edge ou Safari)."); return false; }
      window.speechSynthesis && window.speechSynthesis.cancel();  // barge-in : on coupe la lecture
      reco = new Reco();
      // continuous = true : on N'écoute PAS jusqu'à la 1ʳᵉ pause (qui coupait la parole),
      // c'est NOUS qui décidons de la fin (clic ou minuteur de silence).
      reco.lang = VOIX_LOCALE; reco.interimResults = true; reco.continuous = true;
      texteCourant = ''; fini = false;
      reco.onresult = (e) => {
        texteCourant = Array.from(e.results).map(r => r[0].transcript).join('');
        document.getElementById('chat-input').value = texteCourant;
        if (mode() === 'silence') {                 // on (re)arme le minuteur à chaque mot
          clearTimeout(minuteur);
          minuteur = setTimeout(livrer, delaiMs());
        }
      };
      reco.onerror = () => arreterMicro();
      reco.onend = () => { if (MICRO_ACTIF) arreterMicro(); };
      reco.start();
      return true;
    },
    arreter() {
      clearTimeout(minuteur);
      if (reco) { try { reco.stop(); } catch(e){} reco = null; }
      if (mode() === 'appui') livrer();             // appui = l'utilisateur termine son tour
    },
    onTexte(cb) { cbTexte = cb; },
    parler(texte) {
      if (!('speechSynthesis' in window) || !texte) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(texte);
      u.lang = VOIX_LOCALE; u.rate = 1.05;
      const pref = VOIX_LOCALE.slice(0, 2);
      const vf = window.speechSynthesis.getVoices().find(v => v.lang && v.lang.startsWith(pref));
      if (vf) u.voice = vf;
      window.speechSynthesis.speak(u);
    },
    stop() { window.speechSynthesis && window.speechSynthesis.cancel(); }
  };
}

// Fournisseur Kyutai Unmute (full-duplex) — serveur distant à GPU pointé sur notre Gateway.
// Protocole calqué sur l'API Realtime d'OpenAI (cf. docs/browser_backend_communication.md
// d'Unmute) : WS sur /v1/realtime (sous-protocole « realtime »), session.update d'abord,
// puis input_audio_buffer.append (audio Opus 24 kHz mono base64) ; le serveur renvoie
// response.text.delta / response.audio.delta / transcription. Audio Opus via WebCodecs.
// NB : Unmute EST le cerveau (il utilise notre LLM via KYUTAI_LLM_URL) mais ne passe PAS
// par la boucle à outils de l'assistant → mode « conversation/brainstorming » à voix.
// À VALIDER avec un vrai serveur (impossible sans GPU ici) ; structurellement conforme.
// Consigne Unmute localisée (S39) : choisie selon VOIX_LOCALE au moment de l'ouverture WS.
const UNMUTE_INSTRUCTIONS_PAR_LANGUE = {
  fr: "Tu es l'assistant de Workplace. Réponds en français, de façon concise, pour aider à réfléchir et préparer le travail.",
  en: "You are the Workplace assistant. Answer in English, concisely, to help think through and prepare the work.",
  es: "Eres el asistente de Workplace. Responde en español, de forma concisa, para ayudar a reflexionar y preparar el trabajo."
};
function instructionsUnmute() {
  return UNMUTE_INSTRUCTIONS_PAR_LANGUE[VOIX_LOCALE.slice(0, 2)] || UNMUTE_INSTRUCTIONS_PAR_LANGUE.fr;
}
function creerUnmute(url) {
  let ws = null, ctx = null, micFlux = null, worklet = null, enc = null, dec = null, bulle = null;
  const okWebCodecs = ('AudioEncoder' in window) && ('AudioDecoder' in window);

  function jouerPCM(float32) {
    if (!ctx) return;
    const buf = ctx.createBuffer(1, float32.length, 24000);
    buf.copyToChannel(float32, 0);
    const src = ctx.createBufferSource(); src.buffer = buf; src.connect(ctx.destination); src.start();
  }
  return {
    supporteEcoute: okWebCodecs, supporteParole: true,
    async demarrer() {
      if (!url) { alert('Renseigne l\\'URL du serveur Unmute dans ⚙ Cerveau (wss://…/v1/realtime).'); return false; }
      if (!okWebCodecs) { alert('Ce navigateur ne fournit pas WebCodecs (Opus). Utilise Chrome/Edge récents, ou le mode Navigateur.'); return false; }
      try {
        ws = new WebSocket(url, 'realtime');
        ws.onopen = () => ws.send(JSON.stringify({ type:'session.update',
          session:{ instructions: instructionsUnmute(), voice:'default' } }));
        ws.onmessage = (e) => {
          let m; try { m = JSON.parse(e.data); } catch(_) { return; }
          if (m.type === 'conversation.item.input_audio_transcription.delta') {
            ajouterBulle('user', '🎙 ' + (m.delta || ''));
          } else if (m.type === 'response.created') {
            bulle = ajouterBulle('assistant', '');
          } else if (m.type === 'response.text.delta') {
            if (!bulle) bulle = ajouterBulle('assistant', '');
            bulle.textContent += (m.delta || ''); chatEcho();
          } else if (m.type === 'response.audio.delta' && m.delta && dec) {
            const octets = Uint8Array.from(atob(m.delta), c => c.charCodeAt(0));
            try { dec.decode(new EncodedAudioChunk({ type:'key', timestamp: performance.now()*1000, data: octets })); } catch(_){}
          } else if (m.type === 'error') {
            ajouterBulle('assistant', '⚠ Unmute : ' + (m.error?.message || JSON.stringify(m)));
          }
        };
        ws.onerror = () => ajouterBulle('assistant', '⚠ Connexion Unmute impossible (' + url + ').');
        ws.onclose = () => arreterMicro();

        // Décodeur Opus → lecture audio.
        dec = new AudioDecoder({ output: (data) => {
          const f = new Float32Array(data.numberOfFrames);
          data.copyTo(f, { planeIndex:0, format:'f32-planar' }); jouerPCM(f); data.close();
        }, error: () => {} });
        dec.configure({ codec:'opus', sampleRate:24000, numberOfChannels:1 });

        // Capture micro → PCM 24 kHz → encodeur Opus → base64 → input_audio_buffer.append.
        ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate:24000 });
        micFlux = await navigator.mediaDevices.getUserMedia({ audio:true });
        enc = new AudioEncoder({ output: (chunk) => {
          const buf = new Uint8Array(chunk.byteLength); chunk.copyTo(buf);
          let bin=''; buf.forEach(b => bin += String.fromCharCode(b));
          if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type:'input_audio_buffer.append', audio: btoa(bin) }));
        }, error: () => {} });
        enc.configure({ codec:'opus', sampleRate:24000, numberOfChannels:1, bitrate:24000 });

        const source = ctx.createMediaStreamSource(micFlux);
        const proc = ctx.createScriptProcessor(2048, 1, 1);  // simple et suffisant pour préparer
        proc.onaudioprocess = (ev) => {
          const f = ev.inputBuffer.getChannelData(0);
          const ad = new AudioData({ format:'f32-planar', sampleRate:24000, numberOfFrames:f.length,
            numberOfChannels:1, timestamp: performance.now()*1000, data: f.slice() });
          try { enc.encode(ad); } catch(_){} ad.close();
        };
        source.connect(proc); proc.connect(ctx.destination); worklet = proc;
        return true;
      } catch (e) { alert('Unmute : ' + e.message); this.arreter(); return false; }
    },
    arreter() {
      try { worklet && worklet.disconnect(); } catch(_){}
      try { micFlux && micFlux.getTracks().forEach(t => t.stop()); } catch(_){}
      try { enc && enc.close(); } catch(_){}
      try { dec && dec.close(); } catch(_){}
      try { ctx && ctx.close(); } catch(_){}
      worklet = micFlux = enc = dec = ctx = null; bulle = null;
    },
    onTexte() {},  // Unmute gère sa propre conversation (il N'utilise PAS /assistant/chat)
    parler() {},   // la parole arrive en flux audio depuis le serveur
    stop() { try { ws && ws.close(); } catch(_){} this.arreter(); }
  };
}

// Fournisseur « mot-clé » (S42) — micro toujours à l'écoute, réveil « comme Siri »
// par la brique ecoute (openWakeWord, CPU). Le navigateur streame le micro en PCM
// 16 kHz mono int16 vers la brique par WebSocket (même rôle que l'audio d'Unmute,
// mais ici brut, pas Opus) ; la brique renvoie {type:'reveil'} ; à ce moment on capte
// la commande via la reconnaissance du navigateur et on l'envoie à /assistant/chat —
// donc le wake word garde TOUTE la boucle à outils de l'assistant (≠ Unmute).
// Marque blanche : l'audio passe par NOTRE infra, plus par Google.
function creerWakeWord(url) {
  let ws = null, ctx = null, micFlux = null, proc = null, source = null;
  let enCapture = false;            // vrai pendant qu'on dicte la commande après réveil
  const web = creerWebSpeech({silenceForce: true});  // capte la commande (fin au silence) + TTS

  // Float32 [-1,1] → Int16 little-endian (le format attendu par openWakeWord).
  function versPCM16(f32) {
    const out = new Int16Array(f32.length);
    for (let i = 0; i < f32.length; i++) {
      const s = Math.max(-1, Math.min(1, f32[i]));
      out[i] = s < 0 ? s * 0x8000 : s * 0x7fff;
    }
    return out.buffer;
  }

  function surReveil() {
    if (enCapture) return;          // déjà en train de dicter : on ignore les réveils
    enCapture = true;
    const b = document.getElementById('btn-micro');
    if (b) b.classList.add('reveil');
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch(_){}
    // Capte la phrase de commande via la reco navigateur (une passe), puis envoi chat.
    web.onTexte((texte) => {
      enCapture = false;
      if (b) b.classList.remove('reveil');
      web.arreter();
      if (texte) envoyerMessage(new Event('wake'));
    });
    web.demarrer();
  }

  return {
    supporteEcoute: !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia) && web.supporteEcoute,
    supporteParole: web.supporteParole,
    async demarrer() {
      if (!url) { alert('Renseigne l\\'URL de la brique ecoute dans ⚙ Cerveau (ws://…/ecoute).'); return false; }
      if (!this.supporteEcoute) { alert('Ce navigateur ne supporte pas le micro + la reconnaissance vocale nécessaires au mot-clé.'); return false; }
      try {
        ws = new WebSocket(url);
        ws.binaryType = 'arraybuffer';
        ws.onmessage = (e) => {
          let m; try { m = JSON.parse(e.data); } catch(_) { return; }
          if (m.type === 'reveil') surReveil();
        };
        ws.onerror = () => ajouterBulle('assistant', '⚠ Brique ecoute injoignable (' + url + ').');
        ws.onclose = () => { if (MICRO_ACTIF) arreterMicro(); };

        ctx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
        micFlux = await navigator.mediaDevices.getUserMedia({ audio: true });
        source = ctx.createMediaStreamSource(micFlux);
        proc = ctx.createScriptProcessor(1024, 1, 1);
        proc.onaudioprocess = (ev) => {
          if (enCapture) return;     // pendant la dictée, on ne pousse pas le flux de veille
          if (ws && ws.readyState === 1) ws.send(versPCM16(ev.inputBuffer.getChannelData(0)));
        };
        source.connect(proc); proc.connect(ctx.destination);
        return true;
      } catch (e) { alert('Mot-clé : ' + e.message); this.arreter(); return false; }
    },
    arreter() {
      enCapture = false;
      try { web.arreter(); } catch(_){}
      try { proc && proc.disconnect(); } catch(_){}
      try { source && source.disconnect(); } catch(_){}
      try { micFlux && micFlux.getTracks().forEach(t => t.stop()); } catch(_){}
      try { ctx && ctx.close(); } catch(_){}
      const b = document.getElementById('btn-micro'); if (b) b.classList.remove('reveil');
      proc = source = micFlux = ctx = null;
    },
    onTexte() {},                    // la capture passe par la reco interne (web), pas par ici
    parler(texte) { web.parler(texte); },
    stop() { try { ws && ws.close(); } catch(_){} ws = null; this.arreter(); }
  };
}

// VOIX est (re)construit depuis la config (panneau ⚙ Cerveau). Défaut : navigateur.
let VOIX = creerWebSpeech();
function construireVoix(provider, url, wakewordUrl) {
  if (MICRO_ACTIF) arreterMicro();
  if (VOIX && VOIX.stop) VOIX.stop();
  VOIX_PROVIDER = (provider === 'unmute' || provider === 'wakeword') ? provider : 'webspeech';
  UNMUTE_URL = url || '';
  WAKEWORD_URL = wakewordUrl || '';
  VOIX = VOIX_PROVIDER === 'unmute' ? creerUnmute(UNMUTE_URL)
       : VOIX_PROVIDER === 'wakeword' ? creerWakeWord(WAKEWORD_URL)
       : creerWebSpeech();
  if (VOIX_PROVIDER === 'webspeech') {
    VOIX.onTexte((texte) => { arreterMicro(); if (texte) envoyerMessage(new Event('voix')); });
  }
}
construireVoix('webspeech', '', '');

function basculerMicro() {
  if (MICRO_ACTIF) { arreterMicro(); return; }
  if (VOIX.demarrer()) { MICRO_ACTIF = true; document.getElementById('btn-micro').classList.add('ecoute'); }
}
function arreterMicro() {
  MICRO_ACTIF = false;
  VOIX.arreter();
  const b = document.getElementById('btn-micro');
  if (b) b.classList.remove('ecoute');
}
function basculerLectureVocale() {
  LECTURE_VOCALE = !LECTURE_VOCALE;
  localStorage.setItem('wp_lecture_vocale', LECTURE_VOCALE ? '1' : '0');
  if (!LECTURE_VOCALE) VOIX.stop();
  majBoutonVoix();
}
function majBoutonVoix() {
  const b = document.getElementById('btn-voix');
  if (b) b.textContent = LECTURE_VOCALE ? '🔊 Voix : on' : '🔊 Voix : off';
}

// ── Dépôt de documents : upload → classement automatique ────────────────────
async function deposerFichier(fichier) {
  if (!fichier) return;
  ajouterBulle('user', '📎 ' + fichier.name);
  const fil = document.getElementById('chat-fil');
  const tip = document.createElement('div');
  tip.className = 'typing'; tip.textContent = 'Ingestion et classement du document…';
  fil.appendChild(tip); chatEcho();
  try {
    const fd = new FormData(); fd.append('fichier', fichier);
    const r = await fetch('/assistant/document', { method:'POST', body: fd });
    tip.remove();
    if (!r.ok) { ajouterBulle('assistant', '⚠ Échec du classement : ' + (await r.text())); return; }
    const data = await r.json();
    afficherClassement(data);
    chargerDossiers().catch(()=>{});
  } catch(err) {
    tip.remove(); ajouterBulle('assistant', '⚠ Erreur : ' + err.message);
  } finally {
    document.getElementById('fichier-input').value = '';
  }
}

const CLASSEMENTS = {};   // doc_id → {nom, classement} (évite d'injecter du texte libre dans le HTML)
function escHtml(s) { const d = document.createElement('div'); d.textContent = s == null ? '' : s; return d.innerHTML; }

function afficherClassement(data) {
  const c = data.classement || {};
  CLASSEMENTS[data.doc_id] = data;
  const fil = document.getElementById('chat-fil');
  const d = document.createElement('div');
  d.className = 'carte-classement';
  const tags = (c.tags || []).map(t => `<span class="chip">${escHtml(t)}</span>`).join('');
  const ent = c.entreprise_nom ? `<div class="cc-ligne"><b>Entreprise :</b> ${escHtml(c.entreprise_nom)}</div>` : '';
  const proj = c.projet ? `<div class="cc-ligne"><b>Projet :</b> ${escHtml(c.projet)}</div>` : '';
  const res = c.resume ? `<div class="cc-ligne">${escHtml(c.resume)}</div>` : '';
  d.innerHTML =
    `<div class="cc-tete"><span class="cc-cat">${escHtml(c.categorie || 'autre')}</span><span class="cc-nom">${escHtml(data.nom || '')}</span></div>`
    + res + ent + proj
    + (tags ? `<div class="chips">${tags}</div>` : '')
    + `<div class="cc-actions">
         <button class="btn ghost" onclick="ajusterClassement('${data.doc_id}')">Ajuster</button>
         <button class="btn" onclick="retenirDocument('${data.doc_id}')">Retenir en mémoire</button>
       </div>`;
  fil.appendChild(d); chatEcho();
}

function ajusterClassement(docId) {
  const input = document.getElementById('chat-input');
  input.value = 'Reclasse le document ' + docId + ' : ';
  input.focus();
}
function retenirDocument(docId) {
  const data = CLASSEMENTS[docId] || {}; const c = data.classement || {};
  const input = document.getElementById('chat-input');
  input.value = 'Retiens en mémoire ce document « ' + (data.nom || '') + ' » : ' + (c.resume || '');
  envoyerMessage(new Event('mem'));
}

// Glisser-déposer sur la zone de chat.
function brancherDragDrop() {
  const zone = document.getElementById('chat-zone');
  if (!zone || zone.dataset.dd) return; zone.dataset.dd = '1';
  ['dragenter','dragover'].forEach(ev => zone.addEventListener(ev, e => { e.preventDefault(); zone.classList.add('drag'); }));
  ['dragleave','drop'].forEach(ev => zone.addEventListener(ev, e => {
    e.preventDefault();
    if (ev === 'dragleave' && zone.contains(e.relatedTarget)) return;
    zone.classList.remove('drag');
  }));
  zone.addEventListener('drop', e => { const f = e.dataTransfer.files[0]; if (f) deposerFichier(f); });
}

// ── Dossiers (projets + catégories) ─────────────────────────────────────────
async function chargerDossiers() {
  const corps = document.getElementById('dossiers-corps');
  if (!corps) return;
  try {
    const r = await fetch('/assistant/dossiers');
    const d = await r.json();
    const groupe = (titre, obj, filtre) => {
      const items = Object.entries(obj || {});
      if (!items.length) return '';
      const chips = items.map(([nom, n]) =>
        `<span class="dossier-chip" onclick='filtrerDossier(${JSON.stringify(filtre)}, ${JSON.stringify(nom)})'>${nom} <b>${n}</b></span>`).join('');
      return `<div class="dossier-groupe"><div class="dg-titre">${titre}</div>${chips}</div>`;
    };
    const html = groupe('Projets', d.projets, 'projet') + groupe('Catégories', d.categories, 'categorie');
    corps.innerHTML = html || '<span class="liv-sub">Aucun document classé pour l\\'instant — déposez-en un 📎</span>';
  } catch(e) {
    corps.innerHTML = '<span class="liv-sub">Dossiers indisponibles.</span>';
  }
}
function filtrerDossier(type, valeur) {
  const input = document.getElementById('chat-input');
  input.value = (type === 'projet' ? 'Montre les documents du projet « ' : 'Montre les documents de catégorie « ') + valeur + ' »';
  envoyerMessage(new Event('filtre'));
}

function carteHTML(b, h) {
  const roleLabel = ROLES_LABELS[b.role] || b.role;
  const offre = (b.offre || []).map(o => `<span class="chip">${o}</span>`).join('');
  const deps = (b.depends_on || []).map(d => `<span class="chip" style="color:#7c83ff;border-color:#3d4468">${d}</span>`).join('');
  let healthHTML = '';
  if (b.url_sante) {
    const cls = h.statut === 'ok' ? 'ok' : h.statut === 'inaccessible' ? 'inaccessible' : 'inconnu';
    const label = h.statut === 'ok' ? '● en ligne' : h.statut === 'inaccessible' ? '● hors ligne' : '● —';
    healthHTML = `<span class="health health-${cls}">${label}</span>`;
  } else {
    healthHTML = `<span class="health health-inconnu">non exposé</span>`;
  }
  const statutClass = 'statut statut-' + b.statut;
  const statutLabel = {actif:'Actif', setup_requis:'Setup requis', a_tester:'À tester'}[b.statut] || b.statut;
  return `<div class="card">
    <div class="card-header">
      <div>
        <div class="card-title">${b.nom}</div>
        <div class="card-version">v${b.version}</div>
      </div>
      <span class="role-badge role-${b.role}">${roleLabel}</span>
    </div>
    <div class="card-desc">${b.description}</div>
    ${offre ? `<div class="section-label">Offre</div><div class="chips">${offre}</div>` : ''}
    ${deps  ? `<div class="section-label">Dépend de</div><div class="chips">${deps}</div>` : ''}
    <div class="card-footer" style="margin-top:14px">
      <span class="${statutClass}"><span class="dot"></span>${statutLabel}</span>
      ${healthHTML}
    </div>
    <button class="btn ghost card-open" onclick="ouvrirBrique('${b.nom}')">Ouvrir ↗</button>
  </div>`;
}

// ── Panneau de détail d'une brique (clic « Ouvrir ») ────────────────────────
let BRIQUES_MAP = {};
function ouvrirBrique(nom) {
  const item = BRIQUES_MAP[nom]; if (!item) return;
  const b = item.b, h = item.h;
  const role = ROLES_LABELS[b.role] || b.role;
  const offre = (b.offre || []).map(o => `<span class="chip">${o}</span>`).join('');
  const deps = (b.depends_on || []).map(d => `<span class="chip" style="color:#7c83ff;border-color:#3d4468">${d}</span>`).join('');
  const sante = !b.url_sante ? '<span class="health health-inconnu">non exposé</span>'
    : h.statut === 'ok' ? '<span class="health health-ok">● en ligne</span>'
    : h.statut === 'inaccessible' ? '<span class="health health-inaccessible">● hors ligne</span>'
    : '<span class="health health-inconnu">● —</span>';

  // Accès adapté à ce que la brique expose réellement.
  let actions = '';
  if (b.vue_dashboard) {
    actions += `<button class="btn" onclick="switchVue('${b.vue_dashboard}');fermerBrique()">Ouvrir dans le dashboard ↗</button>`;
  }
  if (b.url_ui) {
    actions += `<a class="btn" href="${b.url_ui}" target="_blank" rel="noopener">Ouvrir l'application ↗</a>`;
  }
  // Console API (Swagger) seulement pour les briques dont le port EST une API
  // (pas un frontend : celles-là ont un url_ui).
  if (b.port && !b.url_ui) {
    actions += `<a class="btn ghost" href="http://localhost:${b.port}/docs" target="_blank" rel="noopener">Console API (Swagger) ↗</a>`;
  }
  // Santé : dérivée de l'url_sante du manifest (bon port + chemin par brique).
  if (b.url_sante) {
    const sante_url = b.url_sante.replace('host.docker.internal', 'localhost');
    actions += `<a class="btn ghost" href="${sante_url}" target="_blank" rel="noopener">Santé ↗</a>`;
  }
  if (!actions) actions = '<span class="liv-sub">Cette brique n\\'est pas exposée (aucun port) — rien à ouvrir.</span>';

  document.getElementById('modal-brique-corps').innerHTML = `
    <div class="modal-tete">
      <div>
        <div class="modal-titre">${b.nom} <span class="card-version">v${b.version || '—'}</span></div>
        <span class="role-badge role-${b.role}">${role}</span>
      </div>
      ${sante}
    </div>
    <div class="card-desc" style="margin:12px 0">${b.description || ''}</div>
    ${offre ? `<div class="section-label">Offre</div><div class="chips">${offre}</div>` : ''}
    ${deps  ? `<div class="section-label" style="margin-top:10px">Dépend de</div><div class="chips">${deps}</div>` : ''}
    ${b.port ? `<div class="liv-sub" style="margin-top:10px">Port local : <b>${b.port}</b></div>` : ''}
    <div class="modal-actions">${actions}</div>`;
  document.getElementById('modal-brique').style.display = 'flex';
}
function fermerBrique() { document.getElementById('modal-brique').style.display = 'none'; }

charger();
rafraichirPastilleRappels();
setInterval(charger, 30000);
setInterval(rafraichirPastilleRappels, 60000);
// L'usine évolue vite (étapes async) : on rafraîchit toutes les 4 s quand la vue est ouverte.
setInterval(() => { if (VUE === 'usine') chargerLivraisons(); }, 4000);
// PWA « télécommande » (S61) : enregistre le service-worker (installable, coque hors-ligne).
if ('serviceWorker' in navigator) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js').catch(() => {}));
}
</script>
</body>
</html>"""


@asynccontextmanager
async def lifespan(app: FastAPI):
    registre.charger()
    orchestrateur.init_db()
    proactif.init_db()
    horloge.init_db()
    # Boucle proactive en tâche de fond (rappels : agenda imminent, docs à classer).
    tache_proactif = asyncio.create_task(proactif.boucle(registre))
    # Horloge : déclenche les tâches périodiques déclarées par les briques (S29).
    tache_horloge = asyncio.create_task(horloge.boucle(registre))
    yield
    tache_proactif.cancel()
    tache_horloge.cancel()


app = FastAPI(
    title="Workplace — Cœur",
    description="Orchestrateur central du projet Workplace. Découvre les briques via leurs manifests et pilote l'usine à applications (ETL→Audit→Génération→Déploiement).",
    version="0.2.0",
    lifespan=lifespan,
)

# Origines autorisées : liste explicite via CORS_ORIGINS (CSV). Défaut "*" =
# comportement historique (front servi en local). Pour durcir en déploiement,
# définir CORS_ORIGINS=https://app.${DOMAIN} dans le .env.
_cors = [o.strip() for o in os.getenv("CORS_ORIGINS", "*").split(",") if o.strip()] or ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health", tags=["système"])
def health():
    return {"statut": "ok", "version": "0.2.0", "briques_chargees": len(registre.briques)}


@app.get("/briques", tags=["briques"])
def lister_briques():
    """Liste toutes les briques enregistrées."""
    return {"total": len(registre.briques), "briques": list(registre.briques.values())}


@app.get("/briques/{nom}", tags=["briques"])
def detail_brique(nom: str):
    """Détail d'une brique par son nom."""
    brique = registre.briques.get(nom)
    if not brique:
        raise HTTPException(status_code=404, detail=f"Brique '{nom}' introuvable")
    return brique


@app.post("/briques/reload", tags=["briques"])
def recharger_briques():
    """Recharge tous les manifests sans redémarrer le cœur."""
    registre.charger()
    return {"statut": "ok", "briques_chargees": len(registre.briques)}


@app.post("/mcp", tags=["mcp"])
async def mcp_endpoint(request: Request):
    """Gateway MCP (JSON-RPC 2.0) : point d'entrée unique pour des clients/agents tiers.

    Expose les MÊMES outils que l'assistant (statiques + capacités découvertes par manifest)
    et le co-agent planificateur (`coagent_lancer`). Auth par `MCP_KEY` si définie. Accepte un
    message JSON-RPC ou un lot ; une notification (sans `id`) ne renvoie pas de corps (202)."""
    if not mcp_serveur.actif():
        raise HTTPException(404, "Serveur MCP désactivé (MCP_ACTIF=0).")
    presentee = (request.headers.get("x-api-key")
                 or request.headers.get("authorization", "").removeprefix("Bearer ").strip()
                 or None)
    if not mcp_serveur.cle_ok(presentee):
        raise HTTPException(401, "Clé MCP manquante ou invalide (header X-API-Key).")
    try:
        corps = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(400, "Corps JSON-RPC illisible.")
    if isinstance(corps, list):                       # lot JSON-RPC
        reps = [r for r in [await mcp_serveur.traiter(m, registre) for m in corps]
                if r is not None]
        return JSONResponse(reps) if reps else Response(status_code=202)
    rep = await mcp_serveur.traiter(corps, registre)
    if rep is None:                                   # notification → pas de corps
        return Response(status_code=202)
    return JSONResponse(rep)


@app.get("/capacites", tags=["briques"])
def lister_capacites():
    """Catalogue des capacités appelables découvertes dans les manifests (S63).

    Le « schéma corporel » : ce que le Cœur sait faire en agrégeant le champ `capacites`
    de chaque brique. Inspection seule — le câblage au LLM est le sujet de S64."""
    cap = catalogue.collecter_capacites(registre)
    return {
        "total": len(cap),
        "briques": sorted({c["brique"] for c in cap}),
        "doublons": catalogue.doublons(cap),
        "capacites": cap,
    }


@app.get("/briques/{nom}/sante", tags=["briques"])
async def sante_brique(nom: str):
    """Ping le endpoint de santé d'une brique (si url_sante définie)."""
    brique = registre.briques.get(nom)
    if not brique:
        raise HTTPException(status_code=404, detail=f"Brique '{nom}' introuvable")
    url = brique.get("url_sante")
    if not url:
        return {"nom": nom, "statut": "non_applicable", "message": "Pas d'url_sante définie dans le manifest"}
    try:
        async with httpx.AsyncClient(timeout=3.0) as client:
            r = await client.get(url)
            statut = "ok" if r.status_code < 400 else "erreur"
            return {"nom": nom, "statut": statut, "code_http": r.status_code}
    except Exception as e:
        return {"nom": nom, "statut": "inaccessible", "erreur": str(e)}


@app.get("/horloge/taches", tags=["horloge"])
def horloge_taches():
    """Tâches périodiques déclarées par les briques (manifest `taches`) avec, pour
    chacune, sa cadence, sa dernière exécution et sa prochaine échéance (S29)."""
    taches = horloge.lister_etat(registre)
    return {"total": len(taches), "taches": taches}


@app.post("/horloge/executer", tags=["horloge"])
async def horloge_executer(forcer: bool = False, brique: str | None = None,
                           tache: str | None = None):
    """Déclenche les tâches dues maintenant. `forcer=true` ignore la cadence ;
    `brique`/`tache` restreignent à une seule tâche (utile pour tester ou rejouer)."""
    return await horloge.run_due(registre, forcer=forcer,
                                 filtre_brique=brique, filtre_tache=tache)


@app.post("/briefing/executer", tags=["assistant"])
async def briefing_executer(forcer: bool = False):
    """Génère le briefing quotidien (RDV, impayés, pipeline, coût LLM de la veille)
    et le dépose en rappel 🔔. Synthèse par l'économe local (S138). Idempotent par
    jour ; `forcer=true` régénère. Déclenché chaque matin par l'horloge S29 via la
    tâche `briefing-quotidien` du manifest `noyau` (S30)."""
    return await briefing.executer(registre, forcer=forcer)


@app.get("/briefing/dernier", tags=["assistant"])
async def briefing_dernier():
    """Dernier briefing déposé (rappel de type `briefing`), s'il existe."""
    briefings = [r for r in proactif.lister(limite=60) if r.get("type") == "briefing"]
    return {"briefing": briefings[0] if briefings else None}


@app.post("/pouls/battre", tags=["assistant"])
async def pouls_battre(forcer: bool = False):
    """Fait battre le cœur (S67) : réveille le co-agent (S66) sur l'objectif récurrent,
    en autonomie et lecture seule, puis dépose sa synthèse en rappel 🔔. Borné par le
    budget quotidien de tokens. Idempotent par jour ; `forcer=true` rejoue. Déclenché
    par l'horloge S29 via la tâche `pouls-autonome` du manifest `noyau`."""
    return await pouls.battre(registre, forcer=forcer)


@app.get("/pouls/dernier", tags=["assistant"])
async def pouls_dernier():
    """Dernier point autonome déposé (rappel de type `pouls`), s'il existe."""
    points = [r for r in proactif.lister(limite=60) if r.get("type") == "pouls"]
    return {"pouls": points[0] if points else None}


@app.get("/proprioception", tags=["assistant"])
async def proprioception_rapport(limite: int = 15):
    """Proprioception (S68) : le Cœur mesure ses propres réponses échantillonnées (juge
    LLM gratuit, repli heuristique honnête) et PROPOSE des cibles d'amélioration (S69
    prompts / S70 capacités). Lecture seule : ne modifie ni prompts ni code."""
    return await proprioception.mesurer(limite=limite)


# ── Auto-amélioration des prompts (S69) : proposer → évaluer → gate humain ───
@app.get("/amelioration", tags=["assistant"])
async def amelioration_lister():
    """Liste les propositions d'addendum de prompt + l'addendum actif (S69)."""
    return amelioration.lister()


@app.post("/amelioration/proposer", tags=["assistant"])
async def amelioration_proposer():
    """Propose un addendum de prompt à partir d'un point faible de la proprioception
    (réflexion façon GEPA, repli template honnête). INACTIF tant que non validé."""
    return await amelioration.proposer()


@app.post("/amelioration/{id_}/evaluer", tags=["assistant"])
async def amelioration_evaluer(id_: str):
    """A/B honnête : rejoue des questions sous prompt actuel vs + addendum, note les deux."""
    return await amelioration.evaluer(id_)


@app.post("/amelioration/{id_}/valider", tags=["assistant"])
async def amelioration_valider(id_: str):
    """Gate humain — étape 1 : valide la proposition (ne l'active pas encore)."""
    return amelioration.valider(id_)


@app.post("/amelioration/{id_}/appliquer", tags=["assistant"])
async def amelioration_appliquer(id_: str):
    """Gate humain — étape 2 : active l'addendum (refusé si non validé). Réversible."""
    return amelioration.appliquer(id_)


@app.post("/amelioration/{id_}/rejeter", tags=["assistant"])
async def amelioration_rejeter(id_: str):
    """Écarte une proposition ; la désactive si elle était active."""
    return amelioration.rejeter(id_)


@app.post("/amelioration/desactiver", tags=["assistant"])
async def amelioration_desactiver():
    """Revient au prompt fondateur : aucun addendum actif (historique conservé)."""
    return amelioration.desactiver()


# ── Curator (S70) : cycle hebdo proprioception → propositions → digest 🔔 ─────
@app.post("/curateur/cycle", tags=["assistant"])
async def curateur_cycle(forcer: bool = False):
    """Un tour de curation (S70) : mesure → propose un addendum de prompt (S69) + un
    brouillon de capacité manquante → dépose un digest en rappel 🔔. PROPOSE, n'applique
    rien. Idempotent par jour ; déclenché par l'horloge (tâche `curation-hebdo`)."""
    return await curateur.curer(registre, forcer=forcer)


@app.get("/curateur/capacites", tags=["assistant"])
async def curateur_capacites():
    """Brouillons de capacités proposés (spécifications à implémenter, S70)."""
    return curateur.lister_capacites()


@app.post("/curateur/capacites/{id_}/retenir", tags=["assistant"])
async def curateur_retenir(id_: str):
    """Gate humain : retient un brouillon comme spéc à implémenter (n'active rien)."""
    return curateur.retenir_capacite(id_)


@app.post("/curateur/capacites/{id_}/rejeter", tags=["assistant"])
async def curateur_rejeter(id_: str):
    """Écarte un brouillon de capacité."""
    return curateur.rejeter_capacite(id_)


@app.get("/dashboard", tags=["système"], response_class=HTMLResponse)
async def dashboard():
    """Interface visuelle du registre de briques."""
    # __FORGE_UI_URL__ / __STUDIO_UI_URL__ / __PERSONNAGES_UI_URL__ : injectés au service
    # (pas figés dans le template) pour que les iframes (Forge, Hub Créations) pointent sur
    # la bonne origine selon l'environnement.
    # Si un « compte Studio » (STUDIO_KEY) est configuré, on transporte la clé dans l'URL de
    # l'iframe (?api_key=) pour que le front Studio s'authentifie. Cockpit mono-opérateur :
    # la clé EST l'identité du propriétaire (même frontière de confiance que /dashboard).
    studio_ui = STUDIO_UI_URL
    if STUDIO_KEY:
        sep = "&" if "?" in studio_ui else "?"
        studio_ui = f"{studio_ui}{sep}api_key={STUDIO_KEY}"
    return HTMLResponse(content=DASHBOARD_HTML
        .replace("__FORGE_UI_URL__", FORGE_UI_URL)
        .replace("__STUDIO_UI_URL__", studio_ui)
        .replace("__PERSONNAGES_UI_URL__", PERSONNAGES_UI_URL)
        .replace("__TRANSCRIPTION_UI_URL__", TRANSCRIPTION_UI_URL))


# ── PWA « télécommande » (S61) : dashboard installable sur mobile, plein écran ──────
# Le téléphone n'est qu'une télécommande : zéro calcul/stockage lourd, juste l'UI de chat
# (streaming S60) qui parle au Cœur. Motif éprouvé de la brique transcription.
_PWA_MANIFEST = {
    "name": "Workplace — Cœur", "short_name": "Workplace",
    "description": "Télécommande de la solution : piloter, discuter, capter — depuis le mobile.",
    "start_url": "/dashboard", "scope": "/", "display": "standalone",
    "background_color": "#0f1117", "theme_color": "#0f1117",
    "icons": [{"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml",
               "purpose": "any maskable"}],
}

_PWA_SW = """// Service worker minimal : coque hors-ligne au lancement, API toujours réseau.
const C = 'workplace-coeur-v1';
self.addEventListener('install', e => {
  e.waitUntil(caches.open(C).then(c => c.addAll(['/dashboard', '/icon.svg'])));
  self.skipWaiting();
});
self.addEventListener('activate', e => { e.waitUntil(self.clients.claim()); });
self.addEventListener('fetch', e => {
  const r = e.request;
  if (r.method !== 'GET') return;                 // POST /assistant/chat, etc. → réseau direct
  if (r.mode === 'navigate') {                     // lancement de l'app → coque en repli si hors-ligne
    e.respondWith(fetch(r).catch(() => caches.match('/dashboard')));
  }
});
"""

_PWA_ICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">'
             '<rect width="512" height="512" rx="96" fill="#0f1117"/>'
             '<circle cx="256" cy="256" r="120" fill="none" stroke="#7c83ff" stroke-width="22"/>'
             '<circle cx="256" cy="256" r="46" fill="#7c83ff"/></svg>')


@app.get("/manifest.webmanifest", include_in_schema=False)
def pwa_manifest():
    return Response(json.dumps(_PWA_MANIFEST), media_type="application/manifest+json")


@app.get("/sw.js", include_in_schema=False)
def pwa_service_worker():
    return Response(_PWA_SW, media_type="application/javascript")


@app.get("/icon.svg", include_in_schema=False)
def pwa_icon():
    return Response(_PWA_ICON, media_type="image/svg+xml")


@app.get("/sante-globale", tags=["système"])
async def sante_globale():
    """Ping toutes les briques qui ont une url_sante."""
    resultats = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for nom, brique in registre.briques.items():
            url = brique.get("url_sante")
            if not url:
                resultats[nom] = {"statut": "non_applicable"}
                continue
            try:
                r = await client.get(url)
                resultats[nom] = {"statut": "ok" if r.status_code < 400 else "erreur", "code_http": r.status_code}
            except Exception as e:
                resultats[nom] = {"statut": "inaccessible", "erreur": str(e)}
    return {"briques": resultats}


# ── Usine à applications (S5) ────────────────────────────────────────────────
# Le Cœur pilote la chaîne ETL→Audit→Génération(→Packaging) en une commande et
# tient le tableau des entreprises livrées.

@app.post("/usine/livrer", status_code=202, tags=["usine"])
async def livrer(
    background_tasks: BackgroundTasks,
    fichiers: list[UploadFile] = File(default=[]),
    nom_entreprise: str = Form("Entreprise"),
    persistance: str = Form("hebergee"),
    messagerie: bool = Form(False),
    packager: bool = Form(False),
    email_client: str = Form(""),
    contact_client: str = Form(""),
    langue: str = Form("fr"),
):
    """Livre une entreprise en une commande : ingère les documents, lance l'audit,
    génère l'app (→ packaging optionnel). Renvoie un id de livraison à suivre.

    - `fichiers` : documents de l'entreprise (optionnel — sinon on audite les
      documents déjà présents dans l'ETL).
    - `persistance` : « hebergee » (multi-utilisateur, défaut) ou « autonome ».
    - `messagerie` : embarquer la messagerie Oria (mode hébergé requis).
    - `packager` : produire en plus un bundle Docker de déploiement.
    - `email_client` : si fourni, on crée à la livraison un compte d'accès Oria à cet
      email + envoie un lien « définis ton mot de passe » et rattache le client à son
      espace (S23, best-effort). `contact_client` = nom du contact (optionnel).
    - `langue` (S37) : langue de l'app livrée — « fr » (défaut) | « en » | « es » | « ar ».
      Toute valeur inconnue est ramenée à « fr » par le générateur (repli honnête).
    """
    mode = "hebergee" if persistance == "hebergee" else "autonome"
    langue = (langue or "fr").strip().lower()[:2] or "fr"
    email_client = (email_client or "").strip()
    contact_client = (contact_client or "").strip()
    # Lire le contenu des uploads AVANT de rendre la main (les fichiers temporaires
    # sont fermés à la fin de la requête ; la tâche de fond tourne après).
    charges = [(f.filename, await f.read(), f.content_type) for f in fichiers]

    livraison_id = str(uuid.uuid4())
    orchestrateur.creer_livraison(livraison_id, nom_entreprise, mode, messagerie, packager,
                                  email_client, contact_client)
    background_tasks.add_task(
        orchestrateur.executer_pipeline,
        registre, livraison_id, charges, mode, messagerie, packager,
        email_client, contact_client, langue,
    )
    return {"id": livraison_id, "statut": "en_cours", "nom_entreprise": nom_entreprise,
            "mode": mode, "messagerie": messagerie, "packager": packager, "langue": langue,
            "compte_client": bool(email_client), "nb_fichiers": len(charges)}


def _enrichir_livraison(liv: dict) -> dict:
    """Ajoute les URLs publiques de l'app (vues depuis le navigateur)."""
    if liv.get("app_id"):
        liv["url_apercu"] = f"{GENERATEUR_URL_PUBLIQUE}/apps/{liv['app_id']}/apercu"
        liv["url_html"] = f"{GENERATEUR_URL_PUBLIQUE}/apps/{liv['app_id']}/html"
    return liv


@app.get("/usine/livraisons", tags=["usine"])
def lister_livraisons():
    """Tableau des entreprises livrées."""
    livraisons = [_enrichir_livraison(l) for l in orchestrateur.lister_livraisons()]
    return {"total": len(livraisons), "livraisons": livraisons}


@app.get("/usine/livraisons/{livraison_id}", tags=["usine"])
def detail_livraison(livraison_id: str):
    liv = orchestrateur.lire_livraison(livraison_id)
    if not liv:
        raise HTTPException(404, "Livraison introuvable")
    return _enrichir_livraison(liv)


@app.delete("/usine/livraisons/{livraison_id}", status_code=204, tags=["usine"])
def supprimer_livraison(livraison_id: str):
    orchestrateur.supprimer_livraison(livraison_id)


# ── Cycle de vie des entreprises (S6) ────────────────────────────────────────
# Décrocher = sortir l'entreprise des bases centrales vers un dossier portable.
# Reprendre = la réinjecter pour la modifier, puis on peut la re-décrocher.

@app.post("/usine/livraisons/{livraison_id}/decrocher", tags=["usine"])
async def decrocher_entreprise(livraison_id: str):
    """Met une entreprise « de côté » : rassemble son état dans un dossier portable
    et la retire des bases centrales (la solution principale est libérée)."""
    try:
        return await cycle_de_vie.decrocher(registre, livraison_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except cycle_de_vie.EchecCycle as e:
        raise HTTPException(502, str(e))


@app.post("/usine/livraisons/{livraison_id}/reprendre", tags=["usine"])
async def reprendre_entreprise(livraison_id: str):
    """Réinjecte une entreprise décrochée dans la solution principale (pour la modifier)."""
    try:
        return await cycle_de_vie.reprendre(registre, livraison_id)
    except ValueError as e:
        raise HTTPException(404, str(e))
    except cycle_de_vie.EchecCycle as e:
        raise HTTPException(502, str(e))


# ── Assistant conversationnel du Cœur (S7) ───────────────────────────────────
# Un agent qui dialogue et pilote l'usine via ses outils (lecture + actions
# gardées par confirmation). Flux d'événements en SSE.

@app.post("/assistant/chat", tags=["assistant"])
async def assistant_chat(corps: dict):
    """Conversation avec l'assistant. Corps : {"messages": [{role, content}, …]}.

    Répond en `text/event-stream` : chaque ligne `data:` est un événement JSON
    (texte, outil, resultat_outil, fin, erreur)."""
    messages = corps.get("messages") or []

    async def flux():
        try:
            async for evt in assistant.converser(messages, registre):
                yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"
        except Exception as e:  # noqa: BLE001
            yield f"data: {json.dumps({'type': 'erreur', 'contenu': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(flux(), media_type="text/event-stream")


@app.get("/assistant/config", tags=["assistant"])
async def assistant_config_get():
    """État du « cerveau » : modèle courant, modèles disponibles, clé OpenRouter définie ?"""
    conf = config_assistant.charger()
    return {
        "model": conf["model"],
        "fallback_models": conf["fallback_models"],
        "modeles_disponibles": await config_assistant.lister_modeles(),
        "cle_openrouter_definie": config_assistant.cle_openrouter_definie(),
        "voix_provider": conf["voix_provider"],
        "unmute_url": conf["unmute_url"],
        "wakeword_url": conf["wakeword_url"],
        "voix_fin_mode": conf["voix_fin_mode"],
        "voix_silence_ms": conf["voix_silence_ms"],
        "persona": conf["persona"],
        "personas": personas.catalogue(),
        "langue": conf["langue"],
        "langues": langue_mod.catalogue(),
        "routage_actif": conf["routage_actif"],
        "modele_econome": conf["modele_econome"],
        # Cascade auto (cost-first) : gratuits → repli payant, + chaîne effective.
        "cascade_auto": conf["cascade_auto"],
        "repli_payant": conf["repli_payant"],
        "cascade_free_n": conf["cascade_free_n"],
        "chaine_effective": await config_assistant.chaine_modeles(conf),
        # Muscle déporté (brique calcul, roadmap S58) : opt-in + état des nœuds.
        "muscle_actif": conf["muscle_actif"],
        # Repli souverain CPU sur le Cœur (S62) : dernier maillon local de la cascade.
        "repli_souverain": conf["repli_souverain"],
        "repli_souverain_avant_payant": conf["repli_souverain_avant_payant"],
    }


@app.get("/assistant/muscle", tags=["assistant"])
async def assistant_muscle_get():
    """État du « Muscle » déporté : opt-in actif ? + nœuds de calcul connus (brique calcul)."""
    import muscle
    conf = config_assistant.charger()
    return {"muscle_actif": conf["muscle_actif"], **await muscle.etat()}


@app.post("/assistant/muscle", tags=["assistant"])
async def assistant_muscle_post(corps: dict):
    """Active/désactive le recours au muscle déporté. Corps : {"actif": bool}."""
    conf = config_assistant.definir_muscle(corps.get("actif"))
    return {"muscle_actif": conf["muscle_actif"]}


@app.post("/assistant/routage", tags=["assistant"])
async def assistant_routage_post(corps: dict):
    """Active/désactive le routage dynamique (S138) et fixe le modèle économe.

    Corps : {"actif": bool?, "modele_econome": "free/..."?}."""
    conf = config_assistant.definir_routage(corps.get("actif"), corps.get("modele_econome"))
    return {"routage_actif": conf["routage_actif"], "modele_econome": conf["modele_econome"]}


@app.post("/assistant/config", tags=["assistant"])
async def assistant_config_post(corps: dict):
    """Règle le cerveau de l'assistant (effet immédiat).

    Corps (tous optionnels) :
    - "model"            : modèle mis EN TÊTE de la cascade ("" = pas de tête, cascade pure) ;
    - "fallback_models"  : repli manuel (mode cascade_auto=false) ;
    - "cascade_auto"     : true = gratuits auto → repli payant ; false = [model]+fallbacks ;
    - "repli_payant"     : modèle payant final de la cascade ;
    - "cascade_free_n"   : nombre de gratuits essayés avant le repli ;
    - "repli_souverain"  : modèle CPU local, dernier maillon souverain (S62) ;
    - "repli_souverain_avant_payant" : true = souveraineté d'abord (avant le payant cloud).
    """
    if any(k in corps for k in ("cascade_auto", "repli_payant", "cascade_free_n")):
        config_assistant.definir_cascade(
            actif=corps.get("cascade_auto"),
            repli=corps.get("repli_payant"),
            n=corps.get("cascade_free_n"),
        )
    if "repli_souverain" in corps or "repli_souverain_avant_payant" in corps:
        config_assistant.definir_repli_souverain(
            modele=corps.get("repli_souverain"),
            avant_payant=corps.get("repli_souverain_avant_payant"),
        )
    if "model" in corps or "fallback_models" in corps:
        config_assistant.definir_modele(corps.get("model"), corps.get("fallback_models"))

    conf = config_assistant.charger()
    chaine = await config_assistant.chaine_modeles(conf)
    # On teste le 1er modèle réellement essayé (tête de cascade), pas un champ figé.
    tete = chaine[0] if chaine else (conf.get("model") or conf.get("repli_payant"))
    ok, detail = await config_assistant.tester_modele(tete)
    return {"ok": ok, "config": conf, "chaine_effective": chaine, "tete": tete, "detail": detail}


# ── Profil utilisateur (contexte d'amorçage, éditable depuis le dashboard) ──
# Le défaut est baké dans l'image (core/profil_defaut.md → /app) ; les modifs sont
# persistées dans le volume du Cœur (/data/profil.md) et survivent aux rebuilds.
PROFIL_PATH = os.getenv("PROFIL_PATH", "/data/profil.md")
PROFIL_DEFAUT_PATH = os.getenv("PROFIL_DEFAUT_PATH", "/app/profil_defaut.md")


def _lire_profil() -> str:
    for chemin in (PROFIL_PATH, PROFIL_DEFAUT_PATH):
        try:
            with open(chemin, encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            continue
    return ""


@app.get("/profil", tags=["profil"])
async def profil_get():
    """Profil de l'utilisateur (Markdown). Renvoie la version enregistrée si elle
    existe, sinon le défaut baké dans l'image."""
    return {"contenu": _lire_profil(), "modifie": os.path.exists(PROFIL_PATH)}


@app.post("/profil", tags=["profil"])
async def profil_post(corps: dict):
    """Enregistre le profil dans le volume du Cœur (persistant)."""
    contenu = corps.get("contenu", "")
    os.makedirs(os.path.dirname(PROFIL_PATH), exist_ok=True)
    with open(PROFIL_PATH, "w", encoding="utf-8") as f:
        f.write(contenu)
    return {"ok": True, "taille": len(contenu)}


# ── Fiche d'identité structurée + dérivations (S48 — « se présenter ») ──
# « Se présenter » via 5 champs (prénoms, nom, date/heure/lieu de naissance) → l'assistant
# en dérive plein d'infos (âge, anniversaire, signes, numérologie, mini-thème astral) ET
# reçoit un digest compact dans son contexte. La fiche est À CÔTÉ du profil Markdown libre.
@app.get("/profil/identite", tags=["profil"])
async def identite_get():
    """Fiche d'identité enregistrée + tout ce qu'on en dérive (calcul à la volée)."""
    fiche = identite.charger_fiche()
    return {"fiche": fiche, "derive": identite.deriver(fiche),
            "modifie": identite.FICHE_PATH.exists()}


@app.patch("/profil/identite", tags=["profil"])
async def identite_patch(corps: dict):
    """Met à jour la fiche (champs connus fusionnés) et renvoie les dérivations à jour."""
    fiche = identite.enregistrer_fiche(corps or {})
    return {"ok": True, "fiche": fiche, "derive": identite.deriver(fiche)}


@app.get("/assistant/usage", tags=["assistant"])
async def assistant_usage_get():
    """Suivi des coûts LLM (S138) : tokens & dépense du jour / du mois / total,
    état des budgets, hits de cache, tokens économisés (trim) et appels rétrogradés."""
    return journal_usage.resume()


@app.get("/assistant/shadow", tags=["assistant"])
async def assistant_shadow_get():
    """Rapport shadow (S138-4) : par flux, score d'équivalence d'un candidat moins
    cher, économie observée et recommandation de rétrogradation."""
    return shadow.rapport()


@app.post("/assistant/persona", tags=["assistant"])
async def assistant_persona_post(corps: dict):
    """Change la personnalité de l'assistant (effet immédiat au prochain message)."""
    conf = config_assistant.definir_persona(corps.get("persona"))
    return {"ok": True, "persona": conf["persona"]}


@app.post("/assistant/langue", tags=["assistant"])
async def assistant_langue_post(corps: dict):
    """Change la langue du Jarvis — réponses ET voix (effet immédiat, S39).

    Corps : {"langue": "fr"|"en"|"es"}. Toute langue inconnue retombe sur `fr`."""
    conf = config_assistant.definir_langue(corps.get("langue"))
    return {"ok": True, "langue": conf["langue"],
            "locale_voix": langue_mod.locale_voix(conf["langue"])}


@app.post("/assistant/voix", tags=["assistant"])
async def assistant_voix_post(corps: dict):
    """Règle le fournisseur de voix et les URLs (effet au prochain chargement du front).

    Corps : {"voix_provider": "webspeech"|"unmute"|"wakeword",
             "unmute_url": "wss://…"?, "wakeword_url": "ws://…/ecoute"?,
             "voix_fin_mode": "appui"|"silence"?, "voix_silence_ms": int?}."""
    conf = config_assistant.definir_voix(
        corps.get("voix_provider"), corps.get("unmute_url"), corps.get("wakeword_url"),
        corps.get("voix_fin_mode"), corps.get("voix_silence_ms"))
    return {"ok": True, "voix_provider": conf["voix_provider"],
            "unmute_url": conf["unmute_url"], "wakeword_url": conf["wakeword_url"],
            "voix_fin_mode": conf["voix_fin_mode"], "voix_silence_ms": conf["voix_silence_ms"]}


@app.post("/assistant/cle-openrouter", tags=["assistant"])
async def assistant_cle_openrouter(corps: dict):
    """Enregistre une clé OpenRouter, recrée la Gateway, puis valide par une complétion.

    Corps : {"cle": "sk-or-..."}."""
    cle = (corps.get("cle") or "").strip()
    if not cle:
        raise HTTPException(status_code=400, detail="La clé est vide.")
    config_assistant._ecrire_cle(cle)
    if not await config_assistant.recreer_gateway():
        return {"ok": False, "etape": "recreation",
                "detail": "Conteneur de la Gateway introuvable (le Cœur a-t-il accès au socket Docker ?)."}
    if not await config_assistant.attendre_gateway():
        return {"ok": False, "etape": "attente",
                "detail": "La Gateway n'est pas redevenue joignable après recréation."}
    conf = config_assistant.charger()
    ok, detail = await config_assistant.tester_modele(conf["model"])
    return {"ok": ok, "etape": "fini" if ok else "test", "detail": detail,
            "cle_openrouter_definie": config_assistant.cle_openrouter_definie()}


@app.post("/assistant/document", tags=["assistant"])
async def assistant_document(fichier: UploadFile = File(...)):
    """Dépose un document : l'ingère (ETL), le fait CLASSER par le LLM, puis range
    le classement dans ses métadonnées. Renvoie le classement au front.

    Le résumé n'est PAS écrit en Mémoire ici (action sensible) : le front le propose."""
    etl = orchestrateur._brique_base(registre, "etl")
    contenu = await fichier.read()
    if not contenu:
        raise HTTPException(status_code=400, detail="Fichier vide.")

    async with httpx.AsyncClient(timeout=120) as client:
        # 1) Ingestion (extraction de texte) par l'ETL.
        r = await client.post(
            f"{etl}/ingerer",
            files={"fichier": (fichier.filename or "document", contenu,
                               fichier.content_type or "application/octet-stream")},
        )
        if r.status_code >= 400:
            raise HTTPException(status_code=502, detail=f"Ingestion ETL échouée : {r.text}")
        doc_id = r.json().get("id")

        # 2) Récupération du texte extrait.
        d = await client.get(f"{etl}/documents/{doc_id}")
        texte = d.json().get("texte_extrait", "") if d.status_code < 400 else ""

        # 3) Classement par le LLM (même cerveau que l'assistant).
        classement = await classer.classer_texte(texte, fichier.filename or "document")

        # 4) Persistance du classement dans les métadonnées du document.
        await client.patch(f"{etl}/documents/{doc_id}/classement", json=classement)

    return {"doc_id": doc_id, "nom": fichier.filename,
            "nb_caracteres": len(texte), "classement": classement}


@app.get("/agenda/evenements", tags=["agenda"])
async def agenda_evenements(debut: str | None = None, fin: str | None = None):
    """Événements de l'agenda personnel (proxy de la brique agenda) pour l'onglet Agenda."""
    try:
        return {"evenements": await agenda.lister_evenements(registre, debut, fin)}
    except Exception as e:  # noqa: BLE001
        return {"evenements": [], "detail": str(e)}


@app.get("/assistant/rappels", tags=["assistant"])
async def assistant_rappels(non_lus: bool = False):
    """Rappels proactifs (agenda imminent, documents à classer…)."""
    return {"rappels": proactif.lister(non_lus=non_lus), "non_lus": proactif.compter_non_lus()}


@app.post("/assistant/rappels/check", tags=["assistant"])
async def assistant_rappels_check():
    """Force une vérification proactive immédiate (utile pour tester sans attendre le tick)."""
    nb = await proactif.run_check(registre)
    return {"nouveaux": nb, "non_lus": proactif.compter_non_lus()}


@app.post("/assistant/rappels/{rappel_id}/vu", tags=["assistant"])
async def assistant_rappel_vu(rappel_id: str):
    return {"ok": proactif.marquer_vu(rappel_id), "non_lus": proactif.compter_non_lus()}


@app.get("/assistant/dossiers", tags=["assistant"])
async def assistant_dossiers():
    """Dossiers (projets + catégories avec compteurs), relayés depuis l'ETL."""
    etl = orchestrateur._brique_base(registre, "etl")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(f"{etl}/dossiers")
            return r.json() if r.status_code < 400 else {"projets": {}, "categories": {}}
    except httpx.HTTPError:
        return {"projets": {}, "categories": {}}
