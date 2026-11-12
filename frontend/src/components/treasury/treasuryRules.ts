import axios from 'axios';
import { getErrorDetail } from '@/api/errors';

/**
 * BUG-231 / BUG-201 : le serveur borne chaque coupure à 0..100 000 billets
 * (400 `{bills_x: [...]}`). L'écran applique la même borne avant l'envoi ;
 * le serveur reste l'autorité (message affiché tel quel si on l'atteint).
 */
export const MAX_BILLS_PER_DENOMINATION = 100000;

export const BILL_FACES: Record<string, string> = {
  bills_20000: '20 000 FC',
  bills_10000: '10 000 FC',
  bills_5000: '5 000 FC',
  bills_1000: '1 000 FC',
  bills_500: '500 FC',
  bills_200: '200 FC',
  bills_100: '100 FC',
  bills_50: '50 FC',
};

/** Convertit une saisie en nombre entier de billets, jamais négatif (la borne haute est signalée, pas tronquée). */
export const parseBillCount = (raw: string): number => {
  const n = Math.floor(Number(raw));
  return Number.isFinite(n) && n > 0 ? n : 0;
};

/** Renvoie un message en français si une coupure sort de 0..100 000 (entier), sinon null. */
export const validateBillCounts = (bills: Record<string, number>): string | null => {
  for (const [key, count] of Object.entries(bills)) {
    if (!Number.isInteger(count) || count < 0 || count > MAX_BILLS_PER_DENOMINATION) {
      return `Coupure ${BILL_FACES[key] ?? key} : entier entre 0 et ${MAX_BILLS_PER_DENOMINATION.toLocaleString('fr-FR')} billets.`;
    }
  }
  return null;
};

/** Droits d'écriture trésorerie : gérant et au-dessus (miroir de `IsGerant`, appliqué côté serveur). */
export const isGerantOrAbove = (user: { role?: string; is_superuser?: boolean } | null | undefined): boolean =>
  !!user && (!!user.is_superuser || ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(user.role ?? ''));

/** Confirmer / infirmer / inscrire au Livre de Caisse : siège uniquement (le gérant ne confirme pas sa clôture, BUG-200). */
export const canConfirmClosures = (user: { role?: string; is_superuser?: boolean } | null | undefined): boolean =>
  !!user && (!!user.is_superuser || ['ADMIN', 'DIRECTION', 'COMPTABLE'].includes(user.role ?? ''));

/**
 * Message d'erreur d'API ; les erreurs de champ `bills_x` sont libellées par la
 * valeur de la coupure (« Coupure 20 000 FC : … ») au lieu du nom technique.
 */
export const treasuryErrorMessage = (err: unknown, fallback: string): string => {
  if (axios.isAxiosError(err)) {
    const data = err.response?.data as Record<string, unknown> | undefined;
    if (data && typeof data === 'object' && !Array.isArray(data) && typeof data.detail !== 'string') {
      const parts: string[] = [];
      for (const [field, value] of Object.entries(data)) {
        if (!(field in BILL_FACES)) continue;
        const msgs = Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
        if (msgs.length) parts.push(`Coupure ${BILL_FACES[field]} : ${msgs.join(' ')}`);
      }
      if (parts.length) return parts.join(' — ');
    }
    if (err.response?.status === 403 && !(typeof (err.response.data as { detail?: unknown } | undefined)?.detail === 'string')) {
      return "Action réservée à un rôle supérieur (accès refusé).";
    }
  }
  return getErrorDetail(err, fallback);
};

/** Convertit un montant décimal (chaîne API) en centimes entiers : somme sans erreur de flottant. */
export const toCents = (v: string | undefined | null): bigint => {
  const s = String(v ?? '0').trim();
  const m = /^(-?)(\d*)(?:\.(\d*))?$/.exec(s);
  if (!m) return 0n;
  const frac = ((m[3] ?? '') + '00').slice(0, 2);
  const cents = BigInt(m[2] || '0') * 100n + BigInt(frac);
  return m[1] === '-' ? -cents : cents;
};

/** Formate des centimes en `12 500 FC` (sans décimales si entier, 2 sinon). */
export const formatCents = (cents: bigint): string => {
  const neg = cents < 0n;
  const abs = neg ? -cents : cents;
  const whole = (abs / 100n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  const frac = (abs % 100n).toString().padStart(2, '0');
  return `${neg ? '-' : ''}${whole}${frac === '00' ? '' : ',' + frac} FC`;
};

/** Formate directement une chaîne décimale API en `12 500 FC`. */
export const formatDecimalFc = (v: string | undefined | null): string => formatCents(toCents(v));
