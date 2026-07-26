# S199 — Suppression mail groupée — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter dans l'UI de la brique Mail (`briques/mail`) la possibilité de supprimer
plusieurs mails d'un coup (checkboxes + action groupée + confirmation obligatoire),
alors qu'aujourd'hui aucun bouton de suppression n'existe côté front bien que le backend
le supporte déjà (`DELETE /mail/{message_id}`).

**Architecture:** Un nouvel endpoint `POST /mail/supprimer-lot` réutilise la logique déjà
en place dans `supprimer()` (main.py:355) pour chaque id, et renvoie un résultat par
message (succès/échec) au lieu de tout annuler sur le premier échec. Le front (page HTML
embarquée dans `main.py`) ajoute une checkbox par ligne, une barre d'action flottante, et
une confirmation JS bloquante avant l'appel.

**Tech Stack:** FastAPI (Python), SQLite via `stockage.py`, JS vanilla dans la page HTML
embarquée de `briques/mail/main.py` (pas de framework front).

## Global Constraints

- Sur un compte IMAP réel, la suppression peut être **définitive** (EXPUNGE) si aucune
  corbeille n'est détectable côté serveur — la confirmation front doit le dire
  explicitement, pas de bouton de suppression individuelle (uniquement l'action groupée,
  décision produit S199).
- Suivre le motif d'isolation existant : toutes les requêtes passent par
  `Depends(tenant_actuel)` (main.py:44), un tenant ne peut jamais agir sur les messages
  d'un autre (cf. `test_isolation_un_tenant_ne_supprime_pas_chez_un_autre`,
  `test_actions.py:82`).
- Aucune nouvelle capacité assistant (manifest) : cette action est déclenchée uniquement
  depuis l'UI humaine, pas par l'assistant conversationnel.

---

### Task 1: Endpoint backend `POST /mail/supprimer-lot`

**Files:**
- Modify: `briques/mail/main.py:123-125` (ajouter le modèle), `briques/mail/main.py:355-368`
  (ajouter la route juste après `supprimer`)
- Test: `briques/mail/test_actions.py`

**Interfaces:**
- Consumes : `stockage.lire_message(tenant, message_id) -> dict | None`,
  `_compte_reel_du_message(tenant, msg) -> dict | None`,
  `_agir_serveur(compte, action) -> None` (lève `HTTPException(502, detail)` si le
  serveur refuse), `stockage.supprimer_message(tenant, message_id) -> None` — tous déjà
  définis dans `main.py`.
- Produces : `POST /mail/supprimer-lot` — body `{"message_ids": ["id1", "id2", ...]}`,
  réponse `{"resultats": [{"message_id": str, "ok": bool, "erreur": str | None}, ...],
  "supprimes": int}`. Utilisé par le front (Task 2).

- [ ] **Step 1: Écrire les tests qui échouent**

Ajouter à la fin de `briques/mail/test_actions.py` :

