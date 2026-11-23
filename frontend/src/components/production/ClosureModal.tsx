import React, { useEffect, useMemo, useState } from 'react';
import { FiLock, FiCheckCircle } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import { getErrorDetail } from '@/api/errors';
import {
  coreApi, productionApi, BreadDisposal, BreadPrice, ProductionSession, ServiceTeam, TeamAssignment,
} from '@/api/services';
import { DISPOSAL_LABELS } from './productionHelpers';

// BUG-973 (remarque.md demande 3) : boîte de clôture du gérant à l'heure de clôture.
// Montée UNE SEULE fois par `DashboardLayout` (comme la boîte « stock de départ »). Elle reprend les
// champs de « Production & Stocks » §3.4 « Réconciliation & Pains Non Valorisés » : mêmes types de
// sortie (`DISPOSAL_LABELS`) et même API (`productionApi.disposals.create`), une saisie par catégorie
// de pain. Le gérant garde ou change l'équipe (A/B) via `productionApi.teamAssignment`.

type ClosureDisposalType = Extract<BreadDisposal['disposal_type'], 'UNSOLD' | 'DECLASSED' | 'FREE_DIST'>;
const CLOSURE_TYPES: ClosureDisposalType[] = ['UNSOLD', 'DECLASSED', 'FREE_DIST'];
const SHORT_LABELS: Record<ClosureDisposalType, string> = {
  UNSOLD: 'Non vendus (NV)',
  DECLASSED: 'Déclassés',
  FREE_DIST: 'Sorties gratuites',
};

type Draft = Record<string, string>; // clé `${bread_price}:${type}` -> chiffres
const keyOf = (bp: number, type: ClosureDisposalType) => `${bp}:${type}`;

export interface ClosureModalProps {
  /** Jour de clôture (AAAA-MM-JJ) fourni par `closure-status`. */
  closureDate: string;
  closureHour: string | null;
  /** Reporte la boîte (la bannière de blocage reste affichée). */
  onLater: () => void;
  /** Saisie envoyée : la boîte se ferme jusqu'à la validation par la direction. */
  onDone: () => void;
}

