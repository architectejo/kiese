import React from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import type { BreadPrice, Invoice } from '@/api/services';

interface AdjustInvoiceModalProps {
  adjustTarget: Invoice;
  setIsAdjustModalOpen: (open: boolean) => void;
  setAdjustTarget: (inv: Invoice | null) => void;
  adjustSign: 1 | -1;
  setAdjustSign: (s: 1 | -1) => void;
  handleAdjustSubmit: (e: React.FormEvent) => void | Promise<void>;
  breadPrices: BreadPrice[];
  adjustQtys: Record<number, number>;
  setAdjustQtys: React.Dispatch<React.SetStateAction<Record<number, number>>>;
  adjustPaymentAmount: string;
  setAdjustPaymentAmount: (v: string) => void;
  allowBackdatedSales: boolean;
  adjustDate: string;
  setAdjustDate: (v: string) => void;
  adjustError: string | null;
  adjustLoading: boolean;
}

/** Ajustement d'une facture existante (BUG-109, réservé GERANT et supérieurs). */
export const AdjustInvoiceModal: React.FC<AdjustInvoiceModalProps> = ({
  adjustTarget, setIsAdjustModalOpen, setAdjustTarget, adjustSign, setAdjustSign, handleAdjustSubmit,
  breadPrices, adjustQtys, setAdjustQtys, adjustPaymentAmount, setAdjustPaymentAmount, allowBackdatedSales,
  adjustDate, setAdjustDate, adjustError, adjustLoading,
}) => {
  return (
        <Modal
          isOpen={true}
          onClose={() => { setIsAdjustModalOpen(false); setAdjustTarget(null); }}
          title="Ajuster une commande"
          subtitle={`Facture ${adjustTarget.receipt_number}`}
          maxWidth="480px"
        >
          <div style={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: '2px' }}>
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '10px' }}>
              Corrige ou annule une commande déjà enregistrée. La facture d'origine n'est
              jamais modifiée : une nouvelle facture d'ajustement, liée, est créée (« grande
              trace »). Si la commission de la période d'origine est déjà clôturée, la
              Direction/le Comptable en sera averti automatiquement — l'ajustement n'est pas
              bloqué pour autant.
            </div>

            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
              <button
                type="button"
                onClick={() => setAdjustSign(1)}
                className={adjustSign === 1 ? 'btn btn-primary' : 'btn btn-secondary'}
                style={{ flex: 1, padding: '8px', fontSize: '0.78rem', fontWeight: 700 }}
              >
                + Augmentation
              </button>
              <button
                type="button"
                onClick={() => setAdjustSign(-1)}
                className={adjustSign === -1 ? 'btn btn-primary' : 'btn btn-secondary'}
                style={{ flex: 1, padding: '8px', fontSize: '0.78rem', fontWeight: 700 }}
              >
                − Diminution
              </button>
            </div>

            <form onSubmit={handleAdjustSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>
                  Ampleur du changement, par catégorie de pain (quantité, toujours positive) *
                </label>
                {breadPrices.length === 0 ? (
                  <p style={{ fontSize: '0.72rem', color: 'hsl(var(--text-muted))' }}>Aucune catégorie de pain active.</p>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(breadPrices.length, 3)}, 1fr)`, gap: '8px' }}>
                    {breadPrices.map(bp => (
                      <div key={bp.id} style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <label style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>{bp.label}</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={adjustQtys[bp.id] || ''}
                          onChange={e => setAdjustQtys(prev => ({ ...prev, [bp.id]: parseInt(e.target.value, 10) || 0 }))}
                          className="form-input"
                          style={{ height: '32px', fontSize: '0.78rem', fontWeight: 700 }}
                          placeholder="0"
                        />
                        {(adjustQtys[bp.id] || 0) > 0 && (
                          <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>
                            {(adjustQtys[bp.id] * bp.unit_price).toLocaleString('fr-FR')} FC
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                  Versement associé (FC)
                </label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={adjustPaymentAmount}
                  onChange={e => setAdjustPaymentAmount(e.target.value)}
                  placeholder="0"
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.84rem', fontWeight: 700 }}
                />
              </div>

              {allowBackdatedSales && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                    Date de l'ajustement (optionnel — vide = aujourd'hui)
                  </label>
                  <input
                    type="date"
                    value={adjustDate}
                    onChange={e => setAdjustDate(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.78rem' }}
                  />
                </div>
              )}

              {adjustError && (
                <div style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>
                  {adjustError}
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  type="button"
                  onClick={() => { setIsAdjustModalOpen(false); setAdjustTarget(null); }}
                  className="btn btn-secondary"
                  style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={adjustLoading}
                  className="btn btn-primary"
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                >
                  <FiCheckCircle />
                  {adjustLoading ? 'Enregistrement...' : "Confirmer l'ajustement"}
                </button>
              </div>
            </form>
          </div>
        </Modal>
  );
};