```python
def test_supprimer_lot_plusieurs_messages():
    h = _h("t-lot-ok")
    msgs = client.get("/mail", headers=h).json()["messages"]
    ids = [msgs[0]["id"], msgs[1]["id"]]
    avant = client.get("/mail", headers=h).json()["total"]

    r = client.post("/mail/supprimer-lot", json={"message_ids": ids}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["supprimes"] == 2
    assert all(res["ok"] for res in j["resultats"])
    assert {res["message_id"] for res in j["resultats"]} == set(ids)

    apres = client.get("/mail", headers=h).json()
    assert apres["total"] == avant - 2
    assert all(m["id"] not in ids for m in apres["messages"])


def test_supprimer_lot_echec_partiel_id_inexistant():
    h = _h("t-lot-partiel")
    mid_valide = _premier_id(h)

    r = client.post("/mail/supprimer-lot",
                    json={"message_ids": [mid_valide, "id-inexistant"]}, headers=h)
    assert r.status_code == 200
    j = r.json()
    assert j["supprimes"] == 1
    par_id = {res["message_id"]: res for res in j["resultats"]}
    assert par_id[mid_valide]["ok"] is True
    assert par_id["id-inexistant"]["ok"] is False
    assert par_id["id-inexistant"]["erreur"]

    assert client.get(f"/mail/{mid_valide}", headers=h).status_code == 404


def test_supprimer_lot_isolation_entre_tenants():
    a, b = _h("cle-alice-lot"), _h("cle-bob-lot")
    mid_alice = client.get("/mail", headers=a).json()["messages"][0]["id"]

    r = client.post("/mail/supprimer-lot", json={"message_ids": [mid_alice]}, headers=b)
    assert r.status_code == 200
    j = r.json()
    assert j["supprimes"] == 0
    assert j["resultats"][0]["ok"] is False

    # Alice voit toujours son message : Bob n'a rien pu supprimer.
    assert client.get(f"/mail/{mid_alice}", headers=a).status_code == 200


def test_supprimer_lot_liste_vide():
    h = _h("t-lot-vide")
    r = client.post("/mail/supprimer-lot", json={"message_ids": []}, headers=h)
    assert r.status_code == 200
    assert r.json() == {"resultats": [], "supprimes": 0}
```

- [ ] **Step 2: Lancer les tests, vérifier qu'ils échouent**

Run: `cd briques/mail && python -m pytest test_actions.py -k supprimer_lot -v`
Expected: FAIL — `404 Not Found` sur `/mail/supprimer-lot` (route inexistante).

- [ ] **Step 3: Ajouter le modèle et la route**

Dans `briques/mail/main.py`, juste après `class DeplacerEntree` (ligne 123-124), ajouter :

```python
class SupprimerLotEntree(BaseModel):
    message_ids: list[str]
```

Juste après la fonction `supprimer` (après la ligne 367, avant `@app.post("/mail/trier")`),
ajouter :

```python
@app.post("/mail/supprimer-lot")
def supprimer_lot(corps: SupprimerLotEntree, tenant: str = Depends(tenant_actuel)):
    """Supprime PLUSIEURS messages en une fois (action groupée de l'UI — pas de bouton de
    suppression individuelle, décision produit S199). Réutilise la même logique que
    `supprimer` message par message ; un échec sur l'un n'empêche jamais les autres, chaque
    message a son propre résultat (jamais de mensonge global « tout est passé »)."""
    _assurer_cache(tenant)
    resultats = []
    for mid in corps.message_ids:
        msg = stockage.lire_message(tenant, mid)
        if not msg:
            resultats.append({"message_id": mid, "ok": False, "erreur": "Message introuvable."})
            continue
        compte = _compte_reel_du_message(tenant, msg)
        try:
            _agir_serveur(compte, lambda f: f.supprimer(msg["uid"], msg.get("dossier", "INBOX")))
        except HTTPException as e:
            resultats.append({"message_id": mid, "ok": False, "erreur": str(e.detail)})
            continue
        stockage.supprimer_message(tenant, mid)
        resultats.append({"message_id": mid, "ok": True, "erreur": None})
    return {"resultats": resultats, "supprimes": sum(1 for r in resultats if r["ok"])}
```

- [ ] **Step 4: Lancer les tests, vérifier qu'ils passent**

Run: `cd briques/mail && python -m pytest test_actions.py -v`
Expected: PASS (toutes les fonctions de `test_actions.py`, y compris les 4 nouvelles).

- [ ] **Step 5: Commit**

```bash
git add briques/mail/main.py briques/mail/test_actions.py
git commit -m "feat(mail): endpoint suppression groupée /mail/supprimer-lot"
```

---

### Task 2: UI — sélection multiple + suppression groupée

**Files:**
- Modify: `briques/mail/main.py` (page HTML embarquée : CSS ~ligne 700, bandeau ~ligne
  727, structure liste ~ligne 712-715, template de ligne ~ligne 840-848, fonction
  `recharger` ~ligne 827-849)

