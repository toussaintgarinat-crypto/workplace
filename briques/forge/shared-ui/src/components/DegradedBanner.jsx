import { useState, useEffect, useCallback } from 'react';

const DEFAULT_POLL_INTERVAL = 30_000;

/**
 * DegradedBanner — bannière mode dégradé partagée (assistant/oria/forge).
 *
 * Props :
 *  - fetcher  : async () => ({ components: { redis: { degraded: true }, … } })
 *               (obligatoire — chaque app fournit sa stratégie d'auth/baseUrl)
 *  - pollInterval : ms (default 30000)
 *  - showReadonlyHint : boolean (default true) — message "lecture seule" si readonly dégradé
 *  - closeLabel / openLabel : libellés bouton (defaults Détails / Masquer)
 */
export default function DegradedBanner({
  fetcher,
  pollInterval = DEFAULT_POLL_INTERVAL,
  showReadonlyHint = true,
  openLabel = 'Détails',
  closeLabel = 'Masquer',
}) {
  const [components, setComponents] = useState({});
  const [open, setOpen] = useState(false);

  const refresh = useCallback(async () => {
    if (typeof fetcher !== 'function') return;
    try {
      const data = await fetcher();
      if (data && typeof data === 'object') {
        setComponents(data.components ?? {});
      }
    } catch {
      // silencieux — bannière ne doit jamais crasher l'app
    }
  }, [fetcher]);

  useEffect(() => {
    refresh();
    const id = setInterval(refresh, pollInterval);
    return () => clearInterval(id);
  }, [refresh, pollInterval]);

  const degradedList = Object.entries(components).filter(([, v]) => v && v.degraded);
  if (degradedList.length === 0) return null;

  const readonlyDegraded = showReadonlyHint && components.readonly?.degraded;

  return (
    <div style={{
      background: '#92400e',
      color: '#fef3c7',
      padding: '6px 16px',
      display: 'flex',
      alignItems: 'center',
      gap: '8px',
      fontSize: '13px',
      borderBottom: '1px solid #78350f',
      position: 'relative',
      zIndex: 500,
      flexShrink: 0,
    }}>
      <span>⚠</span>
      <span style={{ flex: 1 }}>
        Mode dégradé — {degradedList.map(([k]) => k).join(', ')} indisponible(s)
        {readonlyDegraded && ' — lecture seule activée'}
      </span>
      <button
        onClick={() => setOpen(o => !o)}
        style={{
          background: 'none',
          border: '1px solid #fef3c7',
          borderRadius: '4px',
          color: '#fef3c7',
          cursor: 'pointer',
          padding: '2px 8px',
          fontSize: '12px',
        }}
      >
        {open ? closeLabel : openLabel}
      </button>
      {open && (
        <div style={{
          position: 'absolute',
          top: '100%',
          left: 0,
          right: 0,
          background: '#78350f',
          padding: '12px 16px',
          zIndex: 600,
          borderBottom: '2px solid #92400e',
        }}>
          {degradedList.map(([comp]) => (
            <div key={comp} style={{ marginBottom: '4px' }}>
              <span style={{ marginRight: '8px' }}>▸</span>
              <strong>{comp}</strong> — dégradé
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
