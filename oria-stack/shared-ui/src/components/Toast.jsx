import { useState, useEffect } from 'react';

/**
 * Toast container basé sur un évènement window (event-bus pattern déjà utilisé Oria).
 *
 * Props :
 *  - eventName : string (default 'app:toast'). Listen `window.dispatchEvent(new CustomEvent(eventName, { detail: 'msg' | { message, type } }))`
 *  - timeout   : ms (default 4000)
 *  - position  : 'top-right' | 'top-left' | 'bottom-right' | 'bottom-left' (default 'top-right')
 */
const POSITIONS = {
  'top-right':    { top: 12, right: 12 },
  'top-left':     { top: 12, left: 12 },
  'bottom-right': { bottom: 12, right: 12 },
  'bottom-left':  { bottom: 12, left: 12 },
};

const COLORS = {
  info:    { bg: '#1f2937', border: '#374151', icon: 'ℹ️' },
  warn:    { bg: '#78350f', border: '#92400e', icon: '⚠️' },
  error:   { bg: '#7f1d1d', border: '#991b1b', icon: '⛔' },
  success: { bg: '#14532d', border: '#166534', icon: '✅' },
};

export default function Toast({
  eventName = 'app:toast',
  timeout = 4000,
  position = 'top-right',
}) {
  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    function onEvent(e) {
      const detail = e.detail;
      const item = typeof detail === 'string'
        ? { message: detail, type: 'warn' }
        : { message: detail?.message ?? String(detail), type: detail?.type ?? 'warn' };
      const id = Date.now() + Math.random();
      setToasts(prev => [...prev, { id, ...item }]);
      setTimeout(() => {
        setToasts(prev => prev.filter(t => t.id !== id));
      }, timeout);
    }
    window.addEventListener(eventName, onEvent);
    return () => window.removeEventListener(eventName, onEvent);
  }, [eventName, timeout]);

  if (toasts.length === 0) return null;

  return (
    <div style={{
      position: 'fixed',
      ...POSITIONS[position] ?? POSITIONS['top-right'],
      display: 'flex',
      flexDirection: 'column',
      gap: '8px',
      zIndex: 2000,
      maxWidth: '360px',
    }}>
      {toasts.map(t => {
        const palette = COLORS[t.type] || COLORS.info;
        return (
          <div key={t.id} style={{
            background: palette.bg,
            border: `1px solid ${palette.border}`,
            color: '#f9fafb',
            padding: '8px 12px',
            borderRadius: '6px',
            fontSize: '13px',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            boxShadow: '0 4px 10px rgba(0,0,0,0.3)',
          }}>
            <span>{palette.icon}</span>
            <span style={{ flex: 1 }}>{t.message}</span>
            <button
              onClick={() => setToasts(prev => prev.filter(x => x.id !== t.id))}
              style={{
                background: 'none',
                border: 'none',
                color: '#9ca3af',
                cursor: 'pointer',
                fontSize: '14px',
                lineHeight: 1,
              }}
              aria-label="Fermer"
            >
              ✕
            </button>
          </div>
        );
      })}
    </div>
  );
}
