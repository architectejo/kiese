import { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import type { PaginatedResponse } from '@/api/services';

// BUG-163 (remarque.md l.420/l.422) : chargement progressif d'une liste DRF
// paginée, généralisation du patron de `Clients.tsx` (BUG-132).
//  - la page 1 est exposée dès sa réception (`isLoading` ne couvre qu'elle) ;
//  - mode `auto` : les pages suivantes sont lues l'une après l'autre en arrière-plan
//    (`isLoadingMore`), éventuellement jusqu'à ce que `stopWhen(items)` soit vrai ;
//  - mode `manual` : une page de plus à chaque appel de `loadMore()` (« Voir plus ») ;
//  - `loadAll()` force la lecture de toutes les pages restantes ;
//  - un identifiant de requête annule (ignore) toute réponse devenue obsolète quand
//    `resetKey` ou `enabled` change, ou quand `reload()` est appelé ;
//  - `total` = `count` renvoyé par le serveur (exact dès la page 1) ; `isComplete` n'est
//    vrai qu'une fois toutes les pages lues : c'est la SEULE condition pour afficher un
//    total / KPI / graphique calculé côté client comme définitif.
// Utilise la fonction `getPage` de `services.ts` via `fetchPage` (le hook ne fait aucun
// appel HTTP lui-même).

export interface UseProgressiveListOptions<T> {
  fetchPage: (page: number) => Promise<{ data: PaginatedResponse<T> }>;
  /** Change => annulation des chargements en cours et rechargement depuis la page 1. */
  resetKey: string;
  enabled?: boolean;
  mode?: 'auto' | 'manual';
  /** Mode auto : arrête le chargement d'arrière-plan quand la condition est vraie. */
  stopWhen?: (items: T[]) => boolean;
  /**
   * BUG-172 : contrôle `loaded === total` en fin de lecture (un rechargement complet automatique,
   * puis erreur « Données incomplètes »). Défaut : actif en mode `auto`, inactif en mode `manual`
   * (la liste « Voir plus » n'est jamais présentée comme finale ; un rechargement automatique
   * ferait perdre la position de l'utilisateur).
   */
  verifyConsistency?: boolean;
}

export interface ProgressiveList<T> {
  items: T[];
  /** Page 1 en cours de lecture (liste encore vide). */
  isLoading: boolean;
  /** Une page suivante est en cours de lecture. */
  isLoadingMore: boolean;
  loaded: number;
  /** `count` serveur (null tant que la page 1 n'est pas arrivée). */
  total: number | null;
  /**
   * Plus de page suivante ET `loaded === total` (BUG-172) : la liste est complète.
   * Reste faux si les lignes lues ne correspondent pas au `count` serveur.
   */
  isComplete: boolean;
  /** BUG-172 : dernière page atteinte mais `loaded !== total` après un rechargement automatique. */
  isInconsistent: boolean;
  hasMore: boolean;
  error: string | null;
  loadMore: () => void;
  loadAll: () => void;
  reload: () => void;
}

export function extractApiError(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string' && detail) return detail;
  }
  return fallback;
}

