import React from 'react';
import type { Client } from '@/api/services';
import { FiCheckCircle, FiAlertCircle } from 'react-icons/fi';
import type { InvoiceMotif } from './MotifSelect';
import { Modal } from '@/components/shared/Modal';
import { MotifSelect } from './MotifSelect';

export interface RepaymentModalProps {
  selectedClient: Client | null;
  repaymentMotif: InvoiceMotif;
  setRepaymentMotif: React.Dispatch<React.SetStateAction<InvoiceMotif>>;
  allowBackdatedSales: boolean;
  isRepaymentModalOpen: boolean;
  setIsRepaymentModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  repaymentAmount: string;
  setRepaymentAmount: React.Dispatch<React.SetStateAction<string>>;
  repaymentDate: string;
  setRepaymentDate: React.Dispatch<React.SetStateAction<string>>;
  repaymentLoading: boolean;
  repaymentError: string | null;
  workDate: string;
  handleRepaymentSubmit: (e: React.FormEvent) => Promise<void>;
}

export const RepaymentModal: React.FC<RepaymentModalProps> = ({ selectedClient, repaymentMotif, setRepaymentMotif, allowBackdatedSales, isRepaymentModalOpen, setIsRepaymentModalOpen, repaymentAmount, setRepaymentAmount, repaymentDate, setRepaymentDate, repaymentLoading, repaymentError, workDate, handleRepaymentSubmit }) => {
  return (
      <Modal
        isOpen={isRepaymentModalOpen}
        onClose={() => setIsRepaymentModalOpen(false)}
        title="Remboursement / Dépôt sans commande"
        subtitle={selectedClient ? `${selectedClient.code} — ${selectedClient.full_name}` : undefined}
        maxWidth="380px"
      >
        {selectedClient && (
          <form onSubmit={handleRepaymentSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>
              Un même versement couvre deux cas : réduire une dette existante (<strong>remboursement</strong>),
              ou verser plus que la dette pour un <strong>dépôt épargne</strong> (la BP devient alors négative,
              CLAUDE.md §5.1). Ce versement ne correspond à aucune commande de pain.
            </div>
            <div style={{ display: 'flex', gap: '12px', fontSize: '0.72rem' }}>
              <span>BP actuel : <strong style={{ color: parseFloat(selectedClient.current_debt) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{parseFloat(selectedClient.current_debt).toLocaleString('fr-FR')} FC</strong></span>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                Montant versé (FC, négatif = sortie de caisse) *
              </label>
              <input
                type="text"
                inputMode="text"
                pattern="-?[0-9]*"
                autoComplete="off"
                value={repaymentAmount}
                onChange={e => {
                  const raw = e.target.value.replace(/[−–—]/g, '-').replace(/[\s  ]/g, '');
                  if (/^-?\d*$/.test(raw)) setRepaymentAmount(raw);
                }}
                placeholder="Ex: 10000 ou -5000"
                className="form-input"
                style={{ height: '34px', fontSize: '0.84rem', fontWeight: 700 }}
                autoFocus
                required
              />
            </div>
            {repaymentAmount && repaymentAmount !== '-' && parseFloat(repaymentAmount) !== 0 && (
              <div style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.7rem' }}>
                <span style={{ color: 'hsl(var(--text-secondary))' }}>Nouvelle BP après versement : </span>
                <strong style={{ color: (parseFloat(selectedClient.current_debt) - parseFloat(repaymentAmount)) <= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))' }}>
                  {(parseFloat(selectedClient.current_debt) - parseFloat(repaymentAmount)).toLocaleString('fr-FR')} FC
                </strong>
                {(parseFloat(selectedClient.current_debt) - parseFloat(repaymentAmount)) < 0 && (
                  <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>(dépôt épargne — crédit en faveur du client)</span>
                )}
              </div>
            )}
            <MotifSelect value={repaymentMotif} onChange={setRepaymentMotif} />
            {allowBackdatedSales && (
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '2px', textTransform: 'uppercase' }}>
                  Date du versement (optionnel)
                </label>
                <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                  Laisser vide = aujourd'hui. Jamais une date future.
                </span>
                <input
                  type="date"
                  max={workDate}
                  value={repaymentDate}
                  onChange={e => setRepaymentDate(e.target.value)}
                  className="form-input"
                  style={{ fontSize: '0.78rem', height: '30px', padding: '0 8px' }}
                />
              </div>
            )}
            {repaymentError && (
              <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '7px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                <span>{repaymentError}</span>
              </div>
            )}
            <div style={{ display: 'flex', gap: '8px' }}>
              <button type="button" onClick={() => setIsRepaymentModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>
                Annuler
              </button>
              <button type="submit" disabled={repaymentLoading || !repaymentAmount || repaymentAmount === '-'} className="btn btn-primary" style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: repaymentLoading ? 0.7 : 1 }}>
                <FiCheckCircle />
                <span>{repaymentLoading ? 'Enregistrement...' : 'Confirmer le versement'}</span>
              </button>
            </div>
          </form>
        )}
      </Modal>
  );
};
