import React from 'react';
import type { Invoice } from '@/api/services';

interface ClientRepaymentsTabProps {
  clientInvoices: Invoice[];
  invoicesLoading: boolean;
}

/** Onglet « Remboursements » de la fiche client (factures de remboursement de BP / dépôts). */
export const ClientRepaymentsTab: React.FC<ClientRepaymentsTabProps> = ({ clientInvoices, invoicesLoading }) => {
                const repayments = clientInvoices.filter(inv => inv.is_debt_repayment);
                const totalRemboursé = repayments.reduce((s, inv) => s + parseFloat(inv.payment_amount || '0'), 0);
                return (
                  <div>
                    {invoicesLoading ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>Chargement...</p>
                    ) : repayments.length === 0 ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-muted))', fontSize: '0.78rem' }}>
                        Aucun remboursement BP enregistré pour ce client.
                      </p>
                    ) : (
                      <>
                        <div style={{ overflowX: 'auto' }}>
                          <table className="premium-table" style={{ fontSize: '0.72rem' }}>
                            <thead>
                              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                                <th style={{ padding: '6px 8px' }}>Date</th>
                                <th style={{ padding: '6px 8px' }}>N° Reçu</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>BP Initial (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Montant (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Nouveau BP (FC)</th>
                              </tr>
                            </thead>
                            <tbody>
                              {repayments.map(inv => {
                                const bpAfter = parseFloat(inv.debt_after || '0');
                                return (
                                  <tr key={inv.id}>
                                    <td style={{ padding: '6px 8px', color: 'hsl(var(--text-secondary))' }}>
                                      {inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('fr-FR') : '—'}
                                    </td>
                                    <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(210,80%,50%)' }}>{inv.receipt_number}</td>
                                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(inv.debt_before || '0').toLocaleString('fr-FR')}</td>
                                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: 'hsl(var(--color-success))' }}>
                                      {parseFloat(inv.payment_amount || '0').toLocaleString('fr-FR')}
                                    </td>
                                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: bpAfter <= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-primary))' }}>
                                      {bpAfter <= 0 ? `CRÉDIT : ${Math.abs(bpAfter).toLocaleString('fr-FR')}` : bpAfter.toLocaleString('fr-FR')}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        <div style={{ display: 'flex', gap: '12px', marginTop: '10px', padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>{repayments.length} remboursement(s)</span>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-success))' }}>Total versé : <strong>{totalRemboursé.toLocaleString('fr-FR')} FC</strong></span>
                        </div>
                      </>
                    )}
                  </div>
                );
};
