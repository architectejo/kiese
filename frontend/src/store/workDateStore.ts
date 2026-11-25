import { useCallback, useEffect, useRef, useState } from 'react';
import { create } from 'zustand';

/**
 * BUG-161 (F3) puis BUG-1134 : « date de travail » fournie par le SERVEUR.
 *
 * Décision client (Q-018, 2026-11-24) : la journée comptable va de MIDI à MIDI (heure de
 * clôture de la boulangerie, 12:00 par défaut). Le navigateur ne calcule donc plus « aujourd'hui »
 * avec le calendrier (`new Date().toISOString()` UTC, ni même la date locale : à 09:00 la
 * journée de travail est celle de la VEILLE). La date vient des réponses serveur DÉJÀ existantes
 * (`shift-end-status.current_work_date`, `team-assignment`, `opening-confirmation`,
 * `bread-stocks/by-date`, `daily-closure`) : aucun endpoint ni `setInterval` supplémentaire.
 *
 * Entre deux réponses, la date annoncée est avancée à la prochaine heure de clôture
 * (`handover`, relayée par `team-assignment.handover_time`, 12:00 par défaut) ; tant que le
 * serveur n'a rien annoncé, repli sur l'horloge locale décalée à l'heure de clôture.
 */

const DEFAULT_HANDOVER = '12:00';
const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;
const HANDOVER_RE = /^(\d{1,2}):(\d{2})/;

/** Date locale du navigateur au format AAAA-MM-JJ (jamais UTC). Formatage pur d'un instant :
 *  ce n'est PAS la date de travail (voir `getWorkDate`). */
export function localIsoDate(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function parseHandover(handover: string): { h: number; m: number } {
  const match = HANDOVER_RE.exec(handover) ?? HANDOVER_RE.exec(DEFAULT_HANDOVER);
  return { h: Number(match?.[1] ?? 12), m: Number(match?.[2] ?? 0) };
}

/** Journée comptable (AAAA-MM-JJ) d'un instant : jour du calendrier, moins un jour avant l'heure de clôture. */
export function businessDayOf(instant: Date, handover: string = DEFAULT_HANDOVER): string {
  const { h, m } = parseHandover(handover);
  const shifted = new Date(instant.getTime());
  if (instant.getHours() * 60 + instant.getMinutes() < h * 60 + m) shifted.setDate(shifted.getDate() - 1);
  return localIsoDate(shifted);
}

interface WorkDateState {
  /** Dernière date de travail annoncée par le serveur (AAAA-MM-JJ), ou null. */
  serverWorkDate: string | null;
  /** Vrai si l'annonce vient d'une boulangerie en rotation d'équipes (information). */
  rotation: boolean;
  /** Heure de clôture du nœud ("HH:MM"), 12:00 par défaut. */
  handover: string;
  setWorkDate: (workDate: string | null | undefined, rotation?: boolean) => void;
  setHandover: (handover: string | null | undefined) => void;
  clearWorkDate: () => void;
}

export const useWorkDateStore = create<WorkDateState>((set, get) => ({
  serverWorkDate: null,
  rotation: false,
  handover: DEFAULT_HANDOVER,
  setWorkDate: (workDate, rotation) => {
    if (!workDate || !ISO_DATE_RE.test(workDate)) return;
    const cur = get();
    // Une annonce « rotation » n'est pas rétrogradée par une réponse qui ne le précise pas
    // (ex. `by-date`) tant que la date est la même ; une date différente la remplace.
    const isRotation = rotation ?? (cur.rotation && cur.serverWorkDate === workDate);
    if (cur.serverWorkDate === workDate && cur.rotation === isRotation) return;
    set({ serverWorkDate: workDate, rotation: isRotation });
  },
  setHandover: (handover) => {
    if (!handover || !HANDOVER_RE.test(handover)) return;
    const { h, m } = parseHandover(handover);
    const value = `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
    if (get().handover !== value) set({ handover: value });
  },
  clearWorkDate: () => set({ serverWorkDate: null, rotation: false }),
}));

/**
 * Journée de travail courante. Annonce serveur si elle existe, avancée au prochain passage de
 * l'heure de clôture (la journée D s'achève à D+1 à l'heure de clôture) ; sinon horloge locale
 * décalée à l'heure de clôture.
 */
export function resolveWorkDate(s: Pick<WorkDateState, 'serverWorkDate' | 'handover'>, now: Date = new Date()): string {
  if (!s.serverWorkDate) return businessDayOf(now, s.handover);
  const { h, m } = parseHandover(s.handover);
  const [y, mo, d] = s.serverWorkDate.split('-').map(Number);
  let advanced = 0;
  // La journée annoncée D se termine à D+1 à l'heure de clôture.
  while (advanced < 31) {
    const end = new Date(y, mo - 1, d + advanced + 1, h, m, 0, 0);
    if (now.getTime() < end.getTime()) break;
    advanced += 1;
  }
  if (advanced === 0) return s.serverWorkDate;
  return localIsoDate(new Date(y, mo - 1, d + advanced, 12, 0, 0, 0));
}

/** Hook : date de travail courante (journée comptable de midi à midi, AAAA-MM-JJ). */
export function useWorkDate(): string {
  return useWorkDateStore(s => resolveWorkDate(s));
}

/** Hook : la boulangerie de l'utilisateur est en rotation de 24 h (annonce du serveur). */
export function useRotationActive(): boolean {
  return useWorkDateStore(s => s.rotation);
}

/** Lecture ponctuelle (gestionnaires d'événements, requêtes), sans abonnement. */
export function getWorkDate(): string {
  return resolveWorkDate(useWorkDateStore.getState());
}

/** Décale une date AAAA-MM-JJ de `days` jours (négatif = passé), sans passer par l'UTC. */
export function shiftIsoDate(iso: string, days: number): string {
  const [y, m, d] = iso.split('-').map(Number);
  return localIsoDate(new Date(y, m - 1, d + days, 12, 0, 0, 0));
}

/** Mois et année de la journée de travail (filtres mensuels par défaut). Mois de 1 à 12. */
export function workDateMonthYear(workDate: string): { month: number; year: number } {
  const [y, m] = workDate.split('-').map(Number);
  return { month: m, year: y };
}

/**
 * Hook : jour sélectionné par l'utilisateur dans un sélecteur de jour. Par défaut (aucun choix)
 * il suit la date de travail courante. Si l'utilisateur regardait la journée courante à la
 * relève, il suit la nouvelle.
 */
export function useSelectedWorkDay(): [string, (iso: string) => void, string] {
  const workDate = useWorkDate();
  const [picked, setPicked] = useState<string | null>(null);
  const prevWorkDate = useRef(workDate);
  useEffect(() => {
    if (prevWorkDate.current !== workDate) {
      const previous = prevWorkDate.current;
      prevWorkDate.current = workDate;
      setPicked(p => (p === previous ? null : p));
    }
  }, [workDate]);
  const select = useCallback((iso: string) => setPicked(iso === workDate ? null : iso), [workDate]);
  return [picked ?? workDate, select, workDate];
}
