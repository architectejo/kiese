import axios from 'axios';

/**
 * Forme DRF standard d'une erreur de validation de sérialiseur :
 * `{"<champ>": ["<message>", ...], ...}`, sans clé `detail` (distincte des
 * réponses `Response({'detail': ...})` construites à la main dans les
 * `@action` personnalisées). C'est la forme par défaut renvoyée par
 * `ModelViewSet.create()`/`update()` quand `Serializer.is_valid()` échoue.
 */
type DrfFieldErrors = Record<string, unknown>;

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

/**
 * Construit un message lisible à partir d'une réponse d'erreur de validation
 * DRF sans clé `detail` (ex. `{"from_node": ["Ce champ est obligatoire."]}`).
 * Renvoie `null` si aucun message exploitable n'a été trouvé (ex. objet vide,
 * ou valeurs qui ne sont ni des chaînes ni des tableaux de chaînes).
 */
function formatFieldErrors(data: DrfFieldErrors): string | null {
  const parts: string[] = [];
  for (const [field, value] of Object.entries(data)) {
    const messages = Array.isArray(value)
      ? value.filter((item): item is string => typeof item === 'string')
      : typeof value === 'string'
        ? [value]
        : [];
    if (messages.length > 0) {
      parts.push(`${field} : ${messages.join(' ')}`);
    }
  }
  return parts.length > 0 ? parts.join(' — ') : null;
}

/**
 * Extrait le message d'erreur renvoyé par l'API (format `{"detail": "..."}`,
 * voir CLAUDE.md §4) à partir d'une erreur attrapée dans un `catch (err: unknown)`.
 *
 * Factorise l'idiome répété dans les pages du dashboard :
 * `catch (err: any) { ... (err as any)?.response?.data?.detail ... }`.
 *
 * Si la réponse n'a pas de clé `detail` exploitable mais contient un objet
 * d'erreurs de validation DRF standard (ex. `{"from_node": ["Ce champ est
 * obligatoire."]}`, voir BUG-127), un message lisible est construit à partir
 * des champs en erreur avant de retomber sur `fallback`.
 *
 * @param err      La valeur attrapée par le `catch` (type `unknown`, jamais `any`).
 * @param fallback Le message à afficher si l'API ne renvoie rien d'exploitable.
 */
export function getErrorDetail(err: unknown, fallback: string): string {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as { detail?: unknown } | undefined;
    const detail = data?.detail;
    if (typeof detail === 'string' && detail.trim() !== '') {
      return detail;
    }
    if (isPlainObject(data)) {
      const fieldMessage = formatFieldErrors(data);
      if (fieldMessage) {
        return fieldMessage;
      }
    }
    return fallback;
  }
  if (err instanceof Error && err.message) {
    return err.message;
  }
  return fallback;
}

/**
 * BUG-161 (B2/F2) : vrai si l'API a refusé la facturation parce que l'équipe de service
 * du jour n'est pas désignée (403 `{"detail": "...", "code": "TEAM_NOT_ASSIGNED"}`).
 */
export function isTeamNotAssignedError(err: unknown): boolean {
  if (!axios.isAxiosError(err) || err.response?.status !== 403) return false;
  const data = err.response.data as { code?: unknown } | undefined;
  return data?.code === 'TEAM_NOT_ASSIGNED';
}

/**
 * BUG-196 : vrai si l'API a refusé la désignation de l'équipe parce qu'une fournée d'une
 * journée précédente est encore ouverte (400 `{"detail": "...", "code": "PREVIOUS_WORKDAY_OPEN"}`).
 */
export function isPreviousWorkdayOpenError(err: unknown): boolean {
  if (!axios.isAxiosError(err) || err.response?.status !== 400) return false;
  const data = err.response.data as { code?: unknown } | undefined;
  return data?.code === 'PREVIOUS_WORKDAY_OPEN';
}
