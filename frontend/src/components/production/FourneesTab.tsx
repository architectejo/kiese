import React from 'react';
import type { ProductionSession, BreadStock, ServiceTeam } from '@/api/services';
import type { UserProfile } from '@/store/authStore';
import { StockDuJourSection } from './StockDuJourSection';
import { OpeningConfirmationManualSection } from './OpeningConfirmationManualSection';
import { BatchInProgressPanel } from './BatchInProgressPanel';
import { GapBadge } from './GapBadge';

export interface FourneesTabProps {
  breadStocks: BreadStock[];
  sacValueFc: number | null;
  viewNode: string;
  setShowAllSessionsModal: React.Dispatch<React.SetStateAction<boolean>>;
  setSelectedSession: React.Dispatch<React.SetStateAction<ProductionSession | null>>;
  setSessionNotes: React.Dispatch<React.SetStateAction<string>>;
  serviceTeam: ServiceTeam | null | undefined;
  setServiceTeam: React.Dispatch<React.SetStateAction<ServiceTeam | null | undefined>>;
  historySessions: ProductionSession[];
  historyLoading: boolean;
  historyError: string | null;
  setHistoryTick: React.Dispatch<React.SetStateAction<number>>;
  user: UserProfile | null;
  workDate: string;
  rotationActive: boolean;
  selectedDate: string;
  setSelectedDate: (iso: string) => void;
  currentNodeLabel: string | undefined;
  loadData: (nodeFilterArg?: string) => Promise<void>;
}

export const FourneesTab: React.FC<FourneesTabProps> = ({ breadStocks, sacValueFc, viewNode, setShowAllSessionsModal, setSelectedSession, setSessionNotes, serviceTeam, setServiceTeam, historySessions, historyLoading, historyError, setHistoryTick, user, workDate, rotationActive, selectedDate, setSelectedDate, currentNodeLabel, loadData }) => {
  return (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          {/* BUG-306 : déclaration par nombre de sacs + fournée en cours (BatchInProgressPanel). */}
          <BatchInProgressPanel
            nodeFilter={viewNode || user?.node || undefined}
            canDeclare={!!user?.node}
            workDate={workDate}
            rotationActive={rotationActive}
            serviceTeam={serviceTeam}
            onServiceTeam={setServiceTeam}
            sacValueFc={sacValueFc}
            onChanged={() => { void loadData(); setHistoryTick(t => t + 1); }}
          />

          {/* BUG-151 : accès manuel à la confirmation du reste d'hier pour une AUTRE
              équipe que celle déjà confirmée (même garde de rôle que la boîte modale
              automatique dans DashboardLayout.tsx). */}
          {/* BUG-161 : en rotation, une seule équipe de service par journée : confirmation pour
              « l'autre équipe » (BUG-151) sans objet, section masquée. */}
          {user && (user.role === 'GERANT' || user.role === 'FACTURIER' || user.role === 'LIVREUR') && !user.can_access_all_nodes && !rotationActive && (
            <OpeningConfirmationManualSection onConfirmed={() => loadData(viewNode || undefined)} />
          )}

          {/* Stock Pains du Jour — BUG-145 : extrait dans StockDuJourSection.tsx, piloté par
              `selectedDate`, qui pilote AUSSI « Historique des Fournées » ci-dessous. */}
          <StockDuJourSection
            selectedDate={selectedDate}
            onSelectDate={setSelectedDate}
            liveBreadStocks={breadStocks}
            nodeFilter={viewNode || undefined}
            currentNodeLabel={currentNodeLabel}
          />

          {/* Session history — BUG-145 : filtrée par la même `selectedDate` que ci-dessus. */}
          <div className="glass-card" style={{ padding: '12px 14px' }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: '8px' }}>
              Historique des Fournées
              {currentNodeLabel && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>{currentNodeLabel}</span>}
            </h3>
            {historyError && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '6px' }}>
                {historyError}
              </div>
            )}
            {historyLoading && (
              <div style={{ textAlign: 'center', padding: '10px', color: 'hsl(var(--text-secondary))', fontSize: '0.68rem' }}>Chargement...</div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              {!historyLoading && historySessions.slice(0, 2).map(sess => {
                const tFC  = sess.total_fc_produced || 0;
                const thFC = sess.theoretical_yield || 0;
                const rPct = thFC > 0 ? (tFC / thFC) * 100 : 0;
                const rColor = rPct >= 90 ? 'hsl(var(--color-success))' : rPct >= 75 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                return (
                  <div
                    key={sess.id}
                    onClick={() => { setSelectedSession(sess); setSessionNotes(sess.notes || ''); }}
                    style={{ padding: '6px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.68rem', cursor: 'pointer', transition: 'background-color 0.15s' }}
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
              {historySessions.length === 0 && !historyLoading && (
                <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>Aucune fournée ce jour-là</div>
              )}
              {historySessions.length > 2 && (
                <button
                  type="button"
                  onClick={() => setShowAllSessionsModal(true)}
                  style={{ marginTop: '4px', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--accent-color))', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 0', textAlign: 'center' }}
                >
                  ▼ Voir plus ({historySessions.length - 2} autres fournées)
                </button>
              )}
            </div>
          </div>
        </div>
  );
};
