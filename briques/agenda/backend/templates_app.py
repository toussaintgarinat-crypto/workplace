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
</style>
</head>
<body>
<header>
  <h1>📅 Agenda</h1>
  <div id="entete-droite"></div>
</header>
<main id="main"><div class="centre muted">Chargement…</div></main>
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
    return;
  }

  const refresh = localStorage.getItem(LS_REFRESH);
  if (!refresh) { afficherLogin(); return; }
  const tokens = await rafraichir(refresh);
  if (!tokens) { afficherLogin("Session expirée. Reconnecte-toi."); return; }
  poserSession(tokens);
  await chargerApp();
}

async function chargerApp() {
  document.getElementById("entete-droite").innerHTML =
    '<button class="ghost" id="btn-logout">Se déconnecter</button>';
  document.getElementById("btn-logout").onclick = deconnecter;
  await chargerCalendriers();
}

let CALENDARS = [];
let CAL_ACTIF = null;

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
      h += `<div data-evt="${e.id}" style="background:${c};color:#fff;font-size:11px;border-radius:4px;padding:1px 4px;margin-top:2px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${e.all_day ? "" : esc(fmtHeure(e.start_at))+" "}${esc(e.title)}</div>`;
    }
    if (jevts.length > 3) h += `<div style="font-size:10px;color:#64748b">+${jevts.length-3}</div>`;
    h += "</div>";
  }
  h += "</div>";
  zone.innerHTML = h;
  document.getElementById("mois-prec").onclick = () => { calRef.setMonth(calRef.getMonth()-1); calRef = new Date(calRef); chargerVue(); };
  document.getElementById("mois-suiv").onclick = () => { calRef.setMonth(calRef.getMonth()+1); calRef = new Date(calRef); chargerVue(); };
  document.getElementById("btn-nouveau").onclick = () => ouvrirModaleEvent(null, ymd(new Date()));
  zone.querySelectorAll("[data-evt]").forEach((el) => el.addEventListener("click", (ev) => { ev.stopPropagation(); ouvrirModaleEvent(el.dataset.evt, null); }));
  zone.querySelectorAll("[data-jour]").forEach((el) => el.addEventListener("click", () => ouvrirModaleEvent(null, el.dataset.jour)));
}

function fermerModaleEvent() {
  const m = document.getElementById("modale"); if (m) m.remove();
}

function ouvrirModaleEvent(id, dateYMD) {
  const ev = id ? EVENTS_CACHE.find((e) => e.id === id) : null;
  let dStart, dEnd;
  if (ev) { dStart = isoToLocal(ev.start_at); dEnd = isoToLocal(ev.end_at); }
  else { dStart = dateYMD + "T09:00"; dEnd = dateYMD + "T10:00"; }
  modalCouleur = (ev && ev.color) || "#5865F2";
  modalLabelId = (ev && ev.label_id) || "";
  const palette = COULEURS.map((c) => `<span data-c="${c}" style="display:inline-block;width:20px;height:20px;border-radius:50%;background:${c};cursor:pointer;border:2px solid ${c===modalCouleur?"#fff":"transparent"}"></span>`).join(" ");
  const labelOptions = '<option value="">Aucune</option>' + LABELS_CACHE.map((l) => `<option value="${esc(l.id)}" ${l.id===modalLabelId?"selected":""}>${esc(l.name)}</option>`).join("");
  const html =
    '<div id="modale" style="position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10">' +
    '<div class="card" style="width:100%;max-width:420px">' +
    `<h3 style="margin-top:0">${ev ? "Modifier" : "Nouveau rendez-vous"}</h3>` +
    `<div style="margin-bottom:10px"><input id="ev-titre" placeholder="Titre" style="width:100%" value="${ev ? esc(ev.title) : ""}"></div>` +
    `<div style="display:flex;gap:8px;margin-bottom:10px"><input id="ev-debut" type="datetime-local" value="${dStart}"><input id="ev-fin" type="datetime-local" value="${dEnd}"></div>` +
    `<div style="margin-bottom:10px"><input id="ev-lieu" placeholder="Lieu (optionnel)" style="width:100%" value="${ev && ev.location ? esc(ev.location) : ""}"></div>` +
    `<div style="margin-bottom:10px"><label class="muted">Étiquette</label><select id="ev-label" style="width:100%">${labelOptions}</select></div>` +
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
  document.getElementById("btn-annuler").onclick = fermerModaleEvent;
  document.getElementById("btn-enregistrer").onclick = () => enregistrerEvent(id);
  if (ev) document.getElementById("btn-suppr").onclick = () => supprimerEvent(id);
}

async function enregistrerEvent(id) {
  const corps = {
    title: document.getElementById("ev-titre").value.trim(),
    start_at: localToIso(document.getElementById("ev-debut").value),
    end_at: localToIso(document.getElementById("ev-fin").value),
    location: document.getElementById("ev-lieu").value.trim() || null,
    color: modalCouleur,
    label_id: document.getElementById("ev-label").value || "",
    all_day: false,
  };
  if (!corps.title) { alert("Donne un titre."); return; }
  try {
    if (id) {
      await api(`/events/${encodeURIComponent(id)}`, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
    } else {
      await api(`/calendars/${encodeURIComponent(CAL_ACTIF)}/events`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(corps) });
    }
    fermerModaleEvent();
    await chargerVue();
  } catch (e) { alert("Échec : " + e.message); }
}

async function supprimerEvent(id) {
  if (!confirm("Supprimer cet événement ?")) return;
  try {
    await api(`/events/${encodeURIComponent(id)}`, { method: "DELETE" });
    fermerModaleEvent();
    await chargerVue();
  } catch (e) { alert("Échec : " + e.message); }
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
