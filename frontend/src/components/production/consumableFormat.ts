// BUG-387 : affichage des quantités de consommables selon l'unité.
// Le serveur renvoie des chaînes décimales à 3 décimales (« 0.250 », « 1250.000 »).

/** Normalise une saisie utilisateur (virgule ou point) en chaîne décimale, ou null si invalide. */
export function parseDecimalInput(raw: string): string | null {
  const s = raw.trim().replace(',', '.');
  if (!/^\d+(\.\d{1,3})?$/.test(s)) return null;
  return s;
}

/** Quantité lisible : « 0,25 », « 1 250 », « 12,5 ». Zéros inutiles retirés, 3 décimales max. */
export function formatQty(value: string | number | null | undefined): string {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'number' ? value : Number(value);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('fr-FR', { minimumFractionDigits: 0, maximumFractionDigits: 3 });
}

const UNIT_LABELS: Record<string, string> = { sac: 'sac', g: 'g', l: 'L', paquet: 'paquet' };

/** Unité affichée (« L » pour litres). Les libellés inconnus sont gardés tels quels. */
export function unitLabel(unit: string): string {
  const u = (unit || '').trim();
  return UNIT_LABELS[u.toLowerCase()] ?? u;
}

/** « 1 250 g », « 0,25 paquet » (pluriel non géré : abréviation d'unité). */
export function formatQtyUnit(value: string | number | null | undefined, unit: string): string {
  const q = formatQty(value);
  return q === '—' ? q : `${q} ${unitLabel(unit)}`;
}

/** Écart signé : « +2,5 », « −1 250 », « 0 ». */
export function formatGap(value: string | number | null | undefined): string {
  const n = Number(value);
  if (!Number.isFinite(n)) return '—';
  if (n === 0) return '0';
  return `${n > 0 ? '+' : '−'}${formatQty(Math.abs(n))}`;
}

/** Date AAAA-MM-JJ -> JJ/MM/AAAA. */
export function formatIsoDate(iso: string | undefined | null): string {
  if (!iso) return '—';
  const [y, m, d] = iso.slice(0, 10).split('-');
  return y && m && d ? `${d}/${m}/${y}` : iso;
}
