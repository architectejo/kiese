/**
 * BUG-1140 : affichage des créneaux horaires des équipes A/B dans le
 * formulaire de succursale (`pages/dashboard/Nodes.tsx`).
 *
 * Côté serveur, en rotation de 24 h (`Node.team_rotation_enabled`), les
 * horaires A/B ne sont plus lus : la journée de travail et la relève
 * suivent `handover_time` (`core/workday.py`), la fin de service passe par
 * la relève (`production/views.py`, `_handover_shift_end_response`) et le
 * stock de départ cible l'équipe désignée (`team_at_day_start` /
 * `current_team`), pas `Node.opening_team()`. Les champs sont donc masqués
 * en rotation (valeurs stockées conservées). Hors rotation : inchangé.
 */

export interface TeamScheduleDisplay {
  /** Afficher les quatre champs horaires équipe A / équipe B. */
  showTeamSlots: boolean;
  /** Texte d'aide affiché sous la section. */
  helpText: string;
}

export const DEFAULT_HANDOVER_TIME = '12:00';

/** Normalise une heure « HH:MM » ou « HH:MM:SS » en « HH:MM » (défaut 12:00). */
export function formatHandoverTime(value: string | null | undefined): string {
  const match = /^(\d{1,2}):(\d{2})/.exec((value ?? '').trim());
  if (!match) return DEFAULT_HANDOVER_TIME;
  const hours = Number(match[1]);
  const minutes = Number(match[2]);
  if (hours > 23 || minutes > 59) return DEFAULT_HANDOVER_TIME;
  return `${String(hours).padStart(2, '0')}:${match[2]}`;
}

export function teamScheduleDisplay(
  rotationEnabled: boolean,
  handoverTime: string | null | undefined,
): TeamScheduleDisplay {
  if (rotationEnabled) {
    return {
      showTeamSlots: false,
      helpText:
        `En rotation de 24 h, les équipes se relaient à l'heure de clôture (${formatHandoverTime(handoverTime)}). ` +
        "Les créneaux horaires équipe A / équipe B ne sont pas utilisés ; ceux déjà enregistrés sont conservés " +
        'et reprendront effet si la rotation est désactivée.',
    };
  }
  return {
    showTeamSlots: true,
    helpText:
      "Ces horaires seront remplacés par l'heure de clôture ci-dessus ; ils servent encore, pour l'instant, " +
      'à la confirmation du stock de départ. Laisser vide si les créneaux ne sont pas encore déterminés pour ' +
      'cette succursale. Suggestion : équipe A 06h00–13h00, équipe B 13h00–20h00.',
  };
}
