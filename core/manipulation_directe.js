/* ════════════════════════════════════════════════════════════════════════
 * Socle « Manipulation directe & découvrabilité » (épopée S100→S104)
 * ────────────────────────────────────────────────────────────────────────
 * SOURCE UNIQUE. Copié tel quel dans chaque brique qui le sert (Docker COPY .)
 * via outils/sync_socle.sh. ⚠️ Ne PAS éditer les copies dans briques/* :
 * éditer CE fichier puis relancer la synchro.
 *
 * Fournit, prêt à brancher sur n'importe quel front Workplace (vanilla, sans
 * build) en une ligne `<script src="/manipulation_directe.js"></script>` :
 *   • confirmer / demanderTexte / ouvrirModal — modale lisible (remplace
 *     confirm()/prompt()), avec saisie optionnelle.
 *   • attacherMenu / ouvrirMenu / fermerMenu — menu contextuel : clic droit
 *     (souris) = appui long ~500 ms (tactile), sans avaler le tap court.
 *   • attacherAppuiLong — l'appui long seul, réutilisable.
 *   • sortable — cliquer-déposer pour réordonner une liste ET déposer un
 *     élément sur une zone externe (projet, catégorie, colonne kanban).
 *
 * Choix d'implémentation du drag : Pointer Events UNIQUEMENT (pas HTML5 DnD).
 * HTML5 `draggable` ne se déclenche pas au doigt sur mobile ; les Pointer
 * Events couvrent souris + tactile + stylet avec un seul chemin de code. (Le
 * drop de FICHIERS depuis l'OS dans le chat reste, lui, en HTML5 DnD côté
 * Cœur — c'est un autre besoin : fichiers externes, pas réordonnancement.)
 *
 * Le socle crée son propre DOM (#md-ctx, #md-modal) et injecte son CSS, le
 * tout préfixé `md-` pour ne JAMAIS entrer en collision avec les styles d'un
 * front. Les couleurs héritent du thème via var(--…, repli). Tout est exposé
 * sur `window` depuis une IIFE → aucune redéclaration `const` qui casserait
 * le script inline de la page (scope lexical partagé entre <script> classiques).
 * ════════════════════════════════════════════════════════════════════════ */
