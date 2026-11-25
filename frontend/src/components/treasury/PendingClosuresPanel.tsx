import React, { useMemo } from 'react';
import { FiAlertTriangle, FiCheckCircle, FiRefreshCw } from 'react-icons/fi';
import { treasuryApi } from '@/api/services';
import type { CashClosure } from '@/api/services';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { PAGE_SIZE, fmt, progressLabel } from '@/components/treasury/treasuryShared';
import { formatDayFr, pendingValidationClosures } from '@/utils/closureDay';

interface Props {
  /** Filtre de succursale de la page (vide = toutes). */
  nodeFilter: string;
  /** Change => relecture (après confirmation / infirmation / création). */
  refreshKey: number;
  /** Ouvre la fiche existante (`ClosureDetailModal`) qui porte les boutons Confirmer / Infirmer. */
  onOpenDetail: (closure: CashClosure) => void;
}

/**
 * BUG-1304 (volet valideurs) : depuis la journée de midi à midi (Q-018), la clôture à confirmer est
 * celle de la journée TERMINÉE (souvent la veille) : elle n'apparaît pas dans « Clôtures du Jour »
 * (journée en cours). Cette file liste TOUTES les clôtures non confirmées et non infirmées, quelle
 * que soit leur date (`GET /api/treasury/closures/?is_validated=false`, filtre serveur existant).
 * Réservée aux rôles qui confirment (ADMIN / DIRECTION / COMPTABLE) : le parent décide.
 */
export const PendingClosuresPanel: React.FC<Props> = ({ nodeFilter, refreshKey, onOpenDetail }) => {
  const q = useProgressiveList<CashClosure>({
    fetchPage: p => treasuryApi.closures.page({
      is_validated: 'false',
      ...(nodeFilter ? { node: nodeFilter } : {}),
      page: String(p),
      page_size: PAGE_SIZE,
    }),
    resetKey: `pending|${nodeFilter}|${refreshKey}`,
  });
  // Les clôtures infirmées (aussi `is_validated=false`) attendent la correction du gérant : exclues.
  const pending = useMemo(() => pendingValidationClosures(q.items), [q.items]);

  return (
    <div
      className="glass-card"
      style={{ padding: '14px', border: pending.length > 0 ? '1px solid hsl(var(--color-warning) / 0.45)' : undefined }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px', marginBottom: '10px' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
          <FiAlertTriangle style={{ color: 'hsl(var(--color-warning))' }} />
          Clôtures en attente de validation
          {!q.isLoading && !q.error && (
            <span className={`badge ${pending.length > 0 ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.6rem' }}>
              {pending.length}
            </span>
          )}
        </h2>
        <button
          type="button"
          onClick={q.reload}
          disabled={q.isLoading}
          className="btn btn-secondary"
          style={{ minHeight: '32px', padding: '4px 10px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px' }}
        >
          <FiRefreshCw style={{ animation: q.isLoading ? 'spin 1s linear infinite' : 'none' }} /> Actualiser
        </button>
      </div>

      {q.isLoading ? (
        <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>
          Chargement des clôtures en attente…
        </div>
      ) : q.error ? (
        <div role="alert" style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--color-danger))', padding: '10px' }}>
          {q.error}
        </div>
      ) : pending.length === 0 ? (
        <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--color-success))', padding: '10px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
          <FiCheckCircle /> Aucune clôture en attente de validation.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
          {pending.map(c => {
            const gap = parseFloat(c.cash_gap || '0');
            return (
              <div
                key={c.id}
                style={{
                  display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: '8px',
                  padding: '8px 10px', borderRadius: 'var(--radius-sm)',
                  border: '1px solid hsl(var(--border-color) / 0.5)', backgroundColor: 'hsl(var(--bg-secondary))',
                }}
              >
                <div style={{ minWidth: 0, flex: '1 1 200px', fontSize: '0.72rem' }}>
                  <div>
                    <strong>{c.node_display || c.node}</strong>
                    <span style={{ marginLeft: '6px' }}>journée du {formatDayFr(c.date)}</span>
                    {c.gerant_display && (
                      <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>· {c.gerant_display}</span>
                    )}
                  </div>
                  <div style={{ fontSize: '0.66rem', color: 'hsl(var(--text-secondary))', marginTop: '2px' }}>
                    Espèces physiques : <strong>{fmt(c.physical_cash_total)} FC</strong> · Écart :{' '}
                    <strong style={{ color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                      {gap > 0 ? '+' : ''}{fmt(c.cash_gap)} FC
                    </strong>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => onOpenDetail(c)}
                  className="btn btn-primary"
                  style={{ minHeight: '36px', padding: '6px 12px', fontSize: '0.72rem' }}
                >
                  Confirmer / infirmer
                </button>
              </div>
            );
          })}
          {!q.isComplete && (
            <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', textAlign: 'center' }}>
              {progressLabel(q)}
            </div>
          )}
        </div>
      )}
    </div>
  );
};
