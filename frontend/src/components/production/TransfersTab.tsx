import React from 'react';
import { FiArrowRight, FiCheckCircle, FiTruck, FiX } from 'react-icons/fi';
import type { BreadTransfer, BakeryNode, BreadPrice } from '@/api/services';
import type { UserProfile } from '@/store/authStore';
import { TransferDisputeCard } from './TransferDisputeCard';
import { DirectSendsOutgoing } from './DirectSendsOutgoing';

export interface TransfersTabProps {
  transfers: BreadTransfer[];
  nodes: BakeryNode[];
  breadPrices: BreadPrice[];
  tFromNode: string;
  setTFromNode: React.Dispatch<React.SetStateAction<string>>;
  tLines: Record<number, number>;
  setTLines: React.Dispatch<React.SetStateAction<Record<number, number>>>;
  tNotes: string;
  setTNotes: React.Dispatch<React.SetStateAction<string>>;
  tError: string | null;
  tSending: boolean;
  tSuccess: string | null;
  setTSuccess: React.Dispatch<React.SetStateAction<string | null>>;
  transferNotice: string | null;
  setTransferNotice: React.Dispatch<React.SetStateAction<string | null>>;
  setShowDirectSend: React.Dispatch<React.SetStateAction<boolean>>;
  directNotice: string | null;
  setDirectNotice: React.Dispatch<React.SetStateAction<string | null>>;
  transferActionError: string | null;
  setTransferActionError: React.Dispatch<React.SetStateAction<string | null>>;
  respondQtys: Record<string, Record<number, number>>;
  setRespondQtys: React.Dispatch<React.SetStateAction<Record<string, Record<number, number>>>>;
  confirmQtys: Record<string, Record<number, number>>;
  setConfirmQtys: React.Dispatch<React.SetStateAction<Record<string, Record<number, number>>>>;
  user: UserProfile | null;
  effectiveNode: string;
  isNode: (id: string | number | null | undefined) => boolean;
  pendingRequests: BreadTransfer[];
  respondedToMe: BreadTransfer[];
  disputedTrans: BreadTransfer[];
  outgoingDirect: BreadTransfer[];
  canDirectSend: boolean;
  loadData: (nodeFilterArg?: string) => Promise<void>;
  handleCreateTransfer: (e: React.FormEvent<HTMLFormElement>) => Promise<void>;
  handleRespondToTransfer: (transferId: string, approved: boolean) => Promise<void>;
  handleConfirmReceipt: (transferId: string) => Promise<void>;
}

