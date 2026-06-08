import Spinner from './Spinner.jsx';

/**
 * Button — bouton générique avec variants minimalistes.
 * variants : 'primary' | 'secondary' | 'danger' | 'ghost'
 */
const VARIANTS = {
  primary:   { background: '#2563eb', color: '#fff',    border: '1px solid #2563eb' },
  secondary: { background: '#374151', color: '#f9fafb', border: '1px solid #4b5563' },
  danger:    { background: '#dc2626', color: '#fff',    border: '1px solid #dc2626' },
  ghost:     { background: 'transparent', color: 'currentColor', border: '1px solid currentColor' },
};

export default function Button({
  children,
  variant = 'primary',
  loading = false,
  disabled = false,
  type = 'button',
  onClick,
  style,
  ...rest
}) {
  const palette = VARIANTS[variant] || VARIANTS.primary;
  const isDisabled = disabled || loading;
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={isDisabled}
      style={{
        ...palette,
        padding: '6px 14px',
        borderRadius: '6px',
        cursor: isDisabled ? 'not-allowed' : 'pointer',
        opacity: isDisabled ? 0.6 : 1,
        fontSize: '13px',
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        ...style,
      }}
      {...rest}
    >
      {loading && <Spinner size={12} />}
      {children}
    </button>
  );
}
