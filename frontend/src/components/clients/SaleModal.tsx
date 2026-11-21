import React from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import type { BreadPrice } from '@/api/services';
import { ClientItem, effectiveUnitPrice } from './clientItem';

interface SaleModalProps {
  isSaleModalOpen: boolean;
  setIsSaleModalOpen: (open: boolean) => void;
  saleClient: ClientItem | null;
  debtCeiling: number;
  breadPrices: BreadPrice[];
  saleQtys: Record<number, number>;
  setSaleQtys: React.Dispatch<React.SetStateAction<Record<number, number>>>;
  venteSoldee: boolean;
  setVenteSoldee: (v: boolean) => void;
  sansCommission: boolean;
  setSansCommission: (v: boolean) => void;
  versementJour: string;
  setVersementJour: (v: string) => void;
  isSubmitting: boolean;
  handleSaleSubmit: (e: React.FormEvent) => void | Promise<void>;
  isCasualSale: boolean;
  allowBackdatedSales: boolean;
  workDate: string;
  orderDate: string;
  setOrderDate: (v: string) => void;
  saleError: string | null;
}

/** Enregistrement d'une commande (facture) pour un client ou une vente occasionnelle. */
export const SaleModal: React.FC<SaleModalProps> = ({
  isSaleModalOpen, setIsSaleModalOpen, saleClient, debtCeiling, breadPrices, saleQtys, setSaleQtys,
  venteSoldee, setVenteSoldee, sansCommission, setSansCommission, versementJour, setVersementJour,
  isSubmitting, handleSaleSubmit, isCasualSale, allowBackdatedSales, workDate, orderDate, setOrderDate, saleError,
}) => {
  return (
      <Modal
        isOpen={isSaleModalOpen && !!saleClient}
        onClose={() => setIsSaleModalOpen(false)}
        title="Enregistrer commande"
        maxWidth="520px"
        footer={saleClient && (() => {
          const cl = saleClient.creditLimit || debtCeiling;
          // BUG-107 : aperçu avec remise de 75% (Vente Soldée) prise en compte
          const cmdTotal = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0);
          const isBlocked = !venteSoldee && saleClient.outstandingDebt >= cl && (parseFloat(versementJour) || 0) < cmdTotal;
          return (
            <>
              <button type="button" onClick={() => setIsSaleModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px 16px', fontSize: '0.8rem' }}>
                Annuler
              </button>
              <button
                type="submit"
                form="sale-form"
                disabled={isBlocked || isSubmitting}
                className="btn btn-primary"
                style={{ flex: 2, padding: '8px 16px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: (isBlocked || isSubmitting) ? 0.55 : 1 }}
              >
                <FiCheckCircle />
                <span>{isSubmitting ? 'Enregistrement...' : isBlocked ? 'Plafond atteint — Versement insuffisant' : 'Confirmer la transaction'}</span>
              </button>
            </>
          );
        })()}
      >
          {saleClient && (
            <form id="sale-form" onSubmit={handleSaleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

              {/* Situation actuelle du client — BP affiché en premier */}
              {(() => {
                const debt = saleClient.outstandingDebt;
                const limit = saleClient.creditLimit || debtCeiling;
                // BUG-107 : aperçu avec remise de 75% (Vente Soldée) prise en compte
                const cmdTotal = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0);
                const isOver = debt >= limit;
                const isBlocked = isOver && (parseFloat(versementJour) || 0) < cmdTotal;
                return (
                  <div style={{ backgroundColor: isBlocked ? 'hsl(var(--color-danger) / 0.07)' : isOver ? 'hsl(var(--color-warning) / 0.07)' : 'hsl(var(--color-success) / 0.06)', border: `1px solid hsl(${isBlocked ? 'var(--color-danger)' : isOver ? 'var(--color-warning)' : 'var(--color-success)'} / 0.3)`, borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                    <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '6px' }}>Situation Actuelle du Client</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px', fontSize: '0.72rem' }}>
                      <div>
                        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>BALANCE ANTÉRIEURE (BP)</div>
                        <div style={{ fontWeight: 800, fontSize: '0.88rem', color: isBlocked ? 'hsl(var(--color-danger))' : isOver ? 'hsl(var(--color-warning))' : 'hsl(var(--text-primary))' }}>
                          {debt.toLocaleString('fr-FR')} FC
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>PLAFOND CRÉDIT</div>
                        <div style={{ fontWeight: 700 }}>{limit.toLocaleString('fr-FR')} FC</div>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>STATUT</div>
                        <span className={`badge ${isBlocked ? 'badge-danger' : isOver ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.55rem' }}>
                          {isBlocked ? 'BLOQUÉ' : isOver ? 'DÉPASSÉ' : 'EN RÈGLE'}
                        </span>
                        {isOver && (
                          <div style={{ fontSize: '0.55rem', color: isBlocked ? 'hsl(var(--color-danger))' : 'hsl(var(--color-warning))', fontWeight: 700, marginTop: '2px' }}>
                            +{(debt - limit).toLocaleString('fr-FR')} FC
                          </div>
                        )}
                        {isOver && !isBlocked && cmdTotal > 0 && (
                          <div style={{ fontSize: '0.5rem', color: 'hsl(var(--color-success))', marginTop: '2px' }}>Paiement intégral ✓</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Dynamic bread quantity grid */}
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>
                  Pains vendus par catégorie
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(breadPrices.length, 4)}, 1fr)`, gap: '8px' }}>
                  {breadPrices.map(bp => (
                    <div key={bp.id}>
                      <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textAlign: 'center' }}>{bp.label}</div>
                      <input
                        type="number" min={0}
                        value={saleQtys[bp.id] || ''}
                        placeholder="0"
                        onChange={e => setSaleQtys(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) }))}
                        className="form-input"
                        style={{ fontSize: '0.85rem', height: '34px', padding: '0 6px', textAlign: 'center', fontWeight: 700 }}
                      />
                      {(saleQtys[bp.id] || 0) > 0 && (
                        <div style={{ fontSize: '0.55rem', textAlign: 'center', color: 'hsl(var(--color-info))', marginTop: '2px' }}>
                          {/* BUG-107 : sous-total avec remise de 75% (Vente Soldée) prise en compte */}
                          {(saleQtys[bp.id] * effectiveUnitPrice(bp, venteSoldee)).toLocaleString('fr-FR')} FC
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Versement du jour Cash paid */}
              <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '12px', alignItems: 'center', borderTop: '1px dashed hsl(var(--border-color))', paddingTop: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--color-success))' }}>Versement du Jour (FC)</label>
                  <span style={{ fontSize: '0.65rem', color: isCasualSale ? 'hsl(var(--color-info))' : 'hsl(var(--text-muted))' }}>
                    {isCasualSale ? 'Vente sans client identifié : paiement comptant obligatoire, versement = valeur de la commande.' : 'Acompte en espèces versé ce jour'}
                  </span>
                </div>
                <input
                  type="number"
                  min={0}
                  placeholder="0"
                  value={isCasualSale ? String(breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0)) : versementJour}
                  disabled={isCasualSale}
                  onChange={(e) => setVersementJour(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.85rem', padding: '0 12px', fontWeight: 800, color: 'hsl(var(--color-success))', borderColor: 'hsl(var(--color-success) / 0.4)' }}
                />
              </div>

              {/* BUG-083 : date de commande rétroactive — visible seulement si activé en Configuration */}
              {allowBackdatedSales && (
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '12px', alignItems: 'center' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--color-warning))' }}>Date de la commande (optionnel)</label>
                    <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>Laisser vide = aujourd'hui. Jamais une date future.</span>
                  </div>
                  <input
                    type="date"
                    max={workDate}
                    value={orderDate}
                    onChange={(e) => setOrderDate(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                </div>
              )}

              {/* Dynamic Billing Engine Display */}
              {(() => {
                // BUG-107 : remise de 75% (Vente Soldée) appliquée dès l'aperçu, cohérente
                // avec le total réellement facturé par le serveur.
                const totalFc    = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0);
                const catalogFc  = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * bp.unit_price, 0);
                const commRate   = (sansCommission || venteSoldee) ? 0 : saleClient.commissionRate;
                const effectivePay = isCasualSale ? totalFc : (parseFloat(versementJour) || 0);
                // Vente soldée : manquant passé en perte, pas de dette supplémentaire
                const nouvelEncours = venteSoldee
                  ? saleClient.outstandingDebt
                  : saleClient.outstandingDebt + totalFc - effectivePay;
                return (
                  <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>Balance Antérieure (BP) :</span>
                      <span style={{ fontWeight: 700 }}>{saleClient.outstandingDebt.toLocaleString('fr-FR')} FC</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>+ Valeur Commande :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--text-primary))' }}>
                        + {totalFc.toLocaleString('fr-FR')} FC
                        {venteSoldee && catalogFc !== totalFc && (
                          <span style={{ fontSize: '0.6rem', color: 'hsl(var(--color-warning))', fontWeight: 400, marginLeft: '4px' }}>
                            (catalogue plein : {catalogFc.toLocaleString('fr-FR')} FC)
                          </span>
                        )}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>Commission CM ({commRate * 100}%) :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>- {(totalFc * commRate).toLocaleString('fr-FR')} FC</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>- Versement du Jour :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-info))' }}>
                        - {effectivePay.toLocaleString('fr-FR')} FC
                        {venteSoldee && totalFc > effectivePay && (
                          <span style={{ fontSize: '0.62rem', color: 'hsl(var(--color-warning))', marginLeft: '4px' }}>
                            (+{(totalFc - effectivePay).toLocaleString('fr-FR')} soldé)
                          </span>
                        )}
                      </span>
                    </div>
                    <div style={{ height: '1px', backgroundColor: 'hsl(var(--border-color))', margin: '4px 0' }} />
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: 'hsl(var(--text-primary))', fontWeight: 800 }}>
                      <span>= Nouvelle Dette (BP) :</span>
                      {(() => {
                        const cl = saleClient.creditLimit || debtCeiling;
                        return (
                          <span style={{ color: nouvelEncours > cl ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                            {nouvelEncours.toLocaleString('fr-FR')} FC
                          </span>
                        );
                      })()}
                    </div>
                    {(() => {
                      const cl = saleClient.creditLimit || debtCeiling;
                      return nouvelEncours > cl ? (
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--color-danger))', fontWeight: 700, textAlign: 'right' }}>
                          ⚠ Plafond dépassé de {(nouvelEncours - cl).toLocaleString('fr-FR')} FC
                        </div>
                      ) : null;
                    })()}
                  </div>
                );
              })()}

              {/* Checkboxes: vente sans commission / vente soldée — BUG-052 : les deux cases
                  sont désormais COMBINABLES (remarque.md l.190 ne les décrit jamais comme
                  exclusives ; l'exclusion mutuelle précédente empêchait, par ex., une vente
                  soldée explicitement exonérée en plus de sa remise de prix). */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px dashed hsl(var(--border-color))', paddingTop: '12px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 600, color: 'hsl(var(--text-primary))' }}>
                  <input
                    type="checkbox"
                    checked={sansCommission}
                    onChange={e => setSansCommission(e.target.checked)}
                    style={{ width: '15px', height: '15px', cursor: 'pointer' }}
                  />
                  Vente sans commission (25%) <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', fontWeight: 400 }}>(geste commercial ponctuel, prix et BP inchangés)</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 600, color: 'hsl(var(--text-primary))' }}>
                  <input
                    type="checkbox"
                    checked={venteSoldee}
                    onChange={e => setVenteSoldee(e.target.checked)}
                    style={{ width: '15px', height: '15px', cursor: 'pointer' }}
                  />
                  Vente Soldée / Vente Cash <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', fontWeight: 400 }}>(-25% sur le prix catalogue, 0% commission, manquant non imputé en BP)</span>
                </label>
                {sansCommission && venteSoldee && (
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', paddingLeft: '23px' }}>
                    Facture à la fois SOLDÉE (prix à 75%, BP gelée) ET sans commission — les deux cases restent combinables, CM=0 dans tous les cas.
                  </div>
                )}
                {venteSoldee && (
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', paddingLeft: '23px' }}>
                    Remise automatique de 25 % appliquée par le serveur sur le prix catalogue de chaque pain ;
                    distinct de « Client Occasionnel » (client non identifié) — les deux restent combinables.
                  </div>
                )}
              </div>

              {saleError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>{saleError}</div>
              )}
            </form>
          )}
      </Modal>
  );
};
