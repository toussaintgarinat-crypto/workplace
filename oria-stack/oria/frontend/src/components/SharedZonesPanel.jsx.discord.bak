import { useState, useEffect, useRef, useCallback } from 'react';
import { useSharedZone } from '../hooks/useSharedZone';
import { api } from '../services/api.js';

// ── Zone editor — collaborative text via Yjs ─────────────────────

function ZoneEditor({ zoneId }) {
  const { doc, connected } = useSharedZone(zoneId);
  const [text, setText]     = useState('');
  const yTextRef            = useRef(null);
  const isLocalEdit         = useRef(false);

  useEffect(() => {
    const yText = doc.getText('notes');
    yTextRef.current = yText;

    const handler = () => {
      if (!isLocalEdit.current) {
        setText(yText.toString());
      }
    };
    yText.observe(handler);
    setText(yText.toString());

    return () => yText.unobserve(handler);
  }, [doc]);

  const handleChange = useCallback((e) => {
    const yText = yTextRef.current;
    if (!yText) return;
    const newVal = e.target.value;
    isLocalEdit.current = true;
    doc.transact(() => {
      yText.delete(0, yText.length);
      yText.insert(0, newVal);
    });
    isLocalEdit.current = false;
    setText(newVal);
  }, [doc]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{
        fontSize: '0.72rem',
        color: connected ? '#22c55e' : '#f59e0b',
        letterSpacing: '0.02em',
      }}>
        {connected ? '● Synchronisé' : '○ Hors ligne — modifications sauvegardées localement'}
      </div>
      <textarea
        value={text}
        onChange={handleChange}
        placeholder="Notes partagées… tout le monde dans cette zone peut écrire ici."
        style={{
          width: '100%',
          minHeight: 220,
          resize: 'vertical',
          fontFamily: 'inherit',
          fontSize: '0.9rem',
          padding: '10px 12px',
          border: '1px solid #334155',
          borderRadius: 6,
          background: '#0f172a',
          color: '#e2e8f0',
          outline: 'none',
          lineHeight: 1.6,
        }}
      />
    </div>
  );
}

// ── Invite modal ─────────────────────────────────────────────────

function InviteModal({ zoneId, onClose }) {
  const [userId,  setUserId]  = useState('');
  const [role,    setRole]    = useState('reader');
  const [loading, setLoading] = useState(false);
  const [error,   setError]   = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setLoading(true); setError('');
    const res = await api.post(`/shared-zones/${zoneId}/members`, { user_id: userId, role });
    setLoading(false);
    if (res) {
      onClose();
    } else {
      setError('Erreur lors de l\'invitation');
    }
  };

  return (
    <div style={{
      position: 'fixed', inset: 0, background: 'rgba(0,0,0,.6)',
      display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
    }}>
      <div style={{
        background: '#1e293b', borderRadius: 10, padding: 24, minWidth: 320,
        border: '1px solid #334155',
      }}>
        <h3 style={{ margin: '0 0 16px', color: '#f1f5f9' }}>Inviter un membre</h3>
        <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          <input
            value={userId}
            onChange={e => setUserId(e.target.value)}
            placeholder="ID utilisateur"
            required
            style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid #475569',
              background: '#0f172a', color: '#e2e8f0', fontSize: '0.875rem' }}
          />
          <select
            value={role}
            onChange={e => setRole(e.target.value)}
            style={{ padding: '8px 10px', borderRadius: 6, border: '1px solid #475569',
              background: '#0f172a', color: '#e2e8f0', fontSize: '0.875rem' }}
          >
            <option value="contributor">Contributeur (lit &amp; écrit)</option>
            <option value="reader">Lecteur (lit uniquement)</option>
          </select>
          {error && <div style={{ color: '#f87171', fontSize: '0.8rem' }}>{error}</div>}
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end' }}>
            <button type="button" onClick={onClose}
              style={{ padding: '7px 14px', borderRadius: 6, border: '1px solid #475569',
                background: 'transparent', color: '#94a3b8', cursor: 'pointer' }}>
              Annuler
            </button>
            <button type="submit" disabled={loading}
              style={{ padding: '7px 14px', borderRadius: 6, border: 'none',
                background: '#6366f1', color: '#fff', cursor: 'pointer' }}>
              {loading ? '…' : 'Inviter'}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ── Main panel ───────────────────────────────────────────────────

