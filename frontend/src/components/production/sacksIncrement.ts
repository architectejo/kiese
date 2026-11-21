// BUG-355 : « Augmenter les sacs » ajoute une quantité au nombre de sacs déjà déclarés.
// Tout le calcul se fait en CENTIÈMES entiers (pas de dérive flottante) ; l'API reçoit le nouveau total absolu.

/** Plafond de sacs ajoutés en une fois (au-delà : saisie démesurée). */
export const MAX_ADDED_SACKS = 100000;

export type ParsedAddition = { ok: true; cents: number } | { ok: false; message: string };

/** Valide la saisie (virgule ou point, 2 décimales max, positive) et la convertit en centièmes. */
export function parseSacksAddition(raw: string): ParsedAddition {
  const s = raw.trim();
  if (s === '') return { ok: false, message: 'Indiquez le nombre de sacs à ajouter.' };
  if (s.startsWith('-')) return { ok: false, message: 'Le nombre de sacs à ajouter ne peut pas être négatif.' };
  if (!/^\d+([.,]\d*)?$|^[.,]\d+$/.test(s)) return { ok: false, message: 'Saisissez un nombre valide (ex. 1,5).' };
  const [intPart, decPart = ''] = s.replace(',', '.').split('.');
  if (decPart.length > 2) return { ok: false, message: 'Deux décimales au maximum (ex. 0,25).' };
  const cents = parseInt(intPart || '0', 10) * 100 + parseInt((decPart + '00').slice(0, 2), 10);
  if (!Number.isSafeInteger(cents) || cents > MAX_ADDED_SACKS * 100) {
    return { ok: false, message: `Quantité démesurée : ${MAX_ADDED_SACKS.toLocaleString('fr-FR')} sacs au maximum.` };
  }
  if (cents <= 0) return { ok: false, message: 'Indiquez un nombre de sacs supérieur à 0.' };
  return { ok: true, cents };
}

/** Valeur API (chaîne décimale, ex. « 3.00 ») -> centièmes. */
export function sacksToCents(apiValue: string): number {
  const n = Number(apiValue);
  return Number.isFinite(n) ? Math.round(n * 100) : 0;
}

/** Centièmes -> chaîne décimale exacte pour l'API (ex. 450 -> « 4.50 »). */
export function centsToApi(cents: number): string {
  return `${Math.trunc(cents / 100)}.${String(cents % 100).padStart(2, '0')}`;
}

/** Centièmes -> affichage français (ex. 450 -> « 4,5 »). */
export function centsToLabel(cents: number): string {
  return `${Math.trunc(cents / 100).toLocaleString('fr-FR')}${cents % 100 === 0 ? '' : ',' + String(cents % 100).padStart(2, '0').replace(/0$/, '')}`;
}

export function sacksWord(cents: number): string {
  return cents > 100 ? 'sacs' : 'sac';
}
