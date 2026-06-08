"""Générateur d'application HTML (Bootstrap 5) à partir d'un audit Workplace.

Produit une app à la fois :
- OPÉRATIONNELLE : un module interactif par entité métier (tableau + formulaire
  d'ajout + suppression), avec persistance dans le navigateur (localStorage).
- ANALYTIQUE : Pareto du chiffre d'affaires (80/20) + les analyses de l'audit
  (Territoire/DDD, Flux/VSM, Problèmes/Ishikawa, Priorités/SWOT/MoSCoW/Chemin critique).
"""
import json


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _s(val, default="—"):
    if val is None:
        return default
    if isinstance(val, (list, dict)):
        return val
    return str(val)


def _d(val) -> dict:
    """Garantit un dict (le JSON LLM peut renvoyer une liste/None là où on attend un objet)."""
    return val if isinstance(val, dict) else {}


def _l(val) -> list:
    """Garantit une liste."""
    return val if isinstance(val, list) else []


def _first(d: dict, *cles, default=None):
    """Renvoie la première clé présente et non vide — tolère les variations de nommage du LLM."""
    for c in cles:
        if isinstance(d, dict) and d.get(c) not in (None, "", [], {}):
            return d.get(c)
    return default


def _num(val):
    """Convertit en float si possible, sinon None."""
    if isinstance(val, (int, float)):
        return float(val)
    if isinstance(val, str):
        s = val.replace("€", "").replace(" ", "").replace(" ", "").replace(",", ".").strip()
        try:
            return float(s)
        except ValueError:
            return None
    return None


def _liste(items: list, cls: str = "") -> str:
    items = _l(items)
    if not items:
        return '<span class="text-muted fst-italic small">Non renseigné</span>'
    lis = "".join(f"<li>{_s(i)}</li>" for i in items)
    return f'<ul class="mb-0 ps-3 {cls}">{lis}</ul>'


def _badge(text: str, couleur: str = "secondary") -> str:
    return f'<span class="badge bg-{couleur} me-1">{_s(text)}</span>'


def _tendance_icone(t: str) -> str:
    return {
        "hausse": '<i class="bi bi-arrow-up-circle-fill text-success"></i>',
        "baisse": '<i class="bi bi-arrow-down-circle-fill text-danger"></i>',
        "alerte": '<i class="bi bi-exclamation-triangle-fill text-warning"></i>',
    }.get(t, '<i class="bi bi-dash-circle text-secondary"></i>')


def _priorite_badge(p: str) -> str:
    m = {"critique": "danger", "haute": "warning", "normale": "info"}
    return _badge(p, m.get(p, "secondary"))


# ── Pareto du chiffre d'affaires (80/20) ──────────────────────────────────────────

def _pareto_compute(repartition: list):
    """Transforme la répartition du CA en lignes triées avec part et cumul.
    Retourne (lignes, base) où base ∈ {"montant","pourcentage",None}."""
    items = []
    for r in _l(repartition):
        r = _d(r)
        lib = _first(r, "libelle", "segment", "activite", "nom", "client", default="—")
        montant = _num(_first(r, "montant", "ca", "montant_ca", "valeur"))
        pct = _num(_first(r, "pourcentage", "part", "pct", "part_ca"))
        temps = _num(_first(r, "temps_pct", "temps", "occupation_pct", "part_temps"))
        peni = _first(r, "penibilite", "pénibilité", "penibilité", default=None)
        items.append({"libelle": str(lib), "montant": montant, "pourcentage": pct,
                      "temps_brut": temps, "penibilite": peni})
    if not items:
        return [], None

    # Normalise la part de temps sur le total (pour comparer à la part de CA).
    total_temps = sum(i["temps_brut"] for i in items if i["temps_brut"] is not None)
    a_temps = total_temps > 0

    base = "montant" if any(i["montant"] is not None for i in items) else (
        "pourcentage" if any(i["pourcentage"] is not None for i in items) else None)
    if base is None:
        return [], None

    for i in items:
        i["_v"] = (i["montant"] if base == "montant" else i["pourcentage"]) or 0.0
    items.sort(key=lambda x: x["_v"], reverse=True)
    total = sum(i["_v"] for i in items) or 1.0

    cumul = 0.0
    lignes = []
    for i in items:
        part = i["_v"] / total * 100.0
        avant = cumul
        cumul += part
        temps = (i["temps_brut"] / total_temps * 100.0) if (a_temps and i["temps_brut"] is not None) else None
        # Rentabilité du temps : compare la part de CA à la part de temps consommée.
        if temps is None:
            rentab = None
        elif part - temps >= 8:
            rentab = "rentable"        # rapporte plus qu'il ne coûte en temps
        elif temps - part >= 8:
            rentab = "chronophage"     # consomme beaucoup de temps pour peu de CA
        else:
            rentab = "equilibre"
        lignes.append({
            "libelle": i["libelle"],
            "montant": i["montant"],
            "part": round(part, 1),
            "cumul": round(min(cumul, 100.0), 1),
            "temps": round(temps, 1) if temps is not None else None,
            "penibilite": i["penibilite"],
            "rentab": rentab,
            # "vital" = les segments cumulés tant qu'on n'a pas dépassé 80 % (les 20% qui font 80%)
            "vital": avant < 80.0 - 1e-9,
        })
    if lignes:
        lignes[0]["vital"] = True
    return lignes, base


_PENI_BADGE = {
    "faible": '<span class="badge bg-success-subtle text-success border border-success">faible</span>',
    "moyenne": '<span class="badge bg-warning-subtle text-warning border border-warning">moyenne</span>',
    "élevée": '<span class="badge bg-danger-subtle text-danger border border-danger">élevée</span>',
    "elevee": '<span class="badge bg-danger-subtle text-danger border border-danger">élevée</span>',
}
_RENTAB_BADGE = {
    "rentable": '<span class="badge bg-success">rentable</span>',
    "equilibre": '<span class="badge bg-secondary">équilibré</span>',
    "chronophage": '<span class="badge bg-danger">chronophage</span>',
}


