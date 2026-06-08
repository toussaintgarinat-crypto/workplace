import { useState, useRef, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../hooks/useAuth'
import { orgsApi, venturesApi, activeOrg } from '../../services/api'
import styles from './Sidebar.module.css'

export default function Sidebar({ sessions, activeId, onNew, onNewInContext, onSelect, onRename, onDelete, onSettings, collapsed, onToggleCollapse }) {
  const { logout, user } = useAuth()
  const navigate  = useNavigate()
  const location  = useLocation()
  const isBridge  = location.pathname === '/command-bridge'

  const [ventures, setVentures]         = useState([])
  const [poles, setPoles]               = useState([])
  const [openVentures, setOpenVentures] = useState({})
  const [venturesOpen, setVenturesOpen] = useState(true)
  const [iaOpen, setIaOpen]             = useState(false)
  const [orgSectOpen, setOrgSectOpen]   = useState(false)
  const [orgs, setOrgs]                 = useState([])
  const [currentOrgId, setCurrentOrgId] = useState(() => activeOrg.get())
  const [orgMenuOpen, setOrgMenuOpen]   = useState(false)

  useEffect(() => {
    if (!user) return
    orgsApi.list().then(data => {
      setOrgs(data)
      if (!data.length) return
      // Réconcilie l'org active : si aucune n'est sélectionnée OU si la valeur
      // stockée ne correspond plus à une org réelle (ex. reseed DB → forge_org_id
      // périmé → X-Org-ID fantôme → 500 FK à la création), on retombe sur une org valide.
      const stillValid = currentOrgId && data.some(o => o.id === currentOrgId)
      if (!stillValid) {
        const personal = data.find(o => o.plan === 'personal') ?? data[0]
        activeOrg.set(personal.id)
        setCurrentOrgId(personal.id)
      }
    }).catch(() => {})
  }, [user])

  useEffect(() => {
    if (!user) return
    venturesApi.list().then(vs => {
      setVentures(vs)
      return Promise.all(vs.map(v => venturesApi.poles(v.id).catch(() => [])))
    }).then(results => {
      setPoles(results.flat())
    }).catch(() => {})
  }, [user, currentOrgId])

  function switchOrg(orgId) {
    activeOrg.set(orgId)
    setCurrentOrgId(orgId)
    setOrgMenuOpen(false)
    navigate('/workspace')
    window.location.reload()
  }

  function toggleVenture(id) {
    setOpenVentures(v => ({ ...v, [id]: !v[id] }))
  }

  const [editingId, setEditingId] = useState(null)
  const [editValue, setEditValue] = useState('')
  const inputRef = useRef(null)

  function startEdit(session, e) {
    e.stopPropagation()
    setEditingId(session.id)
    setEditValue(session.name)
    setTimeout(() => inputRef.current?.focus(), 50)
  }

  function commitEdit(id) {
    if (editValue.trim()) onRename(id, editValue.trim())
    setEditingId(null)
  }

  const today     = new Date().toDateString()
  const yesterday = new Date(Date.now() - 86400000).toDateString()

  function getGroup(session) {
    const d = new Date(session.updatedAt).toDateString()
    if (d === today)     return 'Today'
    if (d === yesterday) return 'Yesterday'
    return 'Older'
  }

  const groups     = sessions.reduce((acc, s) => {
    const g = getGroup(s)
    if (!acc[g]) acc[g] = []
    acc[g].push(s)
    return acc
  }, {})
  const groupOrder = ['Today', 'Yesterday', 'Older']

  const polesByVenture = poles.reduce((acc, p) => {
    if (!p.ventureId) return acc
    if (!acc[p.ventureId]) acc[p.ventureId] = []
    acc[p.ventureId].push(p)
    return acc
  }, {})

  function poleActive(poleId) {
    return location.pathname.endsWith(`/poles/${poleId}`)
  }

  function navigatePole(pole) {
    navigate(`/ventures/${pole.ventureId}/poles/${pole.id}`)
  }

  if (collapsed) {
    return (
      <aside className={`${styles.sidebar} ${styles.sidebarCollapsed}`}>
        <button className={styles.collapseBtn} onClick={onToggleCollapse} title="Ouvrir la sidebar">›</button>
        <div className={styles.collapsedIcons}>
          <button title="Workspace"     onClick={() => navigate('/workspace')}>💬</button>
          <button title="Command Bridge" onClick={() => navigate('/command-bridge')}>🎯</button>
          <button title="Analytics"     onClick={() => navigate('/analytics')}>📈</button>
          <button title="Ventures"      onClick={() => navigate('/ventures')}>🚀</button>
          <button title="Agents"        onClick={() => navigate('/agents')}>🤖</button>
        </div>
      </aside>
    )
  }

  return (
    <aside className={styles.sidebar}>
      <div className={styles.header}>
        <div className={styles.logoRow}>
          <span className={styles.logo}>⚡ Forge</span>
          <button className={styles.collapseBtn} onClick={onToggleCollapse} title="Réduire la sidebar">‹</button>
        </div>
        {orgs.length > 0 && (
          <div className={styles.orgSwitcher}>
            <button className={styles.orgBtn} onClick={() => setOrgMenuOpen(v => !v)}>
              <span>{orgs.find(o => o.id === currentOrgId)?.emoji ?? '🏢'}</span>
              <span className={styles.orgName}>{orgs.find(o => o.id === currentOrgId)?.nom ?? 'Org'}</span>
              <span className={styles.orgChevron}>▾</span>
            </button>
            {orgMenuOpen && (
              <div className={styles.orgMenu}>
                {orgs.map(org => (
                  <button
                    key={org.id}
                    className={`${styles.orgMenuItem} ${org.id === currentOrgId ? styles.orgMenuItemActive : ''}`}
                    onClick={() => switchOrg(org.id)}
                  >
                    <span>{org.emoji}</span>
                    <span>{org.nom}</span>
                    {org.plan === 'personal' && <span className={styles.orgPlan}>Perso</span>}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Navigation principale */}
      <div className={styles.nav}>
        <button className={`${styles.navItem} ${location.pathname.startsWith('/workspace') ? styles.navActive : ''}`} onClick={() => navigate('/workspace')}>
          💬 Workspace
        </button>
        <button className={`${styles.navItem} ${isBridge ? styles.navActive : ''}`} onClick={() => navigate('/command-bridge')}>
          🎯 Command Bridge
        </button>
        <button className={`${styles.navItem} ${location.pathname === '/analytics' ? styles.navActive : ''}`} onClick={() => navigate('/analytics')}>
          📈 Analytics
        </button>
        <button className={`${styles.navItem} ${location.pathname === '/morning-brief' ? styles.navActive : ''}`} onClick={() => navigate('/morning-brief')}>
          ☀️ Morning Brief
        </button>
        <button className={`${styles.navItem} ${location.pathname === '/search' ? styles.navActive : ''}`} onClick={() => navigate('/search')}>
          🔍 Recherche
        </button>
        <button className={`${styles.navItem} ${location.pathname === '/mempalace' ? styles.navActive : ''}`} onClick={() => navigate('/mempalace')}>
          🧠 MemPalace
        </button>
      </div>

      {/* Ventures & Pôles */}
      <div className={styles.polesSection}>
        <div className={styles.sectionHeaderRow}>
          <button className={styles.sectionHeader} onClick={() => setVenturesOpen(v => !v)}>
            <span>Ventures & Pôles</span>
            <span>{venturesOpen ? '▾' : '▸'}</span>
          </button>
          <button
            className={styles.sectionAddBtn}
            onClick={() => navigate('/ventures')}
            title="Gérer les ventures"
          >+</button>
        </div>

        {venturesOpen && (
          <>
            <button className={`${styles.poleItem} ${location.pathname === '/team' ? styles.poleActive : ''}`} onClick={() => navigate('/team')}>
              <span>👥</span><span className={styles.poleName}>Équipes</span>
            </button>
            <button className={`${styles.poleItem} ${location.pathname === '/network' ? styles.poleActive : ''}`} onClick={() => navigate('/network')}>
              <span>🌐</span><span className={styles.poleName}>Réseaux</span>
            </button>
            {ventures.length === 0 && (
              <div className={styles.emptySection}>
                <button className={styles.poleItem} onClick={() => navigate('/ventures')}>
                  <span>🚀</span><span className={styles.poleName}>Créer une venture</span>
                </button>
              </div>
            )}

            {ventures.map(venture => {
              const vPoles = polesByVenture[venture.id] || []
              const isOpen = openVentures[venture.id]
              const isActive = location.pathname.startsWith(`/ventures/${venture.id}`)
              return (
                <div key={venture.id}>
                  <div className={`${styles.ventureRow} ${isActive ? styles.ventureRowActive : ''}`}>
                    <button
                      className={styles.ventureToggle}
                      onClick={() => toggleVenture(venture.id)}
                    >{isOpen ? '▾' : '▸'}</button>
                    <button
                      className={styles.ventureLabel}
                      onClick={() => navigate(`/ventures/${venture.id}`)}
                      style={isActive ? { color: venture.couleur } : {}}
                    >
                      <span>{venture.emoji}</span>
                      <span className={styles.poleName}>{venture.nom}</span>
                      {venture.type === 'audit' && <span className={styles.auditChip}>Audit</span>}
                    </button>
                    <button
                      className={styles.contextChatBtn}
                      title={`Nouveau chat · ${venture.nom}`}
                      onClick={e => {
                        e.stopPropagation()
                        onNewInContext?.({ ventureId: venture.id, ventureNom: venture.nom, ventureEmoji: venture.emoji, scope: 'venture' })
                      }}
                    >💬</button>
                  </div>
                  {isOpen && (
                    <div className={styles.ventureChildren}>
                      {vPoles.length === 0 && (
                        <button
                          className={styles.poleItem}
                          onClick={() => navigate(`/ventures/${venture.id}`)}
                        >
                          <span style={{ opacity: 0.4 }}>+</span>
                          <span className={styles.poleName} style={{ opacity: 0.5 }}>Ajouter un pôle</span>
                        </button>
                      )}
                      {vPoles.map(pole => (
                        <div key={pole.id} className={styles.poleItemRow}>
                          <button
                            className={`${styles.poleItem} ${poleActive(pole.id) ? styles.poleActive : ''}`}
                            onClick={() => navigatePole(pole)}
                            style={poleActive(pole.id) ? { borderLeftColor: pole.couleur } : {}}
                          >
                            <span>{pole.emoji}</span>
                            <span className={styles.poleName}>{pole.nom}</span>
                          </button>
                          <button
                            className={styles.contextChatBtn}
                            title={`Nouveau chat · ${pole.nom}`}
                            onClick={e => {
                              e.stopPropagation()
                              onNewInContext?.({ poleId: pole.id, poleNom: pole.nom, poleEmoji: pole.emoji, ventureId: pole.ventureId, scope: 'pole' })
                            }}
                          >💬</button>
                        </div>
                      ))}
                    </div>
                  )}
                </div>
              )
            })}

          </>
        )}
      </div>

      {/* Gouvernance IA */}
      <div className={styles.polesSection}>
        <button className={styles.sectionHeader} onClick={() => setIaOpen(v => !v)}>
          <span>Gouvernance IA</span>
          <span>{iaOpen ? '▾' : '▸'}</span>
        </button>
        {iaOpen && (
          <>
            <button className={`${styles.poleItem} ${location.pathname === '/agents' ? styles.poleActive : ''}`} onClick={() => navigate('/agents')}>
              <span>🤖</span><span className={styles.poleName}>Agents</span>
            </button>
            <button className={`${styles.poleItem} ${location.pathname === '/governor' ? styles.poleActive : ''}`} onClick={() => navigate('/governor')}>
              <span>⚙️</span><span className={styles.poleName}>Governor</span>
            </button>
            <button className={`${styles.poleItem} ${location.pathname === '/slo' ? styles.poleActive : ''}`} onClick={() => navigate('/slo')}>
              <span>📊</span><span className={styles.poleName}>SLO Dashboard</span>
            </button>
            <button className={`${styles.poleItem} ${location.pathname === '/automation' ? styles.poleActive : ''}`} onClick={() => navigate('/automation')}>
              <span>⚡</span><span className={styles.poleName}>Automation</span>
            </button>
            <button className={`${styles.poleItem} ${location.pathname === '/skills' ? styles.poleActive : ''}`} onClick={() => navigate('/skills')}>
              <span>🧩</span><span className={styles.poleName}>Skills</span>
            </button>
            <button className={`${styles.poleItem} ${location.pathname === '/mcp' ? styles.poleActive : ''}`} onClick={() => navigate('/mcp')}>
              <span>🔌</span><span className={styles.poleName}>MCP</span>
            </button>
          </>
        )}
      </div>

      {/* Organisation */}
      <div className={styles.polesSection}>
        <button className={styles.sectionHeader} onClick={() => setOrgSectOpen(v => !v)}>
          <span>Organisation</span>
          <span>{orgSectOpen ? '▾' : '▸'}</span>
        </button>
        {orgSectOpen && (
          <>
            <button className={`${styles.poleItem} ${location.pathname === '/abonnements' ? styles.poleActive : ''}`} onClick={() => navigate('/abonnements')}>
              <span>💳</span><span className={styles.poleName}>Abonnements</span>
            </button>
          </>
        )}
      </div>

      <button className={styles.newBtn} onClick={onNew}>
        <span>+</span> New conversation
      </button>

      <nav className={styles.list}>
        {groupOrder.map(group => groups[group] && (
          <div key={group}>
            <div className={styles.groupLabel}>{group}</div>
            {groups[group].map(session => (
              <div
                key={session.id}
                className={`${styles.item} ${session.id === activeId ? styles.active : ''}`}
                onClick={() => onSelect(session.id)}
              >
                {editingId === session.id ? (
                  <input
                    ref={inputRef}
                    className={styles.editInput}
                    value={editValue}
                    onChange={e => setEditValue(e.target.value)}
                    onBlur={() => commitEdit(session.id)}
                    onKeyDown={e => {
                      if (e.key === 'Enter') commitEdit(session.id)
                      if (e.key === 'Escape') setEditingId(null)
                    }}
                    onClick={e => e.stopPropagation()}
                  />
                ) : (
                  <>
                    <span className={styles.name}>{session.name}</span>
                    {session.scope === 'pole' && session.poleEmoji && (
                      <span className={styles.sessionScope} title={session.poleName ?? 'Pôle'}>
                        {session.poleEmoji}
                      </span>
                    )}
                    {session.scope === 'venture' && session.ventureEmoji && (
                      <span className={styles.sessionScope} title={session.ventureName ?? 'Venture'}>
                        {session.ventureEmoji}
                      </span>
                    )}
                    <div className={styles.actions}>
                      <button onClick={e => startEdit(session, e)} title="Rename">✎</button>
                      <button onClick={e => { e.stopPropagation(); onDelete(session.id) }} title="Delete">✕</button>
                    </div>
                  </>
                )}
              </div>
            ))}
          </div>
        ))}
      </nav>

      <div className={styles.footer}>
        <div className={styles.userInfo}>
          <span className={styles.avatar}>{user?.avatarEmoji || '👤'}</span>
          <span className={styles.userName}>{user?.nom}</span>
        </div>
        <div className={styles.footerActions}>
          <button onClick={onSettings} title="Settings" className={styles.footerBtn}>⚙</button>
          <button onClick={logout}     title="Sign out"  className={styles.footerBtn}>↪</button>
        </div>
      </div>
    </aside>
  )
}
