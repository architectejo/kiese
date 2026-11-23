/**
 * Écart de fournée (remarque.md l.512, BUG-1072).
 *
 * Convention d'affichage : écart = valeur théorique (sacs × valeur du sac) − valeur produite.
 *   écart > 0 → MANQUANT ; écart < 0 → EXCÉDENT ; écart = 0 → ÉQUILIBRE.
 * Le backend expose `yield_gap = produit − théorique` (signe opposé) : on le convertit ici.
 */
export type GapKind = 'EXCEDENT' | 'EQUILIBRE' | 'MANQUANT';

export function classifyGap(ecart: number): GapKind {
  if (ecart > 0) return 'MANQUANT';
  if (ecart < 0) return 'EXCEDENT';
  return 'EQUILIBRE';
}

export const GAP_LABELS: Record<GapKind, string> = {
  EXCEDENT: 'Excédent',
  EQUILIBRE: 'Équilibre',
  MANQUANT: 'Manquant',
};

export interface GapSessionLike {
  theoretical_yield?: number | null;
  total_fc_produced?: number | null;
  auto_track?: boolean;
  is_closed?: boolean;
}

/**
 * Écart (théorique − produit) d'une fournée, ou `null` si non calculable
 * (fournée par sacs encore en cours, valeur du sac absente → théorique nul).
 */
export function sessionGap(sess: GapSessionLike): number | null {
  if (sess.auto_track && !sess.is_closed) return null;
  const theo = sess.theoretical_yield;
  const produced = sess.total_fc_produced;
  if (typeof theo !== 'number' || !Number.isFinite(theo) || theo <= 0) return null;
  if (typeof produced !== 'number' || !Number.isFinite(produced)) return null;
  return Math.round(theo) - Math.round(produced);
}

/** Montant absolu « 12 500 FC » (espaces insécables remplacés par des espaces simples). */
export function formatGapFc(value: number): string {
  return `${Math.abs(Math.round(value)).toLocaleString('fr-FR').replace(/[  ]/g, ' ')} FC`;
}