**Interfaces:**
- Consumes : `POST /mail/supprimer-lot` (Task 1) — body `{message_ids: string[]}`, réponse
  `{resultats: [{message_id, ok, erreur}], supprimes: number}`.
- Produces : rien consommé par une tâche suivante (dernière tâche du plan).

- [ ] **Step 1: Retirer le bandeau « lecture seule » devenu faux**

Dans `briques/mail/main.py`, remplacer (ligne 727-728) :

```html
      <span class=muted>Lecture seule : rien n'est jamais supprimé ni déplacé. Le mot de passe est
      chiffré au repos, jamais affiché. Tu peux connecter plusieurs adresses.</span></p>
```

par :

```html
      <span class=muted>Le mot de passe est chiffré au repos, jamais affiché. Tu peux
      connecter plusieurs adresses. La suppression (sélection multiple dans la liste) met
      le message à la corbeille du serveur si une corbeille est détectable, sinon
      l'efface définitivement.</span></p>
```

- [ ] **Step 2: Ajouter la barre d'action au-dessus de la liste**

Dans `briques/mail/main.py`, remplacer (ligne 712-715) :

```html
<div class=body>
  <div class=liste id=liste></div>
  <div class=lec id=lec><div class=vide>Sélectionne un message pour le lire.</div></div>
</div>
```

par :

```html
<div class=body>
  <div class=listewrap>
    <div class=actbar id=actbar>
      <label style="display:flex;align-items:center;gap:6px;font-size:.82rem">
        <input type=checkbox id=selAll onchange="toggleSelAll(this.checked)">Tout sélectionner
      </label>
      <span id=selCount class=muted style="font-size:.82rem"></span>
      <button class=btn style="color:#dc2626;margin-left:auto" onclick=supprimerSelection()>
        🗑️ Supprimer la sélection</button>
    </div>
    <div class=liste id=liste></div>
  </div>
  <div class=lec id=lec><div class=vide>Sélectionne un message pour le lire.</div></div>
</div>
```

Ajouter au bloc `<style>` (après la règle `.muted{color:var(--mut)}` ligne 700) :

```css
 .listewrap{display:flex;flex-direction:column;min-width:0}
 .actbar{display:none;align-items:center;gap:10px;padding:8px 10px;border-bottom:1px solid var(--bd)}
 .actbar.on{display:flex}
```

- [ ] **Step 3: Ajouter la checkbox par ligne et la logique de sélection**

Dans `briques/mail/main.py`, remplacer la fonction `recharger` (ligne 827-849) par :

