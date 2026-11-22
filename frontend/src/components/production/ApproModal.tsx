import React from 'react';
import { FiAlertTriangle } from 'react-icons/fi';
import type { ConsumableStock } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { STOCK_ICONS, displayStock, isStockInsufficientError } from './productionHelpers';

export interface ApproModalProps {
  stocks: ConsumableStock[];
  showApproModal: boolean;
  setShowApproModal: React.Dispatch<React.SetStateAction<boolean>>;
  approStock: string;
  setApproStock: React.Dispatch<React.SetStateAction<string>>;
  approQty: string;
  setApproQty: React.Dispatch<React.SetStateAction<string>>;
  approPrice: string;
  setApproPrice: React.Dispatch<React.SetStateAction<string>>;
  approDesc: string;
  setApproDesc: React.Dispatch<React.SetStateAction<string>>;
  approSupplier: string;
  setApproSupplier: React.Dispatch<React.SetStateAction<string>>;
  approError: string | null;
  approSaving: boolean;
  handleAppro: (e: React.FormEvent<HTMLFormElement>) => Promise<void>;
}

export const ApproModal: React.FC<ApproModalProps> = ({ stocks, showApproModal, setShowApproModal, approStock, setApproStock, approQty, setApproQty, approPrice, setApproPrice, approDesc, setApproDesc, approSupplier, setApproSupplier, approError, approSaving, handleAppro }) => {
  return (
      <Modal
        isOpen={showApproModal}
        onClose={() => setShowApproModal(false)}
        title="Approvisionnement Consommable"
        maxWidth="420px"
      >
            <form onSubmit={handleAppro} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Consommable *</label>
                <select value={approStock} onChange={e => setApproStock(e.target.value)} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }}>
                  <option value="">— Sélectionner —</option>
                  {stocks.map(s => <option key={s.id} value={s.id}>{STOCK_ICONS[s.consumable_type] || '📦'} {displayStock(s.consumable_type_display || s.consumable_type)} (actuel: {s.quantity} {s.unit})</option>)}
                </select>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Quantité Entrante *</label>
                  <input type="number" step="any" min={0} value={approQty} onChange={e => setApproQty(e.target.value)} placeholder="Ex: 10 ou 10.5" className="form-input" style={{ height: '36px', fontSize: '0.8rem', padding: '0 10px' }} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Prix unitaire (FC) *</label>
                  <input type="number" step="any" min={0} value={approPrice} onChange={e => setApproPrice(e.target.value)} placeholder="Ex: 15000" className="form-input" style={{ height: '36px', fontSize: '0.8rem', padding: '0 10px' }} />
                </div>
              </div>
              {approQty && approPrice && parseFloat(approQty) > 0 && parseFloat(approPrice) > 0 && (
                <div style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', backgroundColor: 'hsl(var(--bg-tertiary))', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                  Coût total : <strong style={{ color: 'hsl(var(--accent-color))' }}>{(parseFloat(approQty) * parseFloat(approPrice)).toLocaleString('fr-FR')} FC</strong>
                </div>
              )}
              {/* Fournisseur — visible only when FLOUR stock is selected */}
              {(() => {
                const sel = stocks.find(s => s.id === approStock);
                return sel?.consumable_type === 'FLOUR' ? (
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Fournisseur Farine</label>
                    <select value={approSupplier} onChange={e => setApproSupplier(e.target.value)} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }}>
                      <option value="">— Non précisé —</option>
                      <option value="MIDEMA">MIDEMA</option>
                      <option value="GMK">GMK</option>
                      <option value="DVS">DVS</option>
                      <option value="LOCAL">Achat local</option>
                    </select>
                  </div>
                ) : null;
              })()}
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Description</label>
                <input type="text" value={approDesc} onChange={e => setApproDesc(e.target.value)} placeholder="Lot, observations..." className="form-input" style={{ height: '36px', fontSize: '0.78rem', padding: '0 10px' }} />
              </div>
              {approError && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                  {isStockInsufficientError(approError) && <FiAlertTriangle style={{ flexShrink: 0 }} />}
                  <span>{approError}</span>
                </div>
              )}
              <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
                <button type="button" onClick={() => setShowApproModal(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>Annuler</button>
                <button type="submit" disabled={approSaving} className="btn btn-primary" style={{ flex: 2, padding: '8px', fontSize: '0.8rem', opacity: approSaving ? 0.6 : 1 }}>{approSaving ? 'Enregistrement...' : "Valider l'Approvisionnement"}</button>
              </div>
            </form>
      </Modal>
  );
};
