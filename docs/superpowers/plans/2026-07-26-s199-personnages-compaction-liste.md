# S199 — Compaction de la liste des personnages enregistrés — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rendre la liste « Mes personnages enregistrés » (`briques/personnages/front_holistique.html`)
navigable quand elle devient longue, en repliant les groupes par catégorie et en ajoutant
une recherche par nom.

**Architecture:** Le groupement par catégorie existe déjà (`chargerFiches()`) mais tout est
toujours affiché en entier. On ajoute un état de repli par catégorie (Set en mémoire, tout
replié par défaut), un champ de recherche qui filtre `_fichesCache` et déplie
automatiquement les catégories contenant un résultat, et deux boutons « tout déplier / tout
replier ». Aucun changement backend : la donnée (`categorie` par fiche) existe déjà.

**Tech Stack:** JS vanilla dans la page HTML embarquée `briques/personnages/front_holistique.html`
(pas de framework front, pas de build step).

## Global Constraints

- Ne pas casser le cliquer-déposer existant (`brancherDndFiches`, S104) : les zones
  `.cat-zone[data-cat=...]` doivent rester présentes dans le DOM (repliées = lignes
  cachées, pas la zone elle-même) pour rester des cibles de dépôt valides.
- Fiches sans catégorie assignée → groupées sous « Non rangés », toujours visibles (jamais
  de perte silencieuse).
- Pas de nouvelle capacité assistant, pas de nouvel endpoint : purement front.

---

### Task 1: État de repli + recherche sur la liste des fiches

**Files:**
- Modify: `briques/personnages/front_holistique.html:199` (zone de recherche),
  `briques/personnages/front_holistique.html:593-622` (`chargerFiches`),
  `briques/personnages/front_holistique.html:642-677` (`ligneFiche`, inchangée dans sa
  signature)

**Interfaces:**
- Consumes : `api('/fiches')` → `Array<{id, nom, nom_naissance, archetype, categorie,
  cree_le}>` (déjà existant, inchangé).
- Produces : rien consommé par une tâche suivante (unique tâche du plan).

- [ ] **Step 1: Ajouter la barre de recherche + boutons déplier/replier au-dessus de la liste**

Dans `briques/personnages/front_holistique.html`, remplacer (ligne 196-200) :

```html
    <details id="mes-fiches" style="margin-top:12px" ontoggle="if(this.open) chargerFiches()">
      <summary style="cursor:pointer;font-size:.8rem;color:var(--accent)">💾 Mes personnages enregistrés</summary>
      <p class="hint" style="margin:6px 0 0">Touchez pour ouvrir · <b>clic droit</b> / <b>appui long</b> pour le menu (renommer, ranger, supprimer).</p>
      <div id="fiches-liste" class="hint" style="margin-top:8px">…</div>
    </details>
```

par :

```html
    <details id="mes-fiches" style="margin-top:12px" ontoggle="if(this.open) chargerFiches()">
      <summary style="cursor:pointer;font-size:.8rem;color:var(--accent)">💾 Mes personnages enregistrés</summary>
      <p class="hint" style="margin:6px 0 0">Touchez pour ouvrir · <b>clic droit</b> / <b>appui long</b> pour le menu (renommer, ranger, supprimer).</p>
      <div class="row" style="margin-top:8px;gap:8px;align-items:center">
        <input id="fiches-recherche" type="text" placeholder="Rechercher un nom…"
          oninput="dessinerFichesGroupees()" style="flex:1">
        <button type="button" class="ghost" style="width:auto;margin:0;padding:6px 10px;font-size:.78rem"
          onclick="deplierTout(true)">Tout déplier</button>
        <button type="button" class="ghost" style="width:auto;margin:0;padding:6px 10px;font-size:.78rem"
          onclick="deplierTout(false)">Tout replier</button>
      </div>
      <div id="fiches-liste" class="hint" style="margin-top:8px">…</div>
    </details>
```

- [ ] **Step 2: Séparer chargement (réseau) et rendu (regroupement + repli + recherche)**

Dans `briques/personnages/front_holistique.html`, remplacer la fonction `chargerFiches`
(ligne 593-622) par :