def _section_pareto(lignes: list, base) -> str:
    if not lignes:
        return ""
    a_temps = any(l["temps"] is not None for l in lignes)
    n_vital = sum(1 for l in lignes if l["vital"])
    pct_vital = round(n_vital / len(lignes) * 100)
    part_vital = round(sum(l["part"] for l in lignes if l["vital"]))

    chronos = [l for l in lignes if l["rentab"] == "chronophage"]
    alerte = ""
    if chronos:
        noms = ", ".join(l["libelle"] for l in chronos)
        alerte = f"""
        <div class="alert alert-danger py-2 mb-3">
          <i class="bi bi-hourglass-split me-1"></i><strong>Activités chronophages :</strong> {noms} —
          consomment une grande part du temps pour une part de CA plus faible. À questionner (tarif, automatisation, ou abandon).
        </div>"""

    th_temps = '<th class="text-end">Temps</th><th class="text-center">Pénibilité</th><th class="text-center">Rentabilité</th>' if a_temps else ""
    rows = ""
    star = '<i class="bi bi-star-fill text-warning me-1"></i>'
    for l in lignes:
        montant = (f"{l['montant']:,.0f} €".replace(",", "\u00a0")) if l["montant"] is not None else "—"
        prefix = star if l["vital"] else ""
        cls = "table-warning" if l["vital"] else ""
        cols_temps = ""
        if a_temps:
            temps_txt = f"{l['temps']} %" if l["temps"] is not None else "—"
            peni = _PENI_BADGE.get(str(l["penibilite"]).lower(), '<span class="text-muted">—</span>') if l["penibilite"] else '<span class="text-muted">—</span>'
            rentab = _RENTAB_BADGE.get(l["rentab"], '<span class="text-muted">—</span>') if l["rentab"] else '<span class="text-muted">—</span>'
            cols_temps = f'<td class="text-end">{temps_txt}</td><td class="text-center">{peni}</td><td class="text-center">{rentab}</td>'
        rows += f"""
        <tr class="{cls}">
          <td>{prefix}{_s(l['libelle'])}</td>
          <td class="text-end">{montant}</td>
          <td class="text-end fw-bold">{l['part']} %</td>
          <td class="text-end text-muted">{l['cumul']} %</td>
          {cols_temps}
        </tr>"""
    data = json.dumps(
        {"labels": [l["libelle"] for l in lignes],
         "parts": [l["part"] for l in lignes],
         "temps": [l["temps"] for l in lignes],
         "cumul": [l["cumul"] for l in lignes]},
        ensure_ascii=False)
    if a_temps:
        sous_titre = ("Comparez la part de CA et la part de temps de chaque activité : l\u2019où la barre "
                      "<span class='text-danger'>temps</span> dépasse la barre <span class='text-primary'>CA</span>, "
                      "l\u2019activité est chronophage (≈ 80 % du temps pour 20 % du CA).")
    else:
        sous_titre = "Les lignes surlignées sont les « 20 % qui font 80 % » du CA."
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold d-flex justify-content-between align-items-center">
        <span><i class="bi bi-bar-chart-line me-2 text-wp"></i>Pareto : chiffre d\u2019affaires vs temps consommé</span>
        <span class="badge bg-wp">{pct_vital} % des postes = {part_vital} % du CA</span>
      </div>
      <div class="card-body">
        <p class="text-muted small mb-3">{sous_titre}</p>
        {alerte}
        <div class="row g-3 align-items-center">
          <div class="col-lg-7">
            <div class="table-responsive">
              <table class="table table-sm table-hover mb-0">
                <thead class="table-light">
                  <tr><th>Poste</th><th class="text-end">CA</th><th class="text-end">Part CA</th><th class="text-end">Cumul</th>{th_temps}</tr>
                </thead>
                <tbody>{rows}</tbody>
              </table>
            </div>
          </div>
          <div class="col-lg-5"><canvas id="paretoChart" height="240"></canvas></div>
        </div>
      </div>
    </div>
    <script>window.__PARETO__ = {data};</script>"""


# ── Sections « Résumé » ────────────────────────────────────────────────────────────

def _section_kpis(kpis: list) -> str:
    kpis = _l(kpis)
    if not kpis:
        return ""
    cartes = ""
    for k in kpis:
        k = _d(k)
        cartes += f"""
        <div class="col-md-4 col-lg-2">
          <div class="card kpi-card h-100 text-center p-3">
            <i class="bi {k.get('icone','bi-bar-chart')} fs-2 kpi-icon"></i>
            <div class="kpi-valeur">{_s(k.get('valeur','—'))}<small class="text-muted ms-1 fs-6">{_s(k.get('unite',''),'')}</small></div>
            <div class="kpi-nom">{_s(k.get('nom',''),'')}</div>
            <div class="mt-1">{_tendance_icone(k.get('tendance',''))}</div>
          </div>
        </div>"""
    return f'<div class="row g-3 mb-4">{cartes}</div>'


def _section_resume(resume: str, message: str) -> str:
    return f"""
    <div class="card mb-4 border-0 shadow-sm">
      <div class="card-body">
        <p class="lead text-muted mb-2">{_s(message)}</p>
        <p class="mb-0">{_s(resume)}</p>
      </div>
    </div>"""


def _section_actions(actions: list) -> str:
    actions = _l(actions)
    if not actions:
        return ""
    items = ""
    for a in actions:
        a = _d(a)
        items += f"""
        <div class="col-md-4">
          <div class="card h-100 border-start border-4 border-wp">
            <div class="card-body">
              <div class="d-flex align-items-center mb-2">
                <i class="bi {a.get('icone','bi-lightning')} me-2 text-wp fs-5"></i>
                <strong>{_s(a.get('titre',''),'')}</strong>
                <span class="ms-auto">{_priorite_badge(a.get('priorite',''))}</span>
              </div>
              <p class="mb-0 text-muted small">{_s(a.get('description',''),'')}</p>
            </div>
          </div>
        </div>"""
    return f"""
    <h5 class="fw-bold mb-3"><i class="bi bi-lightning-charge me-2 text-wp"></i>Actions immédiates</h5>
    <div class="row g-3 mb-4">{items}</div>"""


# ── Modules opérationnels (CRUD) ───────────────────────────────────────────────────

def _entites_normalisees(entites: list) -> list:
    """Nettoie/complète les entités pour le moteur JS (id, champs typés, exemples)."""
    out = []
    used = set()
    for idx, e in enumerate(_l(entites)):
        e = _d(e)
        nom = _s(e.get("nom"), f"Entité {idx+1}")
        eid = e.get("id") or "".join(c for c in str(nom).lower() if c.isalnum()) or f"ent{idx}"
        while eid in used:
            eid += "x"
        used.add(eid)
        champs = []
        for c in _l(e.get("champs")):
            if isinstance(c, dict):
                cle = c.get("cle") or "".join(ch for ch in str(c.get("label", "champ")).lower() if ch.isalnum()) or f"c{len(champs)}"
                champs.append({
                    "cle": cle,
                    "label": _s(c.get("label"), cle),
                    "type": c.get("type") if c.get("type") in ("texte", "nombre", "montant", "date", "statut") else "texte",
                    "options": _l(c.get("options")),
                })
            else:  # ancien format : champ = simple chaîne
                cle = "".join(ch for ch in str(c).lower() if ch.isalnum()) or f"c{len(champs)}"
                champs.append({"cle": cle, "label": str(c), "type": "texte", "options": []})
        if not champs:
            champs = [{"cle": "nom", "label": "Nom", "type": "texte", "options": []}]
        exemples = [x for x in _l(e.get("exemples")) if isinstance(x, dict)]
        out.append({
            "id": eid, "nom": nom, "icone": e.get("icone", "bi-box"),
            "description": _s(e.get("description"), ""), "champs": champs, "exemples": exemples,
        })
    return out


def _nav_entites(entites: list) -> str:
    liens = ""
    for e in entites:
        liens += f"""
      <li class="nav-item">
        <a class="nav-link" href="#" onclick="afficher('ent-{e['id']}', this)">
          <i class="bi {e['icone']}"></i> {_s(e['nom'])}
        </a>
      </li>"""
    return liens


def _sections_entites(entites: list) -> str:
    secs = ""
    for e in entites:
        thead = "".join(f"<th>{_s(c['label'])}</th>" for c in e["champs"])
        secs += f"""
  <section id="sec-ent-{e['id']}" class="page-section">
    <div class="page-header d-flex justify-content-between align-items-start flex-wrap gap-2">
      <div>
        <h4><i class="bi {e['icone']} me-2 text-wp"></i>{_s(e['nom'])}
          <span class="badge bg-wp-light text-wp ms-2" id="cnt-{e['id']}">0</span></h4>
        <p class="text-muted mb-0">{_s(e['description'],'')} <span class="small note-stockage"></span></p>
      </div>
      <button class="btn btn-wp" onclick="ajouter('{e['id']}')"><i class="bi bi-plus-lg me-1"></i>Ajouter</button>
    </div>
    <div class="card">
      <div class="card-body p-0">
        <div class="table-responsive">
          <table class="table table-hover align-middle mb-0">
            <thead class="table-light"><tr>{thead}<th class="text-end">Actions</th></tr></thead>
            <tbody id="tb-{e['id']}"></tbody>
          </table>
        </div>
      </div>
    </div>
  </section>
