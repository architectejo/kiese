import type { DailyClosureCategory, DailyClosureReport } from '@/api/services';

// BUG-319 : avant clôture, le « Produit » d'une journée dérivée n'a pas de sens (il vaut 0
// côté serveur) ; on affiche « — ». Aucune règle métier ici : lecture de `produit_derive`.

/** Vrai si le produit de la catégorie est dérivé mais la journée pas encore clôturée. */
export const isProduitEnAttente = (cat: DailyClosureCategory): boolean =>
  !!cat.produit_derive && cat.produit_derive.derived && !cat.produit_derive.closed;

/** Vrai si au moins une catégorie a un produit en attente de clôture. */
export const isReportProduitEnAttente = (report: DailyClosureReport): boolean =>
  report.categories.some(isProduitEnAttente);

export const PRODUIT_EN_ATTENTE_HELP =
  'Le total produit est calculé à la clôture : pains vendus + restes déclarés.';
