import { describe, expect, it } from 'vitest';
import {
  closureDayRange, defaultClosureDay, formatDayFr, nextIsoDay, pendingClosureDay,
  pendingValidationClosures,
} from './closureDay';

describe('closureDay (BUG-1304)', () => {
  const workDate = '2026-11-25';

  it('journée terminée non validée -> cette journée', () => {
    const s = { closure_date: '2026-11-24', validated: false };
    expect(defaultClosureDay(s, workDate)).toBe('2026-11-24');
    expect(pendingClosureDay(s, workDate)).toBe('2026-11-24');
  });

  it('journée terminée déjà validée -> date de travail', () => {
    const s = { closure_date: '2026-11-24', validated: true };
    expect(defaultClosureDay(s, workDate)).toBe(workDate);
    expect(pendingClosureDay(s, workDate)).toBeNull();
  });

  it('closure_date null (SIEGE) ou statut absent -> date de travail', () => {
    expect(defaultClosureDay({ closure_date: null, validated: false }, workDate)).toBe(workDate);
    expect(defaultClosureDay(null, workDate)).toBe(workDate);
    expect(defaultClosureDay(undefined, workDate)).toBe(workDate);
  });

  it("jamais la journée en cours ni une date future, ni une date mal formée", () => {
    expect(defaultClosureDay({ closure_date: workDate, validated: false }, workDate)).toBe(workDate);
    expect(defaultClosureDay({ closure_date: '2026-11-26', validated: false }, workDate)).toBe(workDate);
    expect(defaultClosureDay({ closure_date: '24/11/2026', validated: false }, workDate)).toBe(workDate);
  });

  it('formate la journée et ses bornes de midi à midi', () => {
    expect(formatDayFr('2026-11-24')).toBe('24/11/2026');
    expect(nextIsoDay('2026-11-30')).toBe('2026-12-01');
    expect(nextIsoDay('2026-12-31')).toBe('2027-01-01');
    expect(closureDayRange('2026-11-24', '12:00')).toBe('de 12:00 le 24/11 à 12:00 le 25/11');
    expect(closureDayRange('2026-11-24', null)).toBe('de 12:00 le 24/11 à 12:00 le 25/11');
  });
});

describe('pendingValidationClosures (BUG-1304, valideurs)', () => {
  const c = (node: string, date: string, is_validated = false, is_rejected = false) =>
    ({ id: `${node}-${date}`, node, node_display: node, date, is_validated, is_rejected });

  it('garde les clôtures ni confirmées ni infirmées, toutes dates, plus anciennes d’abord', () => {
    const list = [
      c('K2 COQ', '2026-11-25'),
      c('K1 TABORA', '2026-11-24'),
      c('K3 ATHENEE', '2026-11-24', true),
      c('K4 LOMA', '2026-11-23', false, true),
      c('B1 KUMBI', '2026-11-24'),
    ];
    expect(pendingValidationClosures(list).map(x => x.id)).toEqual([
      'B1 KUMBI-2026-11-24', 'K1 TABORA-2026-11-24', 'K2 COQ-2026-11-25',
    ]);
  });

  it('liste vide si tout est confirmé ou infirmé, sans modifier l’entrée', () => {
    const list = [c('K1', '2026-11-24', true), c('K2', '2026-11-24', false, true)];
    expect(pendingValidationClosures(list)).toEqual([]);
    expect(list).toHaveLength(2);
  });
});