"""
    return secs


def _section_modules_proposes(entites: list, navigation: list) -> str:
    """Cartes des modules/fonctionnalités proposés pour l'application sur-mesure."""
    cartes = ""
    for e in entites:
        nb = len(e["champs"])
        cartes += f"""
        <div class="col-md-6 col-lg-4">
          <div class="card h-100 border-start border-4 border-wp">
            <div class="card-body">
              <div class="d-flex align-items-center mb-1">
                <i class="bi {e['icone']} fs-4 text-wp me-2"></i>
                <strong>{_s(e['nom'])}</strong>
                <span class="badge bg-success-subtle text-success ms-auto">livré ✓</span>
              </div>
              <p class="text-muted small mb-2">{_s(e['description'],'')}</p>
              <div class="small text-muted"><i class="bi bi-input-cursor-text me-1"></i>{nb} champ(s) — création, liste, suppression</div>
            </div>
          </div>
        </div>"""
    # modules suggérés en plus (navigation issue du plan, non couverts par une entité)
    ids = {e["id"] for e in entites}
    for n in _l(navigation):
        n = _d(n)
        nid = n.get("id") or ""
        if nid in ids:
            continue
        cartes += f"""
        <div class="col-md-6 col-lg-4">
          <div class="card h-100 border-start border-4 border-secondary">
            <div class="card-body">
              <div class="d-flex align-items-center mb-1">
                <i class="bi {n.get('icone','bi-grid')} fs-4 text-secondary me-2"></i>
                <strong>{_s(n.get('label','Module'))}</strong>
                <span class="badge bg-light text-muted border ms-auto">proposé</span>
              </div>
              <p class="text-muted small mb-0">Module identifié par l'audit, à activer dans une prochaine itération.</p>
            </div>
          </div>
        </div>"""
    if not cartes:
        return ""
    return f"""
    <h5 class="fw-bold mb-3"><i class="bi bi-grid-3x3-gap me-2 text-wp"></i>Modules de l'application</h5>
    <p class="text-muted small mb-3">Fonctionnalités générées sur-mesure pour l'entreprise. Celles marquées
      <span class="badge bg-success-subtle text-success">livré ✓</span> sont déjà opérationnelles (menu « Outils »).</p>
    <div class="row g-3 mb-4">{cartes}</div>"""


# ── Sections « Analyse stratégique » (depuis l'audit) ─────────────────────────────

def _section_swot(swot: dict) -> str:
    swot = _d(swot)
    if not any(swot.get(k) for k in ("forces", "faiblesses", "opportunites", "menaces")):
        return ""

    def cell(titre, items, cls):
        return f"""
        <div class="col-6">
          <div class="swot-cell swot-{cls} p-3 rounded">
            <strong class="d-block mb-2">{titre}</strong>
            {_liste(items)}
          </div>
        </div>"""

    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-diagram-3 me-2"></i>Analyse SWOT</div>
      <div class="card-body">
        <div class="row g-3">
          {cell("Forces", swot.get("forces"), "f")}
          {cell("Faiblesses", swot.get("faiblesses"), "fa")}
          {cell("Opportunités", _first(swot, "opportunites", "opportunités"), "o")}
          {cell("Menaces", swot.get("menaces"), "m")}
        </div>
      </div>
    </div>"""


def _section_okrs(okrs: list) -> str:
    okrs = _l(okrs)
    if not okrs:
        return ""
    cartes = ""
    for i, o in enumerate(okrs):
        o = _d(o)
        krs = ""
        for kr in _l(_first(o, "resultats_cles", "key_results", "krs")):
            if isinstance(kr, dict):
                texte = _s(_first(kr, "kr", "resultat", "intitule", "description"), "")
                cible = f"{_s(_first(kr, 'valeur_cible', 'cible', 'valeur'), '')} {_s(kr.get('unite', ''), '')}".strip()
                badge = f'<span class="badge bg-wp-light text-wp rounded-pill">{cible}</span>' if cible else ""
            else:  # KR fourni comme simple chaîne
                texte = _s(kr, "")
                badge = ""
            krs += f"""
            <li class="list-group-item d-flex justify-content-between align-items-center gap-2">
              <span>{texte}</span>{badge}
            </li>"""
        cartes += f"""
        <div class="col-md-6 col-lg-4">
          <div class="card h-100">
            <div class="card-header bg-wp text-white">
              <strong>O{i+1}</strong> — {_s(o.get('objectif',''),'')}
            </div>
            <ul class="list-group list-group-flush">{krs}</ul>
          </div>
        </div>"""
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-bullseye me-2"></i>OKRs proposés</div>
      <div class="card-body"><div class="row g-3">{cartes}</div></div>
    </div>"""


def _section_moscow(moscow: dict) -> str:
    moscow = _d(moscow)
    # le LLM varie la casse des clés (must/Must, wont/Won't…) → on lit en tolérant.
    must = _first(moscow, "must", "Must")
    should = _first(moscow, "should", "Should")
    could = _first(moscow, "could", "Could")
    wont = _first(moscow, "wont", "won't", "Won't", "Wont", "wont_have")
    if not any((must, should, could, wont)):
        return ""

    def tab(tid, label, items, couleur, active):
        items = _l(items)
        liste = "".join(
            f'<li class="list-group-item"><i class="bi bi-check2 me-2 text-{couleur}"></i>{_s(i)}</li>'
            for i in items) or '<li class="list-group-item text-muted fst-italic">Aucun élément</li>'
        nav = (f'<li class="nav-item"><button class="nav-link {"active" if active else ""}" '
               f'data-bs-toggle="tab" data-bs-target="#moscow-{tid}" type="button">{label} '
               f'<span class="badge bg-{couleur}">{len(items)}</span></button></li>')
        pane = (f'<div class="tab-pane fade {"show active" if active else ""}" id="moscow-{tid}">'
                f'<ul class="list-group list-group-flush">{liste}</ul></div>')
        return nav, pane

    specs = [("must", "Must", must, "danger", True),
             ("should", "Should", should, "warning", False),
             ("could", "Could", could, "info", False),
             ("wont", "Won't", wont, "secondary", False)]
    navs = panes = ""
    for tid, label, items, couleur, active in specs:
        n, p = tab(tid, label, items, couleur, active)
        navs += n
        panes += p
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-kanban me-2"></i>Priorisation MoSCoW</div>
      <div class="card-body p-0">
        <ul class="nav nav-tabs px-3 pt-2" role="tablist">{navs}</ul>
        <div class="tab-content">{panes}</div>
      </div>
    </div>"""


def _section_processus(processus: list) -> str:
    processus = _l(processus)
    if not processus:
        return ""
    items = ""
    for i, p in enumerate(processus):
        p = _d(p)
        etapes = "".join(
            f'<span class="badge bg-light text-dark border me-1 mb-1">{j+1}. {_s(e)}</span>'
            for j, e in enumerate(_l(p.get("etapes"))))
        items += f"""
        <div class="accordion-item">
          <h2 class="accordion-header">
            <button class="accordion-button {"collapsed" if i > 0 else ""}" type="button"
              data-bs-toggle="collapse" data-bs-target="#proc-{i}">
              <i class="bi bi-gear me-2 text-wp"></i><strong>{_s(p.get('nom','Processus'))}</strong>
            </button>
          </h2>
          <div id="proc-{i}" class="accordion-collapse collapse {"show" if i == 0 else ""}">
            <div class="accordion-body">
              <div class="row mb-2">
                <div class="col-sm-6"><span class="text-muted small">Déclencheur :</span>
                  <span class="ms-1">{_s(p.get('declencheur','—'))}</span></div>
                <div class="col-sm-6"><span class="text-muted small">Résultat :</span>
                  <span class="ms-1">{_s(p.get('resultat','—'))}</span></div>
              </div>
              <div>{etapes}</div>
            </div>
          </div>
        </div>"""
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-diagram-2 me-2"></i>Processus clés</div>
      <div class="card-body p-0"><div class="accordion accordion-flush">{items}</div></div>
    </div>"""


def _section_bounded_contexts(contexts: list) -> str:
    contexts = _l(contexts)
    if not contexts:
        return ""
    cartes = ""
    for ctx in contexts:
        ctx = _d(ctx)
        badges = "".join(_badge(m, "outline-secondary") for m in _l(_first(ctx, "langage_ubiquitaire", "vocabulaire", "termes")))
        cartes += f"""
        <div class="col-md-4 col-lg-3">
          <div class="card h-100">
            <div class="card-header bg-wp text-white small fw-bold">{_s(ctx.get('nom','Context'))}</div>
            <div class="card-body">
              <div class="text-muted small mb-2">Responsable : {_s(ctx.get('responsable','—'))}</div>
              <div class="small">{badges if badges else '<span class="text-muted fst-italic">—</span>'}</div>
            </div>
          </div>
        </div>"""
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-boxes me-2"></i>Bounded Contexts (DDD)</div>
      <div class="card-body"><div class="row g-3">{cartes}</div></div>
    </div>"""


def _section_stakeholders(stakeholders: list) -> str:
    stakeholders = _l(stakeholders)
    if not stakeholders:
        return ""

    def bdg(v):
        m = {"haute": "danger", "moyenne": "warning", "basse": "success"}
        return _badge(v, m.get(str(v).lower(), "secondary"))

    lignes = ""
    for s in stakeholders:
        s = _d(s)
        lignes += f"""
        <tr><td>{_s(s.get('nom','—'))}</td><td>{_s(s.get('role','—'))}</td>
          <td>{bdg(s.get('influence','—'))}</td><td>{bdg(_first(s,'interet','intérêt','—'))}</td></tr>"""
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-people me-2"></i>Parties prenantes</div>
      <div class="card-body p-0"><div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead class="table-light"><tr><th>Nom</th><th>Rôle</th><th>Influence</th><th>Intérêt</th></tr></thead>
          <tbody>{lignes}</tbody>
        </table>
      </div></div>
    </div>"""


