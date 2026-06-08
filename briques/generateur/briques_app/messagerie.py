"""Brique_app « Messagerie interne » — embarque la messagerie Oria dans l'app livrée.

Auto-découverte par le générateur (contrat : `construire(ctx) -> list[vue]`).

• N'apparaît qu'en mode hébergé AVEC messagerie provisionnée : la config Oria
  (`ctx["oria"]`) est injectée par le générateur après provisioning de l'espace
  (world + salons). En mode autonome / sans Oria → carte d'information.
• SSO : OpenID Connect Authorization Code + PKCE contre Keycloak (client `oria-app`,
  le MÊME que le frontend Oria → session partagée = vrai single sign-on). Aucune
  dépendance JS externe (flow implémenté à la main avec crypto.subtle).
• Messagerie : l'utilisateur authentifié récupère ses identifiants Matrix via Oria
  (`/api/auth/me`), rejoint l'espace de l'entreprise (`/rejoindre`), puis lit/écrit
  dans les salons directement via l'API Matrix (salons non chiffrés — cf.
  oria_provisioning, l'E2EE complet via l'embed du frontend Oria reste l'évolution).
"""
import json


def construire(ctx):
    oria = ctx.get("oria")

    # ── Mode sans messagerie : carte d'information ────────────────────────────
    if not oria or not oria.get("world_id"):
        html = """
        <div class="page-header"><h4><i class="bi bi-chat-dots me-2 text-wp"></i>Messagerie interne</h4>
          <p class="text-muted mb-0">Espace de discussion de l'équipe.</p></div>
        <div class="card"><div class="card-body">
          <p class="mb-1"><i class="bi bi-info-circle me-2"></i>La messagerie interne (espace + salons
          par entreprise, propulsée par Oria) est disponible quand l'application est générée en
          <strong>mode hébergé</strong> avec l'option messagerie.</p>
          <p class="text-muted small mb-0">Régénérez l'application avec
          <code>{"persistance":"hebergee","messagerie":true}</code> pour l'activer.</p>
        </div></div>
        """
        return [{"id": "messagerie", "label": "Messagerie", "icone": "bi-chat-dots",
                 "categorie": "outils", "html": html}]

    cfg = {
        "worldId": oria["world_id"],
        "salons": oria.get("salons", []),
        "oriaApi": oria.get("oria_api", "http://localhost:8000"),
        "matrix": oria.get("matrix", "http://localhost:8010"),
        "kc": oria.get("keycloak", {}),
    }

    html = _UI.replace("__ORIA_CFG__", json.dumps(cfg, ensure_ascii=False))
    return [{"id": "messagerie", "label": "Messagerie", "icone": "bi-chat-dots",
             "categorie": "outils", "html": html}]


