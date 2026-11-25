import type { ClosureStatus } from '@/api/services';

/**
 * BUG-1304 : journée proposée par défaut dans « Opérations de clôture ».
 *
 * Depuis Q-018 (BUG-1130), la journée comptable D court de D à l'heure de clôture (12:00) jusqu'à
 * D+1 à la même heure. Après la bascule, la journée qui VIENT DE SE TERMINER est
 * `closure-status.closure_date` : tant que sa clôture n'est pas validée (direction ou comptable),
 * c'est elle que le gérant doit clôturer, pas la journée en cours (date de travail).
 * Le serveur reste l'autorité : cette fonction ne fait que choisir la date affichée.
 */
export type ClosureDayStatus = Pick<ClosureStatus, 'closure_date' | 'validated'>;

const ISO_DATE_RE = /^(\d{4})-(\d{2})-(\d{2})$/;

/** Journée à clôturer en attente (AAAA-MM-JJ) ou null si rien n'est à faire. */
export function pendingClosureDay(
  status: ClosureDayStatus | null | undefined,
  workDate: string,
): string | null {
  if (!status || status.validated) return null;
  const day = status.closure_date;
  if (!day || !ISO_DATE_RE.test(day)) return null;
  // Garde : jamais une journée en cours ou future (comparaison lexicographique AAAA-MM-JJ).
  if (ISO_DATE_RE.test(workDate) && day >= workDate) return null;
  return day;
}

/** Date par défaut de la section : journée terminée non validée, sinon date de travail. */
export function defaultClosureDay(
  status: ClosureDayStatus | null | undefined,
  workDate: string,
): string {
  return pendingClosureDay(status, workDate) ?? workDate;
}

/** « 24/11/2026 » à partir de « 2026-11-24 » (sans passer par le fuseau du navigateur). */
export function formatDayFr(isoDay: string): string {
  const m = ISO_DATE_RE.exec(isoDay);
  return m ? `${m[3]}/${m[2]}/${m[1]}` : isoDay;
}

/** Lendemain d'une date AAAA-MM-JJ (calcul UTC, insensible au fuseau). */
export function nextIsoDay(isoDay: string): string {
  const m = ISO_DATE_RE.exec(isoDay);
  if (!m) return isoDay;
  const d = new Date(Date.UTC(Number(m[1]), Number(m[2]) - 1, Number(m[3]) + 1));
  return d.toISOString().slice(0, 10);
}

/** « de 12:00 le 24/11 à 12:00 le 25/11 » : bornes de la journée comptable. */
export function closureDayRange(isoDay: string, closureHour: string | null | undefined): string {
  const hour = closureHour && /^\d{1,2}:\d{2}$/.test(closureHour) ? closureHour : '12:00';
  const short = (d: string) => formatDayFr(d).slice(0, 5);
  return `de ${hour} le ${short(isoDay)} à ${hour} le ${short(nextIsoDay(isoDay))}`;
}

/** Champs utiles d'une clôture pour la file de validation (sous-ensemble de `CashClosure`). */
export interface PendingClosureLike {
  date: string;
  is_validated: boolean;
  is_rejected: boolean;
  node_display?: string;
  node: string;
}

/**
 * BUG-1304 (volet valideurs) : clôtures EN ATTENTE de confirmation par la direction, le comptable
 * ou l'admin, quelle que soit leur date — ni confirmées, ni infirmées (une clôture infirmée attend
 * la correction du gérant). Ordre : la plus ancienne journée d'abord, puis la boulangerie.
 */
export function pendingValidationClosures<T extends PendingClosureLike>(closures: readonly T[]): T[] {
  return closures
    .filter(c => !c.is_validated && !c.is_rejected)
    .sort((a, b) => (a.date === b.date
      ? (a.node_display || a.node).localeCompare(b.node_display || b.node, 'fr')
      : a.date < b.date ? -1 : 1));
}