```javascript
let _fichesCache=[];
let _categoriesOuvertes=new Set();   // vide par défaut = tout replié

async function chargerFiches(){
  const box=$('fiches-liste'); box.textContent='Chargement…';
  try{
    const r=await api('/fiches'); if(!r.ok) throw new Error('HTTP '+r.status);
    _fichesCache=await r.json();
    if(!_fichesCache.length){ box.textContent="Aucun personnage enregistré pour l'instant."; return; }
    majDatalistCategories(_fichesCache);
    dessinerFichesGroupees();
  }catch(e){ box.textContent='⚠ '+e.message; }
}

function deplierTout(ouvrir){
  if(ouvrir){
    const groupes={}; _fichesCache.forEach(f=>{ const c=(f.categorie||'').trim(); groupes[c]=true; });
    _categoriesOuvertes=new Set(Object.keys(groupes));
  } else {
    _categoriesOuvertes=new Set();
  }
  dessinerFichesGroupees();
}

function dessinerFichesGroupees(){
  const box=$('fiches-liste');
  if(!_fichesCache.length){ box.textContent="Aucun personnage enregistré pour l'instant."; return; }
  const q=($('fiches-recherche')?.value||'').trim().toLowerCase();
  const arr=q ? _fichesCache.filter(f=>
    (f.nom||'').toLowerCase().includes(q) || (f.nom_naissance||'').toLowerCase().includes(q)
  ) : _fichesCache;
  box.innerHTML='';
  if(!arr.length){ box.innerHTML='<p class="hint">Aucun résultat pour cette recherche.</p>'; return; }
  // Regroupe par catégorie libre pour éviter un gros scroll quand il y en a beaucoup.
  // Les catégories sont triées (alpha), « Non rangés » en dernier.
  const groupes={};
  arr.forEach(f=>{ const c=(f.categorie||'').trim(); (groupes[c]=groupes[c]||[]).push(f); });
  const nommees=Object.keys(groupes).filter(c=>c).sort((a,b)=>a.localeCompare(b,'fr'));
  const ordre=nommees.concat(groupes[''] ? [''] : []);
  ordre.forEach(cat=>{
    // S104 : chaque section de catégorie est une ZONE de dépôt (data-cat), TOUJOURS présente
    // dans le DOM (repliée = lignes cachées, pas la zone) pour rester une cible de dépôt valide.
    const ouverte=q ? true : _categoriesOuvertes.has(cat);
    const zone=document.createElement('div');
    zone.className='cat-zone'; zone.dataset.cat=cat;
    const titre=document.createElement('div');
    titre.style.cssText='margin:12px 0 4px;font-size:.78rem;font-weight:600;cursor:pointer;'+
      'color:var(--accent);text-transform:uppercase;letter-spacing:.04em';
    titre.textContent=(ouverte?'▾ ':'▸ ')+(cat||'Non rangés')+'  ('+groupes[cat].length+')';
    titre.onclick=()=>{
      if(_categoriesOuvertes.has(cat)) _categoriesOuvertes.delete(cat); else _categoriesOuvertes.add(cat);
      dessinerFichesGroupees();
    };
    zone.append(titre);
    const rows=document.createElement('div');
    rows.style.display=ouverte?'':'none';
    groupes[cat].forEach(f=>rows.append(ligneFiche(f)));
    zone.append(rows);
    box.append(zone);
  });
  brancherDndFiches(box);
}
```

- [ ] **Step 3: Vérifier manuellement dans le navigateur**

Lancer la brique en local (`cd briques/personnages && uvicorn main:app --port 5900
--reload`), ouvrir `http://localhost:5900/holistique` (ou le chemin de la page), créer
au moins 5-6 fiches réparties sur 2-3 catégories différentes, ouvrir « Mes personnages
enregistrés » et vérifier : toutes les catégories démarrent repliées (▸), cliquer sur un
titre de catégorie la déplie (▾) et affiche ses fiches, taper dans la recherche filtre et
déplie automatiquement les catégories concernées, « Tout déplier »/« Tout replier »
fonctionnent, le glisser-déposer d'une fiche dépliée vers une autre catégorie (repliée ou
non) la range toujours correctement.

- [ ] **Step 4: Commit**

```bash
git add briques/personnages/front_holistique.html
git commit -m "feat(personnages): compaction de la liste des fiches (repli par catégorie + recherche)"
```

## Self-Review

1. **Spec coverage** : accordéon replié par défaut → Task 1 Step 2 (`_categoriesOuvertes`
   vide par défaut) ; recherche texte → `dessinerFichesGroupees` filtre sur nom/nom_naissance ;
   tout déplier/replier → `deplierTout` ; fiches sans catégorie groupées sous « Non rangés »,
   toujours visibles → `ordre` inclut `''` en dernier, jamais filtré hors de `groupes`. Tout
   couvert.
2. **Placeholder scan** : aucun TODO/TBD, code complet.
3. **Type consistency** : `ligneFiche(f)` (inchangée, ligne 642) reste appelée avec le même
   objet fiche `{id, nom, nom_naissance, archetype, categorie, cree_le}` qu'avant ;
   `brancherDndFiches(box)` reste appelée avec le conteneur racine comme avant (signature
   inchangée, ligne 626).