_UI = r"""
<div class="page-header"><h4><i class="bi bi-chat-dots me-2 text-wp"></i>Messagerie interne</h4>
  <p class="text-muted mb-0">Salons d'équipe synchronisés avec votre espace Oria.</p></div>

<div id="msgAuth" class="card mb-3" style="display:none"><div class="card-body text-center">
  <p class="mb-3"><i class="bi bi-shield-lock me-2"></i>Connectez-vous pour accéder à la messagerie de l'entreprise.</p>
  <button class="btn btn-wp" id="msgLoginBtn"><i class="bi bi-box-arrow-in-right me-1"></i>Se connecter à la messagerie</button>
  <div id="msgAuthErr" class="text-danger small mt-2"></div>
</div></div>

<div id="msgApp" class="card" style="display:none"><div class="card-body p-0">
  <div class="d-flex" style="min-height:460px">
    <div style="width:210px;border-right:1px solid #eee" class="p-2">
      <div class="small text-muted px-2 mb-1 d-flex justify-content-between align-items-center">
        <span>SALONS</span><span id="msgUser" class="badge bg-secondary" style="font-weight:400"></span>
      </div>
      <ul id="msgSalons" class="nav flex-column"></ul>
    </div>
    <div class="d-flex flex-column flex-grow-1">
      <div class="px-3 py-2 border-bottom"><strong id="msgSalonTitre"># salon</strong></div>
      <div id="msgFil" class="flex-grow-1 p-3" style="overflow-y:auto;max-height:360px;background:#fafafa"></div>
      <div class="p-2 border-top d-flex gap-2">
        <input id="msgInput" class="form-control" placeholder="Votre message…" autocomplete="off">
        <button class="btn btn-wp" id="msgSend"><i class="bi bi-send"></i></button>
      </div>
    </div>
  </div>
</div></div>

<script>
(function(){
  const CFG = __ORIA_CFG__;
  // App livrée avec son PROPRE Keycloak (bundle) : la messagerie utilise CE serveur
  // d'identité (et réutilise plus bas le jeton de connexion de l'app → login unique).
  // NB : le serveur Oria doit faire confiance à ce realm pour valider le jeton.
  if (window.__WP_AUTH) CFG.kc = window.__WP_AUTH;
  const SS = window.sessionStorage;
  const REDIRECT = location.origin + location.pathname;   // sans query
  let token = null, me = null, salonCourant = null, pollTimer = null;

  // ── util PKCE ──────────────────────────────────────────────────────────────
  function b64url(buf){ return btoa(String.fromCharCode.apply(null, new Uint8Array(buf)))
      .replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''); }
  async function sha256(s){ return await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)); }
  function rand(){ return b64url(crypto.getRandomValues(new Uint8Array(32))); }

  async function login(){
    const verifier = rand(), state = rand();
    SS.setItem('wp_pkce_verifier', verifier);
    SS.setItem('wp_pkce_state', state);
    SS.setItem('wp_open_msg', '1');
    const challenge = b64url(await sha256(verifier));
    const u = CFG.kc.url + '/realms/' + CFG.kc.realm + '/protocol/openid-connect/auth'
      + '?client_id=' + encodeURIComponent(CFG.kc.clientId)
      + '&redirect_uri=' + encodeURIComponent(REDIRECT)
      + '&response_type=code&scope=openid'
      + '&code_challenge=' + challenge + '&code_challenge_method=S256'
      + '&state=' + state;
    location.assign(u);
  }

  async function echangeCode(code){
    const verifier = SS.getItem('wp_pkce_verifier');
    const body = new URLSearchParams({
      grant_type: 'authorization_code', client_id: CFG.kc.clientId,
      code: code, redirect_uri: REDIRECT, code_verifier: verifier || ''
    });
    const r = await fetch(CFG.kc.url + '/realms/' + CFG.kc.realm + '/protocol/openid-connect/token',
      { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
    if(!r.ok) throw new Error('Échec de l\'échange de jeton ('+r.status+')');
    const d = await r.json();
    token = d.access_token;
    SS.setItem('wp_token', token);
  }

  // ── Oria + Matrix ───────────────────────────────────────────────────────────
  async function oria(path, opts){
    opts = opts || {};
    opts.headers = Object.assign({'Authorization':'Bearer '+token}, opts.headers||{});
    return fetch(CFG.oriaApi + path, opts);
  }
  async function mx(path, opts){
    opts = opts || {};
    opts.headers = Object.assign({'Authorization':'Bearer '+me.mxtoken}, opts.headers||{});
    return fetch(CFG.matrix + path, opts);
  }

  async function chargerMe(){
    const r = await oria('/api/auth/me');
    if(r.status === 401){ token=null; SS.removeItem('wp_token'); throw new Error('401'); }
    if(!r.ok) throw new Error('auth/me '+r.status);
    const d = await r.json();
    me = { id:d.user.id, nom:d.user.nom, mxid:d.matrix_user_id, mxtoken:d.matrix_access_token };
  }

  async function rejoindreEspace(){
    // Adhésion à l'espace de l'entreprise (idempotent côté Oria)
    const qs = '?user_id=' + encodeURIComponent(me.id) + '&nom=' + encodeURIComponent(me.nom||'Membre');
    try { await oria('/api/worlds/' + CFG.worldId + '/rejoindre' + qs, {method:'POST'}); } catch(e){}
    // Rejoindre chaque salon Matrix (accepte l'invitation)
    for(const s of CFG.salons){
      try { await mx('/_matrix/client/v3/join/' + encodeURIComponent(s.matrix_room_id), {method:'POST',
        headers:{'Content-Type':'application/json'}, body:'{}'}); } catch(e){}
    }
  }

  // ── UI ────────────────────────────────────────────────────────────────────
  function rendreSalons(){
    const ul = document.getElementById('msgSalons'); ul.innerHTML='';
    CFG.salons.forEach(function(s, i){
      const li = document.createElement('li'); li.className='nav-item';
      const a = document.createElement('a'); a.href='#'; a.className='nav-link py-1';
      a.innerHTML = '<i class="bi bi-hash"></i> ' + s.nom;
      a.onclick = function(e){ e.preventDefault(); ouvrirSalon(s, a); };
      li.appendChild(a); ul.appendChild(li);
      if(i===0) setTimeout(function(){ ouvrirSalon(s, a); }, 0);
    });
  }

  function ouvrirSalon(s, el){
    salonCourant = s;
    document.querySelectorAll('#msgSalons .nav-link').forEach(function(n){ n.classList.remove('active'); });
    if(el) el.classList.add('active');
    document.getElementById('msgSalonTitre').textContent = '# ' + s.nom;
    chargerMessages();
    if(pollTimer) clearInterval(pollTimer);
    pollTimer = setInterval(chargerMessages, 4000);
  }

  function escape(t){ const d=document.createElement('div'); d.textContent=t; return d.innerHTML; }

  async function chargerMessages(){
    if(!salonCourant) return;
    try {
      const r = await mx('/_matrix/client/v3/rooms/' + encodeURIComponent(salonCourant.matrix_room_id)
        + '/messages?dir=b&limit=40');
      if(!r.ok) return;
      const d = await r.json();
      const evs = (d.chunk||[]).filter(function(e){ return e.type==='m.room.message' && e.content && e.content.body; }).reverse();
      const fil = document.getElementById('msgFil');
      fil.innerHTML = evs.map(function(e){
        const moi = e.sender === me.mxid;
        const qui = moi ? 'Vous' : (e.sender.split(':')[0].replace('@oria_','').slice(0,8));
        return '<div class="mb-2"><span class="badge ' + (moi?'bg-wp text-white':'bg-light text-dark')
          + '" style="font-weight:400">' + qui + '</span> '
          + '<span>' + escape(e.content.body) + '</span></div>';
      }).join('') || '<p class="text-muted small">Aucun message. Lancez la conversation 👋</p>';
      fil.scrollTop = fil.scrollHeight;
    } catch(e){}
  }

  async function envoyer(){
    const inp = document.getElementById('msgInput');
    const txt = inp.value.trim(); if(!txt || !salonCourant) return;
    inp.value='';
    const txn = 'wp' + Date.now() + Math.floor(Math.random()*1000);
    try {
      await mx('/_matrix/client/v3/rooms/' + encodeURIComponent(salonCourant.matrix_room_id)
        + '/send/m.room.message/' + txn, { method:'PUT',
        headers:{'Content-Type':'application/json'},
        body: JSON.stringify({msgtype:'m.text', body:txt}) });
      chargerMessages();
    } catch(e){ inp.value = txt; }
  }

  function montrerApp(){
    document.getElementById('msgAuth').style.display='none';
    document.getElementById('msgApp').style.display='block';
    document.getElementById('msgUser').textContent = me.nom || me.mxid;
    rendreSalons();
    document.getElementById('msgSend').onclick = envoyer;
    document.getElementById('msgInput').addEventListener('keydown', function(e){
      if(e.key==='Enter'){ e.preventDefault(); envoyer(); } });
    // Réactive l'onglet Messagerie après le retour de Keycloak
    if(SS.getItem('wp_open_msg')){ SS.removeItem('wp_open_msg');
      const lien = document.querySelector("[onclick*=\"'messagerie'\"]"); if(lien) lien.click(); }
  }

  function montrerLogin(msg){
    document.getElementById('msgApp').style.display='none';
    document.getElementById('msgAuth').style.display='block';
    if(msg) document.getElementById('msgAuthErr').textContent = msg;
  }

  async function demarrer(){
    try {
      await chargerMe();
      await rejoindreEspace();
      montrerApp();
    } catch(e){
      montrerLogin(e.message==='401' ? '' : ('Connexion impossible : ' + e.message));
    }
  }

  async function init(){
    document.getElementById('msgLoginBtn').onclick = login;
    // Retour de Keycloak ?
    const p = new URLSearchParams(location.search);
    if(p.get('code') && p.get('state') === SS.getItem('wp_pkce_state')){
      try {
        await echangeCode(p.get('code'));
        history.replaceState({}, '', REDIRECT);  // nettoie l'URL
      } catch(e){ montrerLogin(e.message); return; }
    }
    // Réutilise en priorité le jeton de connexion de l'app (Keycloak du bundle).
    token = token || window.__WP_TOKEN || SS.getItem('wp_app_token') || SS.getItem('wp_token');
    if(token){ demarrer(); } else { montrerLogin(); }
  }

  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
})();
</script>
"""
