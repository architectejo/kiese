import React from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import type { ClientItem } from './clientItem';

interface RepaymentModalProps {
  repaymentClient: ClientItem;
  setIsRepaymentModalOpen: (open: boolean) => void;
  handleRepaymentSubmit: (e: React.FormEvent) => void | Promise<void>;
  repaymentAmount: string;
  setRepaymentAmount: (v: string) => void;
  repaymentError: string | null;
  repaymentLoading: boolean;
}

/** Remboursement de dette / dépôt sans commande (facture sans ligne). */
export const RepaymentModal: React.FC<RepaymentModalProps> = ({
  repaymentClient, setIsRepaymentModalOpen, handleRepaymentSubmit, repaymentAmount, setRepaymentAmount,
  repaymentError, repaymentLoading,
}) => {
  return (
        <Modal
          isOpen={true}
          onClose={() => setIsRepaymentModalOpen(false)}
          title="Remboursement / Dépôt sans commande"
          subtitle={repaymentClient.name}
          maxWidth="380px"
        >
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '10px' }}>
              Un même versement couvre deux cas : réduire une dette existante (<strong>remboursement</strong>),
              ou verser pour un <strong>dépôt épargne</strong> même sans dette préalable (la BP devient alors
              négative, CLAUDE.md §5.1). Ce versement ne correspond à aucune commande de pain.
            </div>
            <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', marginBottom: '14px' }}>
              <div style={{ marginTop: '4px', display: 'flex', gap: '12px' }}>
                <span>BP actuel : <strong style={{ color: repaymentClient.outstandingDebt > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{repaymentClient.outstandingDebt.toLocaleString('fr-FR')} FC</strong></span>
              </div>
            </div>
            <form onSubmit={handleRepaymentSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                  Montant versé (FC) *
                </label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={repaymentAmount}
                  onChange={e => setRepaymentAmount(e.target.value)}
                  placeholder="Ex : 10 000"
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.84rem', fontWeight: 700 }}
                  autoFocus
                  required
                />
              </div>
              {repaymentAmount && parseFloat(repaymentAmount) > 0 && (
                <div style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.72rem' }}>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Nouveau BP après versement : </span>
                  <strong style={{ color: (repaymentClient.outstandingDebt - parseFloat(repaymentAmount)) <= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))' }}>
                    {(repaymentClient.outstandingDebt - parseFloat(repaymentAmount)).toLocaleString('fr-FR')} FC
                  </strong>
                  {(repaymentClient.outstandingDebt - parseFloat(repaymentAmount)) < 0 && (
                    <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>(dépôt épargne — crédit en faveur du client)</span>
                  )}
                </div>
              )}
              {repaymentError && (
                <div style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>
                  {repaymentError}
                </div>
              )}
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="button" onClick={() => setIsRepaymentModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>
                  Annuler
                </button>
                <button type="submit" disabled={repaymentLoading || !repaymentAmount} className="btn btn-primary" style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                  <FiCheckCircle />
                  {repaymentLoading ? 'Enregistrement...' : 'Confirmer le versement'}
                </button>
              </div>
            </form>
        </Modal>
  );
};
