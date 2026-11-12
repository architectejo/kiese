import { useCallback, useEffect, useRef, useState } from 'react';
import { create } from 'zustand';

/**
 * BUG-161 (F3) : « date de travail » fournie par le SERVEUR.
 *
 * Le navigateur ne calcule plus « aujourd'hui » avec `new Date().toISOString()` (date UTC :
 * la veille entre 00:00 et 01:00 à Kinshasa). BUG-272 (décision client 2026-11-12) : la date
 * annoncée par le serveur est TOUJOURS le jour calendaire local (minuit à minuit), avec ou sans
 * rotation ; la relève ne change que l'équipe en service, jamais la date. Le store est
 * alimenté par les réponses DÉJÀ existantes (`opening-confirmation`, `team-assignment`,
 * `shift-end-status`, `bread-stocks/by-date`, `daily-closure`) : aucun endpoint ni
 * `setInterval` supplémentaire.
 *
 * Repli tant que le serveur n'a pas répondu : date LOCALE du navigateur (jamais UTC), ce
 * qui est exact (date de travail = date du calendrier). Une annonce d'un autre jour calendaire
 * est périmée (minuit passé sans rechargement).
 */

/** Date locale du navigateur au format AAAA-MM-JJ (jamais UTC). */
export function localIsoDate(d: Date = new Date()): string {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

const ISO_DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

interface WorkDateState {
  /** Dernier jour calendaire annoncé par le serveur (AAAA-MM-JJ), ou null. */
  serverWorkDate: string | null;
  /** Vrai si l'annonce vient d'une boulangerie en rotation d'équipes (information : la date
   *  reste calendaire dans tous les cas). */
  rotation: boolean;
  /** Date locale du navigateur au moment de l'annonce (pour périmer l'annonce au changement de jour). */
  localDateAtFeed: string | null;
  setWorkDate: (workDate: string | null | undefined, rotation?: boolean) => void;
  clearWorkDate: () => void;
}

export const useWorkDateStore = create<WorkDateState>((set, get) => ({
  serverWorkDate: null,
  rotation: false,
  localDateAtFeed: null,
  setWorkDate: (workDate, rotation) => {
    if (!workDate || !ISO_DATE_RE.test(workDate)) return;
    const cur = get();
    // Une annonce « rotation » n'est pas rétrogradée par une réponse qui ne le précise pas
    // (ex. `by-date`) tant que la date est la même ; une date différente la remplace.
    const isRotation = rotation ?? (cur.rotation && cur.serverWorkDate === workDate);
    if (cur.serverWorkDate === workDate && cur.rotation === isRotation && cur.localDateAtFeed === localIsoDate()) return;
    set({ serverWorkDate: workDate, rotation: isRotation, localDateAtFeed: localIsoDate() });
  },
  clearWorkDate: () => set({ serverWorkDate: null, rotation: false, localDateAtFeed: null }),
}));

/** Jour courant (calendaire) : annonce serveur si elle date d'aujourd'hui, sinon date locale. */
export function resolveWorkDate(s: Pick<WorkDateState, 'serverWorkDate' | 'rotation' | 'localDateAtFeed'>): string {
  const local = localIsoDate();
  if (!s.serverWorkDate) return local;
  // La date de travail = jour calendaire : une annonce d'un autre jour est périmée
  // (minuit passé sans rechargement), avec ou sans rotation.
  if (s.localDateAtFeed !== local) return local;
  return s.serverWorkDate;
}

/** Hook : jour courant (calendaire, AAAA-MM-JJ). */
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

/**
 * Hook : jour sélectionné par l'utilisateur dans un sélecteur de jour. Par défaut (aucun choix)
 * il suit le jour courant. Si l'utilisateur regardait le jour courant au passage de minuit,
 * il suit le nouveau.
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
