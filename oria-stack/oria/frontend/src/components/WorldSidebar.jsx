import { useTranslation } from 'react-i18next'
import NotificationBell from './NotificationBell.jsx'

export default function WorldSidebar({
  worlds, worldActifId, moi,
  onSelectWorld, onCreerWorld, onDeconnexion, onNetwork, onSettings,
  onDiscovery, onMyDocs, onMap, onAgents, onIPCRA, onFeed, onConductor,
  vueActive,
}) {
  const { t } = useTranslation()
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
            className={`world-btn garden-btn ${vueActive === 'jardin' ? 'actif' : ''}`}
            onClick={() => onSelectWorld(jardin.id)}
            title={t('sidebar.garden')}
          >
            <span className="world-btn-emoji">🌿</span>
            <span className="world-btn-tooltip">{t('sidebar.garden')}</span>
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

      <button className="world-btn add" onClick={onCreerWorld} title={t('sidebar.createWorld')}>
        <span>＋</span>
        <span className="world-btn-tooltip">{t('sidebar.newWorld')}</span>
      </button>

      <div className="sidebar-divider" />

      {/* Navigation globale */}
      <button
        className={`world-btn nav-btn ${vueActive === 'discovery' ? 'actif' : ''}`}
        onClick={onDiscovery}
        title={t('sidebar.explore')}
      >
        <span>🔭</span>
        <span className="world-btn-tooltip">{t('sidebar.exploreWorlds')}</span>
      </button>

      <button
        className={`world-btn nav-btn ${vueActive === 'feed' ? 'actif' : ''}`}
        onClick={onFeed}
        title={t('sidebar.feed')}
      >
        <span>🌊</span>
        <span className="world-btn-tooltip">{t('sidebar.feed')}</span>
      </button>

      <button
        className={`world-btn nav-btn ${vueActive === 'map' ? 'actif' : ''}`}
        onClick={onMap}
        title={t('sidebar.map2d')}
      >
        <span>🗺</span>
        <span className="world-btn-tooltip">{t('sidebar.worldMap')}</span>
      </button>

      <button
        className={`world-btn nav-btn ${vueActive === 'agents' ? 'actif' : ''}`}
        onClick={onAgents}
        title={t('sidebar.agentsAI')}
      >
        <span>🤖</span>
        <span className="world-btn-tooltip">{t('sidebar.agentsAI')}</span>
      </button>

      <button
        className={`world-btn nav-btn ${vueActive === 'mydocs' ? 'actif' : ''}`}
        onClick={onMyDocs}
        title={t('sidebar.myFolders')}
      >
        <span>📁</span>
        <span className="world-btn-tooltip">{t('sidebar.myFolders')}</span>
      </button>

      <button
        className={`world-btn nav-btn ${vueActive === 'ipcra' ? 'actif' : ''}`}
        onClick={onIPCRA}
        title={t('sidebar.ipcra')}
      >
        <span>🎯</span>
        <span className="world-btn-tooltip">{t('sidebar.ipcraSessions')}</span>
      </button>

      <button
        className={`world-btn nav-btn ${vueActive === 'conductor' ? 'actif' : ''}`}
        onClick={onConductor}
        title={t('sidebar.conductor')}
      >
        <span>🎛</span>
        <span className="world-btn-tooltip">{t('sidebar.conductor')}</span>
      </button>

      <button
        className={`world-btn network-btn ${vueActive === 'network' ? 'actif' : ''}`}
        onClick={onNetwork}
        title={t('sidebar.network')}
      >
        <span>🏘</span>
        <span className="world-btn-tooltip">{t('sidebar.network')}</span>
      </button>

      <div className="sidebar-bottom">
        <div className="sidebar-divider" />
        <NotificationBell />
        <button className="moi-btn" onClick={onSettings} title={t('sidebar.settings')}>
          <span>{moi.avatar_emoji}</span>
        </button>
      </div>
    </div>
  )
}
