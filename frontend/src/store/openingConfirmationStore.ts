import { create } from 'zustand';
import { OpeningConfirmationTeam } from '@/api/services';

/**
 * BUG-151 (docs/qa/REGISTRE_BUGS.md, remarque.md après l.406) : petit état partagé pour
 * déclencher MANUELLEMENT la boîte modale « Stock de départ du jour »
 * (`components/production/OpeningStockConfirmationModal.tsx`, montée une seule fois par
 * `DashboardLayout`) depuis un autre endroit de l'arbre — ici la page « Production & Stocks »
 * (`pages/dashboard/Production.tsx`), qui veut proposer de confirmer le reste d'hier d'une
 * équipe précise APRÈS que l'équipe du créneau d'ouverture a déjà été confirmée (cas où la
 * boîte modale automatique ne se réaffiche plus, BUG-139/140/141 — comportement voulu pour
 * l'affichage automatique, mais qui ne laissait plus aucun moyen de confirmer l'AUTRE équipe
 * volontairement plus tard dans la journée).
 *
 * Un simple store Zustand plutôt qu'un contexte React : évite de coupler `Production.tsx` et
 * `DashboardLayout.tsx` par les props, et la logique métier de confirmation reste entièrement
 * dans `OpeningStockConfirmationModal.tsx` (ce store ne fait que porter « quelle équipe
 * l'utilisateur vient de demander à confirmer manuellement »).
 */
interface OpeningConfirmationStoreState {
  /** `null` = pas de demande manuelle en cours (comportement automatique inchangé). */
  forceOpenForTeam: OpeningConfirmationTeam | null;
  requestManualConfirmation: (team: OpeningConfirmationTeam) => void;
  clearManualConfirmation: () => void;
}

export const useOpeningConfirmationStore = create<OpeningConfirmationStoreState>((set) => ({
  forceOpenForTeam: null,
  requestManualConfirmation: (team) => set({ forceOpenForTeam: team }),
  clearManualConfirmation: () => set({ forceOpenForTeam: null }),
}));
