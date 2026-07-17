"""Page HTML de l'application agenda autonome (S172) — /app.

Auto-suffisante, comme `templates.py` (page d'invitation) : aucune dépendance externe,
PKCE écrit à la main. Contrairement à la page d'invitation (usage ponctuel), l'appli sert
un usage quotidien : le refresh_token est gardé en localStorage (persiste entre
rechargements), rafraîchi silencieusement au chargement — même logique que
`core/auth.py::exiger_session`, mais côté client (pas de cookie/session serveur ici,
appels JSON directs en `Authorization: Bearer`).
"""

import json

_PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="manifest" href="/app/manifest.webmanifest">
<meta name="theme-color" content="#1A1612">
<title>Agenda</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; font: 15px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; }
  header { display: flex; align-items: center; justify-content: space-between; gap: 12px;
           padding: 14px 20px; border-bottom: 1px solid #2d3148; }
  header h1 { font-size: 18px; margin: 0; }
  main { padding: 20px; max-width: 960px; margin: 0 auto; }
  .card { background: #1e293b; border: 1px solid #334155; border-radius: 12px; padding: 20px; }
  .centre { display: grid; place-items: center; min-height: 70vh; }
  button { border: 0; border-radius: 8px; background: #3b82f6; color: #fff; font-size: 14px;
           font-weight: 600; padding: 9px 16px; cursor: pointer; }
  button:hover { background: #2563eb; }
  button.ghost { background: transparent; border: 1px solid #334155; color: #e2e8f0; }
  select, input { background: #141a26; color: #e2e8f0; border: 1px solid #2d3148; border-radius: 8px;
                  padding: 7px 10px; font-size: 14px; }
  .muted { color: #94a3b8; font-size: 13px; }
  .err { color: #f87171; }
  .barre { display: flex; align-items: center; gap: 10px; margin-bottom: 16px; flex-wrap: wrap; }
  .onglets { display: flex; gap: 8px; padding: 10px 20px; border-bottom: 1px solid #2d3148; }
  .onglets button { background: transparent; border: 1px solid #334155; color: #e2e8f0; }
  .onglets button.actif { background: #3b82f6; border-color: #3b82f6; }
  /* Listes de courses (S176) */
  .listes-layout { display: grid; grid-template-columns: 240px 1fr; gap: 16px; }
  @media (max-width: 640px) { .listes-layout { grid-template-columns: 1fr; } }
  .liste-item { display: flex; justify-content: space-between; width: 100%; margin-bottom: 6px; text-align: left; }
  .liste-item .badge { background: #0f172a; border-radius: 10px; padding: 0 8px; font-size: 12px; }
  .item { display: flex; align-items: center; gap: 8px; padding: 8px 10px; border-bottom: 1px solid #263043; cursor: pointer; }
  .item.coche { opacity: .5; text-decoration: line-through; }
  .rayon-titre { margin: 14px 0 4px; font-size: 13px; color: #94a3b8; text-transform: uppercase; letter-spacing: .04em; }
  .grille { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 10px; }
  .cat { background: #141a26; border: 1px solid #2d3148; color: #e2e8f0; font-weight: 500; }
  .cat:hover { background: #1e293b; }
  /* Cartes de fidélité (S176) */
  .cartes-grille { display: flex; flex-wrap: wrap; gap: 12px; }
  .carte { width: 150px; height: 90px; border-radius: 12px; color: #fff; font-weight: 700;
           display: flex; align-items: center; justify-content: center; text-align: center; }
  .modal { position: fixed; inset: 0; background: rgba(0,0,0,.7); display: none;
           align-items: center; justify-content: center; z-index: 50; }
  .modal .contenu { background: #fff; color: #111; border-radius: 16px; padding: 24px; max-width: 92vw; text-align: center; }
  .modal svg { width: 320px; max-width: 80vw; height: 120px; }
</style>
</head>
<body>
<header>
  <h1>📅 Agenda</h1>
  <div id="entete-droite"></div>
</header>
<nav id="onglets" class="onglets" hidden></nav>
<main id="main"><div class="centre muted">Chargement…</div></main>
<div id="carte-modal" class="modal">
  <div class="contenu">
    <h3 id="carte-enseigne" style="margin:0 0 12px"></h3>
    <svg id="carte-barcode" viewBox="0 0 200 100" preserveAspectRatio="none"></svg>
    <p id="carte-numero" style="font:600 18px monospace;letter-spacing:.1em"></p>
    <p id="carte-fallback" class="muted" style="display:none">Code-barres non généré — saisir le numéro à la main.</p>
    <button onclick="fermerCarte()">Fermer</button>
  </div>
</div>
<script src="/static/barcode.js"></script>
<script>
const KC = %%KC%%;
const REDIRECT = location.origin + location.pathname;
const LS_REFRESH = "agenda_refresh_token";
let ACCESS_TOKEN = null;

const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const rand = (n) => { const a = new Uint8Array(n); crypto.getRandomValues(a); return b64url(a.buffer); };
const sha256 = (s) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function afficherLogin(erreur) {
  document.getElementById("main").innerHTML =
    '<div class="centre"><div class="card" style="text-align:center">' +
    (erreur ? '<p class="err">' + esc(erreur) + '</p>' : '') +
    '<p>Connecte-toi pour voir ton agenda.</p>' +
    '<button id="btn-login">Se connecter</button></div></div>';
  document.getElementById("btn-login").onclick = login;
  document.getElementById("entete-droite").innerHTML = "";
}

async function login() {
  const verifier = rand(32), state = rand(16);
  sessionStorage.setItem("pkce_verifier", verifier);
  sessionStorage.setItem("pkce_state", state);
  const challenge = b64url(await sha256(verifier));
  const p = new URLSearchParams({
    client_id: KC.clientId, response_type: "code", scope: "openid",
    redirect_uri: REDIRECT, state, code_challenge: challenge, code_challenge_method: "S256",
  });
  location.href = `${KC.url}/realms/${KC.realm}/protocol/openid-connect/auth?${p}`;
}

async function echangerCode(code) {
  const verifier = sessionStorage.getItem("pkce_verifier");
  const body = new URLSearchParams({
    grant_type: "authorization_code", code, redirect_uri: REDIRECT,
    client_id: KC.clientId, code_verifier: verifier,
  });
  return tokenRequest(body);
}

async function rafraichir(refreshToken) {
  const body = new URLSearchParams({
    grant_type: "refresh_token", client_id: KC.clientId, refresh_token: refreshToken,
  });
  return tokenRequest(body);
}

async function tokenRequest(body) {
  const r = await fetch(`${KC.url}/realms/${KC.realm}/protocol/openid-connect/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
  });
  if (!r.ok) return null;
  return r.json();
}

function poserSession(tokens) {
  ACCESS_TOKEN = tokens.access_token;
  localStorage.setItem(LS_REFRESH, tokens.refresh_token);
}

function deconnecter() {
  localStorage.removeItem(LS_REFRESH);
  ACCESS_TOKEN = null;
  afficherLogin();
}

async function api(path, opts = {}) {
  const headers = Object.assign({ Authorization: "Bearer " + ACCESS_TOKEN }, opts.headers || {});
  const r = await fetch(path, Object.assign({}, opts, { headers }));
  if (r.status === 401) { deconnecter(); throw new Error("session expirée"); }
  if (!r.ok) throw new Error("erreur " + r.status);
  if (r.status === 204) return null;
  return r.json();
}

async function demarrer() {
  const params = new URLSearchParams(location.search);
  const code = params.get("code"), state = params.get("state");

  if (code) {
    history.replaceState({}, "", REDIRECT);
    if (state !== sessionStorage.getItem("pkce_state")) {
      afficherLogin("Échec de la connexion. Réessayez.");
      return;
    }
    const tokens = await echangerCode(code);
    if (!tokens) { afficherLogin("Échec de la connexion. Réessayez."); return; }
    poserSession(tokens);
    await chargerApp();
    await initPWA();
    return;
  }

  const refresh = localStorage.getItem(LS_REFRESH);
  if (!refresh) { afficherLogin(); return; }
  const tokens = await rafraichir(refresh);
  if (!tokens) { afficherLogin("Session expirée. Reconnecte-toi."); return; }
  poserSession(tokens);
  await chargerApp();
  await initPWA();
}

async function chargerApp() {
  document.getElementById("entete-droite").innerHTML =
    '<button class="ghost" id="btn-logout">Se déconnecter</button>';
  document.getElementById("btn-logout").onclick = deconnecter;
  try { await api("/profiles/me", { method: "POST" }); } catch (e) { /* best-effort */ }
  const nav = document.getElementById("onglets");
  nav.hidden = false;
  nav.innerHTML =
    '<button data-vue="agenda" onclick="montrerVue(\'agenda\')">📅 Agenda</button>' +
    '<button data-vue="listes" onclick="montrerVue(\'listes\')">🛒 Listes</button>' +
    '<button data-vue="sondages" onclick="montrerVue(\'sondages\')">📊 Sondages</button>' +
    '<button data-vue="cartes" onclick="montrerVue(\'cartes\')">💳 Cartes</button>' +
    '<button data-vue="reglages" onclick="montrerVue(\'reglages\')">⚙️ Réglages</button>';
  montrerVue("agenda");
}

function montrerVue(nom) {
  for (const b of document.querySelectorAll("#onglets button"))
    b.classList.toggle("actif", b.dataset.vue === nom);
  if (nom !== "listes" && SSE_LISTE) { SSE_LISTE.close(); SSE_LISTE = null; }
  if (nom === "agenda") chargerCalendriers();
  else if (nom === "listes") vueListes();
  else if (nom === "sondages") vueSondages();
  else if (nom === "cartes") vueCartes();
  else if (nom === "reglages") vueReglages();
}

let CALENDARS = [];
let CAL_ACTIF = null;

let PROFILS = {};
async function resoudreProfils(userIds) {
  const manquants = userIds.filter((u) => !PROFILS[u]);
  if (manquants.length) {
    try {
      const arr = await api("/profiles?user_ids=" + encodeURIComponent(manquants.join(",")));
      for (const p of arr) PROFILS[p.user_id] = p;
    } catch (e) { /* défaut ci-dessous */ }
  }
  const out = {};
  for (const u of userIds) out[u] = PROFILS[u] || { user_id: u, display_name: u, avatar_color: "#64748b" };
  return out;
}
function pastille(color) {
  return `<span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:${color};margin-right:6px;vertical-align:middle"></span>`;
}

async function chargerCalendriers() {
  try {
    CALENDARS = await api("/calendars");
  } catch (e) {
    document.getElementById("main").innerHTML = '<p class="err">Erreur : ' + esc(e.message) + "</p>";
    return;
  }
  if (!CALENDARS.length) {
    document.getElementById("main").innerHTML =
      '<div class="card"><p class="muted">Aucun agenda partagé avec toi pour l\'instant.</p></div>';
    return;
  }
  if (!CAL_ACTIF || !CALENDARS.some((c) => c.id === CAL_ACTIF)) CAL_ACTIF = CALENDARS[0].id;
  rendreBarre();
  await chargerVue();
}

function rendreBarre() {
  const options = CALENDARS.map((c) =>
    `<option value="${esc(c.id)}" ${c.id === CAL_ACTIF ? "selected" : ""}>${esc(c.name)} (${esc(c.role)})</option>`
  ).join("");
  const role = (CALENDARS.find((c) => c.id === CAL_ACTIF) || {}).role;
  document.getElementById("main").innerHTML =
    '<div class="barre">' +
    `<select id="sel-cal">${options}</select>` +
    (role === "owner" ? '<button id="btn-inviter">Inviter</button>' : "") +
    '</div><div id="zone-vue"></div>';
  document.getElementById("sel-cal").onchange = (e) => { CAL_ACTIF = e.target.value; rendreBarre(); chargerVue(); };
  const btnInviter = document.getElementById("btn-inviter");
  if (btnInviter) btnInviter.onclick = ouvrirModaleInviter;
}

const JOURS_COURT = ["Lun","Mar","Mer","Jeu","Ven","Sam","Dim"];
const MOIS = ["janvier","février","mars","avril","mai","juin","juillet","août","septembre","octobre","novembre","décembre"];
const COULEURS = ["#5865F2","#3B82F6","#22c55e","#eab308","#f97316","#ef4444","#ec4899","#a855f7"];

let calRef = new Date();
let EVENTS_CACHE = [];
let LABELS_CACHE = [];
let modalCouleur = "#5865F2";
let modalLabelId = "";

function ymd(d) { const p = (n) => String(n).padStart(2, "0"); return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate()); }
function isoToLocal(iso) { const d = new Date(iso); const p = (n) => String(n).padStart(2, "0"); return d.getFullYear()+"-"+p(d.getMonth()+1)+"-"+p(d.getDate())+"T"+p(d.getHours())+":"+p(d.getMinutes()); }
function localToIso(v) { return v ? new Date(v).toISOString() : null; }
function lundiDe(d) { const x = new Date(d); const j = (x.getDay()+6)%7; x.setDate(x.getDate()-j); x.setHours(0,0,0,0); return x; }
function memeJour(a, b) { return a.getFullYear()===b.getFullYear() && a.getMonth()===b.getMonth() && a.getDate()===b.getDate(); }
function fmtHeure(iso) { const d = new Date(iso); return String(d.getHours()).padStart(2,"0")+":"+String(d.getMinutes()).padStart(2,"0"); }
function eventsDuJour(d) { return EVENTS_CACHE.filter((e) => memeJour(new Date(e.start_at), d)).sort((a,b) => new Date(a.start_at)-new Date(b.start_at)); }

async function chargerVue() {
  const zone = document.getElementById("zone-vue");
  zone.innerHTML = '<p class="muted">Chargement…</p>';
  const first = new Date(calRef.getFullYear(), calRef.getMonth(), 1);
  const debut = lundiDe(first), fin = new Date(debut); fin.setDate(fin.getDate()+42);
  try {
    EVENTS_CACHE = await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/events?start=${debut.toISOString()}&end=${fin.toISOString()}`);
    LABELS_CACHE = await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/labels`);
  } catch (e) {
    zone.innerHTML = '<p class="err">Erreur : ' + esc(e.message) + "</p>";
    return;
  }
  let h = '<div class="barre">' +
    '<button class="ghost" id="mois-prec">‹</button>' +
    `<strong>${MOIS[calRef.getMonth()]} ${calRef.getFullYear()}</strong>` +
    '<button class="ghost" id="mois-suiv">›</button>' +
    '<button id="btn-nouveau" style="margin-left:auto">+ Rendez-vous</button>' +
    "</div>";
  h += '<div style="display:grid;grid-template-columns:repeat(7,1fr);gap:1px;background:#2d3148;border:1px solid #2d3148;border-radius:10px;overflow:hidden">';
  for (const j of JOURS_COURT) h += `<div style="background:#161b27;color:#7c83ff;font-size:11px;font-weight:700;text-align:center;padding:6px 0">${j}</div>`;
  const today = new Date();
  for (let i = 0; i < 42; i++) {
    const d = new Date(debut); d.setDate(d.getDate()+i);
    const autre = d.getMonth() !== calRef.getMonth();
    const jevts = eventsDuJour(d);
    h += `<div style="background:${autre ? "#10141d" : "#141a26"};min-height:88px;padding:4px;cursor:pointer" data-jour="${ymd(d)}">` +
      `<div style="font-size:11px;color:${memeJour(d, today) ? "#5865F2" : "#94a3b8"}">${d.getDate()}</div>`;
    for (const e of jevts.slice(0, 3)) {
      const c = e.color || "#5865F2";
      h += `<div data-evt="${e.id}" data-occ="${esc(e.occurrence_start || "")}" style="background:${c};color:#fff;font-size:11px;border-radius:4px;padding:1px 4px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.all_day ? "" : esc(fmtHeure(e.start_at))+" "}${e.recurrent ? "↻ " : ""}${esc(e.title)}</div>`;
    }
    if (jevts.length > 3) h += `<div style="font-size:10px;color:#64748b">+${jevts.length-3}</div>`;
    h += "</div>";
  }
  h += "</div>";
  zone.innerHTML = h;
  document.getElementById("mois-prec").onclick = () => { calRef.setMonth(calRef.getMonth()-1); calRef = new Date(calRef); chargerVue(); };
  document.getElementById("mois-suiv").onclick = () => { calRef.setMonth(calRef.getMonth()+1); calRef = new Date(calRef); chargerVue(); };
  document.getElementById("btn-nouveau").onclick = () => ouvrirModaleEvent(null, null, ymd(new Date()));
  // data-occ porte l'identité d'occurrence (occurrence_start) : sans elle, toutes les
  // occurrences virtuelles d'une série partagent l'id du maître et on résoudrait toujours
  // la première occurrence au lieu de celle cliquée.
  zone.querySelectorAll("[data-evt]").forEach((el) => el.addEventListener("click", (ev) => { ev.stopPropagation(); ouvrirModaleEvent(el.dataset.evt, el.dataset.occ, null); }));
  zone.querySelectorAll("[data-jour]").forEach((el) => el.addEventListener("click", () => ouvrirModaleEvent(null, null, el.dataset.jour)));
}

function fermerModaleEvent() {
  const m = document.getElementById("modale"); if (m) m.remove();
}

function ouvrirModaleEvent(id, occ, dateYMD) {
  // Match sur (id, occurrence_start) : les occurrences virtuelles d'une série récurrente
  // partagent toutes le même id (celui du maître) — occ désambiguïse laquelle a été cliquée.
  const ev = id ? EVENTS_CACHE.find((e) => e.id === id && (e.occurrence_start || "") === (occ || "")) : null;
  let dStart, dEnd;
  if (ev) { dStart = isoToLocal(ev.start_at); dEnd = isoToLocal(ev.end_at); }
  else { dStart = dateYMD + "T09:00"; dEnd = dateYMD + "T10:00"; }
  modalCouleur = (ev && ev.color) || "#5865F2";
  modalLabelId = (ev && ev.label_id) || "";
  const palette = COULEURS.map((c) => `<span data-c="${c}" style="display:inline-block;width:20px;height:20px;border-radius:50%;background:${c};cursor:pointer;border:2px solid ${c===modalCouleur?"#fff":"transparent"}"></span>`).join(" ");
  const labelOptions = '<option value="">Aucune</option>' + LABELS_CACHE.map((l) => `<option value="${esc(l.id)}" ${l.id===modalLabelId?"selected":""}>${esc(l.name)}</option>`).join("");
  // Récurrence : compose une RRULE simple (FREQ), préremplie depuis ev.recurrence_rule.
  const FREQS = [["", "Ne se répète pas"], ["FREQ=DAILY", "Chaque jour"], ["FREQ=WEEKLY", "Chaque semaine"], ["FREQ=MONTHLY", "Chaque mois"], ["FREQ=YEARLY", "Chaque année"]];
  const recurrenceMatch = ev && ev.recurrence_rule ? ev.recurrence_rule.match(/FREQ=(DAILY|WEEKLY|MONTHLY|YEARLY)/) : null;
  const recurrenceValeur = recurrenceMatch ? recurrenceMatch[0] : "";
  const recurrenceOptions = FREQS.map(([v, lbl]) => `<option value="${v}" ${v===recurrenceValeur?"selected":""}>${lbl}</option>`).join("");
  const html =
    '<div id="modale" style="position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10">' +
    '<div class="card" style="width:100%;max-width:420px">' +
    `<h3 style="margin-top:0">${ev ? "Modifier" : "Nouveau rendez-vous"}</h3>` +
    `<div style="margin-bottom:10px"><input id="ev-titre" placeholder="Titre" style="width:100%" value="${ev ? esc(ev.title) : ""}"></div>` +
    `<div style="display:flex;gap:8px;margin-bottom:10px"><input id="ev-debut" type="datetime-local" value="${dStart}"><input id="ev-fin" type="datetime-local" value="${dEnd}"></div>` +
    `<div style="margin-bottom:10px"><input id="ev-lieu" placeholder="Lieu (optionnel)" style="width:100%" value="${ev && ev.location ? esc(ev.location) : ""}"></div>` +
    `<div style="margin-bottom:10px"><label class="muted">Étiquette</label><select id="ev-label" style="width:100%">${labelOptions}</select></div>` +
    `<div style="margin-bottom:10px"><label><input type="checkbox" id="ev-allday" ${ev && ev.all_day ? "checked" : ""}> Journée entière</label></div>` +
    `<div style="margin-bottom:10px"><label class="muted">Répétition</label><select id="ev-recurrence" style="width:100%">${recurrenceOptions}</select></div>` +
    `<div style="margin-bottom:14px">${palette}</div>` +
    '<div style="display:flex;gap:8px;justify-content:flex-end">' +
    (ev ? '<button id="btn-suppr" style="background:#ef4444">Supprimer</button>' : "") +
    '<button class="ghost" id="btn-annuler">Annuler</button>' +
    `<button id="btn-enregistrer">${ev ? "Enregistrer" : "Créer"}</button>` +
    "</div></div></div>";
  document.body.insertAdjacentHTML("beforeend", html);
  document.querySelectorAll("#modale [data-c]").forEach((el) => el.onclick = () => {
    modalCouleur = el.dataset.c;
    document.querySelectorAll("#modale [data-c]").forEach((s) => s.style.borderColor = s.dataset.c===modalCouleur ? "#fff" : "transparent");
  });
  if (ev) {
    document.querySelector("#modale .card").insertAdjacentHTML("beforeend",
      '<hr style="border-color:#2d3148;margin:14px 0">' +
      '<div id="zone-presence"></div>' +
      '<div id="zone-rappels" style="margin-top:12px"></div>' +
      '<div id="zone-chat" style="margin-top:12px"></div>' +
      '<div id="zone-activite" style="margin-top:12px"></div>');
    chargerDetailsEvent(ev.id);
  }
  document.getElementById("btn-annuler").onclick = fermerModaleEvent;
  // On repasse ev.occurrence_start (déjà résolu ci-dessus) plutôt que de laisser
  // enregistrerEvent/supprimerEvent refaire un find() par id seul, qui retomberait
  // sur le même bug (première occurrence trouvée au lieu de celle ouverte).
  document.getElementById("btn-enregistrer").onclick = () => enregistrerEvent(id, ev ? ev.occurrence_start : null);
  if (ev) document.getElementById("btn-suppr").onclick = () => supprimerEvent(id, ev.occurrence_start);
}

function moiSub() {
  try { return JSON.parse(atob(ACCESS_TOKEN.split(".")[1])).sub; } catch (e) { return null; }
}

const STATUT_LABEL = { accepted: "✓ vient", declined: "✗ absent", maybe: "? peut-être", pending: "⏳ en attente" };

async function chargerDetailsEvent(eventId) {
  let parts = [], comments = [], activite = [];
  try {
    parts = await api(`/events/${encodeURIComponent(eventId)}/participants`);
    comments = await api(`/events/${encodeURIComponent(eventId)}/comments`);
    activite = await api(`/events/${encodeURIComponent(eventId)}/activity`);
  } catch (e) { /* best-effort */ }
  const ids = Array.from(new Set(parts.map((p) => p.user_id)
    .concat(comments.map((c) => c.user_id)).concat(activite.map((a) => a.user_id))));
  const profils = await resoudreProfils(ids);
  const moi = moiSub();

  // Présence
  const lignesP = parts.map((p) => {
    const pr = profils[p.user_id];
    return `<div style="display:flex;align-items:center;gap:6px;margin:2px 0">${pastille(pr.avatar_color)}<span>${esc(pr.display_name)}</span><span class="muted" style="margin-left:auto">${STATUT_LABEL[p.status] || p.status}</span></div>`;
  }).join("");
  document.getElementById("zone-presence").innerHTML =
    '<strong>Présence</strong>' + (lignesP || '<p class="muted">Personne pour l\'instant.</p>') +
    '<div style="display:flex;gap:6px;margin-top:6px">' +
    '<button class="ghost" id="btn-inviter-tous">Inviter tous les membres</button>' +
    '<button class="ghost" data-rsvp="accepted">Je viens</button>' +
    '<button class="ghost" data-rsvp="maybe">Peut-être</button>' +
    '<button class="ghost" data-rsvp="declined">Absent</button></div>';
  document.getElementById("btn-inviter-tous").onclick = async () => {
    try { await api(`/events/${encodeURIComponent(eventId)}/participants/all`, { method: "POST" }); chargerDetailsEvent(eventId); } catch (e) { alert("Échec : " + e.message); }
  };
  document.querySelectorAll("#zone-presence [data-rsvp]").forEach((b) => b.onclick = async () => {
    try {
      await api(`/events/${encodeURIComponent(eventId)}/participants/${encodeURIComponent(moi)}`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status: b.dataset.rsvp }) });
      chargerDetailsEvent(eventId);
    } catch (e) { alert("Échec (es-tu participant ?) : " + e.message); }
  });

  // Mon rappel personnel — trois états : hériter (null) / aucun ([]) / personnalisé ([m,...])
  const moiPart = parts.find((p) => p.user_id === moi);
  const rappelsMoi = moiPart ? moiPart.rappels : undefined;
  const modeInitial = !Array.isArray(rappelsMoi) ? "inherit" : (rappelsMoi.length === 0 ? "none" : "custom");
  const minutesInitiales = Array.isArray(rappelsMoi) ? rappelsMoi.join(",") : "";
  document.getElementById("zone-rappels").innerHTML = moiPart
    ? '<strong>Mon rappel</strong>' +
      '<div style="display:flex;gap:6px;margin-top:4px">' +
      '<select id="mon-rappel-mode" style="flex:1">' +
      `<option value="inherit"${modeInitial === "inherit" ? " selected" : ""}>Comme l'événement</option>` +
      `<option value="none"${modeInitial === "none" ? " selected" : ""}>Aucun rappel</option>` +
      `<option value="custom"${modeInitial === "custom" ? " selected" : ""}>Personnalisé</option>` +
      '</select>' +
      `<input id="mon-rappel-min" placeholder="minutes, ex. 10,60" style="flex:1" value="${esc(minutesInitiales)}"${modeInitial === "custom" ? "" : " disabled"}>` +
      '<button id="btn-mon-rappel">OK</button></div>' +
      '<p class="muted" style="font-size:11px">« Comme l\'événement » = hérite des rappels par défaut · « Aucun rappel » = tu ne seras pas prévenu(e) · « Personnalisé » = minutes avant séparées par des virgules (0 = à l\'heure).</p>'
    : '<p class="muted">Rejoins l\'événement pour régler ton rappel.</p>';
  const modeSel = document.getElementById("mon-rappel-mode");
  const minInput = document.getElementById("mon-rappel-min");
  if (modeSel) modeSel.onchange = () => { minInput.disabled = modeSel.value !== "custom"; };
  const btnR = document.getElementById("btn-mon-rappel");
  if (btnR) btnR.onclick = async () => {
    const mode = document.getElementById("mon-rappel-mode").value;
    let rappels;
    if (mode === "inherit") rappels = null;
    else if (mode === "none") rappels = [];
    else {
      const v = document.getElementById("mon-rappel-min").value.trim();
      rappels = v === "" ? [] : v.split(",").map((x) => parseInt(x.trim(), 10)).filter((x) => !isNaN(x));
    }
    try {
      await api(`/events/${encodeURIComponent(eventId)}/participants/${encodeURIComponent(moi)}`,
        { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ rappels }) });
      chargerDetailsEvent(eventId);
    } catch (e) { alert("Échec : " + e.message); }
  };

  // Chat
  const lignesC = comments.map((c) => {
    const pr = profils[c.user_id];
    return `<div style="margin:4px 0">${pastille(pr.avatar_color)}<strong style="font-size:12px">${esc(pr.display_name)}</strong> <span>${esc(c.content)}</span></div>`;
  }).join("");
  document.getElementById("zone-chat").innerHTML =
    '<strong>Discussion</strong><div style="max-height:140px;overflow:auto;margin:4px 0">' +
    (lignesC || '<p class="muted">Aucun message.</p>') + '</div>' +
    '<div style="display:flex;gap:6px"><input id="chat-input" placeholder="Un mot…" style="flex:1"><button id="btn-chat">Envoyer</button></div>';
  document.getElementById("btn-chat").onclick = async () => {
    const content = document.getElementById("chat-input").value.trim();
    if (!content) return;
    try {
      await api(`/events/${encodeURIComponent(eventId)}/comments`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ content }) });
      chargerDetailsEvent(eventId);
    } catch (e) { alert("Échec : " + e.message); }
  };

  // Fil d'activité
  const ACT_LABEL = { event_created: "a créé l'événement", event_updated: "a modifié l'événement", rsvp: "a répondu", comment: "a écrit un message" };
  const lignesA = activite.map((a) => {
    const nom = (profils[a.user_id] || {}).display_name || a.user_nom;
    return `<div class="muted" style="font-size:11px">• ${esc(nom)} ${esc(ACT_LABEL[a.action] || a.action)}</div>`;
  }).join("");
  document.getElementById("zone-activite").innerHTML =
    '<strong>Activité</strong>' + (lignesA || '<p class="muted">—</p>');
}

// Dialogue de portée : pour une occurrence d'une série récurrente, demande si le
// changement (enregistrement ou suppression) s'applique à « Cet événement » (l'occurrence
// seule, via override) ou « Toute la série » (le maître). Renvoie "this"|"all"|null (annulé).
function demanderPortee() {
  return new Promise((resolve) => {
    const html =
      '<div id="modale-portee" style="position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:20">' +
      '<div class="card" style="width:100%;max-width:360px">' +
      '<h3 style="margin-top:0">Événement récurrent</h3>' +
      '<p class="muted">Appliquer le changement à…</p>' +
      '<div style="display:flex;gap:8px;justify-content:flex-end;flex-wrap:wrap">' +
      '<button class="ghost" id="btn-portee-annuler">Annuler</button>' +
      '<button class="ghost" id="btn-portee-this">Cet événement</button>' +
      '<button id="btn-portee-all">Toute la série</button>' +
      "</div></div></div>";
    document.body.insertAdjacentHTML("beforeend", html);
    const m = document.getElementById("modale-portee");
    const fermer = (v) => { m.remove(); resolve(v); };
    document.getElementById("btn-portee-annuler").onclick = () => fermer(null);
    document.getElementById("btn-portee-this").onclick = () => fermer("this");
    document.getElementById("btn-portee-all").onclick = () => fermer("all");
  });
}

// Compose la query string de portée pour un event récurrent, ou "" pour un event simple.
async function requeterPortee(ev) {
  if (!ev || !ev.recurrent) return "";
  const portee = await demanderPortee();
  if (!portee) return null;
  return portee === "this" ? `?scope=this&occurrence=${encodeURIComponent(ev.occurrence_start)}` : "?scope=all";
}

async function enregistrerEvent(id, occ) {
  const corps = {
    title: document.getElementById("ev-titre").value.trim(),
    start_at: localToIso(document.getElementById("ev-debut").value),
    end_at: localToIso(document.getElementById("ev-fin").value),
    location: document.getElementById("ev-lieu").value.trim() || null,
    color: modalCouleur,
    label_id: document.getElementById("ev-label").value || "",
    all_day: document.getElementById("ev-allday").checked,
    recurrence_rule: document.getElementById("ev-recurrence").value || null,
  };
  if (!corps.title) { alert("Donne un titre."); return; }
  const ev = id ? EVENTS_CACHE.find((e) => e.id === id && (e.occurrence_start || "") === (occ || "")) : null;
  const qs = await requeterPortee(ev);
  if (qs === null) return;
  try {
    if (id) {
      await api(`/events/${encodeURIComponent(id)}${qs}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
    } else {
      await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
    }
    fermerModaleEvent();
    await chargerVue();
  } catch (e) { alert("Échec : " + e.message); }
}

async function supprimerEvent(id, occ) {
  const ev = EVENTS_CACHE.find((e) => e.id === id && (e.occurrence_start || "") === (occ || ""));
  const qs = await requeterPortee(ev);
  if (qs === null) return;
  if (!qs && !confirm("Supprimer cet événement ?")) return;
  try {
    await api(`/events/${encodeURIComponent(id)}${qs}`, { method: "DELETE" });
    fermerModaleEvent();
    await chargerVue();
  } catch (e) { alert("Échec : " + e.message); }
}

function ouvrirModaleInviter() {
  const html =
    '<div id="modale" style="position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10">' +
    '<div class="card" style="width:100%;max-width:420px">' +
    '<h3 style="margin-top:0">Inviter quelqu\'un</h3>' +
    '<div style="margin-bottom:10px"><input id="inv-email" placeholder="Email (optionnel, pour info)" style="width:100%"></div>' +
    '<div style="margin-bottom:14px"><select id="inv-role" style="width:100%"><option value="viewer">Lecture seule</option><option value="editor">Lecture et écriture</option></select></div>' +
    '<div id="inv-resultat"></div>' +
    '<div style="display:flex;gap:8px;justify-content:flex-end;margin-top:10px">' +
    '<button class="ghost" id="btn-annuler">Fermer</button>' +
    '<button id="btn-creer-invit">Créer le lien</button>' +
    "</div></div></div>";
  document.body.insertAdjacentHTML("beforeend", html);
  document.getElementById("btn-annuler").onclick = fermerModaleEvent;
  document.getElementById("btn-creer-invit").onclick = creerInvitation;
}

async function creerInvitation() {
  const email = document.getElementById("inv-email").value.trim() || null;
  const role = document.getElementById("inv-role").value;
  try {
    const inv = await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/invitations`, {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email, role }),
    });
    const lien = location.origin + "/invitations/" + inv.token + "/page";
    document.getElementById("inv-resultat").innerHTML =
      '<p class="muted">Envoie ce lien à la personne invitée :</p>' +
      `<input readonly style="width:100%" value="${esc(lien)}" onclick="this.select()">`;
  } catch (e) { alert("Échec : " + e.message); }
}

// ═══════════════ Listes de courses/tâches (S176) ═══════════════
let SSE_LISTE = null, LISTE_ACTIVE = null, LISTES = [], CARTES = [];

async function vueListes() {
  document.getElementById("main").innerHTML =
    '<div class="listes-layout">' +
    '<div><div class="barre"><strong>Mes listes</strong>' +
    '<button onclick="creerListe()">+ Nouvelle</button></div><div id="listes-col"></div></div>' +
    '<div class="card"><div id="liste-detail"><p class="muted">Choisis une liste.</p></div></div>' +
    '</div>';
  await chargerListes();
}

async function chargerListes() {
  try { LISTES = await api("/lists"); } catch (e) { return; }
  const col = document.getElementById("listes-col");
  if (!col) return;
  col.innerHTML = LISTES.map((l, i) =>
    `<button class="liste-item" onclick="ouvrirListe(${i})">` +
    `<span>${esc(l.name)}</span><span class="badge">${l.nb_a_prendre}</span></button>`).join("")
    || '<p class="muted">Aucune liste.</p>';
}

async function creerListe() {
  const nom = prompt("Nom de la liste ?"); if (!nom) return;
  const kind = confirm("Liste de courses ? (Annuler = liste de tâches)") ? "courses" : "taches";
  try {
    await api("/lists", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: nom, kind }) });
    await chargerListes();
  } catch (e) { alert("Échec : " + e.message); }
}

async function ouvrirListe(i) {
  const l = LISTES[i]; if (!l) return;
  LISTE_ACTIVE = l;
  const estCourses = l.kind === "courses";
  document.getElementById("liste-detail").innerHTML =
    `<div class="barre"><strong>${esc(l.name)}</strong></div>` +
    '<div id="liste-items"></div>' +
    '<div class="barre" style="margin-top:14px">' +
    '<input id="item-libre" placeholder="Ajouter un article…" style="flex:1" ' +
    'onkeydown="if(event.key===\'Enter\')ajouterLibre()">' +
    '<button onclick="ajouterLibre()">Ajouter</button>' +
    (estCourses ? '<button class="ghost" onclick="basculerCatalogue()">Catalogue</button>' : "") +
    '</div><div id="catalogue" hidden></div>';
  await rafraichirItems();
  brancherSSE(l.id);
}

async function rafraichirItems() {
  if (!LISTE_ACTIVE) return;
  let items;
  try { items = await api(`/lists/${LISTE_ACTIVE.id}/items`); } catch (e) { return; }
  const cible = document.getElementById("liste-items");
  if (!cible) return;
  const actifs = items.filter((i) => !i.checked), pris = items.filter((i) => i.checked);
  const parRayon = {};
  actifs.forEach((i) => { (parRayon[i.rayon || "Autre"] ||= []).push(i); });
  let html = "";
  for (const rayon of Object.keys(parRayon))
    html += `<div class="rayon-titre">${esc(rayon)}</div>` + parRayon[rayon].map(itemLigne).join("");
  if (!actifs.length) html += '<p class="muted">Rien à prendre.</p>';
  if (pris.length)
    html += `<div class="rayon-titre">Déjà pris (${pris.length}) ` +
      '<button class="ghost" style="padding:2px 8px" onclick="viderPris()">Vider</button></div>' +
      pris.map(itemLigne).join("");
  cible.innerHTML = html;
}

function itemLigne(i) {
  const par = i.checked_by ? pastille((PROFILS[i.checked_by] || {}).avatar_color || "#64748b") : "";
  return `<div class="item ${i.checked ? "coche" : ""}" onclick="basculerItem('${i.id}', ${i.checked ? "false" : "true"})">` +
    `<span>${i.emoji || "•"}</span><span style="flex:1">${esc(i.name)}` +
    `${i.note ? ` <em class="muted">${esc(i.note)}</em>` : ""}</span>${par}</div>`;
}

async function basculerItem(id, checked) {
  try {
    await api(`/lists/${LISTE_ACTIVE.id}/items/${id}`, { method: "PATCH",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ checked }) });
    await rafraichirItems();
  } catch (e) { /* SSE rattrapera */ }
}

