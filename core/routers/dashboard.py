"""Routes « dashboard » du Cœur (extrait de main.py, S114).

Tableau de bord visuel du Cœur (HTML embarqué + injection des URLs d'iframes).
"""
from fastapi import APIRouter
from fastapi.responses import HTMLResponse
from etat import registre
from urls_ui import GENERATEUR_URL_PUBLIQUE, FORGE_UI_URL, STUDIO_UI_URL, PERSONNAGES_UI_URL, TRANSCRIPTION_UI_URL, RESTAURANT_UI_URL, MAIL_UI_URL, SYNOPSIS_UI_URL, VOIX_UI_URL, MEMOIRE_UI_URL, DEV_IDE_URL, GATEWAY_UI_URL, STUDIO_KEY

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
  .port-pill { font-size: 0.74rem; padding: 3px 8px; border-radius: 20px; font-weight: 600;
    font-variant-numeric: tabular-nums; background: #1e293b; color: #93a4c3; border: 1px solid #2d3748; }
  .chips { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
  .chip { font-size: 0.68rem; background: #1e2535; border: 1px solid #2d3148; border-radius: 6px; padding: 2px 8px; color: #64748b; }
  .section-label { font-size: 0.65rem; color: #475569; text-transform: uppercase; letter-spacing: 0.08em; margin-bottom: 4px; margin-top: 10px; }
  #last-check { font-size: 0.75rem; color: #475569; }
  /* Onglets */
  .tabs { display: flex; gap: 4px; }
  .tab { background: transparent; border: none; color: #64748b; font-size: 0.85rem; font-weight: 500; padding: 8px 16px; border-radius: 8px; cursor: pointer; }
  .tab:hover { color: #e2e8f0; }
  .tab.active { background: #1e2535; color: #7c83ff; }
  /* Bulles d'aide (« ⓘ » survolable) — expliquent en clair à quoi sert chaque chose. */
  .aide { position: relative; display: inline-flex; align-items: center; justify-content: center;
          width: 17px; height: 17px; border-radius: 50%; border: 1px solid #3d4468;
          color: #94a3b8; font-size: 0.68rem; font-weight: 700; font-style: italic; font-family: Georgia, serif;
          cursor: help; margin-left: 7px; flex-shrink: 0; user-select: none; vertical-align: middle; }
  .aide:hover, .aide:focus { color: #c7b9ff; border-color: #7c83ff; outline: none; }
  .aide .aide-txt { position: absolute; bottom: calc(100% + 9px); left: 50%; transform: translateX(-50%);
          width: 290px; max-width: 78vw; background: #0f1320; border: 1px solid #3d4468; border-radius: 10px;
          padding: 12px 14px; font-size: 0.8rem; font-weight: 400; font-style: normal; font-family: inherit;
          line-height: 1.55; color: #cbd5e1; text-transform: none; letter-spacing: normal; text-align: left;
          box-shadow: 0 14px 34px #0009; opacity: 0; visibility: hidden; transition: opacity .15s; z-index: 60; }
  .aide:hover .aide-txt, .aide:focus .aide-txt { opacity: 1; visibility: visible; }
  .aide .aide-txt::after { content: ''; position: absolute; top: 100%; left: 50%; transform: translateX(-50%);
          border: 6px solid transparent; border-top-color: #3d4468; }
  .aide.aide-clair { color: #b9c2d8; border-color: #cbd5e1; }
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
  .actions { align-self: flex-start; display: flex; flex-wrap: wrap; gap: 8px; margin: 2px 0 4px; }
  .actions button { font: inherit; font-size: 0.82rem; cursor: pointer; border-radius: 999px; padding: 7px 16px; border: 1px solid #7c83ff66; background: #1f2330; color: #e2e8f0; transition: background .15s, border-color .15s; }
  .actions button:hover { background: #2a2f42; border-color: #7c83ff; }
  .actions button.primaire { background: #7c83ff; border-color: #7c83ff; color: #0f1117; font-weight: 600; }
  .actions button.primaire:hover { background: #9298ff; }
  .actions.fait { opacity: 0.45; pointer-events: none; }
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
  /* Assistant 2-panes (sidebar conversations + projets, façon Claude/Perplexity) */
  .asst { display: grid; grid-template-columns: 268px 1fr; gap: 16px; height: 72vh; }
  .asst-side { background: #161922; border: 1px solid #2d3148; border-radius: 12px; display: flex; flex-direction: column; overflow: hidden; }
  .asst-new { margin: 12px; padding: 11px 14px; border-radius: 10px; border: 1px solid #7c83ff; background: #7c83ff; color: #0f1117; font: inherit; font-weight: 600; font-size: 0.88rem; cursor: pointer; display: flex; align-items: center; justify-content: center; gap: 8px; transition: background .15s; }
  .asst-new:hover { background: #9298ff; }
  .asst-scroll { flex: 1; overflow-y: auto; padding: 0 8px 10px; }
  .asst-sec { margin-top: 6px; }
  .asst-sec-tete { display: flex; align-items: center; justify-content: space-between; padding: 8px 8px 4px; font-size: 0.68rem; text-transform: uppercase; letter-spacing: 0.06em; color: #64748b; font-weight: 700; }
  .asst-sec-tete .asst-add { background: none; border: none; color: #7c83ff; font-size: 1rem; cursor: pointer; line-height: 1; padding: 0 4px; border-radius: 6px; }
  .asst-sec-tete .asst-add:hover { background: #1f2330; }
  .asst-search { width: calc(100% - 16px); margin: 4px 8px 8px; background: #0f1117; border: 1px solid #2d3148; border-radius: 8px; padding: 7px 11px; color: #e2e8f0; font-size: 0.82rem; box-sizing: border-box; }
  .asst-search:focus { outline: none; border-color: #7c83ff; }
  .asst-projet { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
  .asst-projet:hover { background: #1f2330; }
  .asst-projet.actif { background: #1f2330; border-color: #7c83ff55; }
  .asst-projet .pp-dot { width: 9px; height: 9px; border-radius: 3px; flex: 0 0 auto; }
  .asst-projet .pp-nom { font-size: 0.84rem; color: #e2e8f0; font-weight: 600; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .asst-projet .pp-nb { font-size: 0.7rem; color: #64748b; }
  .conv { position: relative; padding: 9px 10px; border-radius: 8px; cursor: pointer; border: 1px solid transparent; }
  .conv:hover { background: #1f2330; }
  .conv.actif { background: #1c2030; border-color: #7c83ff55; }
  .conv.actif .conv-titre { color: #9298ff; }
  .conv-titre { font-size: 0.84rem; color: #e2e8f0; font-weight: 600; display: flex; align-items: center; gap: 6px; padding-right: 44px; }
  .conv-titre span.txt { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .conv-apercu { font-size: 0.73rem; color: #64748b; margin-top: 2px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .conv-actions { position: absolute; top: 7px; right: 7px; display: flex; gap: 2px; opacity: 0; transition: opacity .12s; }
  .conv:hover .conv-actions { opacity: 1; }
  .conv-actions button { background: #232838; border: 1px solid #2d3148; color: #94a3b8; border-radius: 6px; width: 24px; height: 24px; font-size: 0.72rem; cursor: pointer; line-height: 1; }
  .conv-actions button:hover { color: #e2e8f0; border-color: #7c83ff; }
  .conv-surf { font-size: 0.6rem; padding: 1px 6px; border-radius: 999px; flex: 0 0 auto; }
  .conv-surf.telegram { background: #229ed91f; color: #4cc3f0; }
  .conv-surf.web { background: #7c83ff1f; color: #9298ff; }
  .conv-pin { font-size: 0.7rem; flex: 0 0 auto; }
  .conv.archivee { opacity: 0.5; }
  .conv.archivee .conv-titre { font-style: italic; }
  .asst-arch-toggle { font-size: 0.74rem; color: #64748b; padding: 8px 10px; cursor: pointer; user-select: none; }
  .asst-arch-toggle:hover { color: #9298ff; }
  .asst-vide-side { color: #475569; font-size: 0.78rem; padding: 14px 10px; }
  .asst-main { display: flex; flex-direction: column; min-width: 0; }
  .asst-tete { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 10px; }
  .asst-tete-gauche { display: flex; align-items: center; gap: 10px; min-width: 0; }
  .asst-conv-titre { font-size: 1rem; font-weight: 700; color: #e2e8f0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .asst-projet-tag { font-size: 0.72rem; padding: 3px 10px; border-radius: 999px; border: 1px solid #2d3148; color: #cbd5e1; display: inline-flex; align-items: center; gap: 6px; cursor: pointer; }
  .asst-projet-tag .pt-dot { width: 8px; height: 8px; border-radius: 3px; }
  .asst-main .chat { height: auto; flex: 1; min-height: 0; }
  /* Modale projet : instructions + dossiers rattachés */
  .pm-row { margin-bottom: 14px; }
  .pm-row label { display: block; font-size: 0.74rem; color: #94a3b8; font-weight: 600; margin-bottom: 5px; }
  .pm-in, .pm-ta { width: 100%; box-sizing: border-box; background: #0f1117; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 8px; padding: 9px 11px; font-size: 0.88rem; font-family: inherit; }
  .pm-in:focus, .pm-ta:focus { outline: none; border-color: #7c83ff; }
  .pm-ta { min-height: 96px; resize: vertical; line-height: 1.5; }
  .pm-docs { display: flex; flex-wrap: wrap; gap: 8px; }
  .pm-doc { display: inline-flex; align-items: center; gap: 6px; background: #1e2535; border: 1px solid #2d3148; border-radius: 8px; padding: 5px 10px; font-size: 0.8rem; color: #cbd5e1; cursor: pointer; user-select: none; }
  .pm-doc.sel { border-color: #7c83ff; background: #7c83ff1f; color: #c7cbff; }
  /* Agenda */
  .agenda-corps { display: flex; flex-direction: column; gap: 4px; }
  .agenda-jour { font-size: 0.72rem; color: #7c83ff; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; margin: 14px 0 6px; }
  .agenda-jour:first-child { margin-top: 0; }
  .agenda-evt { display: flex; align-items: center; gap: 12px; padding: 9px 12px; background: #1e2535; border: 1px solid #2d3148; border-radius: 8px; }
  .agenda-heure { font-variant-numeric: tabular-nums; color: #94a3b8; font-size: 0.82rem; min-width: 92px; }
  .agenda-titre { color: #e2e8f0; font-weight: 600; font-size: 0.9rem; flex: 1; }
  .agenda-lieu { color: #64748b; font-size: 0.78rem; }
  .agenda-cal { width: 9px; height: 9px; border-radius: 50%; flex: 0 0 auto; display: inline-block; }
  .agenda-rappel { color: #7c83ff; font-size: 0.78rem; white-space: nowrap; }
  .tt-panel { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; padding: 10px 12px; background: #18203044; border: 1px solid #2d3148; border-radius: 8px; margin-bottom: 10px; font-size: 0.82rem; color: #94a3b8; }
  .tt-dot { width: 9px; height: 9px; border-radius: 50%; background: #4CD2C0; display: inline-block; }
  .tt-off { background: #64748b; }
  .agenda-select { background: #1e2535; color: #94a3b8; border: 1px solid #2d3148; border-radius: 6px; font-size: 0.76rem; padding: 3px 6px; }
  /* Calendrier façon TimeTree */
  .cal-toolbar { display: flex; align-items: center; justify-content: space-between; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .cal-nav { display: flex; align-items: center; gap: 8px; }
  .cal-label { font-size: 1.05rem; font-weight: 700; color: #e2e8f0; margin-left: 6px; text-transform: capitalize; }
  .cal-fleche { background: #1e2535; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 8px; width: 32px; height: 32px; font-size: 1.1rem; cursor: pointer; }
  .cal-fleche:hover { background: #2a3346; }
  .cal-modes { display: flex; gap: 0; border: 1px solid #2d3148; border-radius: 8px; overflow: hidden; }
  .cal-mode { background: #1e2535; color: #94a3b8; border: none; padding: 6px 14px; font-size: 0.82rem; cursor: pointer; }
  .cal-mode.active { background: #5865F2; color: #fff; }
  /* Grille mensuelle */
  .cal-grid { display: grid; grid-template-columns: repeat(7, 1fr); gap: 1px; background: #2d3148; border: 1px solid #2d3148; border-radius: 10px; overflow: hidden; }
  .cal-dow { background: #161b27; color: #7c83ff; font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.04em; text-align: center; padding: 7px 0; }
  .cal-cell { background: #141a26; min-height: 96px; padding: 4px 5px; cursor: pointer; display: flex; flex-direction: column; gap: 3px; transition: background .12s; }
  .cal-cell:hover { background: #1a2130; }
  .cal-cell.autre { background: #10141d; }
  .cal-cell.autre .cal-num { color: #475569; }
  .cal-num { font-size: 0.76rem; color: #94a3b8; align-self: flex-start; font-variant-numeric: tabular-nums; }
  .cal-cell.aujourdhui .cal-num { background: #5865F2; color: #fff; border-radius: 50%; width: 21px; height: 21px; display: flex; align-items: center; justify-content: center; font-weight: 700; }
  .cal-chip { font-size: 0.72rem; color: #fff; border-radius: 4px; padding: 1px 5px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; cursor: pointer; border-left: 3px solid rgba(0,0,0,.25); }
  .cal-plus { font-size: 0.68rem; color: #64748b; padding-left: 2px; }
  /* Vue semaine (colonnes par jour) */
  .cal-week { display: grid; grid-template-columns: repeat(7, 1fr); gap: 8px; }
  .cal-wcol { background: #141a26; border: 1px solid #2d3148; border-radius: 10px; padding: 8px; min-height: 160px; }
  .cal-wcol.aujourdhui { border-color: #5865F2; }
  .cal-whead { font-size: 0.72rem; color: #94a3b8; font-weight: 700; text-align: center; margin-bottom: 8px; text-transform: capitalize; }
  .cal-wevt { font-size: 0.74rem; color: #e2e8f0; background: #1e2535; border-left: 3px solid #5865F2; border-radius: 5px; padding: 4px 6px; margin-bottom: 5px; cursor: pointer; }
  .cal-wevt .h { color: #94a3b8; font-variant-numeric: tabular-nums; margin-right: 4px; }
  /* Modale événement : champs */
  .ev-row { display: flex; flex-direction: column; gap: 5px; margin-bottom: 12px; }
  .ev-row label { font-size: 0.74rem; color: #94a3b8; font-weight: 600; }
  .ev-in { background: #141a26; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 8px; padding: 8px 10px; font-size: 0.88rem; width: 100%; box-sizing: border-box; }
  .ev-in:disabled { opacity: .55; cursor: not-allowed; }
  .ev-2col { display: flex; gap: 10px; }
  .ev-2col > div { flex: 1; }
  .ev-palette { display: flex; gap: 7px; flex-wrap: wrap; }
  .ev-swatch { width: 24px; height: 24px; border-radius: 50%; cursor: pointer; border: 2px solid transparent; }
  .ev-swatch.sel { border-color: #fff; box-shadow: 0 0 0 2px #5865F2; }
  .ev-sec { border-top: 1px solid #2d3148; margin-top: 16px; padding-top: 14px; }
  .ev-sec h4 { font-size: 0.82rem; color: #cbd5e1; margin: 0 0 8px; }
  .ev-doc { display: flex; align-items: center; gap: 8px; font-size: 0.82rem; padding: 5px 0; }
  .ev-doc a { color: #7c83ff; text-decoration: none; flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .ev-doc .sup { color: #ef4444; cursor: pointer; background: none; border: none; }
  .ev-comm { font-size: 0.82rem; color: #e2e8f0; background: #141a26; border-radius: 8px; padding: 7px 9px; margin-bottom: 6px; }
  .ev-comm .meta { color: #64748b; font-size: 0.7rem; }
  .ev-ro { font-size: 0.74rem; color: #f59e0b; background: #f59e0b18; border: 1px solid #f59e0b44; border-radius: 7px; padding: 6px 9px; margin-bottom: 12px; }
  /* Étiquettes nommées : légende + mini-gestion */
  .cal-legende { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-bottom: 12px; }
  .cal-leg-titre { font-size: 0.74rem; color: #94a3b8; font-weight: 600; }
  .cal-leg-chip { display: inline-flex; align-items: center; gap: 5px; font-size: 0.78rem; color: #cbd5e1; }
  .cal-leg-dot { width: 10px; height: 10px; border-radius: 50%; flex: 0 0 auto; }
  .etq-row { display: flex; align-items: center; gap: 8px; margin-bottom: 8px; }
  .etq-row input[type=text] { flex: 1; background: #0f1117; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 7px; padding: 7px 9px; font-size: 0.85rem; }
  .etq-row input[type=color] { width: 32px; height: 32px; border: none; background: none; padding: 0; cursor: pointer; }
  .etq-row .sup { color: #ef4444; cursor: pointer; background: none; border: none; font-size: 0.95rem; }
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
  .btn.danger { background: transparent; border: 1px solid #5a2d3a; color: #f87171; padding: 6px 12px; font-size: 0.8rem; }
  .btn.danger:hover { background: #2a1820; color: #fca5a5; border-color: #842c3a; }
  .liv-suppr { margin-top: 12px; }
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
    /* Assistant 2-panes : on empile la sidebar (repliée, scrollable) au-dessus du chat. */
    .asst { grid-template-columns: 1fr; height: auto; gap: 12px; }
    .asst-side { max-height: 34vh; }
    .asst-main .chat { height: calc(100dvh - 260px); }
    .asst-tete { flex-wrap: wrap; }
    .bulle { max-width: 88%; font-size: 0.95rem; }
    /* Inputs ≥ 16px : empêche le zoom auto d'iOS au focus. */
    .chat-saisie input, .cerveau-row input, .cerveau-row select { font-size: 16px; }
    .chat-saisie { padding: 10px; padding-bottom: calc(10px + env(safe-area-inset-bottom)); gap: 8px; }
    #panel-cerveau { max-height: 70dvh; overflow-y: auto; }
  }
</style>
<!-- Socle « manipulation directe » (S101/S102) : menu contextuel (clic droit / appui
     long), modale de confirmation et cliquer-déposer, servi par le Cœur. -->
<script src="/manipulation_directe.js"></script>
</head>
<body>
<header>
  <h1>Workplace — <span>Cœur</span></h1>
  <div style="display:flex;align-items:center;gap:16px">
    <div class="tabs">
      <button class="tab active" data-vue="briques" onclick="switchVue('briques')" title="La liste de tous les modules de ton assistant (agenda, mail, recherche web…). Chaque carte est une fonction, avec une pastille verte si elle marche.">Registre de briques</button>
      <button class="tab" data-vue="atelier" onclick="switchVue('atelier')" title="Pour fabriquer et gérer tes outils : créer une app d'entreprise, gérer un restaurant, créer des personnages, ou éditer le code.">Atelier</button>
      <button class="tab" data-vue="assistant" onclick="switchVue('assistant')" title="Parle à ton assistant en langage normal. Tes conversations et tes projets vivent ici, comme dans Claude ou Perplexity. Il cherche sur le web, lit tes mails, gère ton agenda… et te demande confirmation avant toute action importante.">Assistant</button>
      <button class="tab" data-vue="agenda" onclick="switchVue('agenda')" title="Ton calendrier : voir tes rendez-vous, en ajouter, recevoir des rappels.">Agenda</button>
      <button class="tab" data-vue="mail" onclick="switchVue('mail')" title="Ta boîte mail : lire, trier, préparer des réponses avec l'aide de l'assistant.">Mail</button>
      <button class="tab" data-vue="profil" onclick="switchVue('profil')" title="Ce que l'assistant sait de toi (prénom, préférences…) pour te répondre de façon personnalisée.">Profil</button>
    </div>
    <div class="badge">v0.2.0 &nbsp;·&nbsp; <b id="nb-briques">—</b> briques</div>
  </div>
</header>
<main>
  <!-- VUE BRIQUES -->
  <div class="view active" id="vue-briques">
    <div class="topbar">
      <h2>Registre de briques<span class="aide" tabindex="0">i<span class="aide-txt">Pense à ton assistant comme à un téléphone : chaque « brique » est une appli installée (agenda, mail, recherche web, voix…). Cette page les liste toutes et montre si chacune fonctionne — pastille verte = en ligne. « Frontend » = celles qui ont un écran à ouvrir ; « Backend » = les moteurs qui travaillent en coulisse.</span></span></h2>
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
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn ghost" onclick="switchVue('atelier')">← Atelier</button>
        <h2>Usine à applications — livrer une entreprise en une commande<span class="aide" tabindex="0">i<span class="aide-txt">Décris une entreprise (ou dépose ses documents) et l'assistant te fabrique une application sur mesure clé en main — avec ses comptes utilisateurs et son suivi client. Le tout en une seule fois.</span></span></h2>
      </div>
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

  <!-- VUE ASSISTANT (refonte façon Claude/Perplexity : sidebar conversations + projets) -->
  <div class="view" id="vue-assistant">
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
          <label>Clés des autres fournisseurs</label>
          <div class="liv-sub" style="margin-top:2px;margin-bottom:8px">Active un fournisseur direct (Anthropic, Groq, Mistral, OpenAI, DeepSeek, Gemini) ou OpenCode Go. Enregistrer redémarre la Gateway (~15&nbsp;s). Choisis ensuite son modèle dans « Modèle LLM » ci-dessus.</div>
          <div id="cerveau-cles-fournisseurs"><div class="liv-sub">Chargement…</div></div>
        </div>
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

    <!-- Disposition 2-panes : sidebar (conversations + projets) | conversation active -->
    <div class="asst">
      <aside class="asst-side">
        <button class="asst-new" onclick="nouvelleConversation()">＋ Nouvelle conversation</button>
        <input type="text" class="asst-search" id="asst-search" placeholder="Rechercher une conversation…" oninput="filtrerConversations()" autocomplete="off">
        <div class="asst-scroll">
          <div class="asst-sec">
            <div class="asst-sec-tete"><span>Projets</span><button class="asst-add" title="Nouveau projet" onclick="ouvrirProjetModal()">＋</button></div>
            <div id="asst-projets"><div class="asst-vide-side">Aucun projet pour l'instant.</div></div>
          </div>
          <div class="asst-sec">
            <div class="asst-sec-tete"><span id="asst-convs-titre">Conversations</span></div>
            <div id="asst-convs"><div class="asst-vide-side">Chargement…</div></div>
          </div>
        </div>
      </aside>

      <section class="asst-main">
        <div class="asst-tete">
          <div class="asst-tete-gauche">
            <span class="asst-conv-titre" id="asst-conv-titre">Nouvelle conversation</span>
            <span class="asst-projet-tag" id="asst-conv-projet" style="display:none"></span>
          </div>
          <div style="display:flex;gap:8px;flex-shrink:0">
            <button class="btn ghost" id="btn-rappels" onclick="basculerRappels()" title="Rappels">🔔<span id="rappels-pastille" class="pastille" style="display:none">0</span></button>
            <button class="btn ghost" id="btn-voix" onclick="basculerLectureVocale()" title="Lire les réponses à voix haute">🔊 Voix : off</button>
            <button class="btn ghost" id="btn-cerveau" onclick="toggleCerveau()">⚙ Cerveau</button>
          </div>
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
      </section>
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
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn ghost" onclick="switchVue('atelier')">← Atelier</button>
        <h2>Forge — agents IA, RAG, ventures (interface complète intégrée)<span class="aide" tabindex="0">i<span class="aide-txt">L'atelier technique avancé : créer des assistants IA spécialisés, leur donner une base de connaissances (tes documents), et gérer tes projets. Pour aller plus loin que l'assistant principal.</span></span></h2>
      </div>
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

  <!-- VUE ATELIER — hub unique : Usine à apps, Forge, briques créatives (Studio, Personnages,
       Transcription) et Restaurant, réunis pour ne pas multiplier les onglets du dashboard. -->
  <div class="view" id="vue-atelier">
    <!-- Grille de tuiles (état par défaut) -->
    <div id="creations-grille">
      <div class="topbar">
        <h2>Atelier — fabriquer & gérer : apps, créations, restaurant<span class="aide" tabindex="0">i<span class="aide-txt">Ton établi : ici tu fabriques et gères des choses concrètes — livrer une application d'entreprise, gérer un restaurant, créer des personnages, ou ouvrir l'éditeur de code (Atelier dev). Clique une tuile pour entrer.</span></span></h2>
      </div>
      <div class="creations-tuiles">
        <button class="creation-tuile" onclick="switchVue('usine')">
          <span class="creation-emoji">🏭</span>
          <span class="creation-titre">Usine à apps</span>
          <span class="creation-desc">Livrer une entreprise complète (app + comptes + CRM) en une commande.</span>
          <span class="creation-badge">Cœur</span>
        </button>
        <button class="creation-tuile" onclick="ouvrirCreation('__GENERATEUR_BUNDLES_URL__', 'Composeur de solutions — cocher des briques → bundle par client')">
          <span class="creation-emoji">🧩</span>
          <span class="creation-titre">Composeur de solutions</span>
          <span class="creation-desc">Cocher des briques (resto, paiements, mail…) → un bundle livré et isolé par client (ses conteneurs, ses ports, ses données). Vivant : on rajoute une brique plus tard.</span>
          <span class="creation-badge">Cœur · bundles</span>
        </button>
        <button class="creation-tuile" onclick="switchVue('forge')">
          <span class="creation-emoji">⚒️</span>
          <span class="creation-titre">Forge</span>
          <span class="creation-desc">Agents IA, RAG, ventures — l'atelier technique complet (interface intégrée).</span>
          <span class="creation-badge">Brique · port 3000</span>
        </button>
        <button class="creation-tuile" onclick="switchVue('dev')">
          <span class="creation-emoji">💻</span>
          <span class="creation-titre">Atelier dev</span>
          <span class="creation-desc">L'IDE du dépôt (code-server) : relire et éditer le code, le diff d'un chantier. Piloter en parlant à l'Assistant.</span>
          <span class="creation-badge">Cœur · IDE</span>
        </button>
        <button class="creation-tuile" onclick="ouvrirCreation('__RESTAURANT_UI_URL__', 'Restaurant — commande & paiement à table')">
          <span class="creation-emoji">🍽️</span>
          <span class="creation-titre">Restaurant</span>
          <span class="creation-desc">Commande & paiement à table par QR : carte, ruptures en direct, addition partagée, multi-restaurants.</span>
          <span class="creation-badge">Brique · port 6010</span>
        </button>
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
        <button class="creation-tuile" onclick="ouvrirCreation('__SYNOPSIS_UI_URL__', 'Synopsis — résumé de vidéo')">
          <span class="creation-emoji">🎞️</span>
          <span class="creation-titre">Synopsis &amp; résumé vidéo</span>
          <span class="creation-desc">Résume n'importe quelle vidéo (YouTube, lien direct ou fichier) : résumé, chapitres horodatés et points clés.</span>
          <span class="creation-badge">Brique · port 6090</span>
        </button>
        <button class="creation-tuile" onclick="ouvrirCreation('__VOIX_UI_URL__', 'Voix — choisir le moteur')">
          <span class="creation-emoji">🗣️</span>
          <span class="creation-titre">Voix de l'assistant</span>
          <span class="creation-desc">Choisis la voix en un clic (Piper, Kokoro…) et teste-la. Sert pour les réponses vocales (Telegram).</span>
          <span class="creation-badge">Brique · port 5985</span>
        </button>
        <button class="creation-tuile" onclick="ouvrirCreation('__MEMOIRE_UI_URL__', 'Mémoire — graphe IPCRA')">
          <span class="creation-emoji">🧠</span>
          <span class="creation-titre">Mémoire &amp; graphe IPCRA</span>
          <span class="creation-desc">Explore la mémoire de la solution : nœuds rangés par stage IPCRA, canvas graphe, recherche hybride.</span>
          <span class="creation-badge">Brique · port 5600</span>
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
        <button class="btn ghost" onclick="retourCreations()">← Atelier</button>
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
      <h2>Agenda<span class="aide" tabindex="0">i<span class="aide-txt">Ton calendrier : vois tes rendez-vous (mois ou semaine), ajoutes-en, mets des rappels. Tu peux aussi demander à l'assistant « ajoute un déjeuner mardi à 12h ».</span></span></h2>
      <div style="display:flex;gap:8px">
        <button class="btn" style="opacity:.85" onclick="ouvrirGestionEtiquettes()">🏷 Étiquettes</button>
        <button class="btn" onclick="ouvrirModaleEvent(null, null)">+ Nouveau rendez-vous</button>
      </div>
    </div>
    <div class="panel">
      <div id="g-panel" class="tt-panel" style="display:none"></div>
      <div id="tt-panel" class="tt-panel" style="display:none"></div>
      <div class="cal-toolbar">
        <div class="cal-nav">
          <button class="cal-fleche" onclick="calNav(-1)" title="Précédent">‹</button>
          <button class="btn" onclick="calAujourdhui()">Aujourd'hui</button>
          <button class="cal-fleche" onclick="calNav(1)" title="Suivant">›</button>
          <span id="cal-label" class="cal-label"></span>
        </div>
        <div class="cal-modes">
          <button class="cal-mode active" id="cal-mode-mois" onclick="calMode('mois')">Mois</button>
          <button class="cal-mode" id="cal-mode-semaine" onclick="calMode('semaine')">Semaine</button>
        </div>
      </div>
      <div id="cal-legende" class="cal-legende" style="display:none"></div>
      <div id="cal-conteneur" class="cal-conteneur"><span class="liv-sub">Chargement…</span></div>
    </div>
  </div>
  <div id="event-modal"></div>
  <div id="label-modal"></div>

  <!-- VUE MAIL -->
  <div class="view" id="vue-mail">
    <div class="topbar">
      <h2>Mail<span class="aide" tabindex="0">i<span class="aide-txt">Ta boîte de réception. L'assistant peut t'aider à lire, trier tes mails et préparer des réponses — qu'il n'envoie qu'après ton accord.</span></span></h2>
      <a class="btn ghost" href="__MAIL_UI_URL__" target="_blank" rel="noopener">Ouvrir dans un onglet ↗</a>
    </div>
    <div class="panel" style="padding:0;overflow:hidden">
      <iframe id="mail-iframe" title="Mail"
        style="width:100%;height:calc(100vh - 200px);min-height:520px;border:0;border-radius:12px"
        allow="clipboard-read; clipboard-write"></iframe>
    </div>
  </div>

  <!-- Synopsis (brique 6090) et Voix (brique 5985) sont désormais des TUILES de l'Atelier
       (ouvrirCreation) plutôt que des onglets dédiés — cf. la grille du hub Atelier. -->

  <!-- VUE ATELIER DEV (S92) : IDE web code-server monté sur le dépôt -->
  <div class="view" id="vue-dev">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn ghost" onclick="switchVue('atelier')">← Atelier</button>
        <h2 style="margin:0">Atelier dev — l'IDE du dépôt<span class="aide" tabindex="0">i<span class="aide-txt">L'éditeur de code de l'application, pour les curieux ou les développeurs. Pas besoin de t'en servir : tu peux demander toutes les modifications à l'Assistant, en français — il fait le travail et te montre le résultat.</span></span></h2>
      </div>
      <a class="btn ghost" href="__DEV_IDE_URL__" target="_blank" rel="noopener">Ouvrir dans un onglet ↗</a>
    </div>
    <p class="liv-sub" style="margin:0 0 12px">
      Relis et édite le code (et le diff d'un chantier) ici. Pour <b>piloter l'atelier en
      parlant</b> — ouvrir un chantier, planifier, coder, fusionner sur validation — demande-le
      à l'<a href="#" onclick="switchVue('assistant');return false">Assistant</a> (« ajoute un
      champ X à la brique mail ») : le gate se fait dans le chat.
    </p>
    <div class="panel" style="padding:0;overflow:hidden">
      <iframe id="dev-iframe" title="Atelier dev (code-server)"
        style="width:100%;height:calc(100vh - 230px);min-height:520px;border:0;border-radius:12px"
        allow="clipboard-read; clipboard-write"></iframe>
    </div>
  </div>

  <!-- VUE GATEWAY : console d'admin native de la Gateway (LiteLLM UI) en iframe -->
  <div class="view" id="vue-gateway">
    <div class="topbar">
      <div style="display:flex;align-items:center;gap:12px">
        <button class="btn ghost" onclick="switchVue('briques')">← Registre</button>
        <h2 style="margin:0">Gateway — routeur LLM &amp; clés<span class="aide" tabindex="0">i<span class="aide-txt">Le « standard téléphonique » entre ton assistant et les intelligences artificielles : il transmet chaque demande au bon modèle d'IA et suit les coûts. Tu n'as quasiment jamais besoin d'y toucher — c'est de la plomberie interne.</span></span></h2>
      </div>
      <a class="btn ghost" href="__GATEWAY_UI_URL__" target="_blank" rel="noopener">Ouvrir dans un onglet ↗</a>
    </div>
    <p class="liv-sub" style="margin:0 0 12px">
      Console d'admin de la Gateway (LiteLLM) : modèles, <b>clés virtuelles</b>, budgets/quotas,
      <b>logs &amp; dépenses</b>. Connexion avec la clé maîtresse (<code>LITELLM_MASTER_KEY</code>).
      Pour le réglage courant — choisir le modèle de l'assistant, poser une clé de fournisseur —
      passe plutôt par l'<a href="#" onclick="switchVue('assistant');return false">Assistant</a> → ⚙ Cerveau.
    </p>
    <div class="panel" style="padding:0;overflow:hidden">
      <iframe id="gateway-iframe" title="Console Gateway (LiteLLM)"
        style="width:100%;height:calc(100vh - 230px);min-height:520px;border:0;border-radius:12px"
        allow="clipboard-read; clipboard-write"></iframe>
    </div>
    <p class="liv-sub" style="margin:10px 0 0">
      Si la console ne s'affiche pas dans le cadre (certaines versions de LiteLLM
      refusent l'iframe), utilise « Ouvrir dans un onglet ↗ ».
    </p>
  </div>

  <!-- VUE PROFIL -->
  <div class="view" id="vue-profil">
    <div class="topbar">
      <h2>Profil — ton contexte d'amorçage (sert à personnaliser l'assistant)<span class="aide" tabindex="0">i<span class="aide-txt">Qui tu es : prénom, date de naissance, préférences, façon de te parler… L'assistant s'appuie là-dessus pour personnaliser ses réponses. Plus tu remplis, plus il te ressemble.</span></span></h2>
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

<!-- Modale projet (créer/éditer) façon Claude Projects : nom + instructions + dossiers -->
<div class="modal-fond" id="modal-projet" style="display:none" onclick="if(event.target===this)fermerProjetModal()">
  <div class="modal-boite">
    <button class="modal-fermer" onclick="fermerProjetModal()">✕</button>
    <div class="modal-titre" id="pm-titre">Nouveau projet</div>
    <div class="liv-sub" style="margin-bottom:16px">Regroupe des conversations et donne-leur un contexte commun, comme dans Claude ou Perplexity.</div>
    <div class="pm-row">
      <label>Nom du projet</label>
      <input type="text" class="pm-in" id="pm-nom" placeholder="ex. Refonte du restaurant" autocomplete="off">
    </div>
    <div class="pm-row">
      <label>Instructions personnalisées <span class="liv-sub" style="font-weight:400">(facultatif — appliquées à chaque conversation du projet)</span></label>
      <textarea class="pm-ta" id="pm-instructions" placeholder="ex. Tu m'aides sur la brique restaurant. Réponds de façon concise et oriente-toi solutions."></textarea>
    </div>
    <div class="pm-row">
      <label>Documents de référence <span class="liv-sub" style="font-weight:400">(dossiers existants à consulter pour ce projet)</span></label>
      <div class="pm-docs" id="pm-docs"><span class="liv-sub">Aucun dossier disponible — l'assistant en crée en rangeant tes documents.</span></div>
    </div>
    <div class="modal-actions">
      <button class="btn" id="pm-enregistrer" onclick="enregistrerProjet()">Créer le projet</button>
      <button class="btn danger" id="pm-supprimer" style="display:none" onclick="supprimerProjet()">Supprimer</button>
      <button class="btn ghost" onclick="fermerProjetModal()">Annuler</button>
    </div>
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
  // « Atelier » est un hub : les sous-vues Usine / Forge / Atelier dev / hub gardent l'onglet Atelier actif.
  // « Gateway » n'a plus d'onglet : on l'ouvre depuis la carte du registre → l'onglet Registre reste actif.
  const tabActive = ['atelier', 'usine', 'forge', 'dev'].includes(v) ? 'atelier'
                  : v === 'gateway' ? 'briques' : v;
  document.querySelectorAll('.tab').forEach(t => t.classList.toggle('active', t.dataset.vue === tabActive));
  document.querySelectorAll('.view').forEach(el => el.classList.toggle('active', el.id === 'vue-' + v));
  if (v === 'usine') chargerLivraisons();
  if (v === 'assistant') {
    setTimeout(() => document.getElementById('chat-input').focus(), 50);
    chargerCerveau(); majBoutonVoix(); brancherDragDrop(); chargerDossiers(); rafraichirPastilleRappels();
    chargerSidebarAssistant();
    if (!CONV_ID) nouvelleConversation();
  }
  if (v === 'agenda') { chargerAgenda(); chargerGoogle(); chargerTimeTree(); }
  if (v === 'mail') chargerMail();
  if (v === 'dev') chargerDev();
  if (v === 'gateway') chargerGateway();
  if (v === 'profil') chargerProfil();
  if (v === 'forge') chargerForge();
}

// ── Conversations & projets dans l'Assistant (refonte façon Claude/Perplexity) ──────
// L'historique (trace unifiée S78, web + Telegram) vit DANS l'assistant : sidebar de
// conversations + projets. Chaque conversation web a son propre `fil` (web:conv-…),
// reprenable ; les conversations Telegram apparaissent aussi (badge), relisibles ici.
let CONV_ID = null;          // interlocuteur de la conversation web courante (web:CONV_ID)
let CONV_SURFACE = 'web';    // surface de la conversation ouverte (web ou telegram…)
let CONV_PROJET = null;      // projet rattaché à la conversation courante
let FILS_CACHE = [];         // dernier chargement des fils (pour le filtre de recherche)
let PROJETS_CACHE = [];      // dernier chargement des projets
let FILTRE_PROJET = null;    // si défini, la sidebar ne montre que ce projet
let PROJET_EDIT = null;      // projet en cours d'édition dans la modale (null = création)

function badgeSurface(s) {
  s = s || 'web';
  const ico = s === 'telegram' ? '💬' : '🖥';
  return '<span class="conv-surf ' + (s === 'telegram' ? 'telegram' : 'web') + '">' + ico + '</span>';
}
async function chargerSidebarAssistant() {
  await Promise.all([chargerProjetsSidebar(), chargerConversations()]);
}

// Nouvelle conversation : un fil web frais (héritera du projet filtré le cas échéant).
function nouvelleConversation() {
  CONV_ID = 'conv-' + Date.now().toString(36) + Math.random().toString(36).slice(2, 7);
  CONV_SURFACE = 'web';
  CONV_PROJET = FILTRE_PROJET || null;
  CHAT_HIST.length = 0;
  const fil = document.getElementById('chat-fil');
  fil.innerHTML = '<div class="msg assistant"><div class="bulle">Bonjour 👋 Je pilote toute la solution. Demandez-moi « où en sont les entreprises ? », déposez un document (je le range), ou cliquez sur 🎤 pour me parler. Pour toute action, je vous demanderai confirmation.</div></div>';
  majEnteteConversation('Nouvelle conversation');
  document.querySelectorAll('#asst-convs .conv').forEach(x => x.classList.remove('actif'));
  const inp = document.getElementById('chat-input'); if (inp) inp.focus();
}

function majEnteteConversation(titre) {
  document.getElementById('asst-conv-titre').textContent = titre || 'Conversation';
  const tag = document.getElementById('asst-conv-projet');
  const p = PROJETS_CACHE.find(x => x.id === CONV_PROJET);
  if (p) {
    tag.style.display = 'inline-flex';
    tag.innerHTML = '<span class="pt-dot" style="background:' + p.couleur + '"></span>' + escapeHtml(p.nom);
    tag.title = 'Ranger dans un autre projet';
    tag.onclick = () => choisirProjetPourConversation();
  } else {
    tag.style.display = 'inline-flex';
    tag.innerHTML = '＋ Ranger dans un projet';
    tag.title = 'Ranger cette conversation dans un projet';
    tag.onclick = () => choisirProjetPourConversation();
  }
}

function escapeHtml(s) { const d = document.createElement('div'); d.textContent = s || ''; return d.innerHTML; }

async function chargerProjetsSidebar() {
  const box = document.getElementById('asst-projets');
  try {
    const d = await fetch('/assistant/projets').then(r => r.json());
    PROJETS_CACHE = d.projets || [];
    if (!PROJETS_CACHE.length) { box.innerHTML = '<div class="asst-vide-side">Aucun projet. Crée-en un avec ＋.</div>'; return; }
    box.innerHTML = '';
    PROJETS_CACHE.forEach(p => {
      const el = document.createElement('div');
      el.className = 'asst-projet' + (FILTRE_PROJET === p.id ? ' actif' : '');
      el.innerHTML = '<span class="pp-dot" style="background:' + p.couleur + '"></span>'
        + '<span class="pp-nom">' + escapeHtml(p.nom) + '</span>'
        + '<span class="pp-nb">' + (p.conversations || 0) + '</span>';
      el.dataset.pid = p.id;     // zone de dépôt : glisser une conversation ici la range (S104)
      el.onclick = () => basculerFiltreProjet(p.id);
      el.ondblclick = () => ouvrirProjetModal(p.id);
      el.title = 'Cliquer : filtrer · double-clic ou clic droit : éditer · glisser une conversation ici pour la ranger';
      attacherMenu(el, () => [
        { label: 'Éditer le projet', emoji: '✎', fn: () => ouvrirProjetModal(p.id) },
        { label: 'Filtrer sur ce projet', emoji: '🔎', fn: () => basculerFiltreProjet(p.id) },
        { sep: true },
        { label: 'Supprimer le projet', emoji: '🗑', danger: true, fn: () => supprimerProjetParId(p.id) },
      ]);
      box.appendChild(el);
    });
  } catch(e) { box.innerHTML = '<div class="asst-vide-side">Erreur : ' + e.message + '</div>'; }
}

function basculerFiltreProjet(pid) {
  FILTRE_PROJET = (FILTRE_PROJET === pid) ? null : pid;
  document.getElementById('asst-convs-titre').textContent =
    FILTRE_PROJET ? 'Conversations du projet' : 'Conversations';
  chargerProjetsSidebar();
  chargerConversations();
}

async function chargerConversations() {
  const box = document.getElementById('asst-convs');
  try {
    const url = '/assistant/conversations' + (FILTRE_PROJET ? '?projet=' + encodeURIComponent(FILTRE_PROJET) : '');
    const d = await fetch(url).then(r => r.json());
    FILS_CACHE = d.fils || [];
    rendreConversations();
  } catch(e) { box.innerHTML = '<div class="asst-vide-side">Erreur : ' + e.message + '</div>'; }
}

let MONTRER_ARCHIVES = false;   // les conversations archivées sont masquées par défaut

function rendreConversations() {
  const box = document.getElementById('asst-convs');
  const q = (document.getElementById('asst-search').value || '').toLowerCase().trim();
  let fils = FILS_CACHE;
  if (q) fils = fils.filter(f => ((f.titre || '') + ' ' + (f.dernier || '')).toLowerCase().includes(q));
  const nbArch = fils.filter(f => f.archive).length;
  if (!MONTRER_ARCHIVES) fils = fils.filter(f => !f.archive);
  box.innerHTML = '';
  if (!fils.length) {
    box.innerHTML = '<div class="asst-vide-side">' + (q ? 'Aucun résultat.' : 'Aucune conversation. Écris un message pour démarrer.') + '</div>';
  }
  fils.forEach(f => {
    const el = document.createElement('div');
    el.className = 'conv' + (f.fil === filActifCourant() ? ' actif' : '') + (f.archive ? ' archivee' : '');
    el.dataset.fil = f.fil;
    const titre = f.titre || f.dernier || '(sans titre)';
    el.innerHTML = '<div class="conv-titre">' + badgeSurface(f.surface)
      + (f.epingle ? '<span class="conv-pin" title="Épinglée">📌</span>' : '')
      + '<span class="txt">' + escapeHtml(titre) + '</span></div>'
      + '<div class="conv-apercu">' + escapeHtml(f.dernier || '') + '</div>'
      + '<div class="conv-actions">'
      + '<button title="Plus…" onclick="event.stopPropagation();ouvrirMenuConv(event,\\'' + f.fil + '\\')">⋯</button>'
      + '</div>';
    el.dataset.id = f.fil;        // cible du cliquer-déposer (S104)
    el.onclick = () => ouvrirConversation(f);
    // Menu contextuel (clic droit / appui long) : mêmes actions que le bouton ⋯.
    attacherMenu(el, () => itemsMenuConv(f.fil));
    box.appendChild(el);
  });
  brancherDndConversations();
  // Bascule « voir les archivées » (n'apparaît que s'il y en a et qu'on filtre).
  if (nbArch && !q) {
    const t = document.createElement('div');
    t.className = 'asst-arch-toggle';
    t.textContent = MONTRER_ARCHIVES ? '▾ Masquer les archivées' : '▸ Archivées (' + nbArch + ')';
    t.onclick = () => { MONTRER_ARCHIVES = !MONTRER_ARCHIVES; rendreConversations(); };
    box.appendChild(t);
  }
}
function filActifCourant() { return CONV_SURFACE + ':' + CONV_ID; }
function filtrerConversations() { rendreConversations(); }

// S104 — cliquer-déposer dans l'Assistant : réordonner les conversations (persisté via
// /reordonner) ET glisser une conversation sur un projet (zone .asst-projet) pour la
// ranger. Pointer Events via le socle ; le tap court ouvre la conversation (inchangé).
// Le socle est idempotent : on peut rappeler ceci à chaque rendu sans empiler.
function brancherDndConversations() {
  if (typeof window.sortable !== 'function') return;
  window.sortable(document.getElementById('asst-convs'), {
    itemSelector: '.conv', zones: '.asst-projet',
    onReorder: (fils) => persistOrdreConversations(fils),
    onDropZone: (fil, zoneEl) => assignerProjetConversation(fil, zoneEl.dataset.pid),
  });
}
async function persistOrdreConversations(fils) {
  try {
    await fetch('/assistant/conversations/reordonner', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ fils: fils }) });
  } catch(e) { /* l'ordre reste appliqué visuellement ; resync au prochain chargement */ }
}

// Actions du menu contextuel d'une conversation (clic droit, appui long, ou bouton ⋯).
function itemsMenuConv(fil) {
  const f = FILS_CACHE.find(x => x.fil === fil) || {};
  return [
    { label: 'Renommer', emoji: '✎', fn: () => renommerConversation(fil) },
    { label: f.epingle ? 'Désépingler' : 'Épingler', emoji: '📌', fn: () => epinglerConversation(fil, !f.epingle) },
    { label: f.archive ? 'Désarchiver' : 'Archiver', emoji: '🗂', fn: () => archiverConversation(fil, !f.archive) },
    { label: 'Ranger dans un projet…', emoji: '📁', fn: () => rangerConversation(fil) },
    { sep: true },
    { label: 'Supprimer', emoji: '🗑', danger: true, fn: () => supprimerConversation(fil) },
  ];
}
function ouvrirMenuConv(ev, fil) {
  ev.stopPropagation();
  const r = ev.currentTarget.getBoundingClientRect();
  ouvrirMenu(r.left, r.bottom + 4, itemsMenuConv(fil));
}

async function ouvrirConversation(f) {
  const part = (f.fil || '').split(':');
  CONV_SURFACE = part[0] || 'web';
  CONV_ID = part.slice(1).join(':');
  CONV_PROJET = f.projet_id || null;
  try {
    const d = await fetch('/assistant/conversations?fil=' + encodeURIComponent(f.fil) + '&limite=200').then(r => r.json());
    const msgs = d.messages || [];
    CHAT_HIST.length = 0;
    const fil = document.getElementById('chat-fil');
    fil.innerHTML = '';
    msgs.forEach(m => {
      const role = m.role === 'user' ? 'user' : 'assistant';
      ajouterBulle(role, m.content || '');
      CHAT_HIST.push({ role: role, content: m.content || '' });
    });
    majEnteteConversation(f.titre || msgs[0] && msgs[0].content || 'Conversation');
  } catch(e) { ajouterBulle('assistant', '⚠ Impossible de charger : ' + e.message); }
  rendreConversations();
}

async function patchConversation(fil, corps) {
  await fetch('/assistant/conversations/' + encodeURIComponent(fil), {
    method: 'PATCH', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(corps)
  });
}

async function renommerConversation(fil) {
  const f = FILS_CACHE.find(x => x.fil === fil) || {};
  const titre = await demanderTexte({ titre: 'Renommer la conversation',
    message: 'Donnez-lui un nom plus parlant.', valeur: f.titre || '' });
  if (titre === null) return;
  await patchConversation(fil, { titre: titre });
  if (fil === filActifCourant()) majEnteteConversation(titre);
  chargerConversations();
}

async function epinglerConversation(fil, epingle) {
  await patchConversation(fil, { epingle: epingle });
  chargerConversations();
}

async function archiverConversation(fil, archive) {
  await patchConversation(fil, { archive: archive });
  chargerConversations();
}

// Ranger une conversation (par son fil) dans un projet : un second menu liste les projets.
function rangerConversation(fil) {
  const f = FILS_CACHE.find(x => x.fil === fil) || {};
  if (!PROJETS_CACHE.length) {
    confirmer({ titre: 'Aucun projet', message: 'Crée un projet pour y ranger des conversations ?',
      action: 'Créer un projet', danger: false }).then(ok => { if (ok) ouvrirProjetModal(); });
    return;
  }
  const items = PROJETS_CACHE.map(p => ({
    label: p.nom + (p.id === f.projet_id ? '  ✓' : ''), emoji: '📁',
    fn: () => assignerProjetConversation(fil, p.id),
  }));
  if (f.projet_id) items.push({ sep: true }, { label: 'Détacher du projet', emoji: '✖', fn: () => assignerProjetConversation(fil, null) });
  // Centré : pas de coordonnées de clic ici (vient d'un item de menu déjà fermé).
  ouvrirMenu(innerWidth / 2 - 95, innerHeight / 3, items);
}

async function assignerProjetConversation(fil, pid) {
  await patchConversation(fil, { projet_id: pid });
  if (fil === filActifCourant()) {
    CONV_PROJET = pid;
    majEnteteConversation(document.getElementById('asst-conv-titre').textContent);
  }
  chargerSidebarAssistant();
}

async function supprimerConversation(fil) {
  const f = FILS_CACHE.find(x => x.fil === fil) || {};
  const ok = await confirmer({ titre: 'Supprimer la conversation',
    message: 'Supprimer définitivement « ' + (f.titre || f.dernier || 'cette conversation') + ' » ? Cette action est irréversible.' });
  if (!ok) return;
  await fetch('/assistant/conversations/' + encodeURIComponent(fil), { method: 'DELETE' });
  if (fil === filActifCourant()) nouvelleConversation();
  chargerSidebarAssistant();
}

// Ranger la conversation COURANTE dans un projet (depuis l'étiquette d'en-tête) :
// réutilise le menu de choix de projet partagé avec le clic droit.
function choisirProjetPourConversation() {
  if (!CONV_ID) return;
  rangerConversation(filActifCourant());
}

// ── Modale projet (créer / éditer) ──────────────────────────────────────────────
async function ouvrirProjetModal(pid) {
  PROJET_EDIT = pid || null;
  const p = pid ? PROJETS_CACHE.find(x => x.id === pid) : null;
  document.getElementById('pm-titre').textContent = p ? 'Éditer le projet' : 'Nouveau projet';
  document.getElementById('pm-nom').value = p ? p.nom : '';
  document.getElementById('pm-instructions').value = p ? (p.instructions || '') : '';
  document.getElementById('pm-enregistrer').textContent = p ? 'Enregistrer' : 'Créer le projet';
  document.getElementById('pm-supprimer').style.display = p ? 'inline-block' : 'none';
  await rendreDocsProjet(p ? (p.documents || []) : []);
  document.getElementById('modal-projet').style.display = 'flex';
  setTimeout(() => document.getElementById('pm-nom').focus(), 50);
}
function fermerProjetModal() { document.getElementById('modal-projet').style.display = 'none'; }

// Documents = dossiers existants (projets + catégories de l'ETL), cochables.
async function rendreDocsProjet(selection) {
  const box = document.getElementById('pm-docs');
  let dossiers = { projets: {}, categories: {} };
  try { dossiers = await fetch('/assistant/dossiers').then(r => r.json()); } catch(e) {}
  const items = [];
  Object.keys(dossiers.projets || {}).forEach(n => items.push({ type: 'projet', nom: n }));
  Object.keys(dossiers.categories || {}).forEach(n => items.push({ type: 'categorie', nom: n }));
  if (!items.length) { box.innerHTML = '<span class="liv-sub">Aucun dossier disponible — l\\'assistant en crée en rangeant tes documents.</span>'; box.dataset.sel = '[]'; return; }
  const estSel = (it) => (selection || []).some(s => s.nom === it.nom && s.type === it.type);
  box.innerHTML = '';
  items.forEach(it => {
    const chip = document.createElement('span');
    chip.className = 'pm-doc' + (estSel(it) ? ' sel' : '');
    chip.textContent = (it.type === 'projet' ? '📁 ' : '🏷 ') + it.nom;
    chip.onclick = () => chip.classList.toggle('sel');
    chip.dataset.type = it.type; chip.dataset.nom = it.nom;
    box.appendChild(chip);
  });
}
function docsSelectionnes() {
  return Array.from(document.querySelectorAll('#pm-docs .pm-doc.sel'))
    .map(c => ({ type: c.dataset.type, nom: c.dataset.nom }));
}

async function enregistrerProjet() {
  const nom = document.getElementById('pm-nom').value.trim();
  if (!nom) { document.getElementById('pm-nom').focus(); return; }
  const corps = { nom: nom, instructions: document.getElementById('pm-instructions').value, documents: docsSelectionnes() };
  if (PROJET_EDIT) {
    await fetch('/assistant/projets/' + PROJET_EDIT, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps) });
  } else {
    await fetch('/assistant/projets', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(corps) });
  }
  fermerProjetModal();
  await chargerSidebarAssistant();
  if (CONV_PROJET) majEnteteConversation(document.getElementById('asst-conv-titre').textContent);
}

async function supprimerProjet() {
  if (!PROJET_EDIT) return;
  const id = PROJET_EDIT;
  fermerProjetModal();
  await supprimerProjetParId(id);
}

// Supprime un projet par son id (depuis la modale OU le menu contextuel de la sidebar).
async function supprimerProjetParId(pid) {
  const p = PROJETS_CACHE.find(x => x.id === pid) || {};
  const ok = await confirmer({ titre: 'Supprimer le projet',
    message: 'Supprimer « ' + (p.nom || 'ce projet') + ' » ? Ses conversations seront détachées (non supprimées).' });
  if (!ok) return;
  await fetch('/assistant/projets/' + pid, { method: 'DELETE' });
  if (FILTRE_PROJET === pid) FILTRE_PROJET = null;
  if (CONV_PROJET === pid) CONV_PROJET = null;
  chargerSidebarAssistant();
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

// ── Mail (client mail intégré, brique 6030) ────────────────────────────────────
// Chargement paresseux de l'iframe au 1er affichage de l'onglet.
const MAIL_UI_URL = '__MAIL_UI_URL__';
let mailCharge = false;
function chargerMail() {
  if (mailCharge) return;
  const f = document.getElementById('mail-iframe');
  if (f) { f.src = MAIL_UI_URL; mailCharge = true; }
}


// ── Atelier dev (S92) : IDE web code-server, chargé paresseusement au 1er affichage ──
const DEV_IDE_URL = '__DEV_IDE_URL__';
let devCharge = false;
function chargerDev() {
  if (devCharge) return;
  const f = document.getElementById('dev-iframe');
  if (f) { f.src = DEV_IDE_URL; devCharge = true; }
}

// ── Gateway (console LiteLLM, S93) : iframe chargée paresseusement au 1er affichage ──
const GATEWAY_UI_URL = '__GATEWAY_UI_URL__';
let gatewayCharge = false;
function chargerGateway() {
  if (gatewayCharge) return;
  const f = document.getElementById('gateway-iframe');
  if (f) { f.src = GATEWAY_UI_URL; gatewayCharge = true; }
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
const JOURS_COURT = ['Lun','Mar','Mer','Jeu','Ven','Sam','Dim'];
const MOIS = ['janvier','février','mars','avril','mai','juin','juillet','août','septembre','octobre','novembre','décembre'];
const MOIS_COURT = ['janv.','févr.','mars','avr.','mai','juin','juil.','août','sept.','oct.','nov.','déc.'];
const COULEURS_PALETTE = ['#5865F2','#3B82F6','#22c55e','#eab308','#f97316','#ef4444','#ec4899','#a855f7','#14b8a6','#64748b'];
const RAPPEL_PRESETS = [[0,"à l'heure"],[10,"10 min"],[30,"30 min"],[60,"1 h"],[1440,"1 jour"],[10080,"1 sem"]];
function libRappel(m){ if(m===0)return "à l'heure"; if(m<60)return m+" min"; if(m<1440)return (m/60)+" h"; if(m<10080)return (m/1440)+" j"; return (m/10080)+" sem"; }
function fmtHeure(iso){ const d=new Date(iso); return String(d.getHours()).padStart(2,'0')+':'+String(d.getMinutes()).padStart(2,'0'); }
function escAttr(s){ return escHtml(s).replace(/"/g,'&quot;'); }
function ymd(d){ const p=n=>String(n).padStart(2,'0'); return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate()); }
function isoToLocal(iso){ if(!iso) return ''; const d=new Date(iso); const p=n=>String(n).padStart(2,'0'); return d.getFullYear()+'-'+p(d.getMonth()+1)+'-'+p(d.getDate())+'T'+p(d.getHours())+':'+p(d.getMinutes()); }
function localToIso(v){ return v ? new Date(v).toISOString() : null; }
function lundiDe(d){ const x=new Date(d); const j=(x.getDay()+6)%7; x.setDate(x.getDate()-j); x.setHours(0,0,0,0); return x; }
function memeJour(a,b){ return a.getFullYear()===b.getFullYear()&&a.getMonth()===b.getMonth()&&a.getDate()===b.getDate(); }
function estImporte(ev){ return ev && (ev.calendrier==='TimeTree' || ev.calendrier==='Google'); }

let calRef = new Date();
let calModeActuel = 'mois';
let CALENDARS = [];
let EVENTS_CACHE = [];
let modalCouleur = '#5865F2';
let modalLabelId = '';        // étiquette nommée choisie dans la modale ('' = aucune)
let newLabelCouleur = '#5865F2';  // couleur de l'étiquette en cours de création inline

function calMode(m){ calModeActuel=m; const a=document.getElementById('cal-mode-mois'), b=document.getElementById('cal-mode-semaine'); if(a)a.classList.toggle('active',m==='mois'); if(b)b.classList.toggle('active',m==='semaine'); chargerAgenda(); }
function calAujourdhui(){ calRef=new Date(); chargerAgenda(); }
function calNav(dir){ if(calModeActuel==='mois'){ calRef.setMonth(calRef.getMonth()+dir); } else { calRef.setDate(calRef.getDate()+dir*7); } calRef=new Date(calRef); chargerAgenda(); }

async function chargerAgenda(){
  const cont=document.getElementById('cal-conteneur'); if(!cont) return;
  if(!CALENDARS.length){ try{ CALENDARS=(await fetch('/agenda/calendriers').then(r=>r.json())).calendriers||[]; }catch(e){} }
  let debut, fin, label;
  if(calModeActuel==='mois'){
    const first=new Date(calRef.getFullYear(),calRef.getMonth(),1);
    debut=lundiDe(first); fin=new Date(debut); fin.setDate(fin.getDate()+42);
    label=MOIS[calRef.getMonth()]+' '+calRef.getFullYear();
  } else {
    debut=lundiDe(calRef); fin=new Date(debut); fin.setDate(fin.getDate()+7);
    const l=new Date(debut); l.setDate(l.getDate()+6);
    label=debut.getDate()+' '+MOIS_COURT[debut.getMonth()]+' – '+l.getDate()+' '+MOIS_COURT[l.getMonth()]+' '+l.getFullYear();
  }
  const lab=document.getElementById('cal-label'); if(lab) lab.textContent=label;
  cont.innerHTML='<span class="liv-sub">Chargement…</span>';
  let evts=[];
  try{ evts=(await fetch('/agenda/evenements?debut='+encodeURIComponent(debut.toISOString())+'&fin='+encodeURIComponent(fin.toISOString())).then(r=>r.json())).evenements||[]; }
  catch(e){ cont.innerHTML='<span class="liv-sub">Agenda indisponible : '+e.message+'</span>'; return; }
  EVENTS_CACHE=evts;
  cont.innerHTML = calModeActuel==='mois' ? rendreMois(debut,evts) : rendreSemaine(debut,evts);
  rendreLegende();
}
function rendreLegende(){
  const box=document.getElementById('cal-legende'); if(!box) return;
  const seen=new Map();
  for(const e of EVENTS_CACHE){ if(e.etiquette && !seen.has(e.etiquette)) seen.set(e.etiquette, e.couleur||'#5865F2'); }
  if(!seen.size){ box.innerHTML=''; box.style.display='none'; return; }
  box.style.display='flex';
  box.innerHTML = '<span class="cal-leg-titre">Étiquettes :</span>' + Array.from(seen.entries())
    .map(([n,c])=>`<span class="cal-leg-chip"><span class="cal-leg-dot" style="background:${escAttr(c)}"></span>${escHtml(n)}</span>`).join('');
}
function eventsDuJour(evts,d){ return evts.filter(e=>memeJour(new Date(e.start_at),d)).sort((a,b)=>new Date(a.start_at)-new Date(b.start_at)); }
function chipEvent(e){
  const c=e.couleur||'#5865F2';
  const heure=e.all_day?'':fmtHeure(e.start_at)+' ';
  return `<div class="cal-chip" style="background:${escAttr(c)}" title="${escAttr((heure)+e.title)}" onclick="event.stopPropagation();ouvrirModaleEvent('${e.id}',null)">${escHtml(heure)}${escHtml(e.title)}</div>`;
}
function rendreMois(debut,evts){
  const today=new Date();
  let h='<div class="cal-grid">';
  for(const j of JOURS_COURT) h+=`<div class="cal-dow">${j}</div>`;
  for(let i=0;i<42;i++){
    const d=new Date(debut); d.setDate(d.getDate()+i);
    const autre=d.getMonth()!==calRef.getMonth();
    const jevts=eventsDuJour(evts,d), max=3;
    h+=`<div class="cal-cell${autre?' autre':''}${memeJour(d,today)?' aujourdhui':''}" onclick="ouvrirModaleEvent(null,'${ymd(d)}')">`;
    h+=`<span class="cal-num">${d.getDate()}</span>`;
    jevts.slice(0,max).forEach(e=>{ h+=chipEvent(e); });
    if(jevts.length>max) h+=`<span class="cal-plus">+${jevts.length-max}</span>`;
    h+='</div>';
  }
  return h+'</div>';
}
function rendreSemaine(debut,evts){
  const today=new Date();
  let h='<div class="cal-week">';
  for(let i=0;i<7;i++){
    const d=new Date(debut); d.setDate(d.getDate()+i);
    h+=`<div class="cal-wcol${memeJour(d,today)?' aujourdhui':''}" onclick="ouvrirModaleEvent(null,'${ymd(d)}')">`;
    h+=`<div class="cal-whead">${JOURS_COURT[i]} ${d.getDate()}</div>`;
    eventsDuJour(evts,d).forEach(e=>{
      const c=e.couleur||'#5865F2';
      h+=`<div class="cal-wevt" style="border-left-color:${escAttr(c)}" onclick="event.stopPropagation();ouvrirModaleEvent('${e.id}',null)"><span class="h">${e.all_day?'journée':fmtHeure(e.start_at)}</span>${escHtml(e.title)}</div>`;
    });
    h+='</div>';
  }
  return h+'</div>';
}

// ── Modale événement (créer / éditer + documents + commentaires) ─────────────
function fermerModale(){ const m=document.getElementById('event-modal'); if(m) m.innerHTML=''; }
function choisirCouleur(c){ modalCouleur=c; document.querySelectorAll('#event-modal .ev-swatch').forEach(s=>s.classList.toggle('sel', s.dataset.c===c)); }
function ouvrirModaleEvent(id, dateYMD){
  const ev = id ? EVENTS_CACHE.find(e=>e.id===id) : null;
  const ro = estImporte(ev);
  // Dates par défaut (création) : 09:00–10:00 le jour cliqué, sinon prochaine heure pleine.
  let dStart, dEnd;
  if(ev){ dStart=isoToLocal(ev.start_at); dEnd=isoToLocal(ev.end_at); }
  else if(dateYMD){ dStart=dateYMD+'T09:00'; dEnd=dateYMD+'T10:00'; }
  else { const n=new Date(); n.setMinutes(0,0,0); n.setHours(n.getHours()+1); const e2=new Date(n); e2.setHours(e2.getHours()+1); dStart=isoToLocal(n.toISOString()); dEnd=isoToLocal(e2.toISOString()); }
  modalCouleur = (ev && ev.color) || '#5865F2';
  modalLabelId = (ev && ev.label_id) || '';
  newLabelCouleur = '#5865F2';
  const calOptions = CALENDARS.filter(c=>c.name!=='TimeTree'&&c.name!=='Google').map(c=>`<option value="${escAttr(c.id)}" ${ev&&ev.calendar_id===c.id?'selected':''}>${escHtml(c.name)}</option>`).join('');
  const rappels = (ev&&ev.rappels)||[];
  const checks = RAPPEL_PRESETS.map(([m,lib])=>`<label style="font-weight:400;display:inline-flex;align-items:center;gap:4px;margin-right:10px;font-size:0.8rem"><input type="checkbox" class="ev-rap" value="${m}" ${rappels.includes(m)?'checked':''}> ${lib}</label>`).join('');
  const swatches = COULEURS_PALETTE.map(c=>`<span class="ev-swatch ${c===modalCouleur?'sel':''}" data-c="${c}" style="background:${c}" onclick="choisirCouleur('${c}')"></span>`).join('');
  const titre = ev ? (ro?'Événement (lecture seule)':'Modifier l\\'événement') : 'Nouveau rendez-vous';
  const dis = ro ? 'disabled' : '';
  let html = `<div class="modal-fond" onclick="if(event.target===this)fermerModale()"><div class="modal-boite">
    <button class="modal-fermer" onclick="fermerModale()">✕</button>
    <div class="modal-titre">${escHtml(titre)}</div>
    ${ro?`<div class="ev-ro">⚠ Importé de ${escHtml(ev.calendrier)} — modifiable seulement dans ${escHtml(ev.calendrier)}. Ici tu peux ajouter rappels, documents et commentaires.</div>`:''}
    <div class="ev-row"><label>Titre</label><input id="ev-titre" class="ev-in" ${dis} value="${ev?escAttr(ev.title):''}" placeholder="Titre du rendez-vous"></div>
    <div class="ev-2col">
      <div class="ev-row"><label>Début</label><input id="ev-debut" type="datetime-local" class="ev-in" ${dis} value="${dStart}"></div>
      <div class="ev-row"><label>Fin</label><input id="ev-fin" type="datetime-local" class="ev-in" ${dis} value="${dEnd}"></div>
    </div>
    <div class="ev-row"><label><input type="checkbox" id="ev-allday" ${dis} ${ev&&ev.all_day?'checked':''}> Journée entière</label></div>`;
  if(!ev || !ro){
    const newPal = COULEURS_PALETTE.map(c=>`<span class="ev-swatch ${c===newLabelCouleur?'sel':''}" data-nc="${c}" style="background:${c}" onclick="choisirNewLabelCouleur('${c}')"></span>`).join('');
    html += `<div class="ev-row"><label>Calendrier</label><select id="ev-cal" class="ev-in" ${dis} onchange="onCalChange()">${calOptions||'<option value="">Perso</option>'}</select></div>
    <div class="ev-row"><label>🏷 Étiquette</label>
      <select id="ev-label" class="ev-in" ${dis} onchange="onLabelChange()"><option value="">— chargement…</option></select>
      <div id="ev-newlabel" style="display:none;gap:8px;align-items:center;margin-top:8px;flex-wrap:wrap">
        <input id="ev-newlabel-nom" type="text" class="ev-in" style="max-width:200px" placeholder="Nom (ex. Famille)">
        <div class="ev-palette">${newPal}</div>
        <button class="btn" type="button" onclick="creerEtiquetteModale()">Créer</button>
        <button class="btn" type="button" style="opacity:.6" onclick="annulerNewLabel()">Annuler</button>
      </div>
    </div>
    <div class="ev-row" id="ev-couleur-row"><label>Couleur libre</label><div class="ev-palette">${swatches}</div></div>`;
  }
  html += `<div class="ev-row"><label>Lieu</label><input id="ev-lieu" class="ev-in" ${dis} value="${ev&&ev.location?escAttr(ev.location):''}" placeholder="Lieu (optionnel)"></div>
    <div class="ev-row"><label>Notes</label><textarea id="ev-notes" class="ev-in" ${dis} rows="2" placeholder="Notes (optionnel)">${ev&&ev.description?escHtml(ev.description):''}</textarea></div>
    <div class="ev-row"><label>🔔 Rappels</label><div>${checks}</div></div>
    <div class="modal-actions">
      ${ro?'':`<button class="btn" onclick="enregistrerEvent(${ev?`'${ev.id}'`:'null'})">${ev?'Enregistrer':'Créer'}</button>`}
      ${ev?`<button class="btn" style="opacity:.7" onclick="majRappelsModale('${ev.id}')">Enregistrer les rappels</button>`:''}
      ${ev&&!ro?`<button class="btn" style="background:#ef4444" onclick="supprimerEvent('${ev.id}')">Supprimer</button>`:''}
    </div>`;
  if(ev){
    html += `<div class="ev-sec"><h4>📎 Documents</h4><div id="ev-docs"><span class="liv-sub">Chargement…</span></div>
      <input type="file" id="ev-file" style="margin-top:8px;font-size:0.8rem">
      <button class="btn" style="margin-left:8px" onclick="uploadDoc('${ev.id}')">Joindre</button></div>
    <div class="ev-sec"><h4>💬 Commentaires</h4><div id="ev-comms"><span class="liv-sub">Chargement…</span></div>
      <div style="display:flex;gap:8px;margin-top:8px"><input id="ev-comm-in" class="ev-in" placeholder="Ajouter un commentaire…"><button class="btn" onclick="ajouterComm('${ev.id}')">Envoyer</button></div></div>`;
  }
  html += `</div></div>`;
  document.getElementById('event-modal').innerHTML = html;
  if(document.getElementById('ev-label')) chargerEtiquettesModale();
  if(ev){ chargerDocs(ev.id); chargerComm(ev.id); }
}
function currentCalId(){ const s=document.getElementById('ev-cal'); return s ? s.value : ''; }
async function chargerEtiquettesModale(){
  const cal=currentCalId(); const sel=document.getElementById('ev-label'); if(!sel) return;
  let labels=[];
  if(cal){ try{ labels=(await fetch('/agenda/calendriers/'+encodeURIComponent(cal)+'/etiquettes').then(r=>r.json())).etiquettes||[]; }catch(e){} }
  if(modalLabelId && !labels.some(l=>l.id===modalLabelId)) modalLabelId='';  // étiquette d'un autre calendrier → on détache
  sel.innerHTML = `<option value="">Aucune (couleur libre)</option>`
    + labels.map(l=>`<option value="${escAttr(l.id)}" ${l.id===modalLabelId?'selected':''}>${escHtml(l.name)}</option>`).join('')
    + `<option value="__new__">➕ Nouvelle étiquette…</option>`;
  appliquerEtatLabel();
}
function onCalChange(){ modalLabelId=''; chargerEtiquettesModale(); }
function onLabelChange(){
  const sel=document.getElementById('ev-label'); const v=sel.value;
  if(v==='__new__'){ const f=document.getElementById('ev-newlabel'); if(f) f.style.display='flex'; sel.value=modalLabelId||''; return; }
  modalLabelId=v; appliquerEtatLabel();
}
function appliquerEtatLabel(){
  // Quand une étiquette est choisie, sa couleur prime → on masque la palette libre.
  const row=document.getElementById('ev-couleur-row'); if(row) row.style.display = modalLabelId ? 'none' : '';
}
function choisirNewLabelCouleur(c){ newLabelCouleur=c; document.querySelectorAll('#ev-newlabel .ev-swatch').forEach(s=>s.classList.toggle('sel', s.dataset.nc===c)); }
function annulerNewLabel(){ const f=document.getElementById('ev-newlabel'); if(f) f.style.display='none'; }
async function creerEtiquetteModale(){
  const cal=currentCalId(); if(!cal){ alert("Choisis d'abord un calendrier."); return; }
  const nom=(document.getElementById('ev-newlabel-nom').value||'').trim(); if(!nom){ alert('Donne un nom.'); return; }
  try{
    const l=await fetch('/agenda/calendriers/'+encodeURIComponent(cal)+'/etiquettes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nom,color:newLabelCouleur})}).then(r=>r.json());
    if(l && l.id){ modalLabelId=l.id; annulerNewLabel(); document.getElementById('ev-newlabel-nom').value=''; await chargerEtiquettesModale(); }
    else alert('Échec : '+((l&&l.detail)||'inconnu'));
  }catch(e){ alert('Échec : '+e.message); }
}

// ── Mini-gestion des étiquettes (panneau depuis la toolbar) ──────────────────
async function ouvrirGestionEtiquettes(){
  if(!CALENDARS.length){ try{ CALENDARS=(await fetch('/agenda/calendriers').then(r=>r.json())).calendriers||[]; }catch(e){} }
  const cals=CALENDARS.filter(c=>c.name!=='TimeTree'&&c.name!=='Google');
  const opts=cals.map(c=>`<option value="${escAttr(c.id)}">${escHtml(c.name)}</option>`).join('')||'<option value="">Perso</option>';
  const html=`<div class="modal-fond" onclick="if(event.target===this)fermerGestionEtq()"><div class="modal-boite">
    <button class="modal-fermer" onclick="fermerGestionEtq()">✕</button>
    <div class="modal-titre">🏷 Gérer les étiquettes</div>
    <div class="ev-row"><label>Calendrier</label><select id="etq-cal" class="ev-in" onchange="chargerGestionEtq()">${opts}</select></div>
    <div id="etq-liste"><span class="liv-sub">Chargement…</span></div>
    <div class="ev-sec"><h4>Nouvelle étiquette</h4>
      <div class="etq-row">
        <input type="color" id="etq-new-col" value="#5865F2">
        <input type="text" id="etq-new-nom" placeholder="Nom (ex. Famille)">
        <button class="btn" onclick="ajouterGestionEtq()">Ajouter</button>
      </div>
    </div>
  </div></div>`;
  document.getElementById('label-modal').innerHTML=html;
  chargerGestionEtq();
}
function fermerGestionEtq(){ const m=document.getElementById('label-modal'); if(m) m.innerHTML=''; }
function gestionCalId(){ const s=document.getElementById('etq-cal'); return s?s.value:''; }
async function chargerGestionEtq(){
  const cal=gestionCalId(); const box=document.getElementById('etq-liste'); if(!box) return;
  let labels=[];
  if(cal){ try{ labels=(await fetch('/agenda/calendriers/'+encodeURIComponent(cal)+'/etiquettes').then(r=>r.json())).etiquettes||[]; }catch(e){} }
  box.innerHTML = labels.length ? labels.map(l=>`<div class="etq-row">
    <input type="color" value="${escAttr(l.color||'#5865F2')}" id="etq-col-${l.id}">
    <input type="text" value="${escAttr(l.name)}" id="etq-nom-${l.id}">
    <button class="btn" style="padding:4px 10px;font-size:.76rem" onclick="majGestionEtq('${l.id}')">💾</button>
    <button class="sup" title="Supprimer" onclick="supprGestionEtq('${l.id}')">🗑</button>
  </div>`).join('') : '<span class="liv-sub">Aucune étiquette pour ce calendrier.</span>';
}
async function majGestionEtq(id){
  const nom=(document.getElementById('etq-nom-'+id).value||'').trim();
  const col=document.getElementById('etq-col-'+id).value;
  if(!nom){ alert('Le nom ne peut pas être vide.'); return; }
  try{ await fetch('/agenda/etiquettes/'+encodeURIComponent(id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nom,color:col})}); chargerAgenda(); }
  catch(e){ alert('Échec : '+e.message); }
}
async function supprGestionEtq(id){
  if(!confirm("Supprimer cette étiquette ? Les événements concernés repasseront « sans étiquette ».")) return;
  try{ await fetch('/agenda/etiquettes/'+encodeURIComponent(id),{method:'DELETE'}); chargerGestionEtq(); chargerAgenda(); }
  catch(e){ alert('Échec : '+e.message); }
}
async function ajouterGestionEtq(){
  const cal=gestionCalId(); if(!cal){ alert('Choisis un calendrier.'); return; }
  const nom=(document.getElementById('etq-new-nom').value||'').trim(); const col=document.getElementById('etq-new-col').value;
  if(!nom){ alert('Donne un nom.'); return; }
  try{ await fetch('/agenda/calendriers/'+encodeURIComponent(cal)+'/etiquettes',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nom,color:col})}); document.getElementById('etq-new-nom').value=''; chargerGestionEtq(); chargerAgenda(); }
  catch(e){ alert('Échec : '+e.message); }
}
function rappelsCoches(){ return Array.from(document.querySelectorAll('#event-modal .ev-rap:checked')).map(c=>parseInt(c.value,10)); }
function corpsEvent(){
  const allday=document.getElementById('ev-allday').checked;
  return {
    title: document.getElementById('ev-titre').value.trim(),
    start_at: localToIso(document.getElementById('ev-debut').value),
    end_at: localToIso(document.getElementById('ev-fin').value),
    location: document.getElementById('ev-lieu').value.trim() || null,
    description: document.getElementById('ev-notes').value.trim() || null,
    color: modalCouleur, label_id: modalLabelId || '', all_day: allday, rappels: rappelsCoches()
  };
}
async function enregistrerEvent(id){
  const corps=corpsEvent();
  if(!corps.title){ alert('Donne un titre.'); return; }
  if(!corps.start_at||!corps.end_at){ alert('Indique début et fin.'); return; }
  try{
    if(id){ await fetch('/agenda/evenements/'+encodeURIComponent(id),{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify(corps)}); }
    else { const sel=document.getElementById('ev-cal'); corps.calendar_id=sel?sel.value:null; await fetch('/agenda/evenements',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(corps)}); }
    fermerModale(); chargerAgenda();
  }catch(e){ alert('Échec : '+e.message); }
}
async function majRappelsModale(id){
  try{ await fetch('/agenda/evenements/'+encodeURIComponent(id)+'/rappels',{method:'PATCH',headers:{'Content-Type':'application/json'},body:JSON.stringify({rappels:rappelsCoches()})}); fermerModale(); chargerAgenda(); }
  catch(e){ alert('Échec : '+e.message); }
}
async function supprimerEvent(id){
  if(!confirm('Supprimer cet événement ?')) return;
  try{ await fetch('/agenda/evenements/'+encodeURIComponent(id),{method:'DELETE'}); fermerModale(); chargerAgenda(); }
  catch(e){ alert('Échec : '+e.message); }
}
async function chargerDocs(id){
  const box=document.getElementById('ev-docs'); if(!box) return;
  try{
    const docs=(await fetch('/agenda/evenements/'+encodeURIComponent(id)+'/documents').then(r=>r.json())).documents||[];
    box.innerHTML = docs.length ? docs.map(d=>`<div class="ev-doc"><a href="/agenda/documents/${encodeURIComponent(d.id)}" target="_blank">${escHtml(d.filename)}</a><span class="liv-sub">${Math.round((d.size_bytes||0)/1024)} Ko</span><button class="sup" onclick="supprDoc('${d.id}','${id}')">✕</button></div>`).join('') : '<span class="liv-sub">Aucun document.</span>';
  }catch(e){ box.innerHTML='<span class="liv-sub">Erreur de chargement.</span>'; }
}
async function uploadDoc(id){
  const f=document.getElementById('ev-file'); if(!f||!f.files.length){ alert('Choisis un fichier.'); return; }
  const fd=new FormData(); fd.append('file', f.files[0]);
  try{ await fetch('/agenda/evenements/'+encodeURIComponent(id)+'/documents',{method:'POST',body:fd}); f.value=''; chargerDocs(id); }
  catch(e){ alert('Échec upload : '+e.message); }
}
async function supprDoc(attId,id){ if(!confirm('Supprimer ce document ?'))return; try{ await fetch('/agenda/documents/'+encodeURIComponent(attId),{method:'DELETE'}); chargerDocs(id); }catch(e){} }
async function chargerComm(id){
  const box=document.getElementById('ev-comms'); if(!box) return;
  try{
    const cs=(await fetch('/agenda/evenements/'+encodeURIComponent(id)+'/commentaires').then(r=>r.json())).commentaires||[];
    box.innerHTML = cs.length ? cs.map(c=>`<div class="ev-comm">${escHtml(c.content)}<div class="meta">${new Date(c.created_at).toLocaleString('fr-FR')} <button class="sup" style="border:none;background:none;color:#ef4444;cursor:pointer" onclick="supprComm('${c.id}','${id}')">supprimer</button></div></div>`).join('') : '<span class="liv-sub">Aucun commentaire.</span>';
  }catch(e){ box.innerHTML='<span class="liv-sub">Erreur de chargement.</span>'; }
}
async function ajouterComm(id){
  const inp=document.getElementById('ev-comm-in'); const v=inp.value.trim(); if(!v) return;
  try{ await fetch('/agenda/evenements/'+encodeURIComponent(id)+'/commentaires',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({contenu:v})}); inp.value=''; chargerComm(id); }
  catch(e){ alert('Échec : '+e.message); }
}
async function supprComm(cId,id){ try{ await fetch('/agenda/commentaires/'+encodeURIComponent(cId),{method:'DELETE'}); chargerComm(id); }catch(e){} }

// ── Pont Google Agenda (consenti, lecture seule, OAuth) ──────────────────────
async function chargerGoogle() {
  const p = document.getElementById('g-panel'); if (!p) return;
  let st = {connected:false};
  try { st = await fetch('/agenda/google/status').then(r=>r.json()); } catch(e) {}
  p.style.display = 'flex';
  if (st.connected) {
    p.innerHTML = `<span class="tt-dot"></span> Google Agenda connecté — lecture seule, consenti
      <button class="btn" onclick="gSync()">Synchroniser</button>
      <button class="btn" style="opacity:.7" onclick="gDisconnect()">Déconnecter</button>
      <span id="g-msg" class="liv-sub"></span>`;
  } else {
    p.innerHTML = `<span class="tt-dot tt-off"></span> Google Agenda non connecté — pull consenti, lecture seule
      <button class="btn" onclick="gConnect()">Connecter Google</button>
      <span id="g-msg" class="liv-sub"></span>`;
  }
}
async function gConnect() {
  const msg = document.getElementById('g-msg'); if (msg) msg.textContent = 'Ouverture du consentement Google…';
  try {
    const r = await fetch('/agenda/google/connect').then(r=>r.json());
    if (!r.ok || !r.authorization_url) { if (msg) msg.textContent = 'Indisponible : ' + (r.erreur || 'pont Google non configuré'); return; }
    window.open(r.authorization_url, '_blank');
    if (msg) msg.textContent = 'Autorise dans l\\'onglet Google, puis reviens et clique « Synchroniser ».';
  } catch(e) { if (msg) msg.textContent = 'Erreur : ' + e.message; }
}
async function gSync() {
  const msg = document.getElementById('g-msg'); if (msg) msg.textContent = 'Synchronisation…';
  try {
    const r = await fetch('/agenda/google/sync', {method:'POST'}).then(r=>r.json());
    if (msg) msg.textContent = (r.ok === false) ? ('Échec : ' + (r.erreur || '')) : `✓ ${r.created||0} ajout(s), ${r.updated||0} maj`;
    chargerGoogle(); chargerAgenda();
  } catch(e) { if (msg) msg.textContent = 'Erreur : ' + e.message; }
}
async function gDisconnect() {
  if (!confirm('Déconnecter Google et oublier les jetons ?')) return;
  try { await fetch('/agenda/google/disconnect', {method:'DELETE'}); } catch(e) {}
  chargerGoogle(); chargerAgenda();
}

// ── Pont TimeTree (agenda partagé, lecture seule) ────────────────────────────
async function chargerTimeTree() {
  const p = document.getElementById('tt-panel'); if (!p) return;
  let st = {connected:false};
  try { st = await fetch('/agenda/timetree/status').then(r=>r.json()); } catch(e) {}
  p.style.display = 'flex';
  if (st.connected) {
    const calTxt = st.calendar_id ? ` (calendrier ${escHtml(String(st.calendar_id))})` : ' — choisis un calendrier';
    p.innerHTML = `<span class="tt-dot"></span> TimeTree connecté${calTxt}
      <button class="btn" onclick="ttSync()">Synchroniser</button>
      <button class="btn" style="opacity:.7" onclick="ttDisconnect()">Déconnecter</button>
      <span id="tt-msg" class="liv-sub"></span>`;
  } else {
    p.innerHTML = `<span class="tt-dot tt-off"></span> TimeTree (agenda partagé) non connecté — lecture seule, non officiel
      <input id="tt-email" placeholder="email TimeTree" class="agenda-select" style="min-width:150px">
      <input id="tt-pass" type="password" placeholder="mot de passe" class="agenda-select" style="min-width:130px">
      <button class="btn" onclick="ttConnect()">Connecter</button>
      <span id="tt-msg" class="liv-sub"></span>`;
  }
}
async function ttConnect() {
  const email = document.getElementById('tt-email').value.trim();
  const password = document.getElementById('tt-pass').value;
  const msg = document.getElementById('tt-msg');
  if (!email || !password) { msg.textContent = 'Email et mot de passe requis.'; return; }
  msg.textContent = 'Connexion…';
  try {
    const r = await fetch('/agenda/timetree/connect', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({email, password})}).then(r=>r.json());
    if (!r.connected) { msg.textContent = 'Échec : ' + (r.erreur || 'identifiants invalides ?'); return; }
    const cals = r.calendars || [];
    if (!cals.length) { msg.textContent = 'Connecté, mais aucun calendrier trouvé.'; return; }
    const liste = cals.map((c,i)=>`${i+1}. ${c.name}`).join('\\n');
    const choix = prompt('Quel calendrier synchroniser ?\\n' + liste + '\\n\\nEntre le numéro :');
    const idx = parseInt(choix, 10) - 1;
    if (isNaN(idx) || idx < 0 || idx >= cals.length) { chargerTimeTree(); return; }
    await fetch('/agenda/timetree/select', {method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({calendar_id: cals[idx].id})});
    await ttSync();
    chargerTimeTree();
  } catch(e) { msg.textContent = 'Erreur : ' + e.message; }
}
async function ttSync() {
  const msg = document.getElementById('tt-msg'); if (msg) msg.textContent = 'Synchronisation…';
  try {
    const r = await fetch('/agenda/timetree/sync', {method:'POST'}).then(r=>r.json());
    if (msg) msg.textContent = (r.ok === false) ? ('Échec : ' + (r.erreur || '')) : `✓ ${r.created||0} ajout(s), ${r.updated||0} maj`;
    chargerAgenda();
  } catch(e) { if (msg) msg.textContent = 'Erreur : ' + e.message; }
}
async function ttDisconnect() {
  if (!confirm('Déconnecter TimeTree et oublier les identifiants ?')) return;
  try { await fetch('/agenda/timetree/disconnect', {method:'DELETE'}); } catch(e) {}
  chargerTimeTree(); chargerAgenda();
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
    // Clés des autres fournisseurs (Anthropic, Groq, OpenCode Go…) — OpenRouter a son champ dédié.
    const zoneF = document.getElementById('cerveau-cles-fournisseurs');
    if (zoneF) {
      const fs = (c.cles_fournisseurs || []).filter(f => f.id !== 'openrouter');
      zoneF.innerHTML = fs.map(f => `
        <div class="cerveau-row" style="margin-top:6px;align-items:flex-end">
          <div class="field" style="flex:1">
            <label style="font-size:0.82rem">${f.label} <span class="cerveau-pill">${f.definie ? '● définie' : '● absente'}</span></label>
            <input type="password" id="cle-f-${f.id}" placeholder="${f.placeholder}" autocomplete="off">
          </div>
          <button class="btn ghost" onclick="enregistrerCleFournisseur('${f.id}')">Enregistrer</button>
        </div>`).join('') || '<div class="liv-sub">Aucun fournisseur additionnel.</div>';
    }
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

async function enregistrerCleFournisseur(id) {
  const inp = document.getElementById('cle-f-' + id);
  const cle = (inp && inp.value || '').trim();
  if (!cle) { cerveauMsg('Saisis une clé pour ' + id + '.', 'ko'); return; }
  cerveauMsg('Enregistrement de la clé « ' + id + ' », redémarrage de la Gateway… (~15 s)', 'info');
  try {
    const r = await fetch('/assistant/cle-fournisseur', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ fournisseur: id, cle })
    }).then(r => r.json());
    if (r.ok) { cerveauMsg('✔ Clé « ' + id + ' » enregistrée, la Gateway a redémarré. Choisis son modèle dans « Modèle LLM ».', 'ok'); if (inp) inp.value = ''; }
    else cerveauMsg('⚠ Échec (' + (r.etape || '?') + ') : ' + (r.detail || ''), 'ko');
    await chargerCerveau(true);
  } catch(e) { cerveauMsg('Échec : ' + e.message, 'ko'); }
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
    const AIDE_COUCHE = {
      frontend: "Les briques qui ont un écran ou une page à ouvrir et utiliser directement (ex. l'agenda, le mail, le studio).",
      backend:  "Les briques « moteurs » : elles travaillent en coulisse pour les autres (mémoire, voix, recherche…), sans écran à elles."
    };
    [['frontend', 'Frontend'], ['backend', 'Backend']].forEach(([cle, titre]) => {
      const items = parCouche[cle];
      if (!items.length) return;
      const cartes = items.map(({ b, h }) => carteHTML(b, h)).join('');
      const aide = `<span class="aide aide-clair" tabindex="0">i<span class="aide-txt">${AIDE_COUCHE[cle]}</span></span>`;
      groupes.insertAdjacentHTML('beforeend',
        `<div class="groupe-couche"><h3 class="groupe-titre">${titre}${aide}` +
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
  return `<div class="liv-card" data-liv-id="${l.id}">
    <div class="liv-head">
      <div>
        <div class="liv-title">${l.nom_entreprise || 'Entreprise'}</div>
        <div class="liv-sub">${extra} · ${new Date(l.date_creation).toLocaleString('fr-FR')}</div>
      </div>
      <span class="liv-statut liv-${l.statut}">${ {en_cours:'En cours', livree:'Livrée', erreur:'Erreur', decrochee:'De côté'}[l.statut] || l.statut }</span>
    </div>
    ${steps}
    ${err}${links}
    <div class="liv-suppr"><button class="btn danger" onclick="supprimerApp('${l.id}')">Supprimer</button></div>
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

// Suppression définitive d'une app : gate par SAISIE du mot « SUPPRIMER » (anti-clic
// accidentel, plus fort qu'un simple confirm). On lit le nom depuis la carte (pas
// d'injection dans l'onclick).
async function supprimerApp(id) {
  const carte = document.querySelector('[data-liv-id="' + id + '"]');
  const nom = carte ? carte.querySelector('.liv-title').textContent.trim() : 'cette app';
  const saisie = prompt('Supprimer définitivement « ' + nom + ' » ?\\n\\n'
    + 'Cette action retire l\\'app de l\\'usine et est IRRÉVERSIBLE.\\n'
    + 'Pour confirmer, tape SUPPRIMER (en majuscules) :');
  if (saisie === null) return;                       // annulé
  if (saisie.trim() !== 'SUPPRIMER') { alert('Suppression annulée : le mot saisi ne correspond pas.'); return; }
  try {
    const r = await fetch('/usine/livraisons/' + id, { method: 'DELETE' });
    if (!r.ok && r.status !== 204) throw new Error(await r.text());
    await chargerLivraisons();
  } catch(err) { alert('Échec de la suppression : ' + err.message); }
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
// Actions suggérées (S76) : boutons d'action génériques. Un tap = on injecte le message
// `envoi` dans le chat (le LLM reprend la main) ; le gate humain n'est jamais court-circuité.
function ajouterActions(actions) {
  if (!actions || !actions.length) return;
  const fil = document.getElementById('chat-fil');
  const row = document.createElement('div');
  row.className = 'actions';
  actions.forEach((a, i) => {
    const b = document.createElement('button');
    b.type = 'button';
    if (i === 0) b.className = 'primaire';
    b.textContent = a.label;
    b.onclick = () => { row.classList.add('fait'); taperAction(a.envoi); };
    row.appendChild(b);
  });
  fil.appendChild(row); chatEcho();
}
function taperAction(envoi) {
  const input = document.getElementById('chat-input');
  input.value = envoi;
  document.getElementById('chat-form').requestSubmit();
}
async function envoyerMessage(e) {
  e.preventDefault();
  const input = document.getElementById('chat-input');
  const texte = input.value.trim();
  if (!texte) return false;
  input.value = '';
  // Toujours dans une conversation : si aucune n'est ouverte, on en démarre une.
  if (!CONV_ID) nouvelleConversation();
  const premierMessage = CHAT_HIST.length === 0;
  document.getElementById('chat-btn').classList.add('loading');
  ajouterBulle('user', texte);
  CHAT_HIST.push({ role:'user', content: texte });
  if (premierMessage) majEnteteConversation(texte.length > 48 ? texte.slice(0, 48) + '…' : texte);

  const fil = document.getElementById('chat-fil');
  const tip = document.createElement('div');
  tip.className = 'typing'; tip.textContent = 'L\\'assistant réfléchit…';
  fil.appendChild(tip); chatEcho();

  let bulleAssist = null, texteFinal = '';
  try {
    const r = await fetch('/assistant/chat', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({ messages: CHAT_HIST, surface: CONV_SURFACE,
                             interlocuteur: CONV_ID, projet_id: CONV_PROJET })
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
        else if (evt.type === 'actions') { ajouterActions(evt.actions); }
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
    // La conversation courante a été journalisée → la sidebar reflète le titre auto + l'aperçu.
    chargerConversations().catch(()=>{});
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
        <div class="card-version">v${b.version}${b.port ? ` · <span class="port-pill" title="Port utilisé par la brique">:${b.port}</span>` : ''}</div>
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


router = APIRouter()


@router.get("/dashboard", tags=["système"], response_class=HTMLResponse)
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
        .replace("__TRANSCRIPTION_UI_URL__", TRANSCRIPTION_UI_URL)
        .replace("__RESTAURANT_UI_URL__", RESTAURANT_UI_URL)
        .replace("__MAIL_UI_URL__", MAIL_UI_URL)
        .replace("__SYNOPSIS_UI_URL__", SYNOPSIS_UI_URL)
        .replace("__VOIX_UI_URL__", VOIX_UI_URL)
        .replace("__MEMOIRE_UI_URL__", MEMOIRE_UI_URL)
        .replace("__DEV_IDE_URL__", DEV_IDE_URL)
        .replace("__GENERATEUR_BUNDLES_URL__", f"{GENERATEUR_URL_PUBLIQUE}/bundles-studio")
        .replace("__GATEWAY_UI_URL__", GATEWAY_UI_URL))
