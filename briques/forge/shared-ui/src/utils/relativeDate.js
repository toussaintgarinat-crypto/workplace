/**
 * relativeDate — formate une date ISO en libellé relatif fr-FR.
 *
 * Exemples : "À l'instant", "Il y a 12 min", "Aujourd'hui", "Hier", "12 mai"
 *
 * @param {string|Date|null|undefined} iso
 * @param {object} opts
 *   - locale : default 'fr-FR'
 *   - now : Date injectable pour tests (default new Date())
 */
export function relativeDate(iso, opts = {}) {
  if (!iso) return '';
  const { locale = 'fr-FR', now = new Date() } = opts;
  const d = iso instanceof Date ? iso : new Date(iso);
  if (Number.isNaN(d.getTime())) return '';
  const diff = now - d;
  if (diff < 60_000) return "À l'instant";
  if (diff < 3_600_000) return `Il y a ${Math.floor(diff / 60_000)} min`;
  if (diff < 86_400_000) return "Aujourd'hui";
  if (diff < 172_800_000) return 'Hier';
  return d.toLocaleDateString(locale, { day: 'numeric', month: 'short' });
}

export default relativeDate;
