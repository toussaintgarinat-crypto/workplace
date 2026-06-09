import { useState, useEffect } from 'react'
import { api } from '../services/api.js'

const AVATAR_EMOJIS = [
  '👤', '😊', '🦊', '🐱', '🦁', '🐸', '🦋', '🌟',
  '🌈', '🔥', '⚡', '🌙', '🎯', '🎨', '🎸', '🚀',
  '🌊', '🌿', '🌺', '🍀', '💎', '🏆', '🎭', '🦄',
]

const WORLD_EMOJIS = ['🏛', '🏙', '🌆', '🏘', '⚜️', '🗺', '🏟', '🌇', '🏫', '🗼', '🌿', '🚀']

const S = {
  overlay: {
    position: 'fixed', inset: 0, background: 'var(--ink-900)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 9999, padding: '24px',
  },
  card: {
    background: 'var(--ink-850)', borderRadius: '16px', padding: '40px',
    width: '100%', maxWidth: '480px', boxShadow: '0 24px 80px rgba(0,0,0,0.6)',
  },
  dots: {
    display: 'flex', gap: '8px', justifyContent: 'center', marginBottom: '32px',
  },
  dot: (active) => ({
    width: '8px', height: '8px', borderRadius: '50%',
    background: active ? 'var(--or-500)' : '#4e505880', transition: 'background 0.2s',
  }),
  h2: { fontSize: '22px', fontWeight: 700, color: '#fff', marginBottom: '6px' },
  sub: { color: 'var(--text-mut)', fontSize: '13px', marginBottom: '28px' },
  label: { display: 'block', color: 'var(--text)', fontSize: '12px', fontWeight: 600,
           textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: '8px' },
  input: {
    width: '100%', padding: '10px 14px', borderRadius: '8px',
    background: 'var(--ink-850)', border: '1px solid var(--ink-700)', color: 'var(--text)',
    fontSize: '14px', outline: 'none', marginBottom: '20px',
  },
  textarea: {
    width: '100%', padding: '10px 14px', borderRadius: '8px',
    background: 'var(--ink-850)', border: '1px solid var(--ink-700)', color: 'var(--text)',
    fontSize: '14px', outline: 'none', resize: 'vertical', minHeight: '80px',
    marginBottom: '20px', fontFamily: 'inherit',
  },
  emojiGrid: {
    display: 'grid', gridTemplateColumns: 'repeat(8, 1fr)', gap: '6px', marginBottom: '20px',
  },
  emojiBtn: (active) => ({
    fontSize: '20px', padding: '6px', borderRadius: '8px', border: 'none',
    background: active ? 'color-mix(in srgb, var(--accent), transparent 87%)' : 'transparent',
    outline: active ? '2px solid var(--or-500)' : '2px solid transparent',
    cursor: 'pointer', transition: 'all 0.15s',
  }),
  row: { display: 'flex', gap: '12px', justifyContent: 'flex-end', marginTop: '8px' },
  btnPrimary: {
    padding: '10px 24px', borderRadius: '8px', border: 'none',
    background: 'var(--or-500)', color: '#fff', fontWeight: 600, fontSize: '14px',
    cursor: 'pointer', transition: 'background 0.15s',
  },
  btnSecondary: {
    padding: '10px 24px', borderRadius: '8px', border: 'none',
    background: 'transparent', color: 'var(--text-mut)', fontWeight: 600, fontSize: '14px',
    cursor: 'pointer',
  },
  toggle: {
    display: 'flex', justifyContent: 'space-between', alignItems: 'center',
    padding: '14px 0', borderBottom: '1px solid var(--ink-700)',
  },
  toggleLabel: { color: 'var(--text)', fontSize: '14px' },
  toggleSub: { color: 'var(--text-mut)', fontSize: '12px', marginTop: '2px' },
  switchTrack: (on) => ({
    width: '44px', height: '24px', borderRadius: '12px',
    background: on ? 'var(--or-500)' : 'var(--ink-650)', position: 'relative',
    cursor: 'pointer', transition: 'background 0.2s', flexShrink: 0,
    border: 'none',
  }),
  switchThumb: (on) => ({
    position: 'absolute', top: '3px',
    left: on ? '23px' : '3px', width: '18px', height: '18px',
    borderRadius: '50%', background: '#fff', transition: 'left 0.2s',
  }),
  userCard: {
    display: 'flex', alignItems: 'center', gap: '12px',
    padding: '12px', borderRadius: '10px', background: 'var(--ink-850)', marginBottom: '8px',
  },
  avatar: { fontSize: '28px', lineHeight: 1 },
  userInfo: { flex: 1, minWidth: 0 },
  userName: { color: '#fff', fontWeight: 600, fontSize: '14px' },
  userBio: { color: 'var(--text-mut)', fontSize: '12px', whiteSpace: 'nowrap',
             overflow: 'hidden', textOverflow: 'ellipsis', marginTop: '2px' },
  followBtn: (following) => ({
    padding: '6px 14px', borderRadius: '6px', border: 'none',
    background: following ? 'var(--ink-650)' : 'var(--or-500)', color: '#fff',
    fontSize: '12px', fontWeight: 600, cursor: 'pointer', flexShrink: 0,
    transition: 'background 0.15s',
  }),
}

