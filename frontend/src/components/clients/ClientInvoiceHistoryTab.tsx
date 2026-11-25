import React from 'react';
import type { Invoice } from '@/api/services';
import { getWorkDate, workDateMonthYear } from '@/store/workDateStore';

interface ClientInvoiceHistoryTabProps {
  clientInvoices: Invoice[];
  invoicesLoading: boolean;
  historyYear: number;
  historyMonth: number;
  setHistoryYear: React.Dispatch<React.SetStateAction<number>>;
  setHistoryMonth: React.Dispatch<React.SetStateAction<number>>;
  canAdjustInvoice: boolean;
  openAdjustModal: (invoice: Invoice) => void;
}

/** Onglet « Historique » de la fiche client : commandes du mois, navigation mensuelle, récapitulatif. */
export const ClientInvoiceHistoryTab: React.FC<ClientInvoiceHistoryTabProps> = ({
  clientInvoices, invoicesLoading, historyYear, historyMonth, setHistoryYear, setHistoryMonth,
  canAdjustInvoice, openAdjustModal,
}) => {
                const MOIS_FR = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];
                // BUG-1134 : mois courant = mois de la journée de travail du serveur.
                const current = workDateMonthYear(getWorkDate());
                const isCurrentMonth = historyYear === current.year && historyMonth === current.month;
                const goToPrev = () => {
                  if (historyMonth === 1) { setHistoryMonth(12); setHistoryYear(y => y - 1); }
                  else setHistoryMonth(m => m - 1);
                };
                const goToNext = () => {
                  if (isCurrentMonth) return;
                  if (historyMonth === 12) { setHistoryMonth(1); setHistoryYear(y => y + 1); }
                  else setHistoryMonth(m => m + 1);
                };
                const filtered = clientInvoices.filter(inv => {
                  if (!inv.invoice_date) return false;
                  const d = new Date(inv.invoice_date);
                  return d.getFullYear() === historyYear && d.getMonth() + 1 === historyMonth;
                });
                const monthTotal = filtered.reduce((s, inv) => s + parseFloat(inv.order_total || '0'), 0);
                const monthPaid = filtered.reduce((s, inv) => s + parseFloat(inv.payment_amount || '0'), 0);
                // Pour les ventes soldées, le manquant est passé en perte — ne pas l'inclure dans "Reste dû"
                const monthDebt = filtered.reduce((s, inv) => inv.is_soldee ? s : s + Math.max(0, parseFloat(inv.order_total || '0') - parseFloat(inv.payment_amount || '0')), 0);
                // BUG-092/BUG-096 : perte totale du mois sur les ventes soldées (prix catalogue − prix facturé).
                const monthLoss = filtered.reduce((s, inv) => s + (parseFloat(inv.total_loss || '0') || 0), 0);

                return (
                  <div>
                    {/* Navigation mensuelle */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', padding: '8px 12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
                      <button
                        onClick={goToPrev}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--accent-color))', padding: '4px 8px', borderRadius: '4px', fontSize: '1rem', fontWeight: 700, lineHeight: 1 }}
                        title="Mois précédent"
                      >
                        ‹
                      </button>
                      <span style={{ fontWeight: 800, fontSize: '0.82rem', color: 'hsl(var(--text-primary))' }}>
                        {MOIS_FR[historyMonth - 1]} {historyYear}
                      </span>
                      <button
                        onClick={goToNext}
                        disabled={isCurrentMonth}
                        style={{ background: 'none', border: 'none', cursor: isCurrentMonth ? 'default' : 'pointer', color: isCurrentMonth ? 'hsl(var(--text-muted))' : 'hsl(var(--accent-color))', padding: '4px 8px', borderRadius: '4px', fontSize: '1rem', fontWeight: 700, lineHeight: 1 }}
                        title="Mois suivant"
                      >
                        ›
                      </button>
                    </div>

                    {invoicesLoading ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>Chargement de l'historique...</p>
                    ) : filtered.length === 0 ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-muted))', fontSize: '0.78rem' }}>
                        Aucune commande pour {MOIS_FR[historyMonth - 1]} {historyYear}.
                      </p>
                    ) : (
                      <>
                        <div style={{ overflowX: 'auto' }}>
                          <table className="premium-table" style={{ fontSize: '0.72rem' }}>
                            <thead>
                              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                                <th style={{ padding: '6px 8px' }}>N° Facture</th>
                                <th style={{ padding: '6px 8px' }}>Date</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Total (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Versé (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Perte (FC)</th>
                                <th style={{ padding: '6px 8px' }}>Statut</th>
                                {canAdjustInvoice && <th style={{ padding: '6px 8px' }}></th>}
                              </tr>
                            </thead>
                            <tbody>
                              {filtered.map(inv => {
                                // BUG-109 : référence vers la facture d'origine (si c'est un
                                // ajustement) — recherche dans l'historique déjà chargé ; si la
                                // facture d'origine est hors de ce mois, on retombe sur son id.
                                const originalInvoice = inv.is_adjustment && inv.adjusts
                                  ? clientInvoices.find(o => o.id === inv.adjusts)
                                  : undefined;
                                return (
                                <tr key={inv.id}>
                                  <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{inv.receipt_number}</td>
                                  <td style={{ padding: '6px 8px', color: 'hsl(var(--text-secondary))' }}>
                                    {inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('fr-FR') : '—'}
                                  </td>
                                  <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700 }}>{parseFloat(inv.order_total || '0').toLocaleString('fr-FR')}</td>
                                  <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{parseFloat(inv.payment_amount || '0').toLocaleString('fr-FR')}</td>
                                  <td style={{ padding: '6px 8px', textAlign: 'right', color: parseFloat(inv.total_loss || '0') > 0 ? 'hsl(38, 92%, 38%)' : 'hsl(var(--text-muted))', fontWeight: parseFloat(inv.total_loss || '0') > 0 ? 700 : 400 }}>
                                    {parseFloat(inv.total_loss || '0') > 0 ? `-${parseFloat(inv.total_loss || '0').toLocaleString('fr-FR')}` : '—'}
                                  </td>
                                  <td style={{ padding: '6px 8px', display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center' }}>
                                    <span className={`badge ${inv.status === 'DELIVERED' ? 'badge-success' : inv.status === 'CANCELLED' ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.55rem' }}>
                                      {inv.status === 'DELIVERED' ? 'LIVRÉ' : inv.status === 'CANCELLED' ? 'ANNULÉ' : 'EN ATTENTE'}
                                    </span>
                                    {inv.is_debt_repayment && (
                                      <span className="badge" style={{ fontSize: '0.5rem', background: 'hsl(210,80%,50%)', color: '#fff' }}>REMB</span>
                                    )}
                                    {!inv.is_debt_repayment && inv.is_soldee && (
                                      <span className="badge badge-warning" style={{ fontSize: '0.5rem' }}>SOLDÉE</span>
                                    )}
                                    {!inv.is_debt_repayment && !inv.is_soldee && (
                                      <span className={`badge ${inv.payment_type === 'CASH' ? 'badge-success' : 'badge-secondary'}`} style={{ fontSize: '0.5rem' }}>
                                        {inv.payment_type === 'CASH' ? 'CASH' : 'CRÉDIT'}
                                      </span>
                                    )}
                                    {inv.special_code && (
                                      <span className="badge badge-info" style={{ fontSize: '0.48rem' }}>{inv.special_code === 'NS' ? 'NS — Non servie' : inv.special_code}</span>
                                    )}
                                    {/* BUG-109 : trace d'ajustement — badge + référence vers l'originale */}
                                    {inv.is_adjustment && (
                                      <span
                                        className="badge"
                                        title={`Ajustement de la facture ${originalInvoice?.receipt_number || inv.adjusts}`}
                                        style={{ fontSize: '0.5rem', background: inv.adjustment_sign === -1 ? 'hsl(0,70%,45%)' : 'hsl(150,60%,35%)', color: '#fff' }}
                                      >
                                        AJUST. {inv.adjustment_sign === -1 ? '−' : '+'} · réf {originalInvoice?.receipt_number || inv.adjusts}
                                      </span>
                                    )}
                                    {!inv.is_adjustment && (inv.adjustments_count || 0) > 0 && (
                                      <span className="badge badge-info" style={{ fontSize: '0.48rem' }}>
                                        {inv.adjustments_count} ajustement{(inv.adjustments_count || 0) > 1 ? 's' : ''}
                                      </span>
                                    )}
                                  </td>
                                  {canAdjustInvoice && (
                                    <td style={{ padding: '6px 8px' }}>
                                      {!inv.is_adjustment && !inv.is_debt_repayment && inv.status !== 'CANCELLED' && (
                                        <button
                                          onClick={() => openAdjustModal(inv)}
                                          className="btn btn-secondary"
                                          style={{ padding: '3px 8px', fontSize: '0.62rem', whiteSpace: 'nowrap' }}
                                          title="Corriger/annuler cette commande via une facture d'ajustement"
                                        >
                                          Ajuster
                                        </button>
                                      )}
                                    </td>
                                  )}
                                </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        {/* Récapitulatif mensuel */}
                        <div style={{ display: 'flex', gap: '12px', marginTop: '10px', padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>{filtered.length} commande(s)</span>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>Total : <strong>{monthTotal.toLocaleString('fr-FR')} FC</strong></span>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-success))' }}>Versé : <strong>{monthPaid.toLocaleString('fr-FR')} FC</strong></span>
                          {monthDebt > 0 && (
                            <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))' }}>Reste dû : <strong>{monthDebt.toLocaleString('fr-FR')} FC</strong></span>
                          )}
                          {monthLoss > 0 && (
                            <span style={{ fontSize: '0.65rem', color: 'hsl(38, 92%, 38%)' }} title="Perte attendue du mécanisme de vente soldée (-25% sur le prix catalogue)">
                              Perte (ventes soldées) : <strong>-{monthLoss.toLocaleString('fr-FR')} FC</strong>
                            </span>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                );
};