async function viderPris() {
  try { await api(`/lists/${LISTE_ACTIVE.id}/items/clear-checked`, { method: "POST" }); }
  catch (e) {}
  await rafraichirItems();
}

async function basculerCatalogue() {
  const el = document.getElementById("catalogue");
  el.hidden = !el.hidden;
  if (!el.hidden && !el.dataset.charge) { await chargerCatalogue(); el.dataset.charge = "1"; }
}

async function chargerCatalogue() {
  let data;
  try { data = await api(`/lists/${LISTE_ACTIVE.id}/catalog`); } catch (e) { return; }
  document.getElementById("catalogue").innerHTML = data.rayons.map((g) =>
    `<div class="rayon-titre">${esc(g.rayon)}</div><div class="grille">` +
    g.items.map((ci) => `<button class="cat" onclick="ajouterCatalogue('${ci.id}')">` +
      `${ci.emoji} ${esc(ci.name)}</button>`).join("") + "</div>").join("");
}

async function ajouterCatalogue(catId) {
  try {
    await api(`/lists/${LISTE_ACTIVE.id}/items`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ catalog_item_id: catId }) });
    await rafraichirItems();
  } catch (e) { alert("Échec : " + e.message); }
}

async function ajouterLibre() {
  const inp = document.getElementById("item-libre");
  const v = inp.value.trim(); if (!v) return;
  inp.value = "";
  try {
    await api(`/lists/${LISTE_ACTIVE.id}/items`, { method: "POST",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name: v }) });
    document.getElementById("catalogue").dataset.charge = "";
    await rafraichirItems();
  } catch (e) { alert("Échec : " + e.message); }
}

