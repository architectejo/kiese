import { create } from 'zustand';

// BUG-161 (F2) : petit signal partagé entre les pages (ex. `Sales.tsx`, après un 403
// `TEAM_NOT_ASSIGNED`) et `DashboardLayout.tsx`, qui monte UNE SEULE fois la boîte
// `TeamAssignmentModal`. Une page appelle `requestAssignment()` ; le layout relit alors
// l'équipe de service et rouvre la boîte (non fermable) si elle n'est pas désignée.
interface TeamAssignmentSignalState {
  requestTick: number;
  requestAssignment: () => void;
}

export const useTeamAssignmentStore = create<TeamAssignmentSignalState>((set) => ({
  requestTick: 0,
  requestAssignment: () => set((s) => ({ requestTick: s.requestTick + 1 })),
}));

/** Code machine renvoyé par l'API (403) quand l'équipe de service du jour n'est pas désignée. */
export const TEAM_NOT_ASSIGNED_CODE = 'TEAM_NOT_ASSIGNED';

/** Message affiché par une page quand le 403 `TEAM_NOT_ASSIGNED` est reçu (la boîte se rouvre). */
export const TEAM_NOT_ASSIGNED_MESSAGE =
  "Désignez l'équipe de service du jour avant de facturer. La boîte de désignation vient de s'ouvrir.";
