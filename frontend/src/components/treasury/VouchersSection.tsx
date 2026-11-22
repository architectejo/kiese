import React, { useState } from 'react';
import { FiDollarSign, FiPlus, FiPrinter } from 'react-icons/fi';
import { treasuryApi } from '@/api/services';
import type { DisbursementVoucher } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { isInvalidBillCount, parseBillCount, validateBillCounts, treasuryErrorMessage } from '@/components/treasury/treasuryRules';
import { BILLS, fmt } from '@/components/treasury/treasuryShared';
import type { BillKey } from '@/components/treasury/treasuryShared';
import { printFinalVoucherReport } from '@/components/treasury/treasuryPrint';
import type { ProgressiveList } from '@/hooks/useProgressiveList';

interface Props {
  today: string;
  dateFrom: string;
  dateTo: string;
  vouchersQ: ProgressiveList<DisbursementVoucher>;
  consolidatedBalance: number;
  consolidatedBalanceReady: boolean;
  /** Erreur de chargement du livre de caisse (solde « indisponible »). */
  balanceError: string | null;
  /** Rechargement du livre de caisse et des bordereaux après création. */
  onCreated: () => void;
}

// §5.1.3b — Bordereaux de Versement (décaissements Direction).
export const VouchersSection: React.FC<Props> = ({
  today, dateFrom, dateTo, vouchersQ, consolidatedBalance, consolidatedBalanceReady, balanceError, onCreated,
}) => {
  const [showVoucherForm, setShowVoucherForm] = useState(false);
  const [voucherMotif, setVoucherMotif] = useState('');
  const [voucherBeneficiary, setVoucherBeneficiary] = useState('');
  const [voucherBills, setVoucherBills] = useState<Record<BillKey, number>>({
    bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0,
    bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0,
  });
  const [voucherError, setVoucherError] = useState<string | null>(null);
  const [voucherSubmitting, setVoucherSubmitting] = useState(false);
  const vouchers = vouchersQ.items;
  const vouchersLoading = vouchersQ.isLoading;
  const voucherBillTotal = BILLS.reduce((sum, b) => sum + voucherBills[b.key] * b.face, 0);

  const handleCreateVoucher = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setVoucherError(null);
    if (!voucherMotif) { setVoucherError('Indiquez le motif du bordereau.'); return; }
    const voucherProblem = validateBillCounts(voucherBills);
    if (voucherProblem) { setVoucherError(voucherProblem); return; }
    if (voucherBillTotal <= 0) { setVoucherError('Saisissez au moins un billet.'); return; }
    setVoucherSubmitting(true);
    try {
      await treasuryApi.vouchers.create({
        date: today, motif: voucherMotif, beneficiary: voucherBeneficiary,
        ...voucherBills,
      });
      setVoucherMotif(''); setVoucherBeneficiary('');
      setVoucherBills({ bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0, bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0 });
      setShowVoucherForm(false);
      onCreated();
    } catch (err: unknown) {
      setVoucherError(treasuryErrorMessage(err, 'Erreur lors de la création du bordereau.'));
    } finally {
      setVoucherSubmitting(false);
    }
  };

  const handleFinalReport = async () => {
    try {
      await printFinalVoucherReport(dateFrom, dateTo);
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Erreur lors de la génération du bordereau final.'));
    }
  };

  return (
        <div className="glass-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
            <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
              Bordereaux de Versement — Décaissements Direction
            </h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button onClick={handleFinalReport} className="btn btn-secondary" style={{ padding: '5px 12px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <FiPrinter /> Générer bordereau final
              </button>
              <button onClick={() => setShowVoucherForm(v => !v)} className="btn btn-primary" style={{ padding: '5px 12px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <FiPlus /> {showVoucherForm ? 'Annuler' : 'Nouveau bordereau'}
              </button>
            </div>
          </div>

          <div style={{ marginBottom: '12px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.75rem', display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: 'hsl(var(--text-secondary))' }}>Solde consolidé disponible (Livre de Caisse)</span>
            {consolidatedBalanceReady ? (
              <strong style={{ color: consolidatedBalance >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(consolidatedBalance)} FC</strong>
            ) : (
              <strong style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>{balanceError ? 'indisponible' : 'chargement…'}</strong>
            )}
          </div>

          {showVoucherForm && (
            <form noValidate onSubmit={handleCreateVoucher} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '14px', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '8px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Motif *</label>
                  <input type="text" value={voucherMotif} onChange={e => setVoucherMotif(e.target.value)} placeholder="Ex: Achat matériel, salaire..." className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', width: '100%' }} required />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Bénéficiaire</label>
                  <input type="text" value={voucherBeneficiary} onChange={e => setVoucherBeneficiary(e.target.value)} placeholder="optionnel" className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', width: '100%' }} />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '5px' }}>Billetage (sortie)</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                  {BILLS.map(b => (
                    <div key={b.key}>
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>{b.label}</div>
                      <input
                        type="number" inputMode="numeric" value={voucherBills[b.key]} aria-invalid={isInvalidBillCount(voucherBills[b.key])}
                        onChange={e => setVoucherBills(prev => ({ ...prev, [b.key]: parseBillCount(e.target.value) }))}
                        className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '100%' }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', padding: '6px 8px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)' }}>
                <span>Total du bordereau</span>
                <strong style={{ color: voucherBillTotal > consolidatedBalance ? 'hsl(var(--color-danger))' : 'hsl(var(--accent-color))' }}>{fmt(voucherBillTotal)} FC</strong>
              </div>
              {consolidatedBalanceReady && voucherBillTotal > consolidatedBalance && (
                <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
                  Montant supérieur au solde disponible — la création sera refusée.
                </div>
              )}

              {voucherError && <div style={{ fontSize: '0.7rem', color: 'hsl(var(--color-danger))' }}>{voucherError}</div>}
              <button type="submit" disabled={voucherSubmitting} className="btn btn-primary" style={{ padding: '7px', fontSize: '0.75rem' }}>
                {voucherSubmitting ? 'Enregistrement...' : 'Enregistrer le bordereau'}
              </button>
            </form>
          )}

          {/* Vouchers list */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {vouchersLoading ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement...</div>
            ) : vouchersQ.error ? (
              <div role="alert" style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--color-danger))', padding: '10px' }}>{vouchersQ.error}</div>
            ) : vouchers.length === 0 ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucun bordereau sur la période.</div>
            ) : (
              vouchers.map(v => (
                <div key={v.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-secondary))' }}>
                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700 }}>{v.motif}{v.beneficiary ? ` — ${v.beneficiary}` : ''}</div>
                    <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>{v.piece_number} · {new Date(v.date).toLocaleDateString('fr-FR')} · {v.created_by_display || '—'}</div>
                  </div>
                  <strong style={{ fontSize: '0.78rem', color: 'hsl(var(--color-danger))' }}>−{fmt(v.physical_cash_total)} FC</strong>
                </div>
              ))
            )}
            {!vouchersQ.isLoading && !vouchersQ.isComplete && !vouchersQ.error && (
              <div style={{ textAlign: 'center', fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>
                {vouchersQ.loaded} / {vouchersQ.total ?? '…'} bordereaux chargés…
              </div>
            )}
          </div>
        </div>
  );
};