function brancherSSE(id) {
  if (SSE_LISTE) SSE_LISTE.close();
  // EventSource ne pose pas d'en-tête → JWT en query (cf. get_current_user_sse).
  SSE_LISTE = new EventSource(`/sse/lists/${id}?access_token=${encodeURIComponent(ACCESS_TOKEN)}`);
  SSE_LISTE.onmessage = (e) => {
    let msg; try { msg = JSON.parse(e.data); } catch (_) { return; }
    const pertinents = ["item.added", "item.checked", "item.unchecked", "item.updated", "item.deleted", "checked.cleared"];
    if (pertinents.includes(msg.type)) rafraichirItems();
  };
}

// ═══════════════ Cartes de fidélité (S176) ═══════════════
async function vueCartes() {
  document.getElementById("main").innerHTML =
    '<div class="barre"><strong>Mes cartes de fidélité</strong>' +
    '<button onclick="creerCarte()">+ Ajouter</button></div><div id="cartes-grille" class="cartes-grille"></div>';
  await chargerCartes();
}

async function chargerCartes() {
  try { CARTES = await api("/loyalty-cards"); } catch (e) { return; }
  document.getElementById("cartes-grille").innerHTML = CARTES.map((c, i) =>
    `<button class="carte" style="background:${esc(c.couleur)}" onclick="ouvrirCarte(${i})">` +
    `${esc(c.enseigne)}</button>`).join("") || '<p class="muted">Aucune carte.</p>';
}

