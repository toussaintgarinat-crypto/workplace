import NotificationBell from './NotificationBell.jsx'

export default function WorldSidebar({
  worlds, worldActifId, moi,
  onSelectWorld, onCreerWorld, onDeconnexion, onNetwork, showNetwork, onSettings,
  onDiscovery, showDiscovery,
  onMyDocs, showMyDocs,
  onMap, showMap,
  onAgents, showAgents,
  onIPCRA, showIPCRA,
  onFeed, showFeed,
  showJardin,
  onConductor, showConductor,
}) {
  const jardin       = worlds.find(w => w.is_garden)
  const autresWorlds = worlds.filter(w => !w.is_garden)

  return (
    <div className="sidebar">
      <div className="sidebar-logo">🌐</div>
      <div className="sidebar-divider" />

      {/* Jardin secret en tête, séparé */}
      {jardin && (
        <>
          <button
            className={`world-btn garden-btn ${showJardin ? 'actif' : ''}`}
            onClick={() => onSelectWorld(jardin.id)}
            title="Mon Jardin Secret"
          >
            <span className="world-btn-emoji">🌿</span>
            <span className="world-btn-tooltip">Mon Jardin Secret</span>
            <span className="garden-lock">🔒</span>
          </button>
          <div className="sidebar-divider" />
        </>
      )}

      {/* Autres worlds */}
      <div className="sidebar-worlds">
        {autresWorlds.map(w => (
          <button
            key={w.id}
            className={`world-btn ${worldActifId === w.id ? 'actif' : ''}`}
            onClick={() => onSelectWorld(w.id)}
            title={w.nom}
            style={{ '--couleur': w.couleur }}
          >
            <span className="world-btn-emoji">{w.emoji}</span>
            <span className="world-btn-tooltip">{w.nom}</span>
          </button>
        ))}
      </div>

      <button className="world-btn add" onClick={onCreerWorld} title="Créer un monde">
        <span>＋</span>
        <span className="world-btn-tooltip">Nouveau monde</span>
      </button>

      <div className="sidebar-divider" />

      {/* Navigation globale */}
      <button
        className={`world-btn nav-btn ${showDiscovery ? 'actif' : ''}`}
        onClick={onDiscovery}
        title="Explorer"
      >
        <span>🔭</span>
        <span className="world-btn-tooltip">Explorer les mondes</span>
      </button>

      <button
        className={`world-btn nav-btn ${showFeed ? 'actif' : ''}`}
        onClick={onFeed}
        title="Fil d'activité"
      >
        <span>🌊</span>
        <span className="world-btn-tooltip">Fil d'activité</span>
      </button>

      <button
        className={`world-btn nav-btn ${showMap ? 'actif' : ''}`}
        onClick={onMap}
        title="Carte 2D"
      >
        <span>🗺</span>
        <span className="world-btn-tooltip">Carte du monde</span>
      </button>

      <button
        className={`world-btn nav-btn ${showAgents ? 'actif' : ''}`}
        onClick={onAgents}
        title="Agents IA"
      >
        <span>🤖</span>
        <span className="world-btn-tooltip">Agents IA</span>
      </button>

      <button
        className={`world-btn nav-btn ${showMyDocs ? 'actif' : ''}`}
        onClick={onMyDocs}
        title="Mes dossiers"
      >
        <span>📁</span>
        <span className="world-btn-tooltip">Mes dossiers</span>
      </button>

      <button
        className={`world-btn nav-btn ${showIPCRA ? 'actif' : ''}`}
        onClick={onIPCRA}
        title="IPCRA"
      >
        <span>🎯</span>
        <span className="world-btn-tooltip">Sessions IPCRA</span>
      </button>

      <button
        className={`world-btn nav-btn ${showConductor ? 'actif' : ''}`}
        onClick={onConductor}
        title="Conductor"
      >
        <span>🎛</span>
        <span className="world-btn-tooltip">Conductor</span>
      </button>

      <button
        className={`world-btn network-btn ${showNetwork ? 'actif' : ''}`}
        onClick={onNetwork}
        title="Réseau"
      >
        <span>🏘</span>
        <span className="world-btn-tooltip">Réseau</span>
      </button>

      <div className="sidebar-bottom">
        <div className="sidebar-divider" />
        <NotificationBell />
        <button className="moi-btn" onClick={onSettings} title="Paramètres">
          <span>{moi.avatar_emoji}</span>
        </button>
      </div>
    </div>
  )
}
