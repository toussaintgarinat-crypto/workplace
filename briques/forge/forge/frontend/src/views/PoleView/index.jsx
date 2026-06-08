import { useState, useEffect, useRef, useCallback } from 'react'
import { createPortal } from 'react-dom'
import { useParams, useNavigate } from 'react-router-dom'
import { polesApi, api, sessions as sessionsApi } from '../../services/api'
import SprintPanel from './panels/SprintPanel'
import BudgetPanel from './panels/BudgetPanel'
import CRMPanel from './panels/CRMPanel'
import AuditPanel from './panels/AuditPanel'
import DocumentsPanel from './panels/DocumentsPanel'
import ContratsPanel from './panels/ContratsPanel'
import IncidentsPanel from './panels/IncidentsPanel'
import SocialPanel from './panels/SocialPanel'
import OKRPanel from './panels/OKRPanel'
import ForecastPanel from './panels/ForecastPanel'
import SeoAgentPanel from './panels/SeoAgentPanel'
import ContentAgentPanel from './panels/ContentAgentPanel'
import ProspectionPanel from './panels/ProspectionPanel'
import LegalAgentPanel from './panels/LegalAgentPanel'
import SentinelPanel from './panels/SentinelPanel'
import RapportPanel from './panels/RapportPanel'
import AgentAutonomyPanel from './panels/AgentAutonomyPanel'
import AutomatePanel from './panels/AutomatePanel'
import GovernancePanel from './panels/GovernancePanel'
import DevPoleView from '../DevPoleView'
import DevTeamPanel from './panels/DevTeamPanel'
import DAGPanel from './panels/DAGPanel'
import ServersPanel from './panels/ServersPanel'
import styles from './PoleView.module.css'

const DOZZLE_URL = import.meta.env.VITE_DOZZLE_URL || 'http://localhost:9998'

// Outils communs — disponibles sur tous les pôles, regroupés en dropdown
const COMMON = {
  sprint:        { label: 'Sprints',        icon: '⚡', component: SprintPanel },
  okr:           { label: 'OKRs',           icon: '🎯', component: OKRPanel },
  documents:     { label: 'Documents',      icon: '📄', component: DocumentsPanel },
  incidents:     { label: 'Incidents',      icon: '🚨', component: IncidentsPanel },
  rapport:       { label: 'Rapports',       icon: '📑', component: RapportPanel },
  agentAutonomy: { label: 'Autonomie IA',   icon: '🧠', component: AgentAutonomyPanel },
  automate:      { label: 'Automatiser',    icon: '🤖', component: AutomatePanel },
  governance:    { label: 'Gouvernance IA', icon: '🔌', component: GovernancePanel },
}

// Outils dédiés par type de pôle
const DEDICATED_BY_TYPE = {
  finance: {
    budget:      { label: 'Budget',      icon: '💰', component: BudgetPanel },
    forecast:    { label: 'Prévisions',  icon: '📈', component: ForecastPanel },
    facturation: { label: 'Facturation', icon: '🧾', component: null },
    contrats:    { label: 'Contrats',    icon: '📋', component: ContratsPanel },
    audit:       { label: 'Audit',       icon: '🔍', component: AuditPanel },
    servers:     { label: 'Serveurs',    icon: '🖥️', component: ServersPanel },
    sentinel:    { label: 'RGPD',        icon: '🛡️', component: SentinelPanel },
  },
  sales: {
    budget:      { label: 'Budget',      icon: '💰', component: BudgetPanel },
    crm:         { label: 'CRM',         icon: '🤝', component: CRMPanel },
    forecast:    { label: 'Prévisions',  icon: '📈', component: ForecastPanel },
    prospection: { label: 'Prospection', icon: '🎯', component: ProspectionPanel },
  },
  legal: {
    contrats:    { label: 'Contrats',    icon: '📋', component: ContratsPanel },
    legal:       { label: 'Juridique IA',icon: '⚖️', component: LegalAgentPanel },
    audit:       { label: 'Audit',       icon: '🔍', component: AuditPanel },
    servers:     { label: 'Serveurs',    icon: '🖥️', component: ServersPanel },
    sentinel:    { label: 'RGPD',        icon: '🛡️', component: SentinelPanel },
  },
  marketing: {
    social:   { label: 'Réseaux',  icon: '📣', component: SocialPanel },
    content:  { label: 'Contenu',  icon: '✍️', component: ContentAgentPanel },
    seo:      { label: 'SEO',      icon: '🔍', component: SeoAgentPanel },
    veille:   { label: 'Veille',   icon: '📡', component: null },
  },
  ops: {
    incidents:   { label: 'Incidents',   icon: '🚨', component: IncidentsPanel },
    gitpack:     { label: 'GitPack',     icon: '📦', component: null },
    sentinel:    { label: 'RGPD',        icon: '🛡️', component: SentinelPanel },
  },
  custom: {
    seo:         { label: 'SEO',         icon: '🔍', component: SeoAgentPanel },
    content:     { label: 'Contenu',     icon: '✍️', component: ContentAgentPanel },
    prospection: { label: 'Prospection', icon: '🎯', component: ProspectionPanel },
    legal:       { label: 'Juridique',   icon: '⚖️', component: LegalAgentPanel },
  },
  dev: {
    inbox:      { label: 'Inbox Inter-Pôles', icon: '📥', component: DevPoleView },
    devteam:    { label: 'Kanban Dev',        icon: '🗂️', component: DevTeamPanel },
    dag:        { label: 'DAG Tâches',        icon: '🕸️', component: DAGPanel },
    autonomy:   { label: 'Autonomie agents',  icon: '🧠', component: AgentAutonomyPanel },
    sentinel:   { label: 'RGPD',             icon: '🛡️', component: SentinelPanel },
  },
}