async function creerCarte() {
  const enseigne = prompt("Enseigne ? (ex. Carrefour)"); if (!enseigne) return;
  const numero = prompt("Numéro de carte / code-barres ?"); if (!numero) return;
  const format = (prompt("Format : code128 ou ean13 ?", "code128") || "code128").trim();
  try {
    await api("/loyalty-cards", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ enseigne, numero, format }) });
    await chargerCartes();
  } catch (e) { alert("Échec : " + e.message); }
}

function ouvrirCarte(i) {
  const c = CARTES[i]; if (!c) return;
  document.getElementById("carte-enseigne").textContent = c.enseigne;
  document.getElementById("carte-numero").textContent = c.numero;
  const svg = document.getElementById("carte-barcode");
  const ok = window.dessinerCodeBarres(svg, c.numero, c.format);
  document.getElementById("carte-fallback").style.display = ok ? "none" : "block";
  if (!ok) svg.innerHTML = "";
  document.getElementById("carte-modal").style.display = "flex";
}

function fermerCarte() { document.getElementById("carte-modal").style.display = "none"; }

// ── Sondages de disponibilité (S177) ────────────────────────────────────────
const V_LBL = { oui: "Oui", si_besoin: "Si besoin", non: "Non" };
const V_COL = { oui: "#16a34a", si_besoin: "#d97706", non: "#ef4444" };