export function useProgressiveList<T extends { id: string | number }>(
  options: UseProgressiveListOptions<T>,
): ProgressiveList<T> {
  const { resetKey, enabled = true, mode = 'auto' } = options;

  const optionsRef = useRef(options);
  optionsRef.current = options;

  const [items, setItems] = useState<T[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [isLoading, setIsLoading] = useState(enabled);
  const [isLoadingMore, setIsLoadingMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [reloadTick, setReloadTick] = useState(0);
  const [isInconsistent, setIsInconsistent] = useState(false);

  const requestIdRef = useRef(0);
  const itemsRef = useRef<T[]>([]);
  const pageRef = useRef(0);
  const hasMoreRef = useRef(false);
  const busyRef = useRef(false);
  const forceAllRef = useRef(false);
  const totalRef = useRef<number | null>(null);
  const autoRetryRef = useRef(false);
  const retriedRef = useRef(false);

  const append = (incoming: T[], reset: boolean): T[] => {
    const base = reset ? [] : itemsRef.current;
    const seen = new Set(base.map(i => i.id));
    const merged = base.concat(incoming.filter(i => !seen.has(i.id)));
    itemsRef.current = merged;
    return merged;
  };

  // BUG-172 : appelé quand la dernière page vient d'être lue. Si les lignes lues ne
  // correspondent pas au `count` serveur (ligne sautée/doublée par une insertion ou un tri
  // instable), un seul rechargement complet automatique, puis erreur bloquante.
  const verifyComplete = (reqId: number) => {
    const verify = optionsRef.current.verifyConsistency ?? optionsRef.current.mode !== 'manual';
    if (!verify || reqId !== requestIdRef.current || hasMoreRef.current) return;
    if (totalRef.current === null || itemsRef.current.length === totalRef.current) return;
    if (!retriedRef.current) {
      retriedRef.current = true;
      autoRetryRef.current = true;
      setReloadTick(t => t + 1);
      return;
    }
    setIsInconsistent(true);
    setError('Données incomplètes, réessayez.');
  };

  // Lit `count` pages (ou toutes si count = Infinity), en s'arrêtant si la requête
  // devient obsolète, sur erreur, ou (mode auto) quand `stopWhen` est satisfait.
  const loadPages = useCallback(async (reqId: number, count: number, honorStop: boolean) => {
    busyRef.current = true;
    setIsLoadingMore(true);
    setError(null);
    try {
      let remaining = count;
      while (remaining > 0 && hasMoreRef.current) {
        const page = pageRef.current + 1;
        const res = await optionsRef.current.fetchPage(page);
        if (reqId !== requestIdRef.current) return;
        const data = res.data;
        pageRef.current = page;
        hasMoreRef.current = data.next !== null && data.next !== undefined;
        setHasMore(hasMoreRef.current);
        totalRef.current = data.count;
        setTotal(data.count);
        setItems(append(data.results ?? [], false));
        remaining -= 1;
        const stop = optionsRef.current.stopWhen;
        if (honorStop && !forceAllRef.current && stop && stop(itemsRef.current)) break;
      }
      verifyComplete(reqId);
    } catch (err) {
      if (reqId !== requestIdRef.current) return;
      setError(extractApiError(err, 'Impossible de charger la suite de la liste.'));
    } finally {
      if (reqId === requestIdRef.current) {
        busyRef.current = false;
        setIsLoadingMore(false);
      }
    }
  }, []);

  useEffect(() => {
    requestIdRef.current += 1;
    const reqId = requestIdRef.current;
    itemsRef.current = [];
    pageRef.current = 0;
    hasMoreRef.current = false;
    busyRef.current = false;
    forceAllRef.current = false;
    totalRef.current = null;
    if (!autoRetryRef.current) retriedRef.current = false;
    autoRetryRef.current = false;
    setIsInconsistent(false);
    setItems([]);
    setTotal(null);
    setHasMore(false);
    setError(null);
    setIsLoadingMore(false);
    if (!enabled) {
      setIsLoading(false);
      return;
    }
    setIsLoading(true);
    (async () => {
      try {
        const res = await optionsRef.current.fetchPage(1);
        if (reqId !== requestIdRef.current) return;
        const data = res.data;
        pageRef.current = 1;
        hasMoreRef.current = data.next !== null && data.next !== undefined;
        setHasMore(hasMoreRef.current);
        totalRef.current = data.count;
        setTotal(data.count);
        setItems(append(data.results ?? [], true));
        setIsLoading(false);
        const stop = optionsRef.current.stopWhen;
        if (mode === 'auto' && hasMoreRef.current && !(stop && stop(itemsRef.current))) {
          await loadPages(reqId, Infinity, true);
        } else {
          verifyComplete(reqId);
        }
      } catch (err) {
        if (reqId !== requestIdRef.current) return;
        setError(extractApiError(err, 'Impossible de charger la liste.'));
        setIsLoading(false);
      }
    })();
    return () => {
      // Invalide toute réponse encore en vol (changement de paramètres / démontage).
      requestIdRef.current += 1;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [resetKey, enabled, mode, reloadTick, loadPages]);

  const loadMore = useCallback(() => {
    if (busyRef.current || !hasMoreRef.current) return;
    void loadPages(requestIdRef.current, 1, false);
  }, [loadPages]);

  const loadAll = useCallback(() => {
    forceAllRef.current = true;
    if (busyRef.current || !hasMoreRef.current) return;
    void loadPages(requestIdRef.current, Infinity, false);
  }, [loadPages]);

  const reload = useCallback(() => {
    retriedRef.current = false;
    autoRetryRef.current = false;
    setReloadTick(t => t + 1);
  }, []);

  return {
    items,
    isLoading,
    isLoadingMore,
    loaded: items.length,
    total,
    isComplete:
      !isLoading && !hasMore && error === null && !isInconsistent && total !== null
      && (!(options.verifyConsistency ?? mode !== 'manual') || items.length === total),
    isInconsistent,
    hasMore,
    error,
    loadMore,
    loadAll,
    reload,
  };
}
