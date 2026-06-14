import { useState, useEffect, useRef } from 'react'
import { useTranslation } from 'react-i18next'
import { api, authHeaders } from '../services/api.js'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

export default function CoinPanel({ room, moi }) {
  const { t } = useTranslation()
  const [coins, setCoins]               = useState([])
  const [coinActif, setCoinActif]       = useState(null)
  const [dossiers, setDossiers]         = useState([])
  const [dossierActif, setDossierActif] = useState(null)
  const [fichiers, setFichiers]         = useState([])
  const [monCoin, setMonCoin]           = useState(null)

  // Formulaires
  const [creationCoin, setCreationCoin]       = useState(false)
  const [titreNouv, setTitreNouv]             = useState('')
  const [descNouv, setDescNouv]               = useState('')
  const [creationDossier, setCreationDossier] = useState(false)
  const [nomDossier, setNomDossier]           = useState('')
  const [visiDossier, setVisiDossier]         = useState('prive')
  const [loading, setLoading]                 = useState(false)

  const fileRef = useRef(null)

  useEffect(() => {
    chargerCoins()
  }, [room.id])

  useEffect(() => {
    if (coinActif) chargerDossiers(coinActif.id)
    else { setDossiers([]); setDossierActif(null); setFichiers([]) }
  }, [coinActif?.id])

  useEffect(() => {
    if (dossierActif) chargerFichiers(coinActif.id, dossierActif.id)
    else setFichiers([])
  }, [dossierActif?.id])

  async function chargerCoins() {
    const data = await api.get(`/rooms/${room.id}/coins`)
    if (Array.isArray(data)) {
      setCoins(data)
      const mien = data.find(c => c.est_mien)
      setMonCoin(mien || null)
    }
  }

  async function chargerDossiers(coinId) {
    const data = await api.get(`/coins/${coinId}/dossiers`)
    if (Array.isArray(data)) setDossiers(data)
  }

  async function chargerFichiers(coinId, dossierId) {
    const data = await api.get(`/coins/${coinId}/dossiers/${dossierId}/fichiers`)
    if (Array.isArray(data)) setFichiers(data)
  }

  async function creerCoin(e) {
    e.preventDefault()
    setLoading(true)
    const data = await api.post(`/rooms/${room.id}/coins`, {
      titre: titreNouv, description: descNouv,
    })
    setLoading(false)
    if (data) {
      setCreationCoin(false)
      setTitreNouv(''); setDescNouv('')
      chargerCoins()
      setCoinActif(data)
    }
  }

  async function creerDossier(e) {
    e.preventDefault()
    if (!coinActif) return
    setLoading(true)
    const data = await api.post(`/coins/${coinActif.id}/dossiers`, {
      nom: nomDossier, visibilite: visiDossier,
    })
    setLoading(false)
    if (data) {
      setCreationDossier(false)
      setNomDossier(''); setVisiDossier('prive')
      chargerDossiers(coinActif.id)
    }
  }

  async function supprimerDossier(dossierId) {
    if (!coinActif) return
    await api.del(`/coins/${coinActif.id}/dossiers/${dossierId}`)
    if (dossierActif?.id === dossierId) setDossierActif(null)
    chargerDossiers(coinActif.id)
  }

  async function uploaderFichier(e) {
    const file = e.target.files[0]
    if (!file || !coinActif || !dossierActif) return
    const form = new FormData()
    form.append('file', file)
    const res = await fetch(
      `${API_URL}/api/coins/${coinActif.id}/dossiers/${dossierActif.id}/fichiers`,
      { method: 'POST', credentials: 'include', headers: authHeaders(), body: form }
    )
    if (res.ok) chargerFichiers(coinActif.id, dossierActif.id)
    e.target.value = ''
  }

  async function supprimerFichier(fichierId) {
    if (!coinActif || !dossierActif) return
    await api.del(`/coins/${coinActif.id}/dossiers/${dossierActif.id}/fichiers/${fichierId}`)
    chargerFichiers(coinActif.id, dossierActif.id)
  }

  async function toggleVisibilite(dossier) {
    const nouv = dossier.visibilite === 'prive' ? 'partage' : 'prive'
    await api.patch(`/coins/${coinActif.id}/dossiers/${dossier.id}`, { visibilite: nouv })
    chargerDossiers(coinActif.id)
  }

  const estProprietaireCoin = coinActif?.est_mien

  return (
    <div style={{ display: 'flex', height: '100%', overflow: 'hidden' }}>
      {/* Colonne gauche — liste des Coins */}
      <div style={{
        width: 220, borderRight: '1px solid #3d3f45',
        display: 'flex', flexDirection: 'column', overflowY: 'auto',
        background: 'var(--ink-850)',
      }}>
        <div style={{ padding: '12px 14px 6px', fontSize: 12, color: 'var(--text-mut)', fontWeight: 700,
                      textTransform: 'uppercase', letterSpacing: 1 }}>
          {t('coin.membersCoins')}
        </div>

        {coins.length === 0 && (
          <div style={{ padding: '8px 14px', color: 'var(--text-mut)', fontSize: 13 }}>
            {t('coin.empty')}
          </div>
        )}

        {coins.map(c => (
          <button
            key={c.id}
            onClick={() => setCoinActif(coinActif?.id === c.id ? null : c)}
            style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 14px', border: 'none', cursor: 'pointer', textAlign: 'left',
              background: coinActif?.id === c.id ? '#393c41' : 'transparent',
              color: coinActif?.id === c.id ? '#fff' : 'var(--text)',
              borderLeft: coinActif?.id === c.id ? '3px solid var(--or-500)' : '3px solid transparent',
            }}
          >
            <span style={{ fontSize: 18 }}>{c.user_emoji}</span>
            <div style={{ overflow: 'hidden' }}>
              <div style={{ fontWeight: 600, fontSize: 13, whiteSpace: 'nowrap',
                            overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {c.titre}
              </div>
              <div style={{ fontSize: 11, color: 'var(--text-mut)' }}>{c.user_nom}</div>
            </div>
            {c.est_mien && (
              <span style={{ marginLeft: 'auto', fontSize: 10, color: 'var(--or-500)',
                             fontWeight: 700 }}>{t('coin.me')}</span>
            )}
          </button>
        ))}

        <div style={{ marginTop: 'auto', padding: 12, borderTop: '1px solid #3d3f45' }}>
          {!monCoin ? (
            <button
              onClick={() => setCreationCoin(true)}
              style={{
                width: '100%', padding: '8px', borderRadius: 8, border: 'none',
                background: 'var(--or-500)', color: 'white', cursor: 'pointer',
                fontWeight: 600, fontSize: 13,
              }}
            >{t('coin.createMyCoin')}</button>
          ) : (
            <div style={{ fontSize: 12, color: 'var(--vert)', textAlign: 'center' }}>
              {t('coin.active')}
            </div>
          )}
        </div>
      </div>

      {/* Zone principale */}
      {!coinActif ? (
        <div style={{ flex: 1, display: 'flex', alignItems: 'center',
                      justifyContent: 'center', color: 'var(--text-mut)', flexDirection: 'column', gap: 8 }}>
          <span style={{ fontSize: 40 }}>🏠</span>
          <span style={{ fontSize: 14 }}>{t('coin.selectCoin')}</span>
        </div>
      ) : (
        <div style={{ flex: 1, display: 'flex', overflow: 'hidden' }}>
          {/* Colonne milieu — dossiers */}
          <div style={{
            width: 220, borderRight: '1px solid #3d3f45',
            display: 'flex', flexDirection: 'column', overflowY: 'auto',
            background: 'var(--ink-800)',
          }}>
            <div style={{ padding: '12px 14px 6px', display: 'flex',
                          alignItems: 'center', justifyContent: 'space-between' }}>
              <span style={{ fontSize: 12, color: 'var(--text-mut)', fontWeight: 700,
                             textTransform: 'uppercase', letterSpacing: 1 }}>
                {t('coin.folders')}
              </span>
              {estProprietaireCoin && (
                <button
                  onClick={() => setCreationDossier(true)}
                  style={{ background: 'none', border: 'none', color: 'var(--text)',
                           cursor: 'pointer', fontSize: 16, padding: 0 }}
                  title={t('coin.newFolderTooltip')}
                >+</button>
              )}
            </div>

            {dossiers.length === 0 && (
              <div style={{ padding: '8px 14px', color: 'var(--text-mut)', fontSize: 13 }}>
                {estProprietaireCoin ? t('coin.noFolderOwner') : t('coin.noFolderShared')}
              </div>
            )}

            {dossiers.map(d => (
              <div
                key={d.id}
                style={{
                  display: 'flex', alignItems: 'center', gap: 6,
                  padding: '7px 14px', cursor: 'pointer',
                  background: dossierActif?.id === d.id ? '#393c41' : 'transparent',
                  borderLeft: dossierActif?.id === d.id ? '3px solid var(--or-500)' : '3px solid transparent',
                }}
                onClick={() => setDossierActif(dossierActif?.id === d.id ? null : d)}
              >
                <span style={{ fontSize: 15 }}>{d.visibilite === 'prive' ? '🔒' : '📂'}</span>
                <div style={{ flex: 1, overflow: 'hidden' }}>
                  <div style={{ fontSize: 13, color: 'var(--text)', whiteSpace: 'nowrap',
                                overflow: 'hidden', textOverflow: 'ellipsis' }}>
                    {d.nom}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--text-mut)' }}>
                    {d.visibilite === 'prive' ? t('coin.private') : t('coin.shared')} · {t('coin.files', { count: d.nb_fichiers })}
                  </div>
                </div>
                {estProprietaireCoin && (
                  <div style={{ display: 'flex', gap: 4 }} onClick={e => e.stopPropagation()}>
                    <button
                      onClick={() => toggleVisibilite(d)}
                      title={d.visibilite === 'prive' ? t('coin.makeShared') : t('coin.makePrivate')}
                      style={{ background: 'none', border: 'none', cursor: 'pointer',
                               fontSize: 12, color: 'var(--text-mut)', padding: 2 }}
                    >{d.visibilite === 'prive' ? '👁' : '🔒'}</button>
                    <button
                      onClick={() => supprimerDossier(d.id)}
                      style={{ background: 'none', border: 'none', cursor: 'pointer',
                               fontSize: 12, color: 'var(--rouge)', padding: 2 }}
                      title={t('common.delete')}
                    >✕</button>
                  </div>
                )}
              </div>
            ))}
          </div>

          {/* Colonne droite — fichiers */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto',
                        background: 'var(--ink-800)' }}>
            {!dossierActif ? (
              <div style={{ flex: 1, display: 'flex', alignItems: 'center',
                            justifyContent: 'center', color: 'var(--text-mut)', flexDirection: 'column', gap: 8 }}>
                <span style={{ fontSize: 30 }}>📁</span>
                <span style={{ fontSize: 13 }}>{t('coin.selectFolder')}</span>
              </div>
            ) : (
              <>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid #3d3f45',
                              display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <span style={{ fontWeight: 600, color: '#fff', fontSize: 14 }}>
                    {dossierActif.visibilite === 'prive' ? '🔒' : '📂'} {dossierActif.nom}
                    <span style={{ marginLeft: 8, fontSize: 12,
                                   color: dossierActif.visibilite === 'prive' ? 'var(--or-400)' : 'var(--vert)',
                                   fontWeight: 400 }}>
                      {dossierActif.visibilite === 'prive' ? t('coin.private') : t('coin.shared')}
                    </span>
                  </span>
                  {estProprietaireCoin && (
                    <>
                      <button
                        onClick={() => fileRef.current?.click()}
                        style={{
                          padding: '5px 12px', borderRadius: 8, border: 'none',
                          background: 'var(--or-500)', color: 'white', cursor: 'pointer',
                          fontSize: 13, fontWeight: 600,
                        }}
                      >{t('coin.add')}</button>
                      <input ref={fileRef} type="file" style={{ display: 'none' }}
                             onChange={uploaderFichier} />
                    </>
                  )}
                </div>

                <div style={{ padding: 12, display: 'flex', flexDirection: 'column', gap: 6 }}>
                  {fichiers.length === 0 && (
                    <div style={{ color: 'var(--text-mut)', fontSize: 13, padding: '12px 0' }}>
                      {estProprietaireCoin ? t('coin.noFilesOwner') : t('coin.noFiles')}
                    </div>
                  )}
                  {fichiers.map(f => (
                    <div key={f.id} style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '8px 12px', borderRadius: 8, background: 'var(--ink-850)',
                    }}>
                      <span style={{ fontSize: 20 }}>
                        {f.type_mime?.startsWith('image/') ? '🖼'
                          : f.type_mime === 'application/pdf' ? '📄'
                          : f.type_mime?.startsWith('video/') ? '🎬' : '📎'}
                      </span>
                      <div style={{ flex: 1, overflow: 'hidden' }}>
                        <div style={{ fontSize: 13, color: 'var(--text)', whiteSpace: 'nowrap',
                                      overflow: 'hidden', textOverflow: 'ellipsis' }}>
                          {f.nom}
                        </div>
                        <div style={{ fontSize: 11, color: 'var(--text-mut)' }}>
                          {t('coin.sizeKo', { kb: Math.round(f.taille / 1024) })}
                        </div>
                      </div>
                      <a
                        href={`${API_URL}/api/coins/fichiers/${f.id}/download`}
                        target="_blank" rel="noreferrer"
                        style={{ color: 'var(--or-500)', fontSize: 13, textDecoration: 'none' }}
                      >⬇</a>
                      {estProprietaireCoin && (
                        <button
                          onClick={() => supprimerFichier(f.id)}
                          style={{ background: 'none', border: 'none', cursor: 'pointer',
                                   color: 'var(--rouge)', fontSize: 14, padding: 0 }}
                          title="Supprimer"
                        >✕</button>
                      )}
                    </div>
                  ))}
                </div>
              </>
            )}
          </div>
        </div>
      )}

      {/* Modal création Coin */}
      {creationCoin && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }} onClick={() => setCreationCoin(false)}>
          <div style={{
            background: 'var(--ink-800)', borderRadius: 12, padding: 24,
            width: 380, boxShadow: '0 8px 32px rgba(0,0,0,.4)',
          }} onClick={e => e.stopPropagation()}>
            <h3 style={{ color: '#fff', marginBottom: 16 }}>{t('coin.createCoinTitle')}</h3>
            <form onSubmit={creerCoin}>
              <label style={{ color: 'var(--text)', fontSize: 13 }}>{t('coin.coinNameLabel')}</label>
              <input
                value={titreNouv}
                onChange={e => setTitreNouv(e.target.value)}
                placeholder={t('coin.coinNamePlaceholder')}
                required autoFocus
                style={{ width: '100%', marginBottom: 12 }}
              />
              <label style={{ color: 'var(--text)', fontSize: 13 }}>{t('coin.descOptional')}</label>
              <textarea
                value={descNouv}
                onChange={e => setDescNouv(e.target.value)}
                placeholder={t('coin.descPlaceholder')}
                style={{
                  width: '100%', height: 80, background: 'var(--ink-850)', color: 'var(--text)',
                  border: '1px solid #3d3f45', borderRadius: 6, padding: 8,
                  resize: 'none', fontSize: 14, marginBottom: 16,
                }}
              />
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button type="button" onClick={() => setCreationCoin(false)}
                  style={{ padding: '8px 16px', borderRadius: 8, border: 'none',
                           background: 'var(--ink-850)', color: 'var(--text)', cursor: 'pointer' }}>
                  {t('common.cancel')}
                </button>
                <button type="submit" disabled={loading}
                  style={{ padding: '8px 16px', borderRadius: 8, border: 'none',
                           background: 'var(--or-500)', color: 'white', cursor: 'pointer', fontWeight: 600 }}>
                  {loading ? t('common.working') : t('coin.create')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* Modal création dossier */}
      {creationDossier && (
        <div style={{
          position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)',
          display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
        }} onClick={() => setCreationDossier(false)}>
          <div style={{
            background: 'var(--ink-800)', borderRadius: 12, padding: 24,
            width: 340, boxShadow: '0 8px 32px rgba(0,0,0,.4)',
          }} onClick={e => e.stopPropagation()}>
            <h3 style={{ color: '#fff', marginBottom: 16 }}>{t('coin.newFolderHeader')}</h3>
            <form onSubmit={creerDossier}>
              <label style={{ color: 'var(--text)', fontSize: 13 }}>{t('coin.folderNameLabel')}</label>
              <input
                value={nomDossier}
                onChange={e => setNomDossier(e.target.value)}
                placeholder={t('coin.folderNamePlaceholder')}
                required autoFocus
                style={{ width: '100%', marginBottom: 12 }}
              />
              <label style={{ color: 'var(--text)', fontSize: 13 }}>{t('coin.visibility')}</label>
              <div style={{ display: 'flex', gap: 8, marginBottom: 16 }}>
                {[
                  { id: 'prive',   label: t('coin.privLabel'),  desc: t('coin.privDesc') },
                  { id: 'partage', label: t('coin.sharedLabel'), desc: t('coin.sharedDesc') },
                ].map(opt => (
                  <button key={opt.id} type="button"
                    onClick={() => setVisiDossier(opt.id)}
                    style={{
                      flex: 1, padding: '8px', borderRadius: 8, border: 'none', cursor: 'pointer',
                      background: visiDossier === opt.id ? 'var(--or-500)' : 'var(--ink-850)',
                      color: visiDossier === opt.id ? 'white' : 'var(--text)',
                      fontSize: 13, fontWeight: visiDossier === opt.id ? 600 : 400,
                    }}
                  >
                    <div>{opt.label}</div>
                    <div style={{ fontSize: 11, opacity: .7, marginTop: 2 }}>{opt.desc}</div>
                  </button>
                ))}
              </div>
              <div style={{ display: 'flex', gap: 10, justifyContent: 'flex-end' }}>
                <button type="button" onClick={() => setCreationDossier(false)}
                  style={{ padding: '8px 16px', borderRadius: 8, border: 'none',
                           background: 'var(--ink-850)', color: 'var(--text)', cursor: 'pointer' }}>
                  {t('common.cancel')}
                </button>
                <button type="submit" disabled={loading}
                  style={{ padding: '8px 16px', borderRadius: 8, border: 'none',
                           background: 'var(--or-500)', color: 'white', cursor: 'pointer', fontWeight: 600 }}>
                  {loading ? t('common.working') : t('coin.create')}
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  )
}