export default function PoleView() {
  const { poleId } = useParams()
  const navigate = useNavigate()
  const [pole, setPole]             = useState(null)
  const [activePanel, setActive]    = useState(null)
  const [tabsOpen, setTabsOpen]     = useState(true)
  const [commonOpen, setCommonOpen] = useState(false)
  const [dropdownPos, setDropdownPos] = useState({ top: 0, left: 0 })
  const [hitlSuggestions, setHitlSuggestions] = useState([])
  const [showRepConfig, setShowRepConfig]     = useState(false)
  const [repConfig, setRepConfig] = useState({ seuilOccurrences: 3, periodeJours: 7, silenceDays: 30, actif: true })
  const toggleBtnRef  = useRef(null)
  const dropdownRef   = useRef(null)

  useEffect(() => {
    if (!poleId) return
    polesApi.get(poleId).then(data => {
      setPole(data)
      const dedicated = DEDICATED_BY_TYPE[data.type] ?? {}
      const firstKey = Object.keys(dedicated)[0] ?? 'sprint'
      setActive(firstKey)
    }).catch(() => {})
  }, [poleId])

  useEffect(() => {
    if (!poleId) return
    api.get(`/api/repetition/pending/${poleId}`)
      .then(data => setHitlSuggestions(Array.isArray(data) ? data : []))
      .catch(() => {})
    api.get(`/api/poles/${poleId}/repetition-config`)
      .then(data => setRepConfig(prev => ({ ...prev, ...data })))
      .catch(() => {})
  }, [poleId])

  async function respondHitl(hitlId, decision) {
    try {
      await api.post(`/api/repetition/respond/${hitlId}`, { decision })
      setHitlSuggestions(prev => prev.filter(h => h.id !== hitlId))
    } catch {}
  }

  async function saveRepConfig() {
    try {
      const saved = await api.put(`/api/poles/${poleId}/repetition-config`, repConfig)
      setRepConfig(prev => ({ ...prev, ...saved }))
      setShowRepConfig(false)
    } catch {}
  }

  const openCommon = useCallback(() => {
    if (toggleBtnRef.current) {
      const rect = toggleBtnRef.current.getBoundingClientRect()
      setDropdownPos({ top: rect.bottom + 6, left: rect.left })
    }
    setCommonOpen(v => !v)
  }, [])

  useEffect(() => {
    if (!commonOpen) return
    function onClickOutside(e) {
      const inToggle   = toggleBtnRef.current?.contains(e.target)
      const inDropdown = dropdownRef.current?.contains(e.target)
      if (!inToggle && !inDropdown) {
        setCommonOpen(false)
      }
    }
    document.addEventListener('mousedown', onClickOutside)
    return () => document.removeEventListener('mousedown', onClickOutside)
  }, [commonOpen])

  function selectPanel(key) {
    setActive(key)
    setCommonOpen(false)
  }

  if (!pole) return <div className={styles.loading}>Chargement…</div>

  const dedicated = DEDICATED_BY_TYPE[pole.type] ?? {}
  const activeIsCommon = activePanel in COMMON
  const activeTool = activeIsCommon ? COMMON[activePanel] : dedicated[activePanel]
  const ActiveComponent = activeTool?.component ?? null

  return (
    <div className={styles.page}>
      <div className={styles.header} style={{ borderColor: pole.couleur }}>
        {pole.ventureId && (
          <button
            className={styles.backBtn}
            title="Retour aux pôles"
            onClick={() => navigate(`/ventures/${pole.ventureId}`)}
          >←</button>
        )}
        <span className={styles.emoji}>{pole.emoji}</span>
        <div style={{ flex: 1 }}>
          <h1 className={styles.nom}>{pole.nom}</h1>
          {pole.description && <p className={styles.desc}>{pole.description}</p>}
        </div>
        <button
          className={styles.chatBtn}
          title="Démarrer une discussion dans ce pôle"
          onClick={async () => {
            const s = await sessionsApi.create({ poleId, ventureId: pole.ventureId ?? undefined, scope: 'pole' })
            navigate(`/workspace/${s.id}`)
          }}
        >💬</button>
        {pole.type === 'dev' && (
          <button
            className={styles.chatBtn}
            title="Logs containers (Dozzle)"
            onClick={() => window.open(DOZZLE_URL, '_blank')}
          >🪵</button>
        )}
        <button
          className={styles.repConfigBtn}
          title="Paramètres de détection répétition"
          onClick={() => setShowRepConfig(v => !v)}
        >
          ⚙️
        </button>
      </div>

      {/* Panneau config répétition */}
      {showRepConfig && (
        <div className={styles.repConfigPanel}>
          <h3 className={styles.repConfigTitle}>Détection de répétition</h3>
          <div className={styles.repConfigGrid}>
            <label>
              Seuil d'occurrences
              <input
                type="number" min={1} max={50}
                value={repConfig.seuilOccurrences}
                onChange={e => setRepConfig(p => ({ ...p, seuilOccurrences: +e.target.value }))}
              />
            </label>
            <label>
              Période (jours)
              <input
                type="number" min={1} max={90}
                value={repConfig.periodeJours}
                onChange={e => setRepConfig(p => ({ ...p, periodeJours: +e.target.value }))}
              />
            </label>
            <label>
              Silence après rejet (jours)
              <input
                type="number" min={0} max={365}
                value={repConfig.silenceDays}
                onChange={e => setRepConfig(p => ({ ...p, silenceDays: +e.target.value }))}
              />
            </label>
            <label className={styles.repConfigToggle}>
              Actif
              <input
                type="checkbox"
                checked={repConfig.actif}
                onChange={e => setRepConfig(p => ({ ...p, actif: e.target.checked }))}
              />
            </label>
          </div>
          <div className={styles.repConfigActions}>
            <button className={styles.btnSave} onClick={saveRepConfig}>Sauvegarder</button>
            <button className={styles.btnCancel} onClick={() => setShowRepConfig(false)}>Annuler</button>
          </div>
        </div>
      )}

      {/* Bannière HITL suggestions */}
      {hitlSuggestions.map(hitl => {
        const payload = typeof hitl.payload === 'string' ? JSON.parse(hitl.payload) : hitl.payload
        return (
          <div key={hitl.id} className={styles.hitlBanner}>
            <span className={styles.hitlIcon}>🤖</span>
            <div className={styles.hitlText}>
              <strong>Action répétitive détectée</strong>
              <span>« {payload.actionLabel} » effectuée {payload.count} fois en {payload.periodeJours} jours. Envoyer une demande d'automatisation au Pôle Dev ?</span>
            </div>
            <div className={styles.hitlActions}>
              <button className={styles.hitlApprove} onClick={() => respondHitl(hitl.id, 'approve')}>✅ Automatiser</button>
              <button className={styles.hitlReject}  onClick={() => respondHitl(hitl.id, 'reject')}>❌ Ignorer</button>
            </div>
          </div>
        )
      })}

      <div className={`${styles.tabsBar} ${tabsOpen ? styles.tabsBarOpen : ''}`}>
        <div className={styles.tabs}>

          {/* Outils dédiés au type de ce pôle */}
          {Object.entries(dedicated).map(([key, { label, icon }]) => (
            <button
              key={key}
              className={`${styles.tab} ${activePanel === key ? styles.active : ''}`}
              onClick={() => selectPanel(key)}
            >
              {icon} {label}
            </button>
          ))}

          {/* Dropdown outils communs — rendu via portal pour éviter le clipping */}
          <button
            ref={toggleBtnRef}
            className={`${styles.tab} ${styles.tabCommon} ${activeIsCommon ? styles.active : ''} ${commonOpen ? styles.dropdownOpen : ''}`}
            onClick={openCommon}
          >
            {activeIsCommon ? `${COMMON[activePanel].icon} ${COMMON[activePanel].label}` : '🧰 Communs'}
            <span className={styles.dropdownArrow}>{commonOpen ? '▴' : '▾'}</span>
          </button>

        </div>

        <button
          className={styles.tabsToggle}
          onClick={() => setTabsOpen(v => !v)}
          title={tabsOpen ? 'Masquer les outils' : 'Afficher les outils'}
        >
          {tabsOpen ? '▲' : '▼'}
        </button>
      </div>

      {/* Dropdown portal — hors du bandeau pour éviter overflow:hidden */}
      {commonOpen && createPortal(
        <div
          ref={dropdownRef}
          className={styles.dropdownMenu}
          style={{ position: 'fixed', top: dropdownPos.top, left: dropdownPos.left }}
        >
          {Object.entries(COMMON).map(([key, { label, icon }]) => (
            <button
              key={key}
              className={`${styles.dropdownItem} ${activePanel === key ? styles.dropdownItemActive : ''}`}
              onClick={() => selectPanel(key)}
            >
              {icon} {label}
            </button>
          ))}
        </div>,
        document.body
      )}

      <div className={styles.content}>
        {ActiveComponent
          ? <ActiveComponent poleId={poleId} />
          : <div className={styles.wip}>🚧 Module en cours de développement</div>
        }
      </div>
    </div>
  )
}
