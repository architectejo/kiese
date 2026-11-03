import { describe, expect, it } from 'vitest';
import { AxiosError, type InternalAxiosRequestConfig } from 'axios';
import { getErrorDetail } from './errors';

/**
 * Construit une erreur axios minimale, telle que reçue dans un
 * `catch (err: unknown)` de page du dashboard (voir `src/api/client.ts`).
 */
function makeAxiosError(data: unknown, status = 400): AxiosError {
  const err = new AxiosError('Request failed');
  err.response = {
    data,
    status,
    statusText: 'Bad Request',
    headers: {},
    // `config` n'est pas lu par `getErrorDetail`, un objet vide suffit.
    config: {} as InternalAxiosRequestConfig,
  };
  return err;
}

describe('getErrorDetail', () => {
  it('renvoie la clé "detail" quand le serveur la fournit (@action personnalisée)', () => {
    const err = makeAxiosError({ detail: 'Plafond de crédit dépassé.' });
    expect(getErrorDetail(err, 'Erreur.')).toBe('Plafond de crédit dépassé.');
  });

  // BUG-127 : ModelViewSet.create() DRF renvoie {"<champ>": ["<message>"]} sans
  // clé "detail" — getErrorDetail ne doit plus retomber sur le fallback générique.
  it('BUG-127 — construit un message lisible à partir des erreurs de champ DRF sans clé "detail"', () => {
    const err = makeAxiosError({ from_node: ['Ce champ est obligatoire.'] });
    const message = getErrorDetail(err, 'Erreur.');
    expect(message).not.toBe('Erreur.');
    expect(message).toContain('from_node');
    expect(message).toContain('Ce champ est obligatoire.');
  });

  it('BUG-127 — combine plusieurs champs en erreur dans un seul message', () => {
    const err = makeAxiosError({
      session: ['Ce champ est obligatoire.'],
      quantity: ['Assurez-vous que cette valeur est supérieure à 0.'],
    });
    const message = getErrorDetail(err, 'Erreur.');
    expect(message).toContain('session');
    expect(message).toContain('quantity');
    expect(message).toContain('Ce champ est obligatoire.');
    expect(message).toContain('supérieure à 0');
  });

  it('retombe sur le fallback générique si ni "detail" ni champ exploitable ne sont présents', () => {
    const err = makeAxiosError({});
    expect(getErrorDetail(err, 'Erreur.')).toBe('Erreur.');
  });

  it('retombe sur le fallback générique pour une erreur non-axios sans message', () => {
    expect(getErrorDetail('quelque chose', 'Erreur.')).toBe('Erreur.');
  });

  it("utilise le message d'une Error native quand ce n'est pas une erreur axios", () => {
    expect(getErrorDetail(new Error('Erreur réseau'), 'Erreur.')).toBe('Erreur réseau');
  });
});