def _section_chemin_critique(chemin) -> str:
    # chemin peut être un dict {taches:[...]} ou directement une liste de tâches
    if isinstance(chemin, list):
        taches = chemin
        chemin = {}
    else:
        chemin = _d(chemin)
        taches = _l(_first(chemin, "taches", "tasks", "etapes"))
    if not taches:
        return ""
    duree = _first(chemin, "duree_totale_jours", "duree_totale_projet", "duree_totale", default="—")
    critiques = set(_l(chemin.get("taches_critiques")))
    lignes = ""
    total_calc = 0.0
    for t in taches:
        t = _d(t)
        tid = _first(t, "id", "tache", "ref", default="")
        est_critique = tid in critiques or t.get("est_critique")
        badge = '<span class="badge bg-danger">critique</span>' if est_critique else ""
        depends = ", ".join(_l(_first(t, "depends_de", "dependances"))) or "—"
        dj = _first(t, "duree_jours", "duree_estimee", "duree", default="—")
        dj_num = _num(dj)
        if dj_num and est_critique:
            total_calc += dj_num
        lignes += f"""
        <tr class="{"table-danger" if est_critique else ""}">
          <td><code>{_s(tid,'')}</code></td>
          <td>{_s(_first(t,'nom','description','libelle','intitule'),'')}</td>
          <td class="text-center">{_s(dj)}</td>
          <td>{depends}</td><td>{badge}</td>
        </tr>"""
    if duree == "—" and total_calc > 0:
        duree = int(total_calc) if total_calc.is_integer() else round(total_calc, 1)
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold d-flex justify-content-between align-items-center">
        <span><i class="bi bi-signpost-split me-2"></i>Chemin critique</span>
        <span class="badge bg-wp">Durée totale : {_s(duree)} jours</span>
      </div>
      <div class="card-body p-0"><div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead class="table-light"><tr><th>ID</th><th>Tâche</th><th class="text-center">Durée (j)</th><th>Dépend de</th><th>Statut</th></tr></thead>
          <tbody>{lignes}</tbody>
        </table>
      </div></div>
    </div>"""


def _section_vsm(vsm: dict) -> str:
    vsm = _d(vsm)
    etapes = _l(_first(vsm, "etapes", "steps"))
    if not etapes:
        return ""
    efficacite = _first(vsm, "efficacite_flux_pct", "efficacite_pct", "efficacite", default="—")
    goulots = _l(_first(vsm, "goulots_identifies", "goulots"))
    lignes = ""
    for e in etapes:
        e = _d(e)
        va = _first(e, "temps_valeur_ajoutee_h", "temps_a_valeur_ajoutee", "temps_va", "temps_valeur_ajoutee", default="—")
        att = _first(e, "temps_attente_h", "temps_d_attente", "temps_attente", default="—")
        lignes += f"""
        <tr><td>{_s(e.get('nom',''),'')}</td><td>{_s(_first(e,'acteur','acteur_responsable','responsable'),'—')}</td>
          <td class="text-center text-success fw-bold">{_s(va)}</td>
          <td class="text-center text-danger">{_s(att)}</td></tr>"""
    eff_num = _num(efficacite)
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold d-flex justify-content-between align-items-center">
        <span><i class="bi bi-bezier2 me-2"></i>Value Stream Map</span>
        <span class="badge bg-{"success" if (eff_num is not None and eff_num > 40) else "warning"}">Efficacité flux : {_s(efficacite)}%</span>
      </div>
      <div class="card-body">
        <div class="table-responsive mb-3">
          <table class="table table-hover mb-0">
            <thead class="table-light"><tr><th>Étape</th><th>Acteur</th><th class="text-center">Temps VA</th><th class="text-center">Attente</th></tr></thead>
            <tbody>{lignes}</tbody>
          </table>
        </div>
        <div class="alert alert-warning mb-0 py-2"><strong><i class="bi bi-exclamation-triangle me-1"></i>Goulots :</strong> {_liste(goulots)}</div>
      </div>
    </div>"""


def _section_ishikawa(ishikawa: dict) -> str:
    ishikawa = _d(ishikawa)
    if not ishikawa:
        return ""
    probleme = _first(ishikawa, "probleme_central", "problème_central", "probleme", default="—")
    causes = _d(ishikawa.get("causes"))
    labels = {"main_oeuvre": "Main d'œuvre", "methodes": "Méthodes", "machines": "Machines",
              "matieres": "Matières", "milieu": "Milieu", "management": "Management"}
    cols = ""
    for clé, label in labels.items():
        items = _l(causes.get(clé))
        if items:
            cols += f"""
            <div class="col-md-4 col-lg-2 mb-2">
              <div class="card h-100 border-top border-3 border-danger">
                <div class="card-header py-1 small fw-bold text-danger">{label}</div>
                <div class="card-body py-2">{_liste(items, "small")}</div>
              </div>
            </div>"""
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-diagram-3 me-2"></i>Diagramme d'Ishikawa</div>
      <div class="card-body">
        <div class="alert alert-danger py-2 mb-3"><strong>Problème central :</strong> {_s(probleme)}</div>
        <div class="row">{cols}</div>
      </div>
    </div>"""


def _section_glossaire(glossaire: list) -> str:
    glossaire = _l(glossaire)
    if not glossaire:
        return ""
    lignes = ""
    for g in glossaire:
        g = _d(g)
        lignes += f"""
        <tr><td class="text-muted">{_s(_first(g,'terme_generique','generique'),'—')}</td>
          <td><strong class="text-wp">{_s(_first(g,'terme_entreprise','entreprise'),'—')}</strong></td>
          <td class="small">{_s(g.get('definition',''),'')}</td></tr>"""
    return f"""
    <div class="card mb-4">
      <div class="card-header fw-bold"><i class="bi bi-translate me-2"></i>Glossaire métier — le vocabulaire de l'entreprise</div>
      <div class="card-body p-0"><div class="table-responsive">
        <table class="table table-hover mb-0">
          <thead class="table-light"><tr><th>Terme générique</th><th>Terme de l'entreprise</th><th>Définition</th></tr></thead>
          <tbody>{lignes}</tbody>
        </table>
      </div></div>
    </div>"""


# ── Moteur JS embarqué (CRUD localStorage + Pareto Chart.js) ───────────────────────

_SCRIPT = r"""
const SLUG = "__SLUG__";
const ENTITES = __ENTITES__;

// Persistance : si une API est injectée (mode hébergé), les données vivent sur le
// serveur (brique « donnees ») → multi-utilisateur. Sinon (mode autonome), repli sur
// localStorage (1 fichier, mono-poste). Même interface (Store) dans les deux cas.
// Config par défaut « cuite » à la génération. Un déploiement reproductible (S4) peut
// la surcharger à l'exécution en définissant window.WP_CONFIG (fichier config.js du bundle)
// → le même HTML se déploie n'importe où sans le régénérer.
const CONFIG = Object.assign({ apiBase: "__API_BASE__", appId: "__APP_ID__" }, (window.WP_CONFIG || {}));
CONFIG.apiBase = (CONFIG.apiBase || '').replace(/\/+$/, '');
const HEBERGE = !!(CONFIG.apiBase && CONFIG.appId);
const _cache = {};  // entite_id -> dernier tableau chargé (pour pré-remplir l'édition)

