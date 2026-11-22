import React from 'react';
import { FiPlus, FiAlertTriangle } from 'react-icons/fi';
import type { ConsumableStock, ConsumableCount } from '@/api/services';
import type { UserProfile } from '@/store/authStore';
import { STOCK_ICONS, displayStock } from './productionHelpers';

export interface IntrantsTabProps {
  stocks: ConsumableStock[];
  isLoading: boolean;
  setShowApproModal: React.Dispatch<React.SetStateAction<boolean>>;
  countValues: Record<string, string>;
  setCountValues: React.Dispatch<React.SetStateAction<Record<string, string>>>;
  countError: string | null;
  countSubmitting: boolean;
  lastCounts: ConsumableCount[];
  user: UserProfile | null;
  currentNodeLabel: string | undefined;
  hasLowStock: boolean;
  handleInventoryCount: () => Promise<void>;
}

export const IntrantsTab: React.FC<IntrantsTabProps> = ({ stocks, isLoading, setShowApproModal, countValues, setCountValues, countError, countSubmitting, lastCounts, user, currentNodeLabel, hasLowStock, handleInventoryCount }) => {
  return (
        <div className="glass-card" style={{ padding: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 800 }}>
              Intrants — Stocks Consommables (§3.2)
              {currentNodeLabel && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>{currentNodeLabel}</span>}
            </h2>
            {user?.can_access_all_nodes && (
              <button onClick={() => setShowApproModal(true)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
                <FiPlus /> Approvisionner
              </button>
            )}
          </div>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Chargement...</div>
          ) : (
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                  <th>Intrant</th><th style={{ textAlign: 'right' }}>Qté</th><th>Unité</th>
                  <th style={{ textAlign: 'right' }} title="Coût Unitaire Moyen Pondéré, recalculé à chaque entrée de stock">CUMP</th>
                  <th style={{ textAlign: 'center' }}>Statut</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {stocks.map(st => {
                  const qty = parseFloat(st.quantity);
                  const isLow = qty < 10;
                  const cump = st.average_unit_cost != null ? parseFloat(st.average_unit_cost) : null;
                  return (
                    <tr key={st.id}>
                      <td style={{ fontWeight: 700 }}>{STOCK_ICONS[st.consumable_type] || '📦'} {displayStock(st.consumable_type_display || st.consumable_type)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: isLow ? 'hsl(var(--color-danger))' : undefined }}>{qty}</td>
                      <td style={{ color: 'hsl(var(--text-muted))' }}>{st.unit}</td>
                      <td
                        style={{ textAlign: 'right', color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}
                        title="Coût Unitaire Moyen Pondéré (CUMP) : coût d'achat moyen par unité, recalculé à chaque entrée de stock. Utilisé pour valoriser la consommation réelle au Compte de Résultat."
                      >
                        {cump != null ? `${cump.toLocaleString('fr-FR')} FC` : '—'}
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <span className={`badge ${isLow ? 'badge-danger' : 'badge-success'}`} style={{ fontSize: '0.5rem' }}>{isLow ? 'ALERTE' : 'OK'}</span>
                      </td>
                    </tr>
                  );
                })}
                {stocks.length === 0 && <tr><td colSpan={5} style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))' }}>Aucun stock</td></tr>}
              </tbody>
            </table>
          )}
          {hasLowStock && (
            <div style={{ marginTop: '10px', backgroundColor: 'hsl(var(--color-danger) / 0.08)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', display: 'flex', gap: '8px', alignItems: 'center' }}>
              <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', flexShrink: 0 }} />
              <div>
                <strong style={{ fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>Alerte Stock Critique</strong>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>Approvisionnement urgent requis</div>
              </div>
            </div>
          )}

          {/* ── Inventaire physique (non-FLOUR) ── */}
          {stocks.filter(s => s.consumable_type !== 'FLOUR').length > 0 && (
            <div style={{ marginTop: '14px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '12px' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '8px' }}>
                Inventaire Physique
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {stocks.filter(s => s.consumable_type !== 'FLOUR').map(st => {
                  const lastCount = lastCounts
                    .filter(c => c.consumable_type === st.consumable_type)
                    .sort((a, b) => b.count_date.localeCompare(a.count_date))[0];
                  const gap = lastCount ? parseFloat(lastCount.gap) : null;
                  return (
                    <div key={st.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.7rem' }}>
                      <span style={{ width: '100px', fontWeight: 700 }}>
                        {STOCK_ICONS[st.consumable_type] || '📦'} {displayStock(st.consumable_type_display || st.consumable_type)}
                      </span>
                      <input
                        type="number" step="any" min={0}
                        placeholder={`Sys: ${parseFloat(st.quantity)}`}
                        value={countValues[st.consumable_type] || ''}
                        onChange={e => setCountValues(prev => ({ ...prev, [st.consumable_type]: e.target.value }))}
                        className="form-input"
                        style={{ width: '80px', height: '26px', fontSize: '0.7rem', padding: '0 6px' }}
                      />
                      <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.62rem' }}>{st.unit}</span>
                      {gap !== null && (
                        <span style={{ fontSize: '0.62rem', fontWeight: 700, color: gap < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                          {gap < 0 ? `Écart: ${gap}` : `OK (${lastCount!.count_date})`}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
              {countError && (
                <div style={{ marginTop: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>{countError}</div>
              )}
              <button
                onClick={handleInventoryCount}
                disabled={countSubmitting || Object.keys(countValues).length === 0}
                className="btn btn-secondary"
                style={{ marginTop: '8px', padding: '4px 12px', fontSize: '0.68rem', width: '100%' }}
              >
                {countSubmitting ? 'Validation...' : 'Valider le Comptage'}
              </button>
            </div>
          )}
        </div>
  );
};
