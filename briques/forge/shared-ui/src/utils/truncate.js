/**
 * truncate — tronque une chaîne à `max` caractères en ajoutant un suffixe.
 *
 * @param {string|null|undefined} str
 * @param {number} max — longueur max INCLUS suffixe (default 80)
 * @param {string} suffix — default '…'
 */
export function truncate(str, max = 80, suffix = '…') {
  if (str == null) return '';
  const s = String(str);
  if (s.length <= max) return s;
  const cut = Math.max(0, max - suffix.length);
  return s.slice(0, cut) + suffix;
}

export default truncate;
