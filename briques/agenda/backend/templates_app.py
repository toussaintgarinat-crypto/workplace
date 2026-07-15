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
  document.getElementById("sel-cal").onchange = (e) => { CAL_ACTIF = e.target.value; chargerVue(); };
  const btnInviter = document.getElementById("btn-inviter");
  if (btnInviter) btnInviter.onclick = ouvrirModaleInviter;
}

async function chargerVue() {
  document.getElementById("zone-vue").innerHTML = '<p class="muted">À venir.</p>';
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
