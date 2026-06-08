import { useState, useEffect } from 'react'
import { netbird } from '../../services/api'
import styles from './Network.module.css'
import EnrollmentModal from './EnrollmentModal'

// ── Peers ────────────────────────────────────────────────────
function PeersPanel() {
  const [peers, setPeers]   = useState([])
  const [error, setError]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    netbird.peers()
      .then(setPeers)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.empty}>Chargement…</div>
  if (error)   return <NetbirdError error={error} />
  if (!peers.length) return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}>🖥</div>
      <div>Aucun peer connecté.</div>
      <div>Installez le client NetBird sur vos machines pour les voir apparaître ici.</div>
    </div>
  )

  return (
    <div>
      {peers.map(peer => (
        <div key={peer.id} className={styles.peerCard}>
          <div className={`${styles.dot} ${peer.connected ? styles.online : styles.offline}`} />
          <div className={styles.peerInfo}>
            <div className={styles.peerName}>{peer.name}</div>
            <div className={styles.peerMeta}>
              <span>{peer.ip}</span>
              {peer.os && <span>{peer.os}</span>}
              {peer.version && <span>v{peer.version}</span>}
              {peer.last_seen && <span>Vu {new Date(peer.last_seen).toLocaleString('fr-FR')}</span>}
            </div>
          </div>
          <div className={styles.peerBadges}>
            <span className={`${styles.badge} ${peer.connected ? styles.badgeGreen : styles.badgeGray}`}>
              {peer.connected ? 'En ligne' : 'Hors ligne'}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Groups ───────────────────────────────────────────────────
function GroupsPanel() {
  const [groups, setGroups]   = useState([])
  const [error, setError]     = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    netbird.groups()
      .then(setGroups)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.empty}>Chargement…</div>
  if (error)   return <NetbirdError error={error} />
  if (!groups.length) return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}>📂</div>
      <div>Aucun groupe configuré.</div>
    </div>
  )

  return (
    <div>
      {groups.map(group => (
        <div key={group.id} className={styles.row}>
          <div className={styles.rowLeft}>
            <div className={styles.rowTitle}>{group.name}</div>
            <div className={styles.rowSub}>{group.peers_count ?? 0} peer{(group.peers_count ?? 0) > 1 ? 's' : ''}</div>
          </div>
          <div className={styles.rowRight}>
            <span className={`${styles.badge} ${styles.badgeBlue}`}>
              {group.issued ?? 'api'}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Policies ─────────────────────────────────────────────────
function PoliciesPanel() {
  const [policies, setPolicies] = useState([])
  const [error, setError]       = useState(null)
  const [loading, setLoading]   = useState(true)

  useEffect(() => {
    netbird.policies()
      .then(setPolicies)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.empty}>Chargement…</div>
  if (error)   return <NetbirdError error={error} />
  if (!policies.length) return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}>🔒</div>
      <div>Aucune politique d'accès configurée.</div>
    </div>
  )

  return (
    <div>
      {policies.map(policy => (
        <div key={policy.id} className={styles.row}>
          <div className={styles.rowLeft}>
            <div className={styles.rowTitle}>{policy.name}</div>
            <div className={styles.rowSub}>{policy.description || 'Aucune description'}</div>
          </div>
          <div className={styles.rowRight}>
            <span className={`${styles.badge} ${policy.enabled ? styles.badgeGreen : styles.badgeGray}`}>
              {policy.enabled ? 'Active' : 'Inactive'}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Routes ───────────────────────────────────────────────────
function RoutesPanel() {
  const [routes, setRoutes]   = useState([])
  const [error, setError]     = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    netbird.routes()
      .then(setRoutes)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.empty}>Chargement…</div>
  if (error)   return <NetbirdError error={error} />
  if (!routes.length) return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}>🛣</div>
      <div>Aucune route configurée.</div>
    </div>
  )

  return (
    <div>
      {routes.map(route => (
        <div key={route.id} className={styles.row}>
          <div className={styles.rowLeft}>
            <div className={styles.rowTitle}>{route.network} — {route.description || route.network_id}</div>
            <div className={styles.rowSub}>
              Via {route.peer || '—'} · Métrique {route.metric ?? '—'}
            </div>
          </div>
          <div className={styles.rowRight}>
            <span className={`${styles.badge} ${route.enabled ? styles.badgeGreen : styles.badgeGray}`}>
              {route.enabled ? 'Active' : 'Inactive'}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── DNS ──────────────────────────────────────────────────────
function DnsPanel() {
  const [dns, setDns]       = useState([])
  const [error, setError]   = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    netbird.dns()
      .then(setDns)
      .catch(e => setError(e.message))
      .finally(() => setLoading(false))
  }, [])

  if (loading) return <div className={styles.empty}>Chargement…</div>
  if (error)   return <NetbirdError error={error} />
  if (!dns.length) return (
    <div className={styles.empty}>
      <div className={styles.emptyIcon}>🌐</div>
      <div>Aucun groupe de serveurs DNS configuré.</div>
    </div>
  )

  return (
    <div>
      {dns.map(group => (
        <div key={group.id} className={styles.row}>
          <div className={styles.rowLeft}>
            <div className={styles.rowTitle}>{group.name}</div>
            <div className={styles.rowSub}>
              {group.nameservers?.length
                ? group.nameservers.map(ns => ns.ip).join(', ')
                : 'Aucun serveur'}
              {group.domains?.length ? ` · ${group.domains.join(', ')}` : ''}
            </div>
          </div>
          <div className={styles.rowRight}>
            <span className={`${styles.badge} ${group.enabled ? styles.badgeGreen : styles.badgeGray}`}>
              {group.enabled ? 'Actif' : 'Inactif'}
            </span>
          </div>
        </div>
      ))}
    </div>
  )
}

// ── Erreur NetBird ────────────────────────────────────────────
function NetbirdError({ error }) {
  const isConfig = error?.includes('401') || error?.includes('403') || error?.includes('fetch')

  return (
    <div>
      <div className={styles.error}>
        Erreur de connexion à NetBird : {error}
      </div>
      {isConfig && (
        <div className={styles.configHint}>
          <strong>Configuration requise</strong><br />
          Ajoutez votre token NetBird dans le fichier <code>.env</code> :<br /><br />
          <code>NETBIRD_TOKEN=nbp_votre_personal_access_token</code><br /><br />
          Créez un PAT depuis votre tableau de bord NetBird → Settings → Access Tokens.
        </div>
      )}
    </div>
  )
}

// ── Vue principale ────────────────────────────────────────────
const TABS = [
  { id: 'peers',    label: '🖥 Peers' },
  { id: 'groups',   label: '📂 Groupes' },
  { id: 'policies', label: '🔒 Politiques' },
  { id: 'routes',   label: '🛣 Routes' },
  { id: 'dns',      label: '🌐 DNS' },
]

export default function NetworkView() {
  const [activeTab, setActiveTab]       = useState('peers')
  const [showEnrollment, setEnrollment] = useState(false)

  return (
    <div className={styles.view}>
      {showEnrollment && <EnrollmentModal onClose={() => setEnrollment(false)} />}
      <div className={styles.header}>
        <div className={styles.headerRow}>
          <div>
            <h1 className={styles.title}>🌐 Réseau</h1>
            <p className={styles.subtitle}>Gestion de l'infrastructure NetBird — peers, groupes, politiques d'accès et routes</p>
          </div>
          <button className={styles.enrollBtn} onClick={() => setEnrollment(true)}>
            + Connecter un appareil
          </button>
        </div>
      </div>

      <div className={styles.tabs}>
        {TABS.map(tab => (
          <button
            key={tab.id}
            className={`${styles.tab} ${activeTab === tab.id ? styles.active : ''}`}
            onClick={() => setActiveTab(tab.id)}
          >
            {tab.label}
          </button>
        ))}
      </div>

      <div className={styles.content}>
        {activeTab === 'peers'    && <PeersPanel />}
        {activeTab === 'groups'   && <GroupsPanel />}
        {activeTab === 'policies' && <PoliciesPanel />}
        {activeTab === 'routes'   && <RoutesPanel />}
        {activeTab === 'dns'      && <DnsPanel />}
      </div>
    </div>
  )
}
