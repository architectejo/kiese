import { create } from 'zustand';
import type { ClosureStatus } from '@/api/services';

// BUG-973 : statut de clôture du jour, relu périodiquement par `DashboardLayout` et lu par les
// pages de vente (bannière + boutons désactivés) et par la boîte de clôture du gérant.
interface ClosureStatusState {
  status: ClosureStatus | null;
  /** Clé `<jour>` de la boîte de clôture que le gérant a reportée (« Plus tard ») ou soumise. */
  dismissedFor: string | null;
  /** Incrémenté par une page (403 « Ventes bloquées ») pour forcer une relecture immédiate. */
  refreshTick: number;
  setStatus: (status: ClosureStatus | null) => void;
  dismiss: (closureDate: string) => void;
  requestRefresh: () => void;
}

export const useClosureStatusStore = create<ClosureStatusState>((set) => ({
  status: null,
  dismissedFor: null,
  refreshTick: 0,
  setStatus: (status) => set({ status }),
  dismiss: (closureDate) => set({ dismissedFor: closureDate }),
  requestRefresh: () => set((s) => ({ refreshTick: s.refreshTick + 1 })),
}));

/** Vrai si les ventes sont bloquées pour la boulangerie de l'utilisateur. */
export const useSalesBlocked = (): { blocked: boolean; reason: string } => {
  const blocked = useClosureStatusStore((s) => !!s.status?.blocked);
  const reason = useClosureStatusStore((s) => s.status?.reason ?? '');
  return { blocked, reason };
};