// ── Authentification (apps livrées) — TOUTE l'app derrière un login Keycloak ────────
// Activée uniquement si window.WP_CONFIG.auth est fourni (config.js du bundle livré au
// client : { url, realm, clientId }). En mode autonome / dev (pas d'auth) → l'app reste
// ouverte (rétrocompatibilité totale). Flow OIDC Authorization Code + PKCE, sans dépendance.
const AUTH = (CONFIG.auth && CONFIG.auth.url && CONFIG.auth.realm && CONFIG.auth.clientId) ? CONFIG.auth : null;
let AUTH_TOKEN = null;
const _SS = window.sessionStorage;
const _REDIRECT = location.origin + location.pathname;   // retour Keycloak (sans query)
function _b64url(b){ return btoa(String.fromCharCode.apply(null, new Uint8Array(b))).replace(/\+/g,'-').replace(/\//g,'_').replace(/=+$/,''); }
async function _sha256(s){ return await crypto.subtle.digest('SHA-256', new TextEncoder().encode(s)); }
function _rand(){ return _b64url(crypto.getRandomValues(new Uint8Array(32))); }
function _kc(p){ return AUTH.url.replace(/\/+$/,'') + '/realms/' + encodeURIComponent(AUTH.realm) + p; }
function _claims(t){ try { return JSON.parse(atob(t.split('.')[1].replace(/-/g,'+').replace(/_/g,'/'))); } catch(e){ return {}; } }
function _authH(h){ h = h || {}; if (AUTH_TOKEN) h['Authorization'] = 'Bearer ' + AUTH_TOKEN; return h; }

async function _login(){
  const verifier = _rand(), state = _rand();
  _SS.setItem('wp_app_verifier', verifier); _SS.setItem('wp_app_state', state);
  const challenge = _b64url(await _sha256(verifier));
  location.assign(_kc('/protocol/openid-connect/auth')
    + '?client_id=' + encodeURIComponent(AUTH.clientId)
    + '&redirect_uri=' + encodeURIComponent(_REDIRECT)
    + '&response_type=code&scope=openid&code_challenge_method=S256'
    + '&code_challenge=' + challenge + '&state=' + state);
}
async function _echangeCode(code){
  const body = new URLSearchParams({ grant_type:'authorization_code', client_id:AUTH.clientId,
    code:code, redirect_uri:_REDIRECT, code_verifier:_SS.getItem('wp_app_verifier') || '' });
  const r = await fetch(_kc('/protocol/openid-connect/token'),
    { method:'POST', headers:{'Content-Type':'application/x-www-form-urlencoded'}, body });
  if (!r.ok) throw new Error('Échec de connexion (' + r.status + ')');
  const d = await r.json();
  AUTH_TOKEN = d.access_token; _SS.setItem('wp_app_token', AUTH_TOKEN);
  window.__WP_TOKEN = AUTH_TOKEN; window.__WP_AUTH = AUTH;   // réutilisés par la messagerie
}
function _overlayAuth(msg){
  let o = document.getElementById('wpAuthOverlay');
  if (!o){
    o = document.createElement('div'); o.id = 'wpAuthOverlay';
    o.style.cssText = 'position:fixed;inset:0;z-index:9999;display:flex;align-items:center;justify-content:center;background:var(--wp)';
    o.innerHTML = '<div style="background:#fff;border-radius:14px;padding:2.4rem 2.6rem;max-width:380px;text-align:center;box-shadow:0 14px 44px rgba(0,0,0,.28)">'
      + '<i class="bi bi-shield-lock" style="font-size:2.3rem;color:var(--wp)"></i>'
      + '<h5 class="mt-2 mb-1" style="font-weight:700">Connexion requise</h5>'
      + '<p class="text-muted small mb-3">Accès réservé aux comptes de l\'entreprise.</p>'
      + '<button class="btn btn-wp w-100" id="wpAuthBtn"><i class="bi bi-box-arrow-in-right me-1"></i>Se connecter</button>'
      + '<div id="wpAuthErr" class="text-danger small mt-2"></div></div>';
    document.body.appendChild(o);
    document.getElementById('wpAuthBtn').onclick = _login;
  }
  o.style.display = 'flex';
  if (msg) document.getElementById('wpAuthErr').textContent = msg;
}
function _barreUtilisateur(nom){
  const nav = document.querySelector('.sidebar');
  if (!nav || document.getElementById('wpUserBox')) return;
  const box = document.createElement('div');
  box.id = 'wpUserBox'; box.className = 'px-3 py-2'; box.style.cssText = 'border-top:1px solid rgba(255,255,255,.2)';
  box.innerHTML = '<div class="small text-truncate" style="color:rgba(255,255,255,.9)"><i class="bi bi-person-circle me-1"></i>' + esc(nom || 'Utilisateur') + '</div>'
    + '<a href="#" id="wpLogout" class="small" style="color:rgba(255,255,255,.6)"><i class="bi bi-box-arrow-right me-1"></i>Se déconnecter</a>';
  nav.appendChild(box);
  document.getElementById('wpLogout').onclick = function(e){
    e.preventDefault(); _SS.removeItem('wp_app_token');
    location.assign(_kc('/protocol/openid-connect/logout')
      + '?client_id=' + encodeURIComponent(AUTH.clientId)
      + '&post_logout_redirect_uri=' + encodeURIComponent(_REDIRECT));
  };
}
// Renvoie true si l'app peut s'afficher ; false si un login est requis (overlay montré).
async function _garde(){
  if (!AUTH) return true;                                   // pas d'auth configurée → app ouverte
  const p = new URLSearchParams(location.search);
  if (p.get('code') && p.get('state') === _SS.getItem('wp_app_state')){
    try { await _echangeCode(p.get('code')); history.replaceState({}, '', _REDIRECT); }
    catch(e){ _overlayAuth(e.message); return false; }
  }
  AUTH_TOKEN = AUTH_TOKEN || _SS.getItem('wp_app_token');
  const c = AUTH_TOKEN ? _claims(AUTH_TOKEN) : null;
  if (!AUTH_TOKEN || (c.exp && c.exp * 1000 < Date.now())){
    _SS.removeItem('wp_app_token'); AUTH_TOKEN = null; _overlayAuth(); return false;
  }
  window.__WP_TOKEN = AUTH_TOKEN; window.__WP_AUTH = AUTH;
  _barreUtilisateur(c.name || c.preferred_username);
  return true;
}

function afficher(section, el){
  document.querySelectorAll('.page-section').forEach(s => s.classList.remove('active'));
  document.querySelectorAll('.sidebar .nav-link').forEach(l => l.classList.remove('active'));
  const sec = document.getElementById('sec-' + section);
  if (sec) sec.classList.add('active');
  if (el) el.classList.add('active');
  if (window.event) window.event.preventDefault();
  window.scrollTo(0, 0);
}

function esc(s){ return String(s==null?'':s).replace(/[&<>"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }
function cle(id){ return 'wp_' + SLUG + '_' + id; }
function uid(){ return (window.crypto && crypto.randomUUID) ? crypto.randomUUID() : 'id' + Date.now() + Math.random().toString(16).slice(2); }
function urlApi(eid, rid){
  let u = CONFIG.apiBase + '/apps/' + encodeURIComponent(CONFIG.appId) + '/entites/' + encodeURIComponent(eid) + '/enregistrements';
  return rid ? u + '/' + encodeURIComponent(rid) : u;
}

// ── Stockage local (mode autonome) — enregistrements avec _id stable ──────────────
function charLocal(eid){
  const ent = ENTITES.find(e => e.id === eid);
  const raw = localStorage.getItem(cle(eid));
  if (raw === null){
    const seed = ((ent && Array.isArray(ent.exemples)) ? ent.exemples : []).map(x => Object.assign({ _id: uid() }, x));
    localStorage.setItem(cle(eid), JSON.stringify(seed));
    return seed.slice();
  }
  try { const v = JSON.parse(raw); return Array.isArray(v) ? v : []; } catch(e){ return []; }
}
function sauverLocal(eid, rows){ localStorage.setItem(cle(eid), JSON.stringify(rows)); }

// ── Couche d'accès unifiée ────────────────────────────────────────────────────────
const Store = {
  async list(eid){
    if (HEBERGE){
      const r = await fetch(urlApi(eid), { headers: _authH() }); if (!r.ok) throw new Error('GET ' + r.status);
      return await r.json();
    }
    return charLocal(eid);
  },
  async create(eid, obj){
    if (HEBERGE){
      const r = await fetch(urlApi(eid), { method:'POST', headers: _authH({'Content-Type':'application/json'}), body: JSON.stringify(obj) });
      if (!r.ok) throw new Error('POST ' + r.status); return await r.json();
    }
    const rows = charLocal(eid); const rec = Object.assign({ _id: uid() }, obj); rows.push(rec); sauverLocal(eid, rows); return rec;
  },
  async update(eid, rid, obj){
    if (HEBERGE){
      const r = await fetch(urlApi(eid, rid), { method:'PUT', headers: _authH({'Content-Type':'application/json'}), body: JSON.stringify(obj) });
      if (!r.ok) throw new Error('PUT ' + r.status); return await r.json();
    }
    const rows = charLocal(eid); const i = rows.findIndex(x => x._id === rid);
    if (i >= 0){ rows[i] = Object.assign({ _id: rid }, obj); sauverLocal(eid, rows); } return rows[i];
  },
  async remove(eid, rid){
    if (HEBERGE){
      const r = await fetch(urlApi(eid, rid), { method:'DELETE', headers: _authH() });
      if (!r.ok && r.status !== 204) throw new Error('DELETE ' + r.status); return;
    }
    const rows = charLocal(eid).filter(x => x._id !== rid); sauverLocal(eid, rows);
  }
};

function fmt(ch, v){
  if (v == null || v === '') return '<span class="text-muted">—</span>';
  if (ch.type === 'montant'){ const n = Number(v); return isNaN(n) ? esc(v) : n.toLocaleString('fr-FR') + ' €'; }
  if (ch.type === 'nombre'){ const n = Number(v); return isNaN(n) ? esc(v) : n.toLocaleString('fr-FR'); }
  if (ch.type === 'statut') return '<span class="badge bg-wp-light text-wp border">' + esc(v) + '</span>';
  return esc(v);
}

async function renderTable(id){
  const ent = ENTITES.find(e => e.id === id); if (!ent) return;
  const tb = document.getElementById('tb-' + id); if (!tb) return;
  let rows;
  try { rows = await Store.list(id); }
  catch(e){
    tb.innerHTML = '<tr><td colspan="' + (ent.champs.length + 1) + '" class="text-center text-danger py-4">'
      + '<i class="bi bi-exclamation-triangle me-1"></i>Serveur de données injoignable. Vérifiez que la brique « donnees » est démarrée.</td></tr>';
    return;
  }
  _cache[id] = rows;
  const cnt = document.getElementById('cnt-' + id); if (cnt) cnt.textContent = rows.length;
  if (!rows.length){
    tb.innerHTML = '<tr><td colspan="' + (ent.champs.length + 1) + '" class="text-center text-muted fst-italic py-4">Aucun enregistrement — cliquez sur « Ajouter ».</td></tr>';
    return;
  }
  tb.innerHTML = rows.map(r =>
    '<tr>' + ent.champs.map(ch => '<td>' + fmt(ch, r[ch.cle]) + '</td>').join('') +
    '<td class="text-end text-nowrap">'
    + '<button class="btn btn-sm btn-outline-secondary me-1" onclick="modifier(\'' + id + '\',\'' + r._id + '\')"><i class="bi bi-pencil"></i></button>'
    + '<button class="btn btn-sm btn-outline-danger" onclick="supprimer(\'' + id + '\',\'' + r._id + '\')"><i class="bi bi-trash"></i></button>'
    + '</td></tr>'
  ).join('');
}

async function supprimer(id, rid){
  if (!confirm('Supprimer cet enregistrement ?')) return;
  try { await Store.remove(id, rid); } catch(e){ alert('Échec de la suppression : ' + e.message); return; }
  renderTable(id);
}

let _entCourante = null, _editId = null, _modal = null;

function _remplirModal(ent, valeurs){
  document.getElementById('modalBody').innerHTML = ent.champs.map(ch => {
    const v = valeurs ? (valeurs[ch.cle] == null ? '' : valeurs[ch.cle]) : '';
    let input;
    if (ch.type === 'statut' && Array.isArray(ch.options) && ch.options.length){
      input = '<select class="form-select" data-cle="' + ch.cle + '">' +
        ch.options.map(o => '<option' + (String(o) === String(v) ? ' selected' : '') + '>' + esc(o) + '</option>').join('') + '</select>';
    } else {
      const t = ch.type === 'date' ? 'date' : ((ch.type === 'nombre' || ch.type === 'montant') ? 'number' : 'text');
      input = '<input class="form-control" type="' + t + '" data-cle="' + ch.cle + '" value="' + esc(v) + '">';
    }
    return '<div class="mb-3"><label class="form-label">' + esc(ch.label) + '</label>' + input + '</div>';
  }).join('');
  if (!_modal) _modal = new bootstrap.Modal(document.getElementById('formModal'));
  _modal.show();
}

function ajouter(id){
  const ent = ENTITES.find(e => e.id === id); if (!ent) return;
  _entCourante = id; _editId = null;
  document.getElementById('modalTitre').textContent = 'Nouveau : ' + ent.nom;
  _remplirModal(ent, null);
}

function modifier(id, rid){
  const ent = ENTITES.find(e => e.id === id); if (!ent) return;
  const rec = (_cache[id] || []).find(x => x._id === rid); if (!rec) return;
  _entCourante = id; _editId = rid;
  document.getElementById('modalTitre').textContent = 'Modifier : ' + ent.nom;
  _remplirModal(ent, rec);
}

async function enregistrer(){
  if (!_entCourante) return;
  const obj = {};
  document.querySelectorAll('#modalBody [data-cle]').forEach(el => { obj[el.getAttribute('data-cle')] = el.value; });
  const btn = document.getElementById('btnEnregistrer'); if (btn) btn.disabled = true;
  try {
    if (_editId) await Store.update(_entCourante, _editId, obj);
    else await Store.create(_entCourante, obj);
  } catch(e){ alert('Échec de l\'enregistrement : ' + e.message); if (btn) btn.disabled = false; return; }
  if (btn) btn.disabled = false;
  _modal.hide();
  renderTable(_entCourante);
}

function renderPareto(){
  const data = window.__PARETO__;
  const ctx = document.getElementById('paretoChart');
  if (!data || !ctx || !window.Chart) return;
  const aTemps = Array.isArray(data.temps) && data.temps.some(v => v != null);
  const datasets = [
    { type: 'bar', label: 'Part du CA (%)', data: data.parts, yAxisID: 'y',
      backgroundColor: 'rgba(13,110,253,.65)', order: 3 }
  ];
  if (aTemps) datasets.push(
    { type: 'bar', label: 'Part du temps (%)', data: data.temps, yAxisID: 'y',
      backgroundColor: 'rgba(220,53,69,.55)', order: 2 });
  datasets.push(
    { type: 'line', label: 'Cumul CA (%)', data: data.cumul, yAxisID: 'y',
      borderColor: '#198754', backgroundColor: '#198754', tension: .3, order: 1 });
  new Chart(ctx, {
    data: { labels: data.labels, datasets },
    options: {
      responsive: true, plugins: { legend: { position: 'bottom' } },
      scales: { y: { beginAtZero: true, max: 100, ticks: { callback: v => v + '%' } } }
    }
  });
}

async function _demarrerApp(){
  const note = HEBERGE
    ? '— enregistré sur le serveur (partagé entre utilisateurs).'
    : '— enregistré dans ce navigateur (mode autonome).';
  document.querySelectorAll('.note-stockage').forEach(el => { el.textContent = note; });
  ENTITES.forEach(e => renderTable(e.id));
  renderPareto();
}

document.addEventListener('DOMContentLoaded', async () => {
  // Garde d'authentification : si un login Keycloak est requis (bundle livré) et que
  // l'utilisateur n'est pas connecté, l'overlay est affiché et l'app n'est pas chargée.
  if (!(await _garde())) return;
  _demarrerApp();
});
"""


# ── Socle : registre de briques d'application ─────────────────────────────────────
#
# Chaque brique est un "constructeur" : une fonction ctx -> list[vue].
# Une vue = {"id","label","icone","categorie","html","actif"(opt)}.
# Ajouter une capacite = enregistrer une brique (via @brique) OU deposer un fichier
# dans briques_app/ exposant `construire(ctx)` (auto-decouvert au demarrage).
# C'est le modele "noyau + briques" applique aux applications generees.

import os
import importlib.util

_REGISTRE = []  # liste ordonnee de constructeurs ctx -> list[vue]


def brique(fn):
    """Decorateur : enregistre un constructeur de brique dans le catalogue."""
    _REGISTRE.append(fn)
    return fn


def _vue(idv, label, icone, categorie, html, actif=False):
    return {"id": idv, "label": label, "icone": icone, "categorie": categorie,
            "html": html, "actif": actif}


def _entete(titre, icone, sous_titre=""):
    sous = f'<p class="text-muted mb-0">{_s(sous_titre, "")}</p>' if sous_titre else ""
    return f'<div class="page-header"><h4><i class="bi {icone} me-2 text-wp"></i>{_s(titre)}</h4>{sous}</div>'


# ── Catalogue de briques internes ────────────────────────────────────────────────

@brique
def _b_tableau_bord(ctx):
    html = (_entete(f"Tableau de bord — {ctx['nom']}", "bi-speedometer2", ctx["sous_titre"])
            + _section_resume(ctx["resume"], ctx["message"])
            + _section_kpis(ctx["kpis"])
            + _section_pareto(ctx["pareto_lignes"], ctx["pareto_base"])
            + _section_actions(ctx["actions"]))
    return [_vue("resume", "Tableau de bord", "bi-speedometer2", "pilotage", html, actif=True)]


@brique
def _b_application_proposee(ctx):
    modules = _section_modules_proposes(ctx["entites"], ctx["navigation"])
    moscow = _section_moscow(ctx["moscow"])
    if not (modules or moscow):
        return []
    html = (_entete("Application sur-mesure proposée", "bi-window-stack",
                    f"Les modules générés pour {ctx['nom']} et les fonctionnalités priorisées (MoSCoW).")
            + modules + moscow)
    return [_vue("app", "Application proposée", "bi-window-stack", "pilotage", html)]


@brique
def _b_outils_crud(ctx):
    vues = []
    for e in ctx["entites"]:
        thead = "".join(f"<th>{_s(c['label'])}</th>" for c in e["champs"])
        inner = f"""<div class="page-header d-flex justify-content-between align-items-start flex-wrap gap-2">
      <div>
        <h4><i class="bi {e['icone']} me-2 text-wp"></i>{_s(e['nom'])}
          <span class="badge bg-wp-light text-wp ms-2" id="cnt-{e['id']}">0</span></h4>
        <p class="text-muted mb-0">{_s(e['description'], '')} <span class="small note-stockage"></span></p>
      </div>
      <button class="btn btn-wp" onclick="ajouter('{e['id']}')"><i class="bi bi-plus-lg me-1"></i>Ajouter</button>
    </div>
    <div class="card"><div class="card-body p-0"><div class="table-responsive">
      <table class="table table-hover align-middle mb-0">
        <thead class="table-light"><tr>{thead}<th class="text-end">Actions</th></tr></thead>
        <tbody id="tb-{e['id']}"></tbody>
      </table>
    </div></div></div>"""
        vues.append(_vue(f"ent-{e['id']}", e["nom"], e["icone"], "outils", inner))
    return vues


@brique
def _b_territoire(ctx):
    bc = _section_bounded_contexts(ctx["bounded_contexts"])
    sh = _section_stakeholders(ctx["stakeholders"])
    gl = _section_glossaire(ctx["glossaire"])
    ev = ctx["evenements"]
    ag = ctx["agregats"]
    if not (bc or sh or gl or ev or ag):
        return []
    extra = ""
    if ev or ag:
        extra = (f'<div class="row g-3">'
                 f'<div class="col-md-6"><div class="card mb-4"><div class="card-header fw-bold"><i class="bi bi-calendar-event me-2"></i>Événements clés</div><div class="card-body">{_liste(ev)}</div></div></div>'
                 f'<div class="col-md-6"><div class="card mb-4"><div class="card-header fw-bold"><i class="bi bi-collection me-2"></i>Agrégats métier</div><div class="card-body">{_liste(ag)}</div></div></div>'
                 f'</div>')
    html = _entete("Territoire de l'entreprise", "bi-map") + bc + sh + gl + extra
    return [_vue("territoire", "Territoire", "bi-map", "analyse", html)]


@brique
def _b_flux(ctx):
    vsm = _section_vsm(ctx["vsm"])
    proc = _section_processus(ctx["processus_cles"])
    if not (vsm or proc):
        return []
    return [_vue("flux", "Flux", "bi-arrow-left-right", "analyse",
                 _entete("Flux & Processus", "bi-arrow-left-right") + vsm + proc)]


@brique
def _b_problemes(ctx):
    ish = _section_ishikawa(ctx["ishikawa"])
    if not ish:
        return []
    return [_vue("problemes", "Problèmes", "bi-bug", "analyse",
                 _entete("Analyse des problèmes", "bi-bug") + ish)]


@brique
def _b_priorites(ctx):
    swot = _section_swot(ctx["swot"])
    okrs = _section_okrs(ctx["okrs"])
    chemin = _section_chemin_critique(ctx["chemin"])
    if not (swot or okrs or chemin):
        return []
    return [_vue("priorites", "Priorités", "bi-flag", "analyse",
                 _entete("Priorités & Roadmap", "bi-flag") + swot + okrs + chemin)]


# ── Auto-decouverte de briques externes (deposer un .py = nouvelle brique) ─────────

def _charger_briques_externes():
    dossier = os.path.join(os.path.dirname(os.path.abspath(__file__)), "briques_app")
    if not os.path.isdir(dossier):
        return
    for nom_fichier in sorted(os.listdir(dossier)):
        if not nom_fichier.endswith(".py") or nom_fichier.startswith("_"):
            continue
        chemin = os.path.join(dossier, nom_fichier)
        try:
            spec = importlib.util.spec_from_file_location("briques_app_" + nom_fichier[:-3], chemin)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            if hasattr(mod, "construire"):
                _REGISTRE.append(mod.construire)
        except Exception as e:
            print("[gabarit] brique externe ignoree (" + nom_fichier + "): " + str(e))


_charger_briques_externes()


# ── Contexte partage fourni a chaque brique ──────────────────────────────────────

def _construire_contexte(audit: dict, plan: dict) -> dict:
    nom = _s(audit.get("nom_entreprise"), "Entreprise")
    territoire = _d(audit.get("territoire"))
    flux = _d(audit.get("flux"))
    problemes = _d(audit.get("problemes"))
    priorites = _d(audit.get("priorites"))
    ddd = _d(territoire.get("ddd"))
    return {
        "audit": audit, "plan": plan, "nom": nom,
        "date_audit": _s(audit.get("date_audit"), "")[:10],
        "slug": "".join(c for c in nom.lower() if c.isalnum()) or "entreprise",
        "territoire": territoire, "flux": flux, "problemes": problemes, "priorites": priorites,
        "bounded_contexts": _l(ddd.get("bounded_contexts")),
        "evenements": _l(ddd.get("evenements_cles")),
        "agregats": _l(ddd.get("agregats")),
        "stakeholders": _l(territoire.get("stakeholders")),
        "repartition_ca": _l(territoire.get("repartition_ca")),
        "processus_cles": _l(flux.get("processus_cles")),
        "vsm": _d(flux.get("value_stream_map")),
        "swot": _d(priorites.get("swot")),
        "okrs": _l(priorites.get("okrs_proposes")),
        "moscow": _d(priorites.get("moscow")),
        "chemin": priorites.get("chemin_critique"),
        "ishikawa": _d(problemes.get("ishikawa")),
        "couleur": plan.get("couleur_principale", "#4F46E5"),
        "couleur2": plan.get("couleur_secondaire", "#7C3AED"),
        "resume": plan.get("resume_executif", "Analyse de l'entreprise réalisée par Workplace."),
        "glossaire": _l(plan.get("glossaire")) or _l(territoire.get("glossaire_metier")),
        "kpis": _l(plan.get("kpis")),
        "actions": _l(plan.get("actions_immediates")),
        "secteur": plan.get("secteur", ""),
        "nom_app": plan.get("nom_app", nom + " — Dashboard"),
        "sous_titre": plan.get("sous_titre", "Tableau de bord stratégique"),
        "message": plan.get("message_introduction", "Bienvenue dans votre tableau de bord " + nom),
        "navigation": _l(plan.get("navigation")),
        "entites": _entites_normalisees(plan.get("entites")),
        "pareto_lignes": None, "pareto_base": None,
    }


_CAT_ORDRE = [("pilotage", "Pilotage"), ("outils", "Outils"), ("analyse", "Analyse stratégique")]


# ── Assemblage final (pilote par le registre de briques) ──────────────────────────

def entites_du_plan(plan: dict) -> list:
    """Entités normalisées d'un plan (id + champs + exemples) — sert au seed serveur."""
    return _entites_normalisees(_d(plan).get("entites"))


def generer_html(audit: dict, plan: dict, app_id: str = "", api_base: str = "",
                 oria: dict | None = None) -> str:
    """Génère l'app. Si `app_id` et `api_base` sont fournis → mode hébergé (persistance
    serveur via la brique « donnees ») ; sinon → mode autonome (localStorage).
    `oria` (optionnel) = config de la messagerie interne, lue par la brique_app messagerie."""
    audit = _d(audit)
    plan = _d(plan)
    ctx = _construire_contexte(audit, plan)
    ctx["oria"] = oria
    ctx["pareto_lignes"], ctx["pareto_base"] = _pareto_compute(ctx["repartition_ca"])

    vues = []
    for construire in _REGISTRE:
        try:
            vues.extend(construire(ctx) or [])
        except Exception as e:
            print("[gabarit] brique ignoree (" + getattr(construire, "__name__", "?") + "): " + str(e))
    if not vues:
        vues = [_vue("resume", "Tableau de bord", "bi-speedometer2", "pilotage",
                     _entete("Tableau de bord — " + ctx["nom"], "bi-speedometer2"), actif=True)]

    actif_id = next((v["id"] for v in vues if v.get("actif")), vues[0]["id"])

    def _lien(v):
        cls = "active" if v["id"] == actif_id else ""
        return (f'<li class="nav-item"><a class="nav-link {cls}" href="#" '
                f'onclick="afficher(\'{v["id"]}\', this)"><i class="bi {v["icone"]}"></i> {_s(v["label"])}</a></li>')

    sidebar = ""
    cats_connues = set(c for c, _ in _CAT_ORDRE)
    for cat, titre in _CAT_ORDRE:
        groupe = [v for v in vues if v["categorie"] == cat]
        if groupe:
            sidebar += f'<li class="nav-title">{titre}</li>' + "".join(_lien(v) for v in groupe)
    autres = [v for v in vues if v["categorie"] not in cats_connues]
    if autres:
        sidebar += '<li class="nav-title">Extensions</li>' + "".join(_lien(v) for v in autres)

    sections = ""
    for v in vues:
        cls = "active" if v["id"] == actif_id else ""
        sections += f'\n  <section id="sec-{v["id"]}" class="page-section {cls}">\n{v["html"]}\n  </section>\n'

    script = (_SCRIPT.replace("__SLUG__", ctx["slug"])
              .replace("__ENTITES__", json.dumps(ctx["entites"], ensure_ascii=False))
              .replace("__API_BASE__", api_base or "")
              .replace("__APP_ID__", app_id or ""))

    return (_SHELL
            .replace("__NOMAPP__", _s(ctx["nom_app"]))
            .replace("__COULEUR2__", ctx["couleur2"])
            .replace("__COULEUR__", ctx["couleur"])
            .replace("__SECTEUR__", _s(ctx["secteur"], ""))
            .replace("__DATE__", ctx["date_audit"])
            .replace("__SIDEBAR__", sidebar)
            .replace("__SECTIONS__", sections)
            .replace("__SCRIPT__", script))


# ── Coquille HTML (template a placeholders ; pas une f-string : accolades CSS litterales) ──

_SHELL = """<!DOCTYPE html>
<html lang="fr">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>__NOMAPP__</title>
  <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/css/bootstrap.min.css" rel="stylesheet">
  <link href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.11.3/font/bootstrap-icons.min.css" rel="stylesheet">
  <script src="https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js"></script>
  <style>
    :root { --wp: __COULEUR__; --wp2: __COULEUR2__; }
    body { background: #f8f9fa; font-family: 'Segoe UI', system-ui, sans-serif; }
    .sidebar { width: 240px; min-height: 100vh; background: var(--wp); position: fixed; top: 0; left: 0; z-index: 100; display: flex; flex-direction: column; overflow-y: auto; }
    .sidebar-brand { padding: 1.5rem 1rem 1rem; border-bottom: 1px solid rgba(255,255,255,.2); }
    .sidebar-brand h6 { color: #fff; font-weight: 700; margin: 0; font-size: .9rem; word-break: break-word; }
    .sidebar-brand small { color: rgba(255,255,255,.7); font-size: .75rem; }
    .sidebar .nav-title { color: rgba(255,255,255,.5); font-size: .68rem; text-transform: uppercase; letter-spacing: .08em; padding: .8rem 1rem .2rem; list-style: none; }
    .sidebar .nav-link { color: rgba(255,255,255,.85); padding: .5rem 1rem; border-radius: .4rem; margin: 0 .5rem .1rem; transition: all .15s; font-size: .875rem; }
    .sidebar .nav-link:hover, .sidebar .nav-link.active { background: rgba(255,255,255,.2); color: #fff; }
    .sidebar .nav-link i { width: 20px; }
    .main-content { margin-left: 240px; padding: 2rem; min-height: 100vh; }
    .page-section { display: none; }
    .page-section.active { display: block; }
    .bg-wp { background: var(--wp) !important; }
    .text-wp { color: var(--wp) !important; }
    .btn-wp { background: var(--wp); color: #fff; }
    .btn-wp:hover { filter: brightness(.92); color: #fff; }
    .bg-wp-light { background: color-mix(in srgb, var(--wp) 14%, white) !important; }
    .border-wp { border-color: var(--wp) !important; }
    .kpi-card { border: none; box-shadow: 0 2px 8px rgba(0,0,0,.08); transition: transform .15s; }
    .kpi-card:hover { transform: translateY(-2px); }
    .kpi-icon { color: var(--wp); }
    .kpi-valeur { font-size: 1.6rem; font-weight: 700; color: #1e293b; }
    .kpi-nom { font-size: .8rem; color: #64748b; text-transform: uppercase; letter-spacing: .05em; }
    .swot-f { background: #dcfce7; } .swot-fa { background: #fee2e2; }
    .swot-o { background: #dbeafe; } .swot-m { background: #fef9c3; }
    .page-header { margin-bottom: 1.5rem; }
    .page-header h4 { font-weight: 700; color: #1e293b; }
    @media (max-width: 768px) { .sidebar { width: 100%; min-height: auto; position: relative; } .main-content { margin-left: 0; padding: 1rem; } }
  </style>
</head>
<body>

<nav class="sidebar">
  <div class="sidebar-brand">
    <h6>__NOMAPP__</h6>
    <small>__SECTEUR__</small>
  </div>
  <div class="pt-2 flex-grow-1">
    <ul class="nav flex-column px-1 mt-1">
      __SIDEBAR__
    </ul>
  </div>
  <div class="px-3 py-2 text-center" style="border-top:1px solid rgba(255,255,255,.2)">
    <small style="color:rgba(255,255,255,.5);font-size:.7rem">Généré par Workplace<br>__DATE__</small>
  </div>
</nav>

<main class="main-content">
__SECTIONS__
</main>

<div class="modal fade" id="formModal" tabindex="-1">
  <div class="modal-dialog">
    <div class="modal-content">
      <div class="modal-header"><h5 class="modal-title" id="modalTitre">Nouveau</h5>
        <button type="button" class="btn-close" data-bs-dismiss="modal"></button></div>
      <div class="modal-body" id="modalBody"></div>
      <div class="modal-footer">
        <button type="button" class="btn btn-light" data-bs-dismiss="modal">Annuler</button>
        <button type="button" id="btnEnregistrer" class="btn btn-wp" onclick="enregistrer()"><i class="bi bi-check-lg me-1"></i>Enregistrer</button>
      </div>
    </div>
  </div>
</div>

<script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.3/dist/js/bootstrap.bundle.min.js"></script>
<script>__SCRIPT__</script>
</body>
</html>"""
