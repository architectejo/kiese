import { describe, expect, it } from 'vitest';
import { classifyGap, formatGapFc, sessionGap } from './fourneeGap';

describe('fourneeGap', () => {
  it('classe les trois cas, équilibre exact à 0', () => {
    expect(classifyGap(12500)).toBe('MANQUANT');
    expect(classifyGap(-300)).toBe('EXCEDENT');
    expect(classifyGap(0)).toBe('EQUILIBRE');
  });

  it('calcule théorique − produit', () => {
    expect(sessionGap({ theoretical_yield: 800000, total_fc_produced: 787500 })).toBe(12500);
    expect(sessionGap({ theoretical_yield: 800000, total_fc_produced: 810000 })).toBe(-10000);
    expect(sessionGap({ theoretical_yield: 800000, total_fc_produced: 800000 })).toBe(0);
  });

  it('renvoie null si non calculable', () => {
    expect(sessionGap({ theoretical_yield: 0, total_fc_produced: 100 })).toBeNull();
    expect(sessionGap({ theoretical_yield: 800000, total_fc_produced: 0, auto_track: true, is_closed: false })).toBeNull();
    expect(sessionGap({ theoretical_yield: undefined, total_fc_produced: 5 })).toBeNull();
  });

  it('formate en FC sans décimales', () => {
    expect(formatGapFc(-12500)).toBe('12 500 FC');
  });
});
