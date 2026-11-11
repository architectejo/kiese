import { create } from 'zustand';
import { ShiftEndRemainingLine, ShiftEndTeam } from '@/api/services';

/**
 * BUG-156 (docs/qa/REGISTRE_BUGS.md, volet frontend de BUG-155) : petit état
 * partagé, sur le modèle exact de `openingConfirmationStore.ts` (BUG-151),
 * pour piloter l'ouverture FORCÉE de `CloseSessionModal`
 * (`components/production/CloseSessionModal.tsx`, montée une seule fois par
 * `DashboardLayout`) et l'annonce de clôture automatique — depuis le
 * cycle de sondage déjà en place pour les notifications dans
 * `DashboardLayout.tsx` (pas de second `setInterval`).
 *
 * Un store Zustand plutôt qu'un simple `useState` local à `DashboardLayout` :
 * même raisonnement que `openingConfirmationStore` — garde la logique de
 * sondage découplée du composant qui l'affiche, et permet à une page
 * (ex. `Production.tsx`) de lire/déclencher cet état plus tard sans passer
 * par des props.
 *
 * BUG-157 (instruction client du 2026-11-10) : l'annonce de clôture
 * automatique n'est plus un toast éphémère mais une FILE d'annonces
 * (`autoClosedNotices`) qui restent affichées jusqu'à confirmation explicite.
 * Le backend ne renvoie `auto_closed: true` qu'UNE fois (à l'appel qui
 * effectue la clôture) : la file est donc aussi écrite dans `localStorage`
 * (une clé par boulangerie) pour survivre à un rechargement de page, et
 * n'en est retirée qu'à la confirmation.
 */
export interface ShiftEndPendingState {
  team: ShiftEndTeam;
  session: string;
  remaining: ShiftEndRemainingLine[];
}

/** Comparaison en profondeur (équipe, session, lignes `remaining`). */
const samePending = (a: ShiftEndPendingState | null, b: ShiftEndPendingState | null): boolean => {
  if (a === b) return true;
  if (a === null || b === null) return false;
  if (a.team !== b.team || a.session !== b.session) return false;
  if (a.remaining.length !== b.remaining.length) return false;
  return a.remaining.every((line, i) => {
    const other = b.remaining[i];
    return line.bread_price === other.bread_price
      && line.label === other.label
      && line.quantity_suggested === other.quantity_suggested;
  });
};

/** Annonce de clôture automatique en attente de confirmation (BUG-157). */
export interface AutoClosedNotice {
  team: ShiftEndTeam;
  /** Jour (heure locale du poste) où la clôture automatique a été constatée,
   *  au format `AAAA-MM-JJ`. */
  date: string;
}

const STORAGE_PREFIX = 'kiese_shift_end_auto_closed:';

const storageKey = (nodeKey: string): string => `${STORAGE_PREFIX}${nodeKey}`;

const isNotice = (value: unknown): value is AutoClosedNotice => {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (candidate.team === 'A' || candidate.team === 'B')
    && typeof candidate.date === 'string'
    && /^\d{4}-\d{2}-\d{2}$/.test(candidate.date);
};

const sameNotice = (a: AutoClosedNotice, b: AutoClosedNotice): boolean =>
  a.team === b.team && a.date === b.date;

/** Lit les annonces en attente d'une boulangerie. Ne lève jamais : un
 *  `localStorage` indisponible ou un contenu corrompu donne une liste vide. */
const readNotices = (nodeKey: string): AutoClosedNotice[] => {
  try {
    const raw = localStorage.getItem(storageKey(nodeKey));
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return [];
    const notices: AutoClosedNotice[] = [];
    parsed.forEach((item: unknown) => {
      if (isNotice(item) && !notices.some(n => sameNotice(n, item))) {
        notices.push({ team: item.team, date: item.date });
      }
    });
    return notices;
  } catch {
    return [];
  }
};

/** Écrit les annonces en attente. Ne lève jamais : si `localStorage` est
 *  indisponible, l'annonce reste au moins affichée (état en mémoire). */
const writeNotices = (nodeKey: string, notices: AutoClosedNotice[]): void => {
  try {
    if (notices.length === 0) {
      localStorage.removeItem(storageKey(nodeKey));
    } else {
      localStorage.setItem(storageKey(nodeKey), JSON.stringify(notices));
    }
  } catch {
    /* stockage indisponible (navigation privée, quota) : non bloquant */
  }
};

const localToday = (): string => {
  const now = new Date();
  const month = String(now.getMonth() + 1).padStart(2, '0');
  const day = String(now.getDate()).padStart(2, '0');
  return `${now.getFullYear()}-${month}-${day}`;
};

/** Vrai si l'événement `storage` (autre onglet) concerne cette boulangerie. */
export const isAutoClosedStorageKey = (key: string | null, nodeKey: string): boolean =>
  key === null || key === storageKey(nodeKey);

interface ShiftEndStoreState {
  /** `null` = aucune fournée en attente de clôture forcée actuellement. */
  pending: ShiftEndPendingState | null;
  /** BUG-157 : annonces de clôture automatique (créneau dépassé de plus de
   *  30 min, personne n'avait validé) pas encore confirmées, de la plus
   *  ancienne à la plus récente. Aucune n'en écrase une autre. */
  autoClosedNotices: AutoClosedNotice[];
  setPending: (pending: ShiftEndPendingState | null) => void;
  /** Recharge depuis `localStorage` les annonces en attente de la boulangerie
   *  (montage du layout, rechargement de page, changement dans un autre onglet). */
  loadAutoClosedNotices: (nodeKey: string) => void;
  /** Ajoute une annonce (en fin de file) et la persiste. */
  notifyAutoClosed: (nodeKey: string, team: ShiftEndTeam) => void;
  /** Confirmation explicite : seul chemin qui retire une annonce. */
  confirmAutoClosedNotice: (nodeKey: string, notice: AutoClosedNotice) => void;
}

export const useShiftEndStore = create<ShiftEndStoreState>((set) => ({
  pending: null,
  autoClosedNotices: [],
  // BUG-166 : le sondage de 10 s rappelle setPending avec un NOUVEL objet à
  // chaque tick. On ne remplace l'état que si le contenu a réellement changé
  // (équipe, session, lignes), sinon on garde la même référence.
  setPending: (pending) => set((state) => (
    samePending(state.pending, pending) ? state : { pending }
  )),
  loadAutoClosedNotices: (nodeKey) => set({ autoClosedNotices: readNotices(nodeKey) }),
  notifyAutoClosed: (nodeKey, team) => set((state) => {
    const notice: AutoClosedNotice = { team, date: localToday() };
    // Relit le stockage (source de vérité partagée entre onglets) avant
    // d'ajouter, pour ne perdre aucune annonce déjà en attente.
    const notices = readNotices(nodeKey);
    if (!notices.some(n => sameNotice(n, notice))) notices.push(notice);
    writeNotices(nodeKey, notices);
    return {
      autoClosedNotices: notices,
      // La fournée de CETTE équipe vient d'être close par le serveur : sa
      // modale forcée n'a plus lieu d'être. Celle de l'autre équipe, si elle
      // est ouverte, n'est pas touchée (saisie en cours conservée).
      pending: state.pending && state.pending.team === team ? null : state.pending,
    };
  }),
  confirmAutoClosedNotice: (nodeKey, notice) => set(() => {
    const notices = readNotices(nodeKey).filter(n => !sameNotice(n, notice));
    writeNotices(nodeKey, notices);
    return { autoClosedNotices: notices };
  }),
}));