function fmtCreneau(iso) {
  try { return new Date(iso).toLocaleString("fr-FR",
    { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }); }
  catch (e) { return iso; }
}

async function vueSondages() {
  document.getElementById("main").innerHTML =
    '<div class="barre"><strong>Mes sondages</strong>' +
    '<button onclick="creerSondage()">+ Nouveau sondage</button></div>' +
    '<div id="sondages-liste"></div>';
  await chargerSondages();
}

async function chargerSondages() {
  let polls; try { polls = await api("/polls"); } catch (e) { return; }
  document.getElementById("sondages-liste").innerHTML = polls.length ? polls.map((p) =>
    `<button class="ligne" style="display:block;width:100%;text-align:left;margin:6px 0;padding:12px;` +
    `border:1px solid #334155;border-radius:10px;background:transparent;color:inherit;cursor:pointer" ` +
    `onclick="ouvrirSondage('${p.id}')">` +
    `<strong>${esc(p.title)}</strong>` +
    `<span class="muted"> — ${p.nb_slots} créneau(x) · ${p.nb_voters} votant(s)` +
    `${p.status === "closed" ? " · ✅ finalisé" : ""}</span></button>`).join("")
    : '<p class="muted">Aucun sondage. Créez-en un pour trouver une date à plusieurs.</p>';
}