(function () {
  "use strict";
  if (window.__mdSocle) return;            // idempotent (double inclusion sans dégât)
  window.__mdSocle = true;

  const esc = s => (s == null ? "" : String(s)).replace(/[&<>]/g,
    c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  // ── CSS injecté une fois (préfixe md-, couleurs héritées du thème) ────────
  const CSS = `
  .md-modal{position:fixed;inset:0;background:rgba(0,0,0,.62);display:none;
    z-index:2000;align-items:center;justify-content:center;padding:18px}
  .md-modal.on{display:flex}
  .md-modal .md-box{background:var(--panel,#1b1e26);border:1px solid var(--line,#2c313c);
    border-radius:16px;padding:20px;max-width:420px;width:100%;box-shadow:0 20px 60px rgba(0,0,0,.5)}
  .md-modal h3{margin:0 0 8px;font-size:1.05rem}
  .md-modal p{color:var(--mut,#9aa3b2);font-size:.88rem;line-height:1.55;margin:0 0 14px;white-space:pre-wrap}
  .md-modal input{width:100%;box-sizing:border-box;margin:0 0 16px;padding:10px 12px;
    border-radius:10px;border:1px solid var(--line,#2c313c);background:var(--panel2,#11141a);
    color:inherit;font:inherit}
  .md-modal .md-actions{display:flex;gap:10px;justify-content:flex-end;flex-wrap:wrap}
  .md-modal button{padding:9px 16px;border-radius:10px;border:1px solid var(--line,#2c313c);
    background:var(--panel2,#11141a);color:inherit;cursor:pointer;font:inherit}
  .md-modal button.md-primary{background:var(--accent,#6c8cff);border-color:transparent;color:#fff}
  .md-modal button.md-danger{background:#e0667a;border-color:transparent;color:#fff}
  @media(max-width:560px){.md-modal .md-actions{justify-content:stretch}
    .md-modal .md-actions button{flex:1}}

  .md-ctx{position:fixed;z-index:2002;min-width:190px;background:var(--panel,#1b1e26);
    border:1px solid var(--line,#2c313c);border-radius:12px;padding:6px;display:none;
    box-shadow:0 16px 44px rgba(0,0,0,.5)}
  .md-ctx.on{display:block}
  .md-ctx button{display:flex;align-items:center;gap:9px;width:100%;text-align:left;
    background:none;border:0;color:inherit;padding:9px 11px;border-radius:8px;
    cursor:pointer;font:inherit}
  .md-ctx button:hover{background:var(--panel2,#11141a)}
  .md-ctx button.md-danger{color:#ff8fa0}
  .md-ctx button.md-danger:hover{background:rgba(224,102,122,.12)}
  .md-ctx .md-sep{height:1px;background:var(--line,#2c313c);margin:5px 4px}

  /* Appui long en cours : jauge de remplissage (retour visuel du geste). */
  .md-arming{position:relative;overflow:hidden}
  .md-arming::after{content:'';position:absolute;left:0;bottom:0;height:3px;width:100%;
    transform-origin:left;transform:scaleX(0);background:var(--accent,#6c8cff);
    animation:md-arm .5s linear forwards;opacity:.85}
  @keyframes md-arm{to{transform:scaleX(1)}}

  /* Cliquer-déposer. */
  .md-sortable [data-md-handle],.md-handle{cursor:grab;touch-action:none}
  .md-dragged{opacity:.35}
  .md-ghost{position:fixed;z-index:2003;pointer-events:none;opacity:.95;
    box-shadow:0 14px 40px rgba(0,0,0,.45);transform:rotate(1.5deg);will-change:left,top}
  .md-insert{height:0;border-top:2px solid var(--accent,#6c8cff);margin:-1px 0;
    border-radius:2px;box-shadow:0 0 8px var(--accent,#6c8cff)}
  .md-zone-actif{outline:2px dashed var(--accent,#6c8cff);outline-offset:2px;
    background:rgba(108,140,255,.10)}
  body.md-dragging{user-select:none;-webkit-user-select:none;cursor:grabbing}
  `;

  function injecterCss() {
    if (document.getElementById("md-socle-css")) return;
    const st = document.createElement("style");
    st.id = "md-socle-css"; st.textContent = CSS;
    document.head.appendChild(st);
  }

  // DOM (modale + menu) créé une fois, à la volée.
  let _modal, _ctx;
  function monterDom() {
    if (_modal) return;
    injecterCss();
    _modal = document.createElement("div");
    _modal.className = "md-modal"; _modal.id = "md-modal";
    _modal.setAttribute("role", "dialog"); _modal.setAttribute("aria-modal", "true");
    _modal.innerHTML =
      `<div class="md-box"><h3 id="md-modal-titre">Confirmer</h3>
       <p id="md-modal-msg"></p>
       <input id="md-modal-input" type="text" style="display:none">
       <div class="md-actions">
         <button id="md-modal-non">Annuler</button>
         <button id="md-modal-oui" class="md-primary">OK</button>
       </div></div>`;
    _ctx = document.createElement("div");
    _ctx.className = "md-ctx"; _ctx.id = "md-ctx";
    document.body.appendChild(_modal);
    document.body.appendChild(_ctx);
  }
  if (document.readyState === "loading")
    document.addEventListener("DOMContentLoaded", monterDom);
  else monterDom();

  // ── Modale : confirmation ou saisie (Promise) ─────────────────────────────
  function ouvrirModal({ titre = "Confirmer", message = "", action = "OK",
                         danger = false, saisie = false, valeur = "" } = {}) {
    monterDom();
    return new Promise(resolve => {
      const oui = document.getElementById("md-modal-oui"),
            non = document.getElementById("md-modal-non"),
            inp = document.getElementById("md-modal-input");
      document.getElementById("md-modal-titre").textContent = titre;
      document.getElementById("md-modal-msg").textContent = message;
      oui.textContent = action;
      oui.className = danger ? "md-danger" : "md-primary";
      inp.style.display = saisie ? "block" : "none";
      if (saisie) { inp.value = valeur || ""; setTimeout(() => { inp.focus(); inp.select(); }, 30); }
      _modal.classList.add("on");
      const fermer = v => {
        _modal.classList.remove("on");
        oui.onclick = non.onclick = _modal.onclick = inp.onkeydown = null;
        resolve(v);
      };
      oui.onclick = () => fermer(saisie ? inp.value.trim() : true);
      non.onclick = () => fermer(saisie ? null : false);
      _modal.onclick = e => { if (e.target === _modal) fermer(saisie ? null : false); };
      if (saisie) inp.onkeydown = e => {
        if (e.key === "Enter") oui.click();
        if (e.key === "Escape") non.click();
      };
    });
  }
  const confirmer = o => ouvrirModal({ action: "Supprimer", danger: true, ...o });
  const demanderTexte = o => ouvrirModal({ action: "Valider", saisie: true, ...o });

  // ── Menu contextuel ───────────────────────────────────────────────────────
  // `items` = [{label, emoji?, danger?, fn}] ; séparateur = {sep:true}.
  let _ctxClose = null;
  function ouvrirMenu(x, y, items) {
    monterDom();
    fermerMenu();
    _ctx.innerHTML = items.map((it, i) => it.sep ? '<div class="md-sep"></div>'
      : `<button data-i="${i}" class="${it.danger ? "md-danger" : ""}">` +
        `${it.emoji ? it.emoji + " " : ""}${esc(it.label)}</button>`).join("");
    _ctx.classList.add("on");
    const r = _ctx.getBoundingClientRect();
    const px = Math.min(x, innerWidth - r.width - 8), py = Math.min(y, innerHeight - r.height - 8);
    _ctx.style.left = Math.max(8, px) + "px";
    _ctx.style.top = Math.max(8, py) + "px";
    _ctx.querySelectorAll("button").forEach(b =>
      b.onclick = () => { const it = items[+b.dataset.i]; fermerMenu(); it.fn(); });
    // Listeners NOMMÉS, retirés par fermerMenu quel que soit le chemin → zéro orphelin.
    _ctxClose = ev => { if (!_ctx.contains(ev.target)) fermerMenu(); };
    setTimeout(() => {
      if (!_ctxClose) return;
      document.addEventListener("click", _ctxClose);
      document.addEventListener("contextmenu", _ctxClose);
    }, 0);
    window.addEventListener("scroll", fermerMenu, { capture: true });
  }
  function fermerMenu() {
    if (!_ctx) return;
    _ctx.classList.remove("on");
    if (_ctxClose) {
      document.removeEventListener("click", _ctxClose);
      document.removeEventListener("contextmenu", _ctxClose);
      _ctxClose = null;
    }
    window.removeEventListener("scroll", fermerMenu, { capture: true });
  }
  document.addEventListener("keydown", e => { if (e.key === "Escape") fermerMenu(); });

  // ── Appui long (tactile) réutilisable ─────────────────────────────────────
  // Déclenche `fn(x,y)` après ~`duree` ms d'appui immobile. `armed()` renvoie
  // une fonction qui dit si le dernier geste a effectivement armé (pour neutraliser
  // le clic fantôme qui suit). Retourne un détacheur.
  function attacherAppuiLong(el, fn, duree = 500) {
    let t = null, armed = false, x0 = 0, y0 = 0, lx = 0, ly = 0;
    const demarrer = (x, y) => {
      x0 = lx = x; y0 = ly = y; armed = false; el.classList.add("md-arming");
      t = setTimeout(() => {
        armed = true; el.classList.remove("md-arming");
        if (navigator.vibrate) navigator.vibrate(12);
        fn(lx, ly);
      }, duree);
    };
    const annuler = () => { clearTimeout(t); el.classList.remove("md-arming"); };
    const bouge = (x, y) => { lx = x; ly = y; if (Math.abs(x - x0) > 12 || Math.abs(y - y0) > 12) annuler(); };
    const ts = e => demarrer(e.touches[0].clientX, e.touches[0].clientY);
    const tm = e => bouge(e.touches[0].clientX, e.touches[0].clientY);
    const clic = e => { if (armed) { e.stopPropagation(); e.preventDefault(); armed = false; } };
    el.addEventListener("touchstart", ts, { passive: true });
    el.addEventListener("touchmove", tm, { passive: true });
    el.addEventListener("touchend", annuler);
    el.addEventListener("click", clic, true);   // neutralise le clic fantôme post appui long
    return () => {
      annuler();
      el.removeEventListener("touchstart", ts);
      el.removeEventListener("touchmove", tm);
      el.removeEventListener("touchend", annuler);
      el.removeEventListener("click", clic, true);
    };
  }

  // Lie un menu contextuel : clic droit (souris) + appui long (tactile).
  function attacherMenu(el, itemsFn) {
    el.addEventListener("contextmenu", e => {
      e.preventDefault(); ouvrirMenu(e.clientX, e.clientY, itemsFn());
    });
    attacherAppuiLong(el, (x, y) => ouvrirMenu(x, y, itemsFn()));
  }

  // ── Cliquer-déposer (Pointer Events, souris + tactile) ────────────────────
  // sortable(conteneur, {
  //   itemSelector  : sélecteur des éléments déplaçables (déf. '[data-id]'),
  //   handle        : sélecteur d'une poignée (déf. null = tout l'élément),
  //   seuil         : px à franchir avant d'enclencher (déf. 8, préserve le tap),
  //   onReorder(ids, {id})        : appelé après un réordonnancement (ids = ordre courant),
  //   zones         : sélecteur de zones de dépôt EXTERNES (projet, catégorie, colonne),
  //   onDropZone(id, zoneEl)      : appelé quand on lâche l'élément sur une zone,
  // })
  // Persistance = à la charge des callbacks (le socle ne suppose aucun backend).
  function sortable(conteneur, o = {}) {
    // Idempotent : un conteneur persistant dont on re-rend le contenu (liste rechargée)
    // peut rappeler sortable() ; on ne ré-attache pas le listener (sinon empilement). Les
    // éléments sont relus dynamiquement au drag, donc un seul branchement suffit.
    if (conteneur.__mdSortable) return;
    conteneur.__mdSortable = true;
    o = Object.assign({ itemSelector: "[data-id]", handle: null, seuil: 8,
      onReorder: null, zones: null, onDropZone: null }, o);
    conteneur.classList.add("md-sortable");

    const idDe = el => el.dataset.id;
    const ordreCourant = () => Array.from(conteneur.querySelectorAll(o.itemSelector))
      .filter(e => !e.classList.contains("md-ghost")).map(idDe);

    conteneur.addEventListener("pointerdown", e => {
      if (e.button != null && e.button !== 0) return;      // bouton gauche / doigt seulement
      const item = e.target.closest(o.itemSelector);
      if (!item || !conteneur.contains(item)) return;
      if (o.handle && !e.target.closest(o.handle)) return; // poignée requise si fournie

      const sx = e.clientX, sy = e.clientY, pid = e.pointerId, id = idDe(item);
      let started = false, ghost = null, insert = null, zone = null;

      const placeInsert = ev => {
        const freres = Array.from(conteneur.querySelectorAll(o.itemSelector))
          .filter(el => el !== item && el !== ghost);
        let cible = null;
        for (const f of freres) {
          const r = f.getBoundingClientRect();
          if (ev.clientY < r.top + r.height / 2) { cible = f; break; }
        }
        if (cible) conteneur.insertBefore(insert, cible);
        else conteneur.appendChild(insert);
      };
      const zoneSous = ev => {
        if (!o.zones) return null;
        const el = document.elementFromPoint(ev.clientX, ev.clientY);
        return el ? el.closest(o.zones) : null;
      };
      const eclairerZone = z => {
        if (z === zone) return;
        if (zone) zone.classList.remove("md-zone-actif");
        zone = z;
        if (zone) zone.classList.add("md-zone-actif");
      };

      const demarrer = () => {
        started = true;
        const r = item.getBoundingClientRect();
        ghost = item.cloneNode(true);
        ghost.classList.add("md-ghost");
        ghost.style.width = r.width + "px";
        ghost.style.left = r.left + "px";
        ghost.style.top = r.top + "px";
        ghost._dx = sx - r.left; ghost._dy = sy - r.top;
        document.body.appendChild(ghost);
        insert = document.createElement("div");
        insert.className = "md-insert";
        item.classList.add("md-dragged");
        document.body.classList.add("md-dragging");
        try { item.setPointerCapture(pid); } catch (_) {}
      };

      const onMove = ev => {
        if (!started) {
          if (Math.abs(ev.clientX - sx) < o.seuil && Math.abs(ev.clientY - sy) < o.seuil) return;
          demarrer();
        }
        ghost.style.left = (ev.clientX - ghost._dx) + "px";
        ghost.style.top = (ev.clientY - ghost._dy) + "px";
        const z = zoneSous(ev);
        eclairerZone(z);
        if (z) { if (insert.parentNode) insert.remove(); }   // sur une zone : pas de ligne d'insertion
        else placeInsert(ev);
      };

      const finir = ev => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", finir);
        document.removeEventListener("pointercancel", annuler);
        if (!started) return;
        const z = zone;
        eclairerZone(null);
        ghost.remove();
        item.classList.remove("md-dragged");
        document.body.classList.remove("md-dragging");
        if (z && o.onDropZone) {
          if (insert.parentNode) insert.remove();
          o.onDropZone(id, z);
          return;
        }
        // Réordonnancement : place l'élément là où était la ligne d'insertion.
        if (insert.parentNode) { conteneur.insertBefore(item, insert); insert.remove(); }
        if (o.onReorder) o.onReorder(ordreCourant(), { id });
        // Neutralise le clic fantôme (tap d'ouverture) qui suit un vrai drag.
        const stopClic = c => { c.stopPropagation(); c.preventDefault(); };
        document.addEventListener("click", stopClic, { capture: true, once: true });
        setTimeout(() => document.removeEventListener("click", stopClic, { capture: true }), 0);
      };
      const annuler = () => {
        document.removeEventListener("pointermove", onMove);
        document.removeEventListener("pointerup", finir);
        document.removeEventListener("pointercancel", annuler);
        if (!started) return;
        eclairerZone(null);
        if (ghost) ghost.remove();
        if (insert && insert.parentNode) insert.remove();
        item.classList.remove("md-dragged");
        document.body.classList.remove("md-dragging");
      };

      document.addEventListener("pointermove", onMove);
      document.addEventListener("pointerup", finir);
      document.addEventListener("pointercancel", annuler);
    });
  }

  // ── Exposition (window) ───────────────────────────────────────────────────
  Object.assign(window, {
    ouvrirModal, confirmer, demanderTexte,
    ouvrirMenu, fermerMenu, attacherMenu, attacherAppuiLong,
    sortable,
  });
})();
