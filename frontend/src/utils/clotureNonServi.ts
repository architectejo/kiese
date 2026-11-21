import type { DailyClosureCategory, DailyClosureReport } from '@/api/services';

// BUG-356 : la ligne « Non servi » de la clôture journalière cumule le code spécial NS
// (`non_servi`) et les factures au STATUT NOT_SERVED du jour (`non_servi_jour`, commandé initial).
// Affichage uniquement : ces valeurs ne sont JAMAIS ajoutées au total du jour ni au net produit.
// Les clés `non_servi_jour` / `totals.non_servi_*` sont optionnelles (rétro-compatibilité).

export const NON_SERVI_INCLUT_HELP =
  'Inclut les factures déclarées Non servi (commandé initial) ; elles ne comptent pas dans les ventes.';

const num = (v: string | number | null | undefined): number => {
  const n = typeof v === 'string' ? parseFloat(v) : v;
  return n === null || n === undefined || Number.isNaN(n) ? 0 : n;
};

export interface NonServiCumul {
  quantity: number;
  fc: number;
  /** Part provenant des factures au statut Non servi (0 si l'API ne la fournit pas). */
  jourQuantity: number;
  jourFc: number;
}

export function nonServiCumul(cat: DailyClosureCategory): NonServiCumul {
  const jQ = cat.non_servi_jour?.quantity ?? 0;
  const jF = num(cat.non_servi_jour?.fc);
  return {
    quantity: cat.non_servi.quantity + jQ,
    fc: num(cat.non_servi.fc) + jF,
    jourQuantity: jQ,
    jourFc: jF,
  };
}

/** Valeur de toute la ligne NON SERVI (statut + code NS) ; repli sur la somme des catégories. */
export function nonServiTotalFc(report: DailyClosureReport): number {
  const t = report.totals.non_servi_total_fc;
  if (t !== undefined && t !== null) return num(t);
  return report.categories.reduce((s, c) => s + nonServiCumul(c).fc, 0);
}