```javascript
let SEL=new Set();
async function recharger(){
  const p=new URLSearchParams();
  if(filtre==='__nl')p.set('non_lus','true');
  else if(filtre.startsWith('f:'))p.set('filtre',filtre.slice(2));
  else if(filtre)p.set('categorie',filtre);
  const compte=document.getElementById('fCompte').value; if(compte)p.set('compte',compte);
  p.set('limite','200');
  const j=await fetch(API+'/mail?'+p,{headers:entetes()}).then(r=>r.json());
  let msgs=j.messages||[]; const q=document.getElementById('q').value.trim().toLowerCase();
  if(q)msgs=msgs.filter(m=>((m.sujet||'')+' '+(m.de_nom||'')+' '+(m.de||'')+' '+(m.extrait||'')).toLowerCase().includes(q));
  MSGS=msgs;
  SEL=new Set([...SEL].filter(id=>msgs.some(m=>m.id===id)));  // purge la sélection des mails disparus
  const L=document.getElementById('liste');
  if(!msgs.length){L.innerHTML='<div class=vide style="padding:30px;color:#94a3b8">Aucun message.</div>';majBarreSelection();return;}
  L.innerHTML=msgs.map(m=>`<div class="it ${m.lu?'':'nl'} ${m.id===selId?'sel':''}" onclick="ouvrir('${m.id}')">
    <input type=checkbox onclick="event.stopPropagation()" onchange="toggleSel('${m.id}', this.checked)" ${SEL.has(m.id)?'checked':''}>
    <span class=dot></span><div class=mid>
      <div class=de><span class=de>${esc(m.de_nom||m.de)}</span><span class=muted style="font-size:.72rem">${dateCourte(m.date)}</span></div>
      <div class=suj>${esc(m.sujet||'(sans sujet)')}</div>
      <div class=ex>${esc(m.extrait||'')}</div>
      <div class=meta><span class=cat>${ETIQ[m.categorie]||m.categorie||''}</span>
        ${m.score>=70?'<span class=pri-h>● prioritaire</span>':''}
        ${m.compte?('<span class=muted>'+esc(m.compte)+'</span>'):''}</div>
    </div></div>`).join('');
  majBarreSelection();
}

function toggleSel(id, checked){
  if(checked)SEL.add(id); else SEL.delete(id);
  majBarreSelection();
}
function toggleSelAll(checked){
  SEL = checked ? new Set(MSGS.map(m=>m.id)) : new Set();
  document.querySelectorAll('#liste input[type=checkbox]').forEach(cb=>cb.checked=checked);
  majBarreSelection();
}
function majBarreSelection(){
  const bar=document.getElementById('actbar');
  document.getElementById('selCount').textContent = SEL.size ? (SEL.size+' sélectionné(s)') : '';
  bar.classList.toggle('on', SEL.size>0);
  const all=document.getElementById('selAll');
  all.checked = MSGS.length>0 && SEL.size===MSGS.length;
}
async function supprimerSelection(){
  if(!SEL.size)return;
  const n=SEL.size;
  if(!confirm(`Supprimer définitivement ${n} mail(s) ? Sur une vraie boîte, un message peut être effacé pour de bon si aucune corbeille n'est détectable côté serveur — cette action ne peut pas être annulée depuis cette interface.`))return;
  const r=await fetch(API+'/mail/supprimer-lot',{method:'POST',headers:entetes(),
    body:JSON.stringify({message_ids:[...SEL]})});
  const j=await r.json();
  const echecs=(j.resultats||[]).filter(x=>!x.ok);
  SEL=new Set();
  await recharger();
  if(echecs.length)alert(`${j.supprimes||0} supprimé(s), ${echecs.length} échec(s) :\n`+echecs.map(e=>e.erreur).join('\n'));
}
```

- [ ] **Step 4: Vérifier manuellement dans le navigateur**

Lancer la brique en local (`cd briques/mail && MAIL_DB=/tmp/mail_manuel.db uvicorn main:app
--port 6030 --reload`), ouvrir `http://localhost:6030/`, cocher 2-3 mails, vérifier que la
barre d'action apparaît avec le bon compte, cliquer « Tout sélectionner », vérifier que
toutes les cases se cochent, cliquer « Supprimer la sélection », confirmer dans la popup,
vérifier que les mails ont disparu de la liste et qu'un message de résultat s'affiche.

- [ ] **Step 5: Commit**

```bash
git add briques/mail/main.py
git commit -m "feat(mail): sélection multiple + bouton suppression groupée dans l'UI"
```

## Self-Review

1. **Spec coverage** : suppression groupée uniquement (pas de bouton individuel) → Task 2 ;
   confirmation obligatoire → `supprimerSelection()` Step 3 ; endpoint dédié avec résultat
   par message → Task 1 ; bandeau front mis à jour → Task 2 Step 1. Tout couvert.
2. **Placeholder scan** : aucun TODO/TBD, tout le code est complet.
3. **Type consistency** : `message_ids: list[str]` (Task 1) ↔ `{message_ids:[...SEL]}` (Task 2)
   cohérent ; `resultats[].{message_id,ok,erreur}` utilisé identiquement des deux côtés.
