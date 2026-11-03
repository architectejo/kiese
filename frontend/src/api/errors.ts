import axios from 'axios';

/**
 * Extrait le message d'erreur renvoyé par l'API (format `{"detail": "..."}`,
 * voir CLAUDE.md §4) à partir d'une erreur attrapée dans un `catch (err: unknown)`.
 *
 * Factorise l'idiome répété dans les pages du dashboard :
 * `catch (err: any) { ... (err as any)?.response?.data?.detail ... }`.
 *
 * @param err      La valeur attrapée par le `catch` (type `unknown`, jamais `any`).
 * @param fallback Le message à afficher si l'API ne renvoie pas de `detail` exploitable.
 */
export function getErrorDetail(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const detail = (err.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail;
    }
    return fallback;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}