export default function EasySetupWizard({ user, onComplete }) {
  const [step, setStep]       = useState(1)
  const [nom, setNom]         = useState(user.nom || '')
  const [emoji, setEmoji]     = useState(user.avatar_emoji || '👤')
  const [bio, setBio]         = useState(user.bio || '')
  const [isPublic, setIsPublic] = useState(user.is_public ?? true)
  const [docsShare, setDocsShare] = useState(user.documents_partageables_par_defaut ?? false)
  const [suggestions, setSuggestions] = useState([])
  const [followed, setFollowed] = useState(new Set())
  const [saving, setSaving]   = useState(false)
  const [error, setError]     = useState('')
  // Étape 4 — premier monde
  const [worldNom, setWorldNom]         = useState('')
  const [worldEmoji, setWorldEmoji]     = useState('🏛')
  const [worldCouleur, setWorldCouleur] = useState('var(--or-600)')

  useEffect(() => {
    if (step === 3) {
      api.get(`/discover/users?limit=3&exclude=${user.id}`).then(data => {
        setSuggestions(Array.isArray(data) ? data : [])
      })
    }
  }, [step, user.id])

  async function saveStep1() {
    if (!nom.trim()) { setError('Le nom est requis.'); return }
    setError(''); setSaving(true)
    await api.patch('/auth/me', { nom: nom.trim(), avatar_emoji: emoji, bio })
    setSaving(false)
    setStep(2)
  }

  async function saveStep2() {
    setSaving(true)
    await api.patch('/auth/me', { is_public: isPublic, documents_partageables_par_defaut: docsShare })
    setSaving(false)
    setStep(3)
  }

  // Finalise l'onboarding. Si un monde vient d'être créé, on dépose un repère
  // de première visite (sessionStorage) et on pointe l'URL vers ce monde pour
  // que MainLayout l'ouvre directement avec le fil guidé « première pièce ».
  async function finaliser(worldId) {
    setSaving(true)
    await api.post('/auth/me/setup-complete', {})
    if (worldId) {
      sessionStorage.setItem('oria_onboarding', '1')
      window.location.hash = `#/w/${worldId}`
    }
    setSaving(false)
    await onComplete()
  }

  async function creerPremierMonde() {
    if (!worldNom.trim()) { setError('Donne un nom à ton monde.'); return }
    setError(''); setSaving(true)
    const data = await api.post('/worlds/', {
      nom: worldNom.trim(), description: '', emoji: worldEmoji, couleur: worldCouleur,
    })
    setSaving(false)
    await finaliser(data?.id)
  }

  async function toggleFollow(uid) {
    if (followed.has(uid)) {
      await api.del(`/social/follow/${uid}`)
      setFollowed(prev => { const s = new Set(prev); s.delete(uid); return s })
    } else {
      await api.post(`/social/follow/${uid}`, {})
      setFollowed(prev => new Set([...prev, uid]))
    }
  }

  return (
    <div style={S.overlay}>
      <div style={S.card}>
        <div style={S.dots}>
          {[1, 2, 3, 4].map(n => <div key={n} style={S.dot(step >= n)} />)}
        </div>

        {step === 1 && (
          <>
            <h2 style={S.h2}>Personnalise ton profil</h2>
            <p style={S.sub}>Comment veux-tu apparaître sur Oria ?</p>

            <label style={S.label}>Avatar</label>
            <div style={S.emojiGrid}>
              {AVATAR_EMOJIS.map(e => (
                <button key={e} style={S.emojiBtn(emoji === e)} onClick={() => setEmoji(e)}>
                  {e}
                </button>
              ))}
            </div>

            <label style={S.label}>Nom affiché</label>
            <input
              style={{ ...S.input, borderColor: error ? 'var(--rouge)' : 'var(--ink-700)' }}
              value={nom}
              onChange={e => { setNom(e.target.value); setError('') }}
              placeholder="Ton nom ou pseudo"
              autoFocus
            />
            {error && <p style={{ color: 'var(--rouge)', fontSize: '12px', marginTop: '-14px', marginBottom: '14px' }}>{error}</p>}

            <label style={S.label}>Bio <span style={{ color: 'var(--ink-650)', fontWeight: 400 }}>(optionnel)</span></label>
            <textarea
              style={S.textarea}
              value={bio}
              onChange={e => setBio(e.target.value)}
              placeholder="Quelques mots sur toi…"
              maxLength={280}
            />

            <div style={S.row}>
              <button style={S.btnPrimary} onClick={saveStep1} disabled={saving}>
                {saving ? '…' : 'Suivant →'}
              </button>
            </div>
          </>
        )}

        {step === 2 && (
          <>
            <h2 style={S.h2}>Tes préférences</h2>
            <p style={S.sub}>Tu pourras modifier ces réglages à tout moment.</p>

            <Toggle
              label="Profil visible dans la Découverte"
              sub="Les autres utilisateurs peuvent te trouver et te suivre"
              value={isPublic}
              onChange={setIsPublic}
            />
            <Toggle
              label="Documents partageables par défaut"
              sub="Tes nouveaux documents seront partageables avec le réseau"
              value={docsShare}
              onChange={setDocsShare}
            />

            <div style={{ ...S.row, marginTop: '24px' }}>
              <button style={S.btnSecondary} onClick={() => setStep(3)}>Passer</button>
              <button style={S.btnPrimary} onClick={saveStep2} disabled={saving}>
                {saving ? '…' : 'Suivant →'}
              </button>
            </div>
          </>
        )}

        {step === 3 && (
          <>
            <h2 style={S.h2}>Bienvenue sur Oria ! 🎉</h2>
            <p style={S.sub}>Commence par suivre quelques membres de la communauté.</p>

            {suggestions.length > 0 ? (
              suggestions.map(u => (
                <div key={u.id} style={S.userCard}>
                  <span style={S.avatar}>{u.avatar_emoji}</span>
                  <div style={S.userInfo}>
                    <div style={S.userName}>{u.nom}</div>
                    {u.bio && <div style={S.userBio}>{u.bio}</div>}
                  </div>
                  <button
                    style={S.followBtn(followed.has(u.id))}
                    onClick={() => toggleFollow(u.id)}
                  >
                    {followed.has(u.id) ? 'Suivi ✓' : 'Suivre'}
                  </button>
                </div>
              ))
            ) : (
              <p style={{ color: 'var(--text-mut)', fontSize: '13px', marginBottom: '20px', textAlign: 'center' }}>
                Pas encore de membres publics — tu seras le premier !
              </p>
            )}

            <div style={{ ...S.row, marginTop: '24px' }}>
              <button style={S.btnSecondary} onClick={() => setStep(4)} disabled={saving}>Passer</button>
              <button style={S.btnPrimary} onClick={() => setStep(4)} disabled={saving}>
                {saving ? '…' : 'Suivant →'}
              </button>
            </div>
          </>
        )}

        {step === 4 && (
          <>
            <h2 style={S.h2}>Crée ton premier monde</h2>
            <p style={S.sub}>Un monde regroupe tes espaces et tes pièces. Tu pourras en créer d'autres ensuite.</p>

            <label style={S.label}>Emblème</label>
            <div style={S.emojiGrid}>
              {WORLD_EMOJIS.map(e => (
                <button key={e} style={S.emojiBtn(worldEmoji === e)} onClick={() => setWorldEmoji(e)}>
                  {e}
                </button>
              ))}
            </div>

            <label style={S.label}>Nom du monde</label>
            <input
              style={{ ...S.input, borderColor: error ? 'var(--rouge)' : 'var(--ink-700)' }}
              value={worldNom}
              onChange={e => { setWorldNom(e.target.value); setError('') }}
              placeholder="Ex. Mon atelier, Ma commune…"
              autoFocus
            />
            {error && <p style={{ color: 'var(--rouge)', fontSize: '12px', marginTop: '-14px', marginBottom: '14px' }}>{error}</p>}

            <div style={{ ...S.row, marginTop: '24px' }}>
              <button style={S.btnSecondary} onClick={() => finaliser(null)} disabled={saving}>Plus tard</button>
              <button style={S.btnPrimary} onClick={creerPremierMonde} disabled={saving}>
                {saving ? '…' : 'Créer mon monde →'}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  )
}

function Toggle({ label, sub, value, onChange }) {
  return (
    <div style={S.toggle}>
      <div>
        <div style={S.toggleLabel}>{label}</div>
        <div style={S.toggleSub}>{sub}</div>
      </div>
      <button style={S.switchTrack(value)} onClick={() => onChange(!value)}>
        <div style={S.switchThumb(value)} />
      </button>
    </div>
  )
}