export const TransfersTab: React.FC<TransfersTabProps> = ({ transfers, nodes, breadPrices, tFromNode, setTFromNode, tLines, setTLines, tNotes, setTNotes, tError, tSending, tSuccess, setTSuccess, transferNotice, setTransferNotice, setShowDirectSend, directNotice, setDirectNotice, transferActionError, setTransferActionError, respondQtys, setRespondQtys, confirmQtys, setConfirmQtys, user, effectiveNode, isNode, pendingRequests, respondedToMe, disputedTrans, outgoingDirect, canDirectSend, loadData, handleCreateTransfer, handleRespondToTransfer, handleConfirmReceipt }) => {
  return (
      <div className="glass-card" style={{ padding: '16px' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FiTruck style={{ color: 'hsl(var(--accent-color))' }} />
          §3.3 — Transferts Inter-Boulangeries (Règle d'Or Comptable)
          {disputedTrans.length > 0 && (
            <span className="badge badge-danger" style={{ fontSize: '0.6rem' }}>{disputedTrans.length} LITIGE{disputedTrans.length > 1 ? 'S' : ''}</span>
          )}
        </h2>
        <div className="split-grid" style={{ '--split-cols': '1fr 1.6fr', gap: '16px' } as React.CSSProperties}>

          {/* STEP 1 — A creates request FROM B */}
          <div>
            {canDirectSend && (
              <div style={{ marginBottom: '14px', paddingBottom: '12px', borderBottom: '1px solid hsl(var(--border-color))' }}>
                <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '4px', color: 'hsl(var(--text-secondary))' }}>Envoyer des Pains</h3>
                <p style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '8px' }}>
                  Envoyez des pains à une autre boulangerie sans attendre sa demande ; elle confirmera la réception.
                </p>
                <button type="button" onClick={() => { setDirectNotice(null); setShowDirectSend(true); }} className="btn btn-primary" style={{ width: '100%', minHeight: '40px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', fontSize: '0.75rem' }}>
                  <FiArrowRight /> Envoyer des pains
                </button>
                {directNotice && (
                  <div role="status" style={{ marginTop: '8px', fontSize: '0.68rem', fontWeight: 600, color: 'hsl(var(--color-success))', backgroundColor: 'hsl(var(--color-success) / 0.1)', border: '1px solid hsl(var(--color-success) / 0.4)', padding: '6px 8px', borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                    <span>✓ {directNotice}</span>
                    <button type="button" onClick={() => setDirectNotice(null)} aria-label="Fermer le message" style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '0.9rem', lineHeight: 1, padding: '0 2px' }}>×</button>
                  </div>
                )}
              </div>
            )}
            <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '4px', color: 'hsl(var(--text-secondary))' }}>Faire une Demande de Pains</h3>
            <p style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '8px' }}>
              Sélectionnez la boulangerie qui vous enverra les pains et indiquez les quantités souhaitées.
            </p>
            <form onSubmit={handleCreateTransfer} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Demander à *</label>
                <select value={tFromNode} onChange={e => { setTFromNode(e.target.value); setTSuccess(null); }} className="form-input" style={{ fontSize: '0.73rem', height: '30px' }}>
                  <option value="">— Boulangerie source —</option>
                  {nodes.filter(n => String(n.id) !== effectiveNode).map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>Quantités demandées par catégorie *</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {breadPrices.map(bp => (
                    <div key={bp.id} style={{ display: 'grid', gridTemplateColumns: '1fr 80px', gap: '6px', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>{bp.label}</span>
                      <input
                        type="number" min={0}
                        value={tLines[bp.id] || ''}
                        placeholder="0"
                        onChange={e => { setTSuccess(null); setTLines(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) })); }}
                        className="form-input"
                        style={{ fontSize: '0.73rem', height: '26px', padding: '0 6px', textAlign: 'right' }}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Notes</label>
                <input type="text" value={tNotes} onChange={e => { setTNotes(e.target.value); setTSuccess(null); }} placeholder="Motif, urgence..." className="form-input" style={{ fontSize: '0.72rem', height: '28px', padding: '0 6px' }} />
              </div>
              {tError && <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)' }}>{tError}</div>}
              {tSuccess && (
                <div role="status" style={{ fontSize: '0.68rem', fontWeight: 600, color: 'hsl(var(--color-success))', backgroundColor: 'hsl(var(--color-success) / 0.1)', border: '1px solid hsl(var(--color-success) / 0.4)', padding: '6px 8px', borderRadius: 'var(--radius-sm)', display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '8px' }}>
                  <span>✓ {tSuccess}</span>
                  <button type="button" onClick={() => setTSuccess(null)} aria-label="Fermer le message" style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer', fontSize: '0.9rem', lineHeight: 1, padding: '0 2px' }}>×</button>
                </div>
              )}
              <button type="submit" disabled={tSending} className="btn btn-primary" style={{ padding: '6px', fontSize: '0.73rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', opacity: tSending ? 0.7 : 1 }}>
                <FiArrowRight /> {tSending ? 'Envoi en cours…' : 'Envoyer la demande'}
              </button>
            </form>
          </div>

          {/* RIGHT COLUMN — Steps 2 & 3 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

            {/* STEP 2 — B (from_node) responds to pending requests */}
            {pendingRequests.length > 0 && (
              <div>
                <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '6px', color: 'hsl(var(--text-secondary))' }}>
                  Demandes à Traiter
                  <span className="badge badge-warning" style={{ marginLeft: '6px', fontSize: '0.55rem' }}>{pendingRequests.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {pendingRequests.map(t => (
                    <div key={t.id} style={{ backgroundColor: 'hsl(var(--color-warning) / 0.05)', border: '1px solid hsl(var(--color-warning) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <div style={{ fontSize: '0.72rem' }}>
                          <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{t.to_node_display || t.to_node}</span>
                          <span style={{ color: 'hsl(var(--text-muted))', margin: '0 4px' }}>demande à</span>
                          <span style={{ fontWeight: 800 }}>{t.from_node_display || t.from_node}</span>
                        </div>
                        <span className="badge badge-warning" style={{ fontSize: '0.52rem' }}>EN ATTENTE</span>
                      </div>
                      {t.notes && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '6px', fontStyle: 'italic' }}>{t.notes}</div>}

                      {/* B fills in qty they can actually send (may differ from what was requested) */}
                      <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', marginBottom: '4px', textTransform: 'uppercase' }}>
                        Quantités demandées → Quantités envoyées
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
                        {(t.lines || []).map(line => {
                          const bQtys = respondQtys[t.id] || {};
                          const sendQty = bQtys[line.bread_price] ?? line.quantity_sent;
                          const hasGap = sendQty !== line.quantity_sent;
                          return (
                            <div key={line.bread_price} style={{ display: 'grid', gridTemplateColumns: '1fr 50px 70px', gap: '6px', alignItems: 'center', fontSize: '0.65rem' }}>
                              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                                {line.bread_price_display || `Pain ${line.unit_price} FC`}
                                <span style={{ marginLeft: '4px', color: 'hsl(var(--text-muted))' }}>demandé: {line.quantity_sent}</span>
                              </span>
                              <input
                                type="number" min={0}
                                value={sendQty}
                                onChange={e => setRespondQtys(prev => ({
                                  ...prev,
                                  [t.id]: { ...(prev[t.id] || {}), [line.bread_price]: Number(e.target.value) }
                                }))}
                                className="form-input"
                                style={{
                                  fontSize: '0.73rem', height: '24px', padding: '0 5px', textAlign: 'right', fontWeight: 800,
                                  borderColor: hasGap ? 'hsl(var(--color-warning) / 0.7)' : 'hsl(var(--color-success) / 0.5)',
                                }}
                              />
                              {hasGap && (
                                <span style={{ fontSize: '0.55rem', color: 'hsl(var(--color-warning))', fontWeight: 700 }}>
                                  ajusté ⚠
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                        <button
                          onClick={() => handleRespondToTransfer(t.id, true)}
                          className="btn btn-primary"
                          style={{ padding: '5px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                        >
                          <FiCheckCircle /> Envoyer les pains
                        </button>
                        <button
                          onClick={() => handleRespondToTransfer(t.id, false)}
                          className="btn btn-secondary"
                          style={{ padding: '5px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', color: 'hsl(var(--color-danger))' }}
                        >
                          <FiX /> Pas de stock
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <DirectSendsOutgoing transfers={outgoingDirect} />

            {/* STEP 3 — A (to_node) confirms receipt of responded transfers */}
            {respondedToMe.length > 0 && (
              <div>
                <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '6px', color: 'hsl(var(--text-secondary))' }}>
                  Réceptions à Confirmer
                  <span className="badge badge-info" style={{ marginLeft: '6px', fontSize: '0.55rem' }}>{respondedToMe.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {respondedToMe.map(t => (
                    <div key={t.id} style={{ backgroundColor: 'hsl(var(--color-info) / 0.05)', border: '1px solid hsl(var(--color-info) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <div style={{ fontSize: '0.72rem' }}>
                          {t.flow === 'DIRECT' ? (
                            <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>Envoi direct de {t.from_node_display || t.from_node}</span>
                          ) : (
                            <>
                              <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{t.from_node_display || t.from_node}</span>
                              <FiArrowRight style={{ margin: '0 4px' }} />
                              <span style={{ fontWeight: 800 }}>{t.to_node_display || t.to_node}</span>
                            </>
                          )}
                        </div>
                        <span className="badge badge-info" style={{ fontSize: '0.52rem' }}>{t.flow === 'DIRECT' ? 'À CONFIRMER' : 'RÉCEPTIONNÉ'}</span>
                      </div>
                      {t.flow === 'DIRECT' && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>Envoyé spontanément : vous n'aviez pas fait de demande. Vérifiez les quantités reçues.</div>}
                      {t.notes && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '6px', fontStyle: 'italic' }}>{t.notes}</div>}

                      <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', marginBottom: '4px', textTransform: 'uppercase' }}>
                        Envoyé par {t.from_node_display || t.from_node} → Quantités reçues
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
                        {(t.lines || []).map(line => {
                          const aQtys = confirmQtys[t.id] || {};
                          const recvd = aQtys[line.bread_price] ?? line.quantity_sent;
                          const hasGap = recvd !== line.quantity_sent;
                          return (
                            <div key={line.bread_price} style={{ display: 'grid', gridTemplateColumns: '1fr 50px 70px', gap: '6px', alignItems: 'center', fontSize: '0.65rem' }}>
                              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                                {line.bread_price_display || `Pain ${line.unit_price} FC`}
                                <span style={{ marginLeft: '4px', color: 'hsl(var(--text-muted))' }}>envoyé: {line.quantity_sent}</span>
                              </span>
                              <input
                                type="number" min={0}
                                value={recvd}
                                onChange={e => setConfirmQtys(prev => ({
                                  ...prev,
                                  [t.id]: { ...(prev[t.id] || {}), [line.bread_price]: Number(e.target.value) }
                                }))}
                                className="form-input"
                                style={{
                                  fontSize: '0.73rem', height: '24px', padding: '0 5px', textAlign: 'right', fontWeight: 800,
                                  borderColor: hasGap ? 'hsl(var(--color-danger) / 0.7)' : 'hsl(var(--color-success) / 0.5)',
                                }}
                              />
                              {hasGap && (
                                <span style={{ fontSize: '0.58rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                                  écart {recvd - line.quantity_sent} ⚠
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <button
                        onClick={() => handleConfirmReceipt(t.id)}
                        className="btn btn-primary"
                        style={{ width: '100%', padding: '5px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                      >
                        <FiCheckCircle /> {t.flow === 'DIRECT' ? 'Confirmer la réception' : 'Confirmer la Réception'}
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty state */}
            {pendingRequests.length === 0 && respondedToMe.length === 0 && disputedTrans.length === 0 && outgoingDirect.length === 0 && (
              <div style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
                <FiCheckCircle style={{ fontSize: '1.4rem', opacity: 0.3, display: 'block', margin: '0 auto 5px' }} />
                Aucune action en attente.
              </div>
            )}

            {/* DISPUTES */}
            {transferNotice && (
              <div role="status" style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-success) / 0.1)', color: 'hsl(var(--color-success))', fontSize: '0.68rem', fontWeight: 700 }}>
                {transferNotice}
              </div>
            )}
            {transferActionError && (
              <div role="alert" style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', color: 'hsl(var(--color-danger))', fontSize: '0.68rem', fontWeight: 700 }}>
                {transferActionError}
              </div>
            )}
            {disputedTrans.map(t => (
              <TransferDisputeCard
                key={t.id}
                transfer={t}
                userNode={user?.node}
                userRole={user?.role}
                canAccessAllNodes={!!user?.can_access_all_nodes}
                onChanged={async (msg) => { setTransferNotice(msg); setTransferActionError(null); await loadData(); }}
              />
            ))}

            {/* Confirmed history */}
            {transfers.filter(t => t.transfer_status === 'CONFIRMED' && (!effectiveNode || isNode(t.from_node) || isNode(t.to_node))).slice(0, 3).length > 0 && (
              <div>
                <h4 style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-muted))', marginBottom: '5px', textTransform: 'uppercase' }}>Transferts Récents Confirmés</h4>
                {transfers.filter(t => t.transfer_status === 'CONFIRMED' && (!effectiveNode || isNode(t.from_node) || isNode(t.to_node))).slice(0, 3).map(t => (
                  <div key={t.id} style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))', display: 'flex', justifyContent: 'space-between', padding: '3px 6px', backgroundColor: 'hsl(var(--color-success) / 0.04)', borderRadius: '3px', marginBottom: '2px' }}>
                    <span>
                      {t.flow === 'DIRECT' ? `Envoi direct de ${t.from_node_display} → ${t.to_node_display}` : `${t.from_node_display} → ${t.to_node_display}`}
                      {(t.lines || []).map(l => <span key={l.bread_price} style={{ marginLeft: '5px' }}>{l.bread_price_display}: {l.quantity_received ?? l.quantity_sent}</span>)}
                    </span>
                    <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>✓</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
  );
};
