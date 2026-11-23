import React from 'react';
import { FiPackage } from 'react-icons/fi';
import type { ProductionSession, BreadDisposal, BakeryNode, BreadPrice } from '@/api/services';
import type { UserProfile } from '@/store/authStore';
import { ReconciliationPanel } from './ReconciliationPanel';
import { DISPOSAL_CREATE_LABELS } from './productionHelpers';
import { DisposalJournal } from './DisposalJournal';

export interface ReconciliationTabProps {
  sessions: ProductionSession[];
  disposals: BreadDisposal[];
  nodes: BakeryNode[];
  breadPrices: BreadPrice[];
  dSession: string;
  setDSession: React.Dispatch<React.SetStateAction<string>>;
  dType: BreadDisposal['disposal_type'];
  setDType: React.Dispatch<React.SetStateAction<BreadDisposal['disposal_type']>>;
  dBreadPrice: string;
  setDBreadPrice: React.Dispatch<React.SetStateAction<string>>;
  dQty: number;
  setDQty: React.Dispatch<React.SetStateAction<number>>;
  dNotes: string;
  setDNotes: React.Dispatch<React.SetStateAction<string>>;
  dError: string | null;
  user: UserProfile | null;
  workDate: string;
  effectiveNode: string;
  handleDisposal: (e: React.FormEvent<HTMLFormElement>) => Promise<void>;
}

export const ReconciliationTab: React.FC<ReconciliationTabProps> = ({ sessions, disposals, nodes, breadPrices, dSession, setDSession, dType, setDType, dBreadPrice, setDBreadPrice, dQty, setDQty, dNotes, setDNotes, dError, user, workDate, effectiveNode, handleDisposal }) => {
  return (
      <div className="glass-card" style={{ padding: '16px' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
          §3.4 — Réconciliation & Pains Non Valorisés
        </h2>

        {/* BUG-051 : écart production déclarée vs ventes livrées + retours (CLAUDE.md §5.4) */}
        <ReconciliationPanel
          effectiveNode={effectiveNode}
          canPickNode={!!user?.can_access_all_nodes}
          nodes={nodes}
        />

        <div className="split-grid" style={{ '--split-cols': '1.1fr 1.9fr', gap: '16px' } as React.CSSProperties}>

          {/* DISPOSAL FORM — only for bakery-level users (node assigned) */}
          <div>
            <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '8px', color: 'hsl(var(--text-secondary))' }}>Enregistrer une Sortie Non Standard</h3>
            {!user?.node ? (
              <p style={{ fontSize: '0.7rem', color: 'hsl(var(--text-muted))', fontStyle: 'italic' }}>
                Disponible uniquement pour les gérants de boulangerie.
              </p>
            ) : (
            <form onSubmit={handleDisposal} style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '3px', textTransform: 'uppercase' }}>Session de Production *</label>
                <select value={dSession} onChange={e => setDSession(e.target.value)} className="form-input" style={{ fontSize: '0.68rem', height: '30px' }}>
                  <option value="">— Sélectionner la fournée —</option>
                  {sessions.filter(s => s.date === workDate).map(s => (
                    <option key={s.id} value={s.id}>
                      Éq.{s.team} · {s.node_display || s.node} · {s.total_breads} pains
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Nature de la Sortie *</label>
                <select value={dType} onChange={e => setDType(e.target.value as BreadDisposal['disposal_type'])} className="form-input" style={{ fontSize: '0.72rem', height: '30px' }}>
                  {Object.entries(DISPOSAL_CREATE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                {dType === 'REMAINING' && (
                  <p style={{ fontSize: '0.6rem', color: 'hsl(var(--accent-color))', margin: '3px 0 0' }}>
                    Ces pains restent dans le stock — ils s'ajouteront automatiquement à la prochaine fournée.
                  </p>
                )}
                <p style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', margin: '5px 0 0', fontStyle: 'italic' }}>
                  Pour une vente soldée avec un client, utilisez Facturation / Gestion Clientèle
                  (« Vente Soldée ») — la perte y est calculée automatiquement par rapport au prix catalogue.
                </p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '6px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Catégorie Pain *</label>
                  <select value={dBreadPrice} onChange={e => setDBreadPrice(e.target.value)} className="form-input" style={{ fontSize: '0.72rem', height: '30px' }}>
                    <option value="">—</option>
                    {breadPrices.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Qté *</label>
                  <input type="number" min={1} value={dQty || ''} placeholder="0" onChange={e => setDQty(Math.max(0, Number(e.target.value)))} className="form-input" style={{ fontSize: '0.75rem', height: '30px', padding: '0 6px', width: '70px' }} />
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Notes / Bénéficiaire</label>
                <input type="text" value={dNotes} onChange={e => setDNotes(e.target.value)} placeholder="Motif, destinataire..." className="form-input" style={{ fontSize: '0.7rem', height: '28px', padding: '0 6px' }} />
              </div>
              {dError && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)' }}>{dError}</div>}
              <button type="submit" className="btn btn-primary" style={{ padding: '6px', fontSize: '0.73rem' }}>Enregistrer</button>
            </form>
            )}
          </div>

          {/* DISPOSAL LOG */}
          <DisposalJournal defaultDisposals={disposals} workDate={workDate} effectiveNode={effectiveNode} />
        </div>
      </div>
  );
};
