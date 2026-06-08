/**
 * Spinner — loader léger CSS pur (aucune dépendance).
 * Props : size (px, default 16), color (default currentColor)
 */
export default function Spinner({ size = 16, color = 'currentColor', label }) {
  const border = Math.max(2, Math.round(size / 8));
  return (
    <span
      role="status"
      aria-label={label || 'Chargement'}
      style={{
        display: 'inline-block',
        width: size,
        height: size,
        border: `${border}px solid ${color}33`,
        borderTopColor: color,
        borderRadius: '50%',
        animation: 'sharedui-spin 0.8s linear infinite',
        verticalAlign: 'middle',
      }}
    >
      <style>{`
        @keyframes sharedui-spin {
          to { transform: rotate(360deg); }
        }
      `}</style>
    </span>
  );
}