async function creerSondage() {
  const titre = prompt("Objet du sondage ? (ex. Dîner de famille)"); if (!titre) return;
  const lieu = prompt("Lieu ? (optionnel)") || null;
  const creneaux = [];
  while (true) {
    const d = prompt(`Créneau ${creneaux.length + 1} — début (AAAA-MM-JJ HH:MM). Vide = terminer.`);
    if (!d) break;
    const f = prompt("Fin (AAAA-MM-JJ HH:MM)"); if (!f) break;
    const debut = new Date(d.replace(" ", "T")), fin = new Date(f.replace(" ", "T"));
    if (isNaN(debut) || isNaN(fin) || debut >= fin) { alert("Dates invalides."); continue; }
    creneaux.push({ start_at: debut.toISOString(), end_at: fin.toISOString() });
  }
  if (!creneaux.length) { alert("Au moins un créneau."); return; }
  try {
    const p = await api("/polls", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: titre, location: lieu, slots: creneaux }) });
    await chargerSondages();
    ouvrirSondage(p.id);
  } catch (e) { alert("Échec : " + e.message); }
}

async function ouvrirSondage(id) {
  let p; try { p = await api("/polls/" + encodeURIComponent(id)); } catch (e) { return; }
  const lien = location.origin + "/polls/p/" + p.share_token;
  const clos = p.status !== "open";
  let h = `<div class="barre"><button class="ghost" onclick="vueSondages()">‹ Retour</button>` +
    `<strong>${esc(p.title)}</strong></div>`;
  if (p.location) h += `<p class="muted">📍 ${esc(p.location)}</p>`;
  h += `<p class="muted">Lien de vote : <code>${esc(lien)}</code> ` +
    `<button class="ghost" onclick="navigator.clipboard&&navigator.clipboard.writeText('${lien}')">Copier</button></p>`;
  h += '<div style="overflow-x:auto"><table style="border-collapse:collapse;width:100%">';
  h += "<tr><th style='text-align:left;padding:6px'>Créneau</th>" +
    "<th style='padding:6px'>✔</th><th style='padding:6px'>~</th><th style='padding:6px'>✕</th>" +
    (clos ? "" : "<th></th>") + "</tr>";
  for (const s of p.slots) {
    const t = p.tallies[s.id] || { oui: 0, si_besoin: 0, non: 0};
    const gagne = p.final_slot_id === s.id;
    h += `<tr style="border-top:1px solid #334155">` +
      `<td style="padding:6px">${gagne ? "✅ " : ""}${fmtCreneau(s.start_at)} → ${fmtCreneau(s.end_at)}</td>` +
      `<td style="padding:6px;text-align:center;color:${V_COL.oui}">${t.oui}</td>` +
      `<td style="padding:6px;text-align:center;color:${V_COL.si_besoin}">${t.si_besoin}</td>` +
      `<td style="padding:6px;text-align:center;color:${V_COL.non}">${t.non}</td>`;
    if (!clos) h += `<td style="padding:6px"><button class="ghost" ` +
      `onclick="finaliserSondage('${p.id}','${s.id}')">Retenir</button></td>`;
    h += "</tr>";
  }
  h += "</table></div>";
  if (p.voters.length) {
    h += "<h4>Réponses</h4>";
    for (const v of p.voters) {
      const reps = p.slots.map((s) => {
        const val = v.votes[s.id];
        return val ? `<span style="color:${V_COL[val]}">${V_LBL[val]}</span>` : "<span class='muted'>—</span>";
      }).join(" · ");
      h += `<div style="padding:4px 0">${esc(v.voter_name)}${v.is_guest ? " (invité)" : ""} : ${reps}</div>`;
    }
  }
  document.getElementById("main").innerHTML = h;
}

