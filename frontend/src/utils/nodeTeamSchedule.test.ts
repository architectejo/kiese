import { describe, expect, it } from 'vitest';
import { formatHandoverTime, teamScheduleDisplay } from './nodeTeamSchedule';

describe('teamScheduleDisplay (BUG-1140)', () => {
  it('rotation de 24 h : champs A/B masqués, relève à l\'heure de clôture', () => {
    const d = teamScheduleDisplay(true, '12:00');
    expect(d.showTeamSlots).toBe(false);
    expect(d.helpText).toContain("En rotation de 24 h, les équipes se relaient à l'heure de clôture (12:00)");
  });

  it('rotation : aucune suggestion de créneaux fixes 06h–13h / 13h–20h', () => {
    const d = teamScheduleDisplay(true, '14:30');
    expect(d.helpText).toContain('(14:30)');
    expect(d.helpText).not.toContain('06h00');
    expect(d.helpText).not.toContain('13h00');
    expect(d.helpText).not.toContain('Suggestion');
  });

  it('rotation : heure au format serveur HH:MM:SS ou vide', () => {
    expect(teamScheduleDisplay(true, '07:15:00').helpText).toContain('(07:15)');
    expect(teamScheduleDisplay(true, '').helpText).toContain('(12:00)');
    expect(teamScheduleDisplay(true, null).helpText).toContain('(12:00)');
  });

  it('hors rotation : comportement inchangé (champs visibles, suggestion)', () => {
    const d = teamScheduleDisplay(false, '12:00');
    expect(d.showTeamSlots).toBe(true);
    expect(d.helpText).toContain('Suggestion : équipe A 06h00–13h00, équipe B 13h00–20h00.');
  });
});

describe('formatHandoverTime', () => {
  it('normalise et protège', () => {
    expect(formatHandoverTime('7:05')).toBe('07:05');
    expect(formatHandoverTime('25:00')).toBe('12:00');
    expect(formatHandoverTime(undefined)).toBe('12:00');
  });
});