export const ClosureModal: React.FC<ClosureModalProps> = ({ closureDate, closureHour, onLater, onDone }) => {
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
  const [sessions, setSessions] = useState<ProductionSession[]>([]);
  const [assignment, setAssignment] = useState<TeamAssignment | null>(null);
  const [team, setTeam] = useState<ServiceTeam | null>(null);
  const [draft, setDraft] = useState<Draft>({});
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      setLoadError(null);
      try {
        const [prices, sess] = await Promise.all([
          coreApi.breadPrices.list(),
          productionApi.sessions.list({ date: closureDate }),
        ]);
        if (cancelled) return;
        setBreadPrices(prices.data.filter(b => b.is_active));
        setSessions(sess.data);
        // Désignation d'équipe : disponible seulement en rotation de 24 h (sinon la section est masquée).
        try {
          const { data } = await productionApi.teamAssignment.get();
          if (!cancelled) { setAssignment(data); setTeam(data.team ?? data.suggested); }
        } catch {
          if (!cancelled) setAssignment(null);
        }
      } catch (err: unknown) {
        if (!cancelled) setLoadError(getErrorDetail(err, 'Impossible de charger les catégories de pains.'));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [closureDate]);

  // Fournée de rattachement : la dernière du jour de clôture (le serveur exige une session).
  const targetSession = useMemo(
    () => [...sessions].sort((a, b) => String(b.created_at ?? '').localeCompare(String(a.created_at ?? '')))[0] ?? null,
    [sessions],
  );

  const setCell = (k: string, raw: string) =>
    setDraft(d => ({ ...d, [k]: raw.replace(/\D/g, '').replace(/^0+(?=\d)/, '') }));

  const entries = Object.entries(draft).filter(([, v]) => v !== '' && Number(v) > 0);

  const submit = async () => {
    setError(null);
    if (entries.length > 0 && !targetSession) {
      setError("Aucune fournée enregistrée pour ce jour : impossible de rattacher les sorties non valorisées.");
      return;
    }
    setSubmitting(true);
    try {
      for (const [k, v] of entries) {
        const [bp, type] = k.split(':') as [string, ClosureDisposalType];
        await productionApi.disposals.create({
          session: targetSession?.id,
          bread_price: Number(bp),
          disposal_type: type,
          quantity: Number(v),
          unit_price_sold: '0',
          notes: 'Clôture du jour',
        });
        // Une ligne envoyée n'est jamais renvoyée en cas de nouvel essai (évite les doublons).
        setDraft(d => ({ ...d, [k]: '' }));
      }
      if (assignment && team && team !== assignment.team) {
        await productionApi.teamAssignment.set(team);
      }
      onDone();
    } catch (err: unknown) {
      setError(getErrorDetail(err, "Impossible d'enregistrer la clôture."));
    } finally {
      setSubmitting(false);
    }
  };

  const cellStyle: React.CSSProperties = { height: '44px', fontSize: '1rem', textAlign: 'center', width: '100%', minWidth: '64px' };

  return (
    <Modal
      isOpen={true}
      onClose={onLater}
      title="Clôture de la journée"
      subtitle={`Heure de clôture${closureHour ? ` : ${closureHour.replace(':', 'h')}` : ''} — saisissez les sorties non valorisées`}
      maxWidth="640px"
      closeOnBackdropClick={false}
      footer={
        <>
          <button type="button" className="btn btn-secondary" onClick={onLater} disabled={submitting}
            style={{ minHeight: '46px', padding: '10px 16px', fontSize: '0.9rem' }}>
            Plus tard
          </button>
          <button type="button" className="btn btn-primary" onClick={submit} disabled={submitting || loading || !!loadError}
            style={{ flex: 1, minHeight: '46px', padding: '10px', fontSize: '0.9rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}>
            <FiCheckCircle />
            {submitting ? 'Enregistrement...' : 'Valider la clôture'}
          </button>
        </>
      }
    >
      <p style={{ display: 'flex', gap: '8px', alignItems: 'flex-start', fontSize: '0.8rem', lineHeight: 1.4, color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
        <FiLock style={{ flexShrink: 0, marginTop: '2px' }} />
        <span>Les ventes sont bloquées jusqu'à la validation de la clôture par la direction. Laissez vide ce qui ne concerne pas votre journée.</span>
      </p>

      {loading && <p role="status" style={{ fontSize: '0.85rem' }}>Chargement...</p>}
      {loadError && <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.85rem' }}>{loadError}</div>}

      {!loading && !loadError && (
        <>
          <h3 style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: '8px' }}>Pains non valorisés (quantité par catégorie)</h3>
          {breadPrices.length === 0 ? (
            <p style={{ fontSize: '0.8rem', fontStyle: 'italic', color: 'hsl(var(--text-muted))' }}>Aucune catégorie de pain active.</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.8rem' }}>
                <thead>
                  <tr>
                    <th style={{ textAlign: 'left', padding: '4px 6px' }}>Catégorie</th>
                    {CLOSURE_TYPES.map(t => (
                      <th key={t} title={DISPOSAL_LABELS[t]} style={{ padding: '4px 6px', fontSize: '0.7rem' }}>{SHORT_LABELS[t]}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {breadPrices.map(bp => (
                    <tr key={bp.id}>
                      <td style={{ padding: '4px 6px', fontWeight: 700 }}>{bp.label}</td>
                      {CLOSURE_TYPES.map(t => (
                        <td key={t} style={{ padding: '4px 6px' }}>
                          <input
                            type="text" inputMode="numeric" className="form-input" placeholder="0"
                            aria-label={`${bp.label} — ${SHORT_LABELS[t]}`}
                            value={draft[keyOf(bp.id, t)] ?? ''}
                            onChange={e => setCell(keyOf(bp.id, t), e.target.value)}
                            style={cellStyle}
                          />
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
          {!targetSession && (
            <p style={{ fontSize: '0.72rem', color: 'hsl(var(--color-warning))', marginTop: '6px' }}>
              Aucune fournée enregistrée pour le {closureDate.split('-').reverse().join('/')} : les sorties ne peuvent pas être rattachées.
            </p>
          )}

          {assignment && (
            <div style={{ marginTop: '16px' }}>
              <h3 style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: '8px' }}>Équipe de service</h3>
              <div style={{ display: 'flex', gap: '10px' }}>
                {(['A', 'B'] as ServiceTeam[]).map(t => {
                  const active = team === t;
                  return (
                    <button key={t} type="button" aria-pressed={active} onClick={() => setTeam(t)} disabled={submitting}
                      style={{
                        flex: 1, minHeight: '56px', fontSize: '1.1rem', fontWeight: 800, cursor: 'pointer',
                        borderRadius: 'var(--radius-md)',
                        border: `2px solid ${active ? 'hsl(var(--accent-color))' : 'hsl(var(--border-color))'}`,
                        backgroundColor: active ? 'hsl(var(--accent-glow))' : 'hsl(var(--bg-tertiary))',
                        color: active ? 'hsl(var(--accent-color))' : 'hsl(var(--text-primary))',
                      }}>
                      Équipe {t}{assignment.team === t ? ' (actuelle)' : ''}
                    </button>
                  );
                })}
              </div>
            </div>
          )}
        </>
      )}

      {error && (
        <div role="alert" style={{
          marginTop: '12px', fontSize: '0.8rem', color: 'hsl(var(--color-danger))',
          backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)',
          padding: '10px', borderRadius: 'var(--radius-sm)',
        }}>{error}</div>
      )}
    </Modal>
  );
};
