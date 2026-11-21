import React from 'react';
import { FiAlertTriangle, FiDollarSign, FiUserCheck, FiX } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import type { ClientItem, DeficitRow, StatModalKind } from './clientItem';

interface ClientStatModalProps {
  statModal: StatModalKind;
  setStatModal: (k: StatModalKind | null) => void;
  clients: ClientItem[];
  deficitData: DeficitRow[];
  deficitLoading: boolean;
}

/** Détail des cartes de statistiques (plafonds dépassés, encours, solvabilité, déficitaires). */
export const ClientStatModal: React.FC<ClientStatModalProps> = ({
  statModal, setStatModal, clients, deficitData, deficitLoading,
}) => {
  return (
        <Modal
          isOpen={true}
          onClose={() => setStatModal(null)}
          maxWidth="620px"
          contentPadding="0"
          showCloseButton={false}
        >

            {/* Modal header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid hsl(var(--border-color))' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {statModal === 'plafonds' && <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
                {statModal === 'encours'  && <FiDollarSign   style={{ color: 'hsl(var(--color-info))' }} />}
                {statModal === 'solvabilite' && <FiUserCheck style={{ color: 'hsl(var(--color-success))' }} />}
                {statModal === 'deficit' && <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
                <span style={{ fontWeight: 800, fontSize: '0.9rem' }}>
                  {statModal === 'plafonds'    && 'Plafonds Dépassés — Détail'}
                  {statModal === 'encours'     && 'Encours Global — Détail'}
                  {statModal === 'solvabilite' && 'Solvabilité — Analyse du Risque'}
                  {statModal === 'deficit'     && 'Clients Déficitaires — BP > CM Période'}
                </span>
              </div>
              <button onClick={() => setStatModal(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--text-muted))', fontSize: '1.1rem', lineHeight: 1 }}>
                <FiX />
              </button>
            </div>

            {/* Modal body */}
            <div style={{ overflowY: 'auto', padding: '14px 18px', flex: 1 }}>

              {/* ── PLAFONDS DÉPASSÉS ── */}
              {statModal === 'plafonds' && (() => {
                const exceeded = clients.filter(c => c.outstandingDebt > c.creditLimit).sort((a, b) => (b.outstandingDebt - b.creditLimit) - (a.outstandingDebt - a.creditLimit));
                if (exceeded.length === 0) return (
                  <p style={{ textAlign: 'center', color: 'hsl(var(--color-success))', fontWeight: 700, padding: '24px 0' }}>Aucun client n'a dépassé son plafond. ✓</p>
                );
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>{exceeded.length} client(s) ont dépassé leur plafond de crédit, triés par excédent décroissant.</p>
                    {exceeded.map(c => {
                      const excess = c.outstandingDebt - c.creditLimit;
                      return (
                        <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.06)', border: '1px solid hsl(var(--color-danger) / 0.2)' }}>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{c.name}</div>
                            <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{c.id} — Plafond : {c.creditLimit.toLocaleString('fr-FR')} FC</div>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <div style={{ fontWeight: 800, fontSize: '0.82rem', color: 'hsl(var(--color-danger))' }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</div>
                            <div style={{ fontSize: '0.6rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>+{excess.toLocaleString('fr-FR')} FC</div>
                          </div>
                        </div>
                      );
                    })}
                    <div style={{ marginTop: '8px', padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800 }}>
                      <span>Total excédent à recouvrer :</span>
                      <span style={{ color: 'hsl(var(--color-danger))' }}>
                        {exceeded.reduce((s, c) => s + (c.outstandingDebt - c.creditLimit), 0).toLocaleString('fr-FR')} FC
                      </span>
                    </div>
                  </div>
                );
              })()}

              {/* ── ENCOURS GLOBAL ── */}
              {statModal === 'encours' && (() => {
                const withDebt  = clients.filter(c => c.outstandingDebt > 0).sort((a, b) => b.outstandingDebt - a.outstandingDebt);
                const inCredit  = clients.filter(c => c.outstandingDebt < 0).sort((a, b) => a.outstandingDebt - b.outstandingDebt);
                const noDebt    = clients.filter(c => c.outstandingDebt === 0);
                const allClear  = withDebt.length === 0 && inCredit.length === 0;
                const netBalance = withDebt.reduce((s, c) => s + c.outstandingDebt, 0);
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                      {[
                        { label: 'Encours Net', value: `${netBalance.toLocaleString('fr-FR')} FC`, color: netBalance > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' },
                        { label: 'Endettés', value: `${withDebt.length}`, color: 'hsl(var(--color-warning))' },
                        { label: 'En Crédit', value: `${inCredit.length}`, color: 'hsl(var(--color-info))' },
                        { label: 'Sans BP', value: `${noDebt.length}`, color: 'hsl(var(--color-success))' },
                      ].map(s => (
                        <div key={s.label} style={{ padding: '8px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', textAlign: 'center' }}>
                          <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>{s.label}</div>
                          <div style={{ fontWeight: 800, fontSize: '0.88rem', color: s.color }}>{s.value}</div>
                        </div>
                      ))}
                    </div>

                    {allClear ? (
                      <p style={{ textAlign: 'center', color: 'hsl(var(--color-success))', fontWeight: 700, padding: '12px 0' }}>Aucun encours. Tous les clients sont à jour. ✓</p>
                    ) : (
                      <>
                        {/* Clients endettés */}
                        {withDebt.length > 0 && (
                          <div style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', textTransform: 'uppercase', marginTop: '4px', marginBottom: '2px' }}>
                            Clients endettés ({withDebt.length})
                          </div>
                        )}
                        {withDebt.map(c => {
                          const pct = c.creditLimit > 0 ? Math.min(100, Math.round(c.outstandingDebt / c.creditLimit * 100)) : 0;
                          const isOver = c.outstandingDebt > c.creditLimit;
                          return (
                            <div key={c.id} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: isOver ? 'hsl(var(--color-danger) / 0.05)' : 'hsl(var(--bg-tertiary))', border: `1px solid hsl(${isOver ? 'var(--color-danger)' : 'var(--border-color)'} / ${isOver ? '0.25' : '1'})` }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                <div>
                                  <span style={{ fontWeight: 800, fontSize: '0.78rem' }}>{c.name}</span>
                                  <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', marginLeft: '6px' }}>{c.id}</span>
                                </div>
                                <div style={{ textAlign: 'right' }}>
                                  <span style={{ fontWeight: 800, fontSize: '0.78rem', color: isOver ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</span>
                                  <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', marginLeft: '4px' }}>/ {c.creditLimit.toLocaleString('fr-FR')} FC</span>
                                </div>
                              </div>
                                  <div style={{ height: '4px', borderRadius: '2px', backgroundColor: 'hsl(var(--border-color))' }}>
                                <div style={{ height: '100%', borderRadius: '2px', width: `${pct}%`, backgroundColor: isOver ? 'hsl(var(--color-danger))' : pct >= 80 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }} />
                              </div>
                              <div style={{ fontSize: '0.55rem', color: 'hsl(var(--text-muted))', marginTop: '2px', textAlign: 'right' }}>{pct}% du plafond</div>
                            </div>
                          );
                        })}

                        {/* Clients en crédit (trop-payé) */}
                        {inCredit.length > 0 && (
                          <div style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-info))', textTransform: 'uppercase', marginTop: '8px', marginBottom: '2px' }}>
                            En Crédit — Trop-payé ({inCredit.length})
                          </div>
                        )}
                        {inCredit.map(c => (
                          <div key={c.id} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-info) / 0.05)', border: '1px solid hsl(var(--color-info) / 0.2)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <div>
                                <span style={{ fontWeight: 800, fontSize: '0.78rem' }}>{c.name}</span>
                                <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', marginLeft: '6px' }}>{c.id}</span>
                              </div>
                              <span style={{ fontWeight: 800, fontSize: '0.78rem', color: 'hsl(var(--color-info))' }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</span>
                            </div>
                            <div style={{ fontSize: '0.55rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>Trop-payé — se régularise à la prochaine commande</div>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                );
              })()}

              {/* ── SOLVABILITÉ ── */}
              {statModal === 'solvabilite' && (() => {
                const high   = clients.filter(c => c.riskScore === 'High');
                const medium = clients.filter(c => c.riskScore === 'Medium');
                const low    = clients.filter(c => c.riskScore === 'Low');
                const globalScore = high.length === 0 ? 'A+' : high.length <= 2 ? 'B' : high.length <= 5 ? 'C' : 'D';
                const scoreColor  = globalScore === 'A+' ? 'hsl(var(--color-success))' : globalScore === 'B' ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', padding: '12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))' }}>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: '2rem', fontWeight: 900, color: scoreColor }}>{globalScore}</div>
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Score Global</div>
                      </div>
                      <div style={{ width: '1px', height: '40px', backgroundColor: 'hsl(var(--border-color))' }} />
                      <div style={{ display: 'flex', gap: '12px' }}>
                        {[
                          { label: 'CRITIQUE', count: high.length,   color: 'hsl(var(--color-danger))' },
                          { label: 'MOYEN',    count: medium.length, color: 'hsl(var(--color-warning))' },
                          { label: 'MINIME',   count: low.length,    color: 'hsl(var(--color-success))' },
                        ].map(s => (
                          <div key={s.label} style={{ textAlign: 'center' }}>
                            <div style={{ fontWeight: 800, fontSize: '1.1rem', color: s.color }}>{s.count}</div>
                            <div style={{ fontSize: '0.55rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>{s.label}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    {[
                      { label: 'Clients à Risque CRITIQUE', list: high,   badgeClass: 'badge-danger',  desc: 'BP ≥ plafond — recouvrement urgent' },
                      { label: 'Clients à Risque MOYEN',    list: medium, badgeClass: 'badge-warning', desc: 'BP élevée — surveillance recommandée' },
                      { label: 'Clients Fiables',           list: low,    badgeClass: 'badge-success', desc: 'BP faible — aucune alerte' },
                    ].filter(g => g.list.length > 0).map(group => (
                      <div key={group.label}>
                        <div style={{ fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '6px' }}>
                          {group.label} ({group.list.length}) — <span style={{ fontWeight: 400 }}>{group.desc}</span>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {group.list.map(c => (
                            <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <div style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: c.avatarColor, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.55rem', flexShrink: 0 }}>
                                  {c.name.substring(0, 2).toUpperCase()}
                                </div>
                                <div>
                                  <div style={{ fontWeight: 700, fontSize: '0.75rem' }}>{c.name}</div>
                                  <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>{c.id}</div>
                                </div>
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontSize: '0.75rem', fontWeight: 800 }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</div>
                                <span className={`badge ${group.badgeClass}`} style={{ fontSize: '0.5rem' }}>{c.riskScore === 'High' ? 'CRITIQUE' : c.riskScore === 'Medium' ? 'MOYEN' : 'MINIME'}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })()}


              {/* ── DÉFICITAIRES ── */}
              {statModal === 'deficit' && (
                deficitLoading ? (
                  <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>Chargement du rapport...</p>
                ) : deficitData.length === 0 ? (
                  <p style={{ textAlign: 'center', color: 'hsl(var(--color-success))', fontWeight: 700, padding: '24px 0' }}>Aucun client déficitaire pour la dernière période. ✓</p>
                ) : (
                  <div>
                    <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '8px' }}>
                      {deficitData.length} client(s) dont la dette actuelle (BP) dépasse la commission de la dernière période — {deficitData[0]?.period}.
                    </p>
                    <div style={{ overflowX: 'auto' }}>
                      <table className="premium-table" style={{ fontSize: '0.7rem' }}>
                        <thead>
                          <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                            <th style={{ padding: '6px 8px' }}>Code</th>
                            <th style={{ padding: '6px 8px' }}>Nom</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>Commande (FC)</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>CM (FC)</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>BP (FC)</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>Déficit (FC)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {deficitData.map(row => (
                            <tr key={row.client_code}>
                              <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{row.client_code}</td>
                              <td style={{ padding: '6px 8px', fontWeight: 600 }}>{row.client_name}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.order_value).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{parseFloat(row.commission_gross).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{parseFloat(row.current_debt).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-danger))' }}>{parseFloat(row.deficit).toLocaleString('fr-FR')}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div style={{ marginTop: '8px', padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800 }}>
                      <span>Déficit total :</span>
                      <span style={{ color: 'hsl(var(--color-danger))' }}>
                        {deficitData.reduce((s, r) => s + parseFloat(r.deficit), 0).toLocaleString('fr-FR')} FC
                      </span>
                    </div>
                  </div>
                )
              )}

            </div>

            <div style={{ padding: '10px 18px', borderTop: '1px solid hsl(var(--border-color))' }}>
              <button onClick={() => setStatModal(null)} className="btn btn-secondary" style={{ width: '100%', fontSize: '0.8rem', padding: '7px' }}>Fermer</button>
            </div>
        </Modal>
  );
};