async function finaliserSondage(id, slotId) {
  if (!confirm("Retenir ce créneau ? Cela crée l'événement dans l'agenda et clôture le sondage.")) return;
  try {
    await api("/polls/" + encodeURIComponent(id) + "/finalize", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ slot_id: slotId }) });
    ouvrirSondage(id);
  } catch (e) { alert("Échec : " + e.message); }
}

// ── Réglages : panneau notifications (S178) ─────────────────────────────────
async function vueReglages() {
  document.getElementById("main").innerHTML =
    '<section id="panneau-notifs" style="margin-top:16px">' +
    '<h3>🔔 Notifications</h3>' +
    '<p id="etat-push">…</p>' +
    '<button id="btn-activer-push" onclick="activerPush()">Activer les notifications sur cet appareil</button>' +
    '<button id="btn-couper-push" onclick="couperPush()" style="display:none">Couper sur cet appareil</button>' +
    '<h4 style="margin-top:16px">Résumé (digest)</h4>' +
    '<div style="display:flex;flex-direction:column;gap:8px;max-width:320px">' +
    '<label>Fréquence : ' +
    '<select id="digest-cadence"><option value="off">Aucun</option>' +
    '<option value="quotidien">Quotidien</option><option value="hebdo">Hebdo</option></select></label>' +
    '<label><input type="checkbox" id="digest-push"> Par notification</label>' +
    '<label><input type="checkbox" id="digest-email"> Par email</label>' +
    '<label>Heures calmes : <input id="heures-calmes" placeholder="22:00-07:00"></label>' +
    '<button onclick="enregistrerNotifs()">Enregistrer</button>' +
    '</div>' +
    '</section>';
  majEtatPush();
}

