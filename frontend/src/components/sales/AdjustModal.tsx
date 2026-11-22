import React from 'react';
import type { BreadPrice } from '@/api/services';
import { FiCheckCircle, FiAlertCircle } from 'react-icons/fi';
import type { QueueItem } from './salesTypes';
import { Modal } from '@/components/shared/Modal';

export interface AdjustModalProps {
  breadPrices: BreadPrice[];
  allowBackdatedSales: boolean;
  isAdjustModalOpen: boolean;
  setIsAdjustModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  adjustTarget: QueueItem | null;
  setAdjustTarget: React.Dispatch<React.SetStateAction<QueueItem | null>>;
  adjustSign: 1 | -1;
  setAdjustSign: React.Dispatch<React.SetStateAction<1 | -1>>;
  adjustQtys: Record<number, number>;
  setAdjustQtys: React.Dispatch<React.SetStateAction<Record<number, number>>>;
  adjustPaymentAmount: string;
  setAdjustPaymentAmount: React.Dispatch<React.SetStateAction<string>>;
  adjustDate: string;
  setAdjustDate: React.Dispatch<React.SetStateAction<string>>;
  adjustLoading: boolean;
  adjustError: string | null;
  workDate: string;
  handleAdjustSubmit: (e: React.FormEvent) => Promise<void>;
}

export const AdjustModal: React.FC<AdjustModalProps> = ({ breadPrices, allowBackdatedSales, isAdjustModalOpen, setIsAdjustModalOpen, adjustTarget, setAdjustTarget, adjustSign, setAdjustSign, adjustQtys, setAdjustQtys, adjustPaymentAmount, setAdjustPaymentAmount, adjustDate, setAdjustDate, adjustLoading, adjustError, workDate, handleAdjustSubmit }) => {
  return (
      <Modal
        isOpen={isAdjustModalOpen}
        onClose={() => { setIsAdjustModalOpen(false); setAdjustTarget(null); }}
        title="Ajuster une commande"
        subtitle={adjustTarget ? `Facture ${adjustTarget.id} — ${adjustTarget.clientName}` : undefined}
        maxWidth="480px"
      >
        {adjustTarget && (
          <div style={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: '2px' }}>
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '10px' }}>
              Corrige ou annule une commande déjà enregistrée. La facture d'origine n'est jamais
              modifiée : une nouvelle facture d'ajustement, liée, est créée (« grande trace »). Si
              la commission de la période d'origine est déjà clôturée, la Direction/le Comptable en
              sera averti automatiquement — l'ajustement n'est pas bloqué pour autant.
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
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Date de l'ajustement (optionnel)
                  </label>
                  <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                    Laisser vide = aujourd'hui. Jamais une date future.
                  </span>
                  <input
                    type="date"
                    max={workDate}
                    value={adjustDate}
                    onChange={e => setAdjustDate(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.78rem', padding: '0 8px' }}
                  />
                </div>
              )}

              {adjustError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '7px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                  <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                  <span>{adjustError}</span>
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
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: adjustLoading ? 0.7 : 1 }}
                >
                  <FiCheckCircle />
                  <span>{adjustLoading ? 'Enregistrement...' : "Confirmer l'ajustement"}</span>
                </button>
              </div>
            </form>
          </div>
        )}
      </Modal>
  );
};
