import React from 'react';
import { FiUsers, FiAlertTriangle, FiDollarSign, FiUserCheck } from 'react-icons/fi';
import { clientsApi } from '@/api/services';
import type { DeficitRow, StatModalKind } from './clientItem';

interface ClientsKpiGridProps {
  clientsTotalCount: number | null;
  kpiComplete: boolean;
  kpiPending: string;
  activeCount: number;
  overdueCount: number;
  totalOutstanding: number;
  setStatModal: (k: StatModalKind | null) => void;
  deficitData: DeficitRow[];
  setDeficitData: (rows: DeficitRow[]) => void;
  deficitLoading: boolean;
  setDeficitLoading: (v: boolean) => void;
}

/** Cartes de statistiques de la page clients (BUG-269 : valeurs définitives après lecture de toutes les pages). */
export const ClientsKpiGrid: React.FC<ClientsKpiGridProps> = ({
  clientsTotalCount, kpiComplete, kpiPending, activeCount, overdueCount, totalOutstanding,
  setStatModal, deficitData, setDeficitData, deficitLoading, setDeficitLoading,
}) => {
  return (
      <div className="kpi-grid" style={{ gap: '14px' }}>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--accent-color))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiUsers />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Total Clients</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--text-primary))' }}>{clientsTotalCount !== null ? clientsTotalCount : kpiPending} fiches</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--color-success))', fontWeight: 700 }}>Actifs : {kpiComplete ? activeCount : kpiPending}</span>
          </div>
        </div>

        <div className="glass-card" onClick={() => setStatModal('plafonds')} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-danger))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiAlertTriangle />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Plafonds Dépassés</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--color-danger))' }}>{kpiComplete ? overdueCount : kpiPending} alertes</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>BP à recouvrer</span>
          </div>
        </div>

        <div className="glass-card" onClick={() => setStatModal('encours')} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-info))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiDollarSign />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Encours Global</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--text-primary))' }}>{kpiComplete ? `${totalOutstanding.toLocaleString('fr-FR')} FC` : kpiPending}</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>BP active consolidée</span>
          </div>
        </div>

        <div className="glass-card" onClick={() => setStatModal('solvabilite')} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-success))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiUserCheck />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Solvabilité</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--color-success))' }}>A+ Stable</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>Risque moyen pondéré</span>
          </div>
        </div>

        <div
          className="glass-card"
          onClick={async () => {
            setStatModal('deficit');
            if (deficitData.length === 0 && !deficitLoading) {
              setDeficitLoading(true);
              try { const r = await clientsApi.deficitReport(); setDeficitData(r.data); }
              catch { /* ignore */ }
              finally { setDeficitLoading(false); }
            }
          }}
          style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}
        >
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-danger))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiAlertTriangle />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Déficitaires</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--color-danger))' }}>{deficitData.length > 0 ? `${deficitData.length} client(s)` : '—'}</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>BP &gt; CM période</span>
          </div>
        </div>
      </div>
  );
};
