"""Page HTML d'acceptation d'une invitation (servie publiquement).

Auto-suffisante : aucune dépendance externe. Si l'auth est active, la connexion
Keycloak se fait par un flux OIDD Authorization Code + PKCE écrit à la main
(pas de CDN). Sinon, l'acceptation est directe (mode réseau interne).

Les valeurs serveur sont injectées comme littéraux JSON (sûr) à la place des
marqueurs %%…%%.
"""

import json

_PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Invitation — Agenda partagé</title>
<style>
  :root { color-scheme: light dark; }
  * { box-sizing: border-box; }
  body { margin: 0; min-height: 100vh; display: grid; place-items: center;
         font: 16px/1.5 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
         background: #0f172a; color: #e2e8f0; padding: 24px; }
  .card { width: 100%; max-width: 420px; background: #1e293b; border: 1px solid #334155;
          border-radius: 16px; padding: 32px; text-align: center;
          box-shadow: 0 10px 40px rgba(0,0,0,.4); }
  .logo { font-size: 44px; line-height: 1; }
  h1 { font-size: 20px; margin: 12px 0 20px; font-weight: 600; }
  p { margin: 8px 0; }
  .muted { color: #94a3b8; font-size: 14px; }
  .err { color: #f87171; }
  .ok { color: #4ade80; }
  strong { color: #f8fafc; }
  button { margin-top: 20px; width: 100%; padding: 12px 16px; border: 0; border-radius: 10px;
           background: #3b82f6; color: #fff; font-size: 15px; font-weight: 600; cursor: pointer; }
  button:hover { background: #2563eb; }
  button:disabled { opacity: .6; cursor: default; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">📅</div>
  <h1>Agenda partagé</h1>
  <div id="content"><p class="muted">Chargement…</p></div>
</div>
<script>
const TOKEN = %%TOKEN%%;
const AUTH_ENABLED = %%AUTH%%;
const KC = %%KC%%;
const ROLES = { viewer: "lecture seule", editor: "lecture et écriture" };
const content = document.getElementById("content");
let accessToken = null;

const html = (s) => { content.innerHTML = s; };
const esc = (s) => (s || "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

// ── OIDC Authorization Code + PKCE (fait main) ──────────────────────────────
const REDIRECT = location.origin + location.pathname + "?do=accept";
const b64url = (buf) => btoa(String.fromCharCode(...new Uint8Array(buf)))
  .replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
const rand = (n) => { const a = new Uint8Array(n); crypto.getRandomValues(a); return b64url(a.buffer); };
const sha256 = (s) => crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));

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

async function exchangeCode(code) {
  const verifier = sessionStorage.getItem("pkce_verifier");
  const body = new URLSearchParams({
    grant_type: "authorization_code", code, redirect_uri: REDIRECT,
    client_id: KC.clientId, code_verifier: verifier,
  });
  const r = await fetch(`${KC.url}/realms/${KC.realm}/protocol/openid-connect/token`, {
    method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body,
  });
  if (!r.ok) return null;
  return (await r.json()).access_token;
}

// ── Invitation ──────────────────────────────────────────────────────────────
async function loadInvitation() {
  const r = await fetch(`/invitations/${TOKEN}`, { headers: { Accept: "application/json" } });
  if (!r.ok) { html('<p class="err">Invitation introuvable ou expirée.</p>'); return null; }
  return r.json();
}

async function accept() {
  if (AUTH_ENABLED && !accessToken) { await login(); return; }
  html("<p>Validation…</p>");
  const headers = {};
  if (AUTH_ENABLED) headers["Authorization"] = "Bearer " + accessToken;
  const r = await fetch(`/invitations/${TOKEN}/accept`, { method: "POST", headers });
  if (r.ok) html('<p class="ok">✓ Invitation acceptée. L\'agenda est maintenant partagé avec vous.</p>');
  else if (r.status === 409) html('<p class="err">Cette invitation a déjà été utilisée.</p>');
  else if (r.status === 410) html('<p class="err">Cette invitation a expiré.</p>');
  else if (r.status === 401) html('<p class="err">Connexion requise pour accepter.</p>');
  else html('<p class="err">Échec de l\'acceptation (' + r.status + ").</p>");
}

function render(inv) {
  if (inv.used_at) { html('<p class="err">Cette invitation a déjà été utilisée.</p>'); return; }
  const role = ROLES[inv.role] || inv.role;
  const cal = inv.calendar_name ? "<strong>" + esc(inv.calendar_name) + "</strong>" : "un agenda";
  const exp = inv.expires_at
    ? `<p class="muted">Valable jusqu'au ${new Date(inv.expires_at).toLocaleString("fr-FR")}.</p>` : "";
  html(`<p>Vous êtes invité à ${cal}.</p>
        <p class="muted">Accès : <strong>${esc(role)}</strong>.</p>${exp}
        <button id="accept">Accepter l'invitation</button>`);
  document.getElementById("accept").onclick = accept;
}

async function main() {
  const params = new URLSearchParams(location.search);
  if (AUTH_ENABLED && params.get("code")) {
    if (params.get("state") === sessionStorage.getItem("pkce_state")) {
      accessToken = await exchangeCode(params.get("code"));
    }
    history.replaceState({}, "", location.pathname + "?do=accept");
    if (!accessToken) { html('<p class="err">Échec de la connexion. Réessayez.</p>'); return; }
  }
  const inv = await loadInvitation();
  if (!inv) return;
  render(inv);
  if (AUTH_ENABLED && accessToken && params.get("do") === "accept") accept();
}
main();
</script>
</body>
</html>
"""


def page_invitation(token: str, auth_enabled: bool, kc_url: str,
                    kc_realm: str, kc_client: str) -> str:
    """Rend la page d'acceptation, valeurs injectées comme littéraux JSON sûrs."""
    return (
        _PAGE
        .replace("%%TOKEN%%", json.dumps(token))
        .replace("%%AUTH%%", "true" if auth_enabled else "false")
        .replace("%%KC%%", json.dumps({"url": kc_url.rstrip("/"), "realm": kc_realm, "clientId": kc_client}))
    )