async function enregistrerNotifs() {
  const body = {
    digest_cadence: document.getElementById("digest-cadence").value,
    digest_push: document.getElementById("digest-push").checked,
    digest_email: document.getElementById("digest-email").checked,
    heures_calmes: document.getElementById("heures-calmes").value.trim(),
  };
  try {
    await api("/profiles/me/notifs", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body) });
    alert("Préférences enregistrées.");
  } catch (e) { alert("Échec : " + e.message); }
}

// ── PWA + push web (S178) — anti-intrusif : rien au chargement, tout sur clic ──
const b64ToUint8 = (s) => {
  const pad = "=".repeat((4 - (s.length % 4)) % 4);
  const b = atob((s + pad).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from([...b].map((c) => c.charCodeAt(0)));
};
let swReg = null;
async function initPWA() {
  if (!("serviceWorker" in navigator)) return;
  try { swReg = await navigator.serviceWorker.register("/app/sw.js", { scope: "/app" }); }
  catch (e) { console.warn("SW non enregistré", e); }
  majEtatPush();
}
async function majEtatPush() {
  const el = document.getElementById("etat-push");
  if (!el) return;
  if (!("Notification" in window) || !swReg) { el.textContent = "Non supporté sur ce navigateur."; return; }
  const sub = await swReg.pushManager.getSubscription();
  el.textContent = sub ? "🔔 Notifications activées sur cet appareil." : "🔕 Notifications coupées ici.";
  document.getElementById("btn-activer-push").style.display = sub ? "none" : "";
  document.getElementById("btn-couper-push").style.display = sub ? "" : "none";
}
async function activerPush() {
  if (Notification.permission === "denied") { alert("Autorise les notifications dans les réglages du navigateur."); return; }
  const perm = await Notification.requestPermission();      // ← demande UNIQUEMENT ici, sur clic
  if (perm !== "granted") return;
  const { cle } = await (await fetch("/push/cle_publique")).json();
  if (!cle) { alert("Push non configuré côté serveur."); return; }
  const sub = await swReg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: b64ToUint8(cle) });
  try {
    await api("/push/appareils", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ appareil: sub.toJSON() }) });
  } catch (e) { alert("Échec : " + e.message); return; }
  majEtatPush();
}
async function couperPush() {
  const sub = await swReg.pushManager.getSubscription();
  if (sub) {
    try {
      await api("/push/appareils", { method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ endpoint: sub.endpoint }) });
    } catch (e) { /* best-effort */ }
    await sub.unsubscribe();
  }
  majEtatPush();
}

demarrer().catch(() => afficherLogin("Erreur réseau. Réessayez."));
</script>
</body>
</html>"""


def page_app(kc_url: str, kc_realm: str, kc_client_id: str) -> str:
    return _PAGE.replace(
        "%%KC%%",
        json.dumps({"url": kc_url, "realm": kc_realm, "clientId": kc_client_id}),
    )
