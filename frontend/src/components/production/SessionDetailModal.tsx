import React from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import type { ProductionSession } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { productionApi } from '@/api/services';
import { GapBadge } from './GapBadge';
import { mergeSessionLines } from './mergeSessionLines';
import { carryoverLines } from './mergeSessionLines';
import { ClosureSummaryCard } from './ReconciliationPanel';

export interface SessionDetailModalProps {
  selectedSession: ProductionSession;
  setSelectedSession: React.Dispatch<React.SetStateAction<ProductionSession | null>>;
  sessionNotes: string;
  setSessionNotes: React.Dispatch<React.SetStateAction<string>>;
  savingNotes: boolean;
  setSavingNotes: React.Dispatch<React.SetStateAction<boolean>>;
  setCloseSessionModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  setHistorySessions: React.Dispatch<React.SetStateAction<ProductionSession[]>>;
}

export const SessionDetailModal: React.FC<SessionDetailModalProps> = ({ selectedSession, setSelectedSession, sessionNotes, setSessionNotes, savingNotes, setSavingNotes, setCloseSessionModalOpen, setHistorySessions }) => {
  return (
        <Modal
          isOpen={true}
          onClose={() => setSelectedSession(null)}
          title="Détail Fournée"
          maxWidth="460px"
        >
            {/* Closed status */}
            {selectedSession.is_closed && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--color-success))', backgroundColor: 'hsl(var(--color-success) / 0.1)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '10px' }}>
                <FiCheckCircle />
                Fournée clôturée{selectedSession.closed_at ? ` le ${new Date(selectedSession.closed_at).toLocaleString('fr-FR')}` : ''} — saisie verrouillée.
              </div>
            )}

            {/* Session summary */}
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '10px 14px', marginBottom: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.75rem' }}>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Boulangerie</div>
                  <div style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{selectedSession.node_display || selectedSession.node}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Date · Équipe</div>
                  <div style={{ fontWeight: 700 }}>{selectedSession.date} — Éq.{selectedSession.team}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Pains Produits</div>
                  <div style={{ fontWeight: 800 }}>{selectedSession.total_breads} pains</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Farine Utilisée</div>
                  <div style={{ fontWeight: 700 }}>{selectedSession.flour_sacks_used} sacs</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Valeur Produite</div>
                  <div style={{ fontWeight: 800, color: 'hsl(var(--color-success))' }}>{(selectedSession.total_fc_produced || 0).toLocaleString('fr-FR')} FC</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Rendement</div>
                  {(() => {
                    const rPct = selectedSession.theoretical_yield > 0 ? ((selectedSession.total_fc_produced || 0) / selectedSession.theoretical_yield) * 100 : 0;
                    const rColor = rPct >= 90 ? 'hsl(var(--color-success))' : rPct >= 75 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                    return <div style={{ fontWeight: 800, color: rColor }}>{rPct.toFixed(1)}%</div>;
                  })()}
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Écart</div>
                  <GapBadge session={selectedSession} fontSize="0.78rem" />
                </div>
              </div>
            </div>

            {/* Breakdown by bread category */}
            {selectedSession.lines && selectedSession.lines.length > 0 && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '6px' }}>
                  Production par Catégorie
                </div>
                <div style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.72rem' }}>
                    <thead>
                      <tr style={{ backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.62rem', textTransform: 'uppercase', color: 'hsl(var(--text-muted))' }}>
                        <th style={{ padding: '5px 10px', textAlign: 'left', fontWeight: 700 }}>Catégorie</th>
                        <th style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700 }}>Qté</th>
                        <th style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700 }}>PU</th>
                        <th style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700 }}>Total FC</th>
                      </tr>
                    </thead>
                    <tbody>
                      {mergeSessionLines(selectedSession.lines).map((line, i) => (
                        <tr key={i} style={{ borderTop: '1px solid hsl(var(--border-color))' }}>
                          <td style={{ padding: '5px 10px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>
                            {line.bread_price_display || `Pain ${line.unit_price} FC`}
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 800 }}>{line.quantity}</td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', color: 'hsl(var(--text-muted))' }}>{(line.unit_price || 0).toLocaleString('fr-FR')} FC</td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700, color: 'hsl(var(--color-success))' }}>
                            {(line.line_fc ?? line.quantity * (line.unit_price || 0)).toLocaleString('fr-FR')} FC
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr style={{ borderTop: '2px solid hsl(var(--border-color))', backgroundColor: 'hsl(var(--bg-tertiary))' }}>
                        <td colSpan={2} style={{ padding: '5px 10px', fontWeight: 800, fontSize: '0.68rem' }}>TOTAL</td>
                        <td />
                        <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>
                          {(selectedSession.total_fc_produced || 0).toLocaleString('fr-FR')} FC
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
                {carryoverLines(selectedSession.lines).length > 0 && (
                  <div style={{ marginTop: '6px', fontSize: '0.68rem', color: 'hsl(var(--text-muted))' }}>
                    Reste d'hier confirmé (non compté dans le total) :{' '}
                    {carryoverLines(selectedSession.lines)
                      .map(l => `${l.quantity} × ${l.bread_price_display || `Pain ${l.unit_price} FC`}`)
                      .join(', ')}
                  </div>
                )}
              </div>
            )}

            {/* BUG-108 : recoupement automatique figé à la clôture */}
            {selectedSession.is_closed && selectedSession.closure_summary && (
              <div style={{ marginBottom: '14px', paddingTop: '10px', borderTop: '1px solid hsl(var(--border-color))' }}>
                <ClosureSummaryCard summary={selectedSession.closure_summary} />
              </div>
            )}

            {/* Notes */}
            <div>
              <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>
                Commentaires / Observations
              </label>
              <textarea
                value={sessionNotes}
                onChange={e => setSessionNotes(e.target.value)}
                rows={4}
                disabled={selectedSession.is_closed}
                placeholder="Saisir vos observations sur cette fournée..."
                className="form-input"
                style={{ resize: 'vertical', fontSize: '0.78rem', padding: '8px 10px', lineHeight: 1.5, opacity: selectedSession.is_closed ? 0.6 : 1 }}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '14px', flexWrap: 'wrap' }}>
              <button onClick={() => setSelectedSession(null)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>
                Fermer
              </button>
              {!selectedSession.is_closed && (
                <button
                  onClick={async () => {
                    setSavingNotes(true);
                    try {
                      await productionApi.sessions.update(selectedSession.id, { notes: sessionNotes });
                      setHistorySessions(prev => prev.map(s => s.id === selectedSession.id ? { ...s, notes: sessionNotes } : s));
                      setSelectedSession(null);
                    } catch (err) {
                      console.error('Failed to save notes', err);
                    }
                    setSavingNotes(false);
                  }}
                  disabled={savingNotes}
                  className="btn btn-primary"
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', opacity: savingNotes ? 0.6 : 1 }}
                >
                  {savingNotes ? 'Enregistrement...' : 'Sauvegarder le commentaire'}
                </button>
              )}
              {!selectedSession.is_closed && (
                <button
                  onClick={() => setCloseSessionModalOpen(true)}
                  className="btn btn-primary"
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', backgroundColor: 'hsl(var(--color-success))', borderColor: 'hsl(var(--color-success))' }}
                >
                  <FiCheckCircle style={{ marginRight: '4px', verticalAlign: '-2px' }} />
                  Clôturer la fournée
                </button>
              )}
            </div>
        </Modal>
  );
};
