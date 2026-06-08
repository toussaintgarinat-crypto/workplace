/**
 * formatBytes — taille humaine (octets/Ko/Mo/Go) en fr-FR.
 * Compatible avec les implémentations dispersées (ChatView, JardinPanel, DocumentsManager).
 *
 * @param {number|null|undefined} bytes
 * @param {object} opts
 *   - placeholder : string si bytes falsy (default '0 o')
 *   - decimals : nombre de décimales pour Mo/Go (default 1)
 */
export function formatBytes(bytes, opts = {}) {
  const { placeholder = '0 o', decimals = 1 } = opts;
  if (bytes == null || bytes === 0) return placeholder;
  if (bytes < 1024) return `${bytes} o`;
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} Ko`;
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(decimals)} Mo`;
  return `${(bytes / 1024 / 1024 / 1024).toFixed(decimals)} Go`;
}

export default formatBytes;
