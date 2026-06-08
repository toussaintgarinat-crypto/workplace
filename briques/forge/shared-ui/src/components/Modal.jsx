import { useEffect } from 'react';

/**
 * Modal — overlay générique. Pas de portail (les apps gèrent leur DOM root).
 *
 * Props :
 *  - open : boolean
 *  - onClose : fn
 *  - title  : string (optionnel)
 *  - children : ReactNode
 *  - width  : string | number (default 480)
 *  - closeOnBackdrop : boolean (default true)
 */
export default function Modal({
  open,
  onClose,
  title,
  children,
  width = 480,
  closeOnBackdrop = true,
}) {
  useEffect(() => {
    if (!open) return;
    function onKey(e) {
      if (e.key === 'Escape') onClose?.();
    }
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      onClick={() => { if (closeOnBackdrop) onClose?.(); }}
      style={{
        position: 'fixed',
        inset: 0,
        background: 'rgba(0,0,0,0.55)',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        zIndex: 1000,
        padding: '16px',
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: '#1f2937',
          color: '#f9fafb',
          borderRadius: '8px',
          padding: '20px',
          maxWidth: '95vw',
          maxHeight: '90vh',
          width,
          overflowY: 'auto',
          boxShadow: '0 10px 30px rgba(0,0,0,0.4)',
        }}
      >
        {title && (
          <div style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            marginBottom: '12px',
          }}>
            <h3 style={{ margin: 0, fontSize: '16px' }}>{title}</h3>
            <button
              onClick={() => onClose?.()}
              aria-label="Fermer"
              style={{
                background: 'none',
                border: 'none',
                color: '#9ca3af',
                cursor: 'pointer',
                fontSize: '20px',
                lineHeight: 1,
              }}
            >
              ×
            </button>
          </div>
        )}
        {children}
      </div>
    </div>
  );
}
