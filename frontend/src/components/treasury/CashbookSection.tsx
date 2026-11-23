import React, { useState } from 'react';
import { FiBook, FiRefreshCw, FiAlertTriangle, FiCheckCircle, FiLock } from 'react-icons/fi';
import { treasuryApi } from '@/api/services';
import type { CashbookEntry } from '@/api/services';
import { fmt, progressLabel } from '@/components/treasury/treasuryShared';
import { DirectionCashCountSection } from '@/components/treasury/DirectionCashCountSection';
import { useAuthStore } from '@/store/authStore';
import type { ProgressiveList } from '@/hooks/useProgressiveList';

interface Props {
  today: string;
  dateFrom: string;
  dateTo: string;
  onDateFromChange: (v: string) => void;
  onDateToChange: (v: string) => void;
  cashbookQ: ProgressiveList<CashbookEntry>;
  /** Rechargement (filtre de dates). */
  onFilter: () => void;
  onSelectEntry: (entry: CashbookEntry) => void;
}

// §5.1.3 — Niveau 3 : livre de caisse direction (lecture seule, chaîne SHA-256) + comptage physique.
export const CashbookSection: React.FC<Props> = ({
  today, dateFrom, dateTo, onDateFromChange, onDateToChange, cashbookQ, onFilter, onSelectEntry,
}) => {
  const { user } = useAuthStore();
  const [integrityResult, setIntegrityResult] = useState<{chain_valid: boolean; tampered_count: number} | null>(null);
  const [checkingIntegrity, setCheckingIntegrity] = useState(false);
  const cashbook = cashbookQ.items;
  const reloadCashbook = cashbookQ.reload;

  const handleIntegrityCheck = async () => {
    setCheckingIntegrity(true);
    try {
      const res = await treasuryApi.cashbook.integrityCheck();
      setIntegrityResult(res.data);
    } catch (err) {
      console.error('Integrity check failed', err);
    } finally {
      setCheckingIntegrity(false);
    }
  };

  return (
      <div className="glass-card" style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiBook style={{ color: 'hsl(var(--accent-color))' }} />
            §5.1.3 — Livre de Caisse Direction (Grand Livre Immuable)
          </h2>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.7rem', flexWrap: 'wrap' }}>
              <label style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Du</label>
              <input type="date" value={dateFrom} onChange={e => onDateFromChange(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px' }} />
              <label style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Au</label>
              <input type="date" value={dateTo} onChange={e => onDateToChange(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px' }} />
              <button onClick={onFilter} className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.68rem' }}>Filtrer</button>
            </div>
            {user?.can_access_all_nodes && (
              <button
                onClick={handleIntegrityCheck}
                disabled={checkingIntegrity}
                className={`btn ${integrityResult ? (integrityResult.chain_valid ? 'btn-secondary' : 'btn-danger') : 'btn-secondary'}`}
                style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
              >
                <FiLock />
                {checkingIntegrity ? 'Vérification...' : 'Vérifier Intégrité SHA-256'}
              </button>
            )}
          </div>
        </div>

        {/* Integrity result */}
        {integrityResult && (
          <div style={{ marginBottom: '12px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: `1px solid hsl(var(--${integrityResult.chain_valid ? 'color-success' : 'color-danger'}) / 0.4)`, backgroundColor: `hsl(var(--${integrityResult.chain_valid ? 'color-success' : 'color-danger'}) / 0.06)`, fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            {integrityResult.chain_valid ? <FiCheckCircle style={{ color: 'hsl(var(--color-success))' }} /> : <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
            <span style={{ fontWeight: 700, color: integrityResult.chain_valid ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
              {integrityResult.chain_valid ? 'Chaîne intègre — Aucune altération détectée' : `ALTÉRATIONS DÉTECTÉES — ${integrityResult.tampered_count} écriture(s) compromise(s)`}
            </span>
          </div>
        )}

        {/* Cashbook table — §5.1.3 structure */}
        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                <th style={{ textAlign: 'center', width: '90px' }}>Date</th>
                <th style={{ width: '110px' }}>N° Pièce</th>
                <th style={{ width: '70px' }}>Imputation</th>
                <th>Libellés (Origine / Nature)</th>
                <th style={{ textAlign: 'right', width: '110px' }}>Entrée FC</th>
                <th style={{ textAlign: 'right', width: '110px' }}>Sortie FC</th>
                <th style={{ textAlign: 'right', width: '120px' }}>Solde Consolidé FC</th>
                <th style={{ textAlign: 'center', width: '50px' }}>Intégrité</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.7rem' }}>
              {cashbook.map(entry => (
                <tr key={entry.id} onClick={() => onSelectEntry(entry)} style={{ backgroundColor: entry.is_tampered ? 'hsl(var(--color-danger) / 0.08)' : 'transparent', cursor: 'pointer' }}>
                  <td style={{ textAlign: 'center', color: 'hsl(var(--text-secondary))', fontFamily: 'monospace', fontSize: '0.65rem' }}>
                    {new Date(entry.date).toLocaleDateString('fr-FR')}
                  </td>
                  <td style={{ fontWeight: 700, color: 'hsl(var(--accent-color))', fontSize: '0.65rem', fontFamily: 'monospace' }}>
                    {entry.piece_number}
                  </td>
                  <td style={{ color: 'hsl(var(--text-muted))', fontSize: '0.62rem', fontFamily: 'monospace' }}>
                    {entry.imputation || '—'}
                  </td>
                  <td style={{ color: 'hsl(var(--text-primary))', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {entry.is_correction && (
                      <span
                        className="badge badge-warning"
                        title={`Écriture de correction${entry.correction_reason ? ` — ${entry.correction_reason}` : ''}`}
                        style={{ fontSize: '0.52rem', marginRight: '6px', display: 'inline-flex', alignItems: 'center', gap: '3px' }}
                      >
                        <FiRefreshCw style={{ fontSize: '0.6rem' }} /> Correction
                      </span>
                    )}
                    <span title={entry.label}>{entry.label}</span>
                    {entry.node_display && (
                      <span style={{ marginLeft: '6px', fontSize: '0.58rem', color: 'hsl(var(--text-muted))' }}>({entry.node_display})</span>
                    )}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 800, color: parseFloat(entry.entry_amount) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))' }}>
                    {parseFloat(entry.entry_amount) > 0 ? `${fmt(entry.entry_amount)}` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 800, color: parseFloat(entry.exit_amount) > 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))' }}>
                    {parseFloat(entry.exit_amount) > 0 ? `${fmt(entry.exit_amount)}` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 800, color: parseFloat(entry.running_balance) >= 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--color-danger))' }}>
                    {fmt(entry.running_balance)}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    {entry.is_tampered ? (
                      <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', fontSize: '0.85rem' }} title="ALTÉRÉ !" />
                    ) : (
                      <FiLock style={{ color: 'hsl(var(--color-success))', fontSize: '0.75rem', opacity: 0.6 }} title="Intègre" />
                    )}
                  </td>
                </tr>
              ))}
              {cashbookQ.isLoading && (
                <tr><td colSpan={8} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))', fontSize: '0.75rem' }}>Chargement du livre de caisse…</td></tr>
              )}
              {cashbookQ.error && (
                <tr><td colSpan={8} role="alert" style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--color-danger))', fontSize: '0.72rem' }}>
                  {cashbookQ.error}{' '}
                  <button onClick={reloadCashbook} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
                </td></tr>
              )}
              {cashbook.length === 0 && !cashbookQ.isLoading && !cashbookQ.error && (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.75rem' }}>
                    <FiBook style={{ fontSize: '1.8rem', opacity: 0.2, display: 'block', margin: '0 auto 8px' }} />
                    Aucune écriture dans le Livre de Caisse pour cette période.
                    <br />Pousser des clôtures validées pour alimenter le grand livre.
                  </td>
                </tr>
              )}
            </tbody>
            {cashbook.length > 0 && (
              <tfoot>
                <tr style={{ fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.72rem' }}>
                  <td colSpan={4} style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>TOTAUX PÉRIODE</td>
                  {cashbookQ.isComplete ? (
                    <>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                        {fmt(cashbook.reduce((a, e) => a + parseFloat(e.entry_amount || '0'), 0))} FC
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>
                        {fmt(cashbook.reduce((a, e) => a + parseFloat(e.exit_amount || '0'), 0))} FC
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--accent-color))' }}>
                        {fmt(cashbook[cashbook.length - 1].running_balance)} FC
                      </td>
                    </>
                  ) : (
                    <td colSpan={3} style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progressLabel(cashbookQ)}</td>
                  )}
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>

        {!cashbookQ.isLoading && !cashbookQ.isComplete && !cashbookQ.error && (
          <div style={{ marginTop: '6px', fontSize: '0.65rem', color: 'hsl(var(--text-muted))', textAlign: 'center' }} aria-live="polite">
            {cashbookQ.loaded} / {cashbookQ.total ?? '…'} écritures chargées — totaux de la période en cours de calcul…
          </div>
        )}

        <DirectionCashCountSection today={today} dateFrom={dateFrom} dateTo={dateTo} />
      </div>
  );
};