export default function SharedZonesPanel({ onFermer }) {
  const [zones,       setZones]      = useState([]);
  const [activeZone,  setActiveZone] = useState(null);
  const [showCreate,  setShowCreate] = useState(false);
  const [showInvite,  setShowInvite] = useState(false);
  const [newZoneName, setNewZoneName] = useState('');
  const [loading,     setLoading]    = useState(true);
  const [error,       setError]      = useState('');

  const fetchZones = useCallback(async () => {
    setLoading(true);
    const res = await api.get('/shared-zones/');
    setLoading(false);
    if (res) {
      setZones(res);
      if (res.length > 0 && !activeZone) setActiveZone(res[0]);
    } else {
      setError('Impossible de charger les zones');
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { fetchZones(); }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const createZone = async (e) => {
    e.preventDefault();
    if (!newZoneName.trim()) return;
    const res = await api.post('/shared-zones/', { name: newZoneName.trim() });
    if (res) {
      setZones(prev => [...prev, res]);
      setActiveZone(res);
      setNewZoneName('');
      setShowCreate(false);
    } else {
      setError('Erreur création zone');
    }
  };

  const deleteZone = async (zoneId) => {
    if (!confirm('Supprimer cette zone ? Cette action est irréversible.')) return;
    const res = await api.del(`/shared-zones/${zoneId}`);
    if (res !== null || true) { // del retourne null sur 204 — on considère ça OK
      setZones(prev => prev.filter(z => z.id !== zoneId));
      if (activeZone?.id === zoneId) setActiveZone(zones.find(z => z.id !== zoneId) || null);
    }
  };

  if (loading) return <div style={{ padding: 24, color: '#94a3b8' }}>Chargement…</div>;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', fontFamily: 'inherit' }}>
      {/* Header */}
      <div className="mairie-panel-header">
        <div className="mairie-panel-title"><span>🔗</span><h2>Zones partagées</h2></div>
        {onFermer && (
          <div className="mairie-panel-actions">
            <button className="mairie-btn-close" onClick={onFermer}>✕</button>
          </div>
        )}
      </div>

      <div style={{ display: 'flex', flex: 1, minHeight: 0 }}>
        {/* Sidebar — zone list */}
        <div style={{
          width: 200, borderRight: '1px solid #2b2d31', padding: '8px 0',
          display: 'flex', flexDirection: 'column', gap: 2,
          overflowY: 'auto', flexShrink: 0,
        }}>
          {zones.map(z => (
            <button
              key={z.id}
              onClick={() => setActiveZone(z)}
              style={{
                textAlign: 'left', padding: '7px 12px', border: 'none', cursor: 'pointer',
                borderRadius: 0, fontSize: '0.875rem',
                background: activeZone?.id === z.id ? '#2b2d31' : 'transparent',
                color: activeZone?.id === z.id ? '#f1f5f9' : '#94a3b8',
                transition: 'background 0.15s',
              }}
            >
              # {z.name}
            </button>
          ))}

          {showCreate ? (
            <form onSubmit={createZone} style={{ padding: '8px 12px', display: 'flex', flexDirection: 'column', gap: 6 }}>
              <input
                autoFocus
                value={newZoneName}
                onChange={e => setNewZoneName(e.target.value)}
                placeholder="Nom de la zone"
                style={{ padding: '5px 8px', borderRadius: 5, border: '1px solid #3f4147',
                  background: '#1e1f22', color: '#dcddde', fontSize: '0.8rem' }}
              />
              <div style={{ display: 'flex', gap: 4 }}>
                <button type="submit" style={{ flex: 1, padding: '4px', borderRadius: 4,
                  border: 'none', background: '#5865f2', color: '#fff', cursor: 'pointer', fontSize: '0.8rem' }}>
                  Créer
                </button>
                <button type="button" onClick={() => setShowCreate(false)}
                  style={{ flex: 1, padding: '4px', borderRadius: 4,
                    border: '1px solid #3f4147', background: 'transparent',
                    color: '#94a3b8', cursor: 'pointer', fontSize: '0.8rem' }}>
                  ✕
                </button>
              </div>
            </form>
          ) : (
            <button
              onClick={() => setShowCreate(true)}
              style={{ textAlign: 'left', padding: '7px 12px', border: 'none', cursor: 'pointer',
                background: 'transparent', color: '#5865f2', fontSize: '0.8rem' }}>
              + Nouvelle zone
            </button>
          )}
        </div>

        {/* Main — editor */}
        <div style={{ flex: 1, padding: 20, overflow: 'auto' }}>
          {error && (
            <div style={{ color: '#f87171', marginBottom: 12, fontSize: '0.85rem' }}>{error}</div>
          )}

          {!activeZone ? (
            <div style={{ color: '#72767d', textAlign: 'center', marginTop: 60 }}>
              Sélectionne une zone ou crée-en une nouvelle
            </div>
          ) : (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between',
                marginBottom: 16 }}>
                <h2 style={{ margin: 0, fontSize: '1rem', color: '#f1f5f9' }}>
                  # {activeZone.name}
                </h2>
                <div style={{ display: 'flex', gap: 8 }}>
                  <button
                    onClick={() => setShowInvite(true)}
                    style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid #3f4147',
                      background: 'transparent', color: '#94a3b8', cursor: 'pointer', fontSize: '0.8rem' }}>
                    Inviter
                  </button>
                  <button
                    onClick={() => deleteZone(activeZone.id)}
                    style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid #3f4147',
                      background: 'transparent', color: '#f87171', cursor: 'pointer', fontSize: '0.8rem' }}>
                    Supprimer
                  </button>
                </div>
              </div>

              <ZoneEditor key={activeZone.id} zoneId={activeZone.id} />
            </>
          )}
        </div>
      </div>

      {showInvite && activeZone && (
        <InviteModal zoneId={activeZone.id} onClose={() => setShowInvite(false)} />
      )}
    </div>
  );
}
