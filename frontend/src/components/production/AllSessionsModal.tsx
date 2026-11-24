import React from 'react';
import type { ProductionSession } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { GapBadge } from './GapBadge';

export interface AllSessionsModalProps {
  showAllSessionsModal: boolean;
  setShowAllSessionsModal: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedSession: React.Dispatch<React.SetStateAction<ProductionSession | null>>;
  setSessionNotes: React.Dispatch<React.SetStateAction<string>>;
  historySessions: ProductionSession[];
}

export const AllSessionsModal: React.FC<AllSessionsModalProps> = ({ showAllSessionsModal, setShowAllSessionsModal, setSelectedSession, setSessionNotes, historySessions }) => {
  return (
      <Modal
        isOpen={showAllSessionsModal}
        onClose={() => setShowAllSessionsModal(false)}
        title={`Toutes les Fournées (${historySessions.length})`}
        maxWidth="560px"
        contentPadding="10px 14px"
        footer={<button onClick={() => setShowAllSessionsModal(false)} className="btn btn-secondary" style={{ width: '100%', fontSize: '0.8rem', padding: '7px' }}>Fermer</button>}
      >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              {historySessions.map(sess => {
                const tFC  = sess.total_fc_produced || 0;
                const thFC = sess.theoretical_yield || 0;
                const rPct = thFC > 0 ? (tFC / thFC) * 100 : 0;
                const rColor = rPct >= 90 ? 'hsl(var(--color-success))' : rPct >= 75 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                return (
                  <div
                    key={sess.id}
                    onClick={() => { setShowAllSessionsModal(false); setSelectedSession(sess); setSessionNotes(sess.notes || ''); }}
                    style={{ padding: '7px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.68rem', cursor: 'pointer', transition: 'background-color 0.15s' }}
                    onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'hsl(var(--bg-tertiary))')}
                    onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                  >
                    <div>
                      <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{sess.node_display || sess.node}</span>
                      <span style={{ marginLeft: '6px', color: 'hsl(var(--text-secondary))' }}>{sess.date} — Éq.{sess.team}</span>
                      {sess.is_closed && <span className="badge badge-info" style={{ fontSize: '0.55rem', marginLeft: '6px' }}>Clôturée</span>}
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginTop: '1px' }}>
                        {sess.total_breads} pains · {sess.flour_sacks_used} sacs · {tFC.toLocaleString('fr-FR')} FC
                        {sess.notes && <span style={{ marginLeft: '4px', color: 'hsl(var(--accent-color))' }}>💬</span>}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontWeight: 800, fontSize: '0.72rem', color: rColor }}>{rPct.toFixed(0)}%</div>
                      <GapBadge session={sess} />
                    </div>
                  </div>
                );
              })}
            </div>
      </Modal>
  );
};
