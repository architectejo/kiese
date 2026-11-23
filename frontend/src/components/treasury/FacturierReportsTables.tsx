import React from 'react';
import type { FacturierReport } from '@/api/services';
import { fmt, renderReportCategoryDetail } from '@/components/treasury/treasuryShared';

interface ReportsTableProps {
  reports: FacturierReport[];
  isLoading: boolean;
  error: string | null;
  onRetry: () => void;
  canAccessAllNodes: boolean;
  reportsReady: boolean;
  progress: string;
  totalCash: number;
  totalCredit: number;
  theoreticalCash: number;
  onValidate: (id: string) => void;
}

/** §5.1.1 — Table des rapports du jour (états d'erreur, de chargement et vide inclus). */
export const FacturierReportsTable: React.FC<ReportsTableProps> = ({
  reports, isLoading, error, onRetry, canAccessAllNodes, reportsReady, progress,
  totalCash, totalCredit, theoreticalCash, onValidate,
}) => {
  // §5.1.1 — Group reports by bakery for DIRECTION view
  const reportsByNode: Record<string, FacturierReport[]> = {};
  reports.forEach(r => {
    const key = r.node_display || r.node;
    if (!reportsByNode[key]) reportsByNode[key] = [];
    reportsByNode[key].push(r);
  });

  return (
    <>
      {error && (
        <div role="alert" style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)', marginBottom: '8px', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
          {error}
          <button onClick={onRetry} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
        </div>
      )}
      {isLoading && reports.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))', fontSize: '0.75rem' }}>Chargement des rapports…</div>
      ) : reports.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))', fontSize: '0.75rem' }}>
          Aucun rapport pour aujourd'hui — cliquez sur "Générer Rapport du Jour" pour agréger les ventes livrées.
        </div>
      ) : (
        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                <th>Boulangerie</th>
                <th style={{ textAlign: 'center' }}>Équipe</th>
                <th style={{ textAlign: 'right' }}>Cash FC</th>
                <th style={{ textAlign: 'right' }}>Crédit FC</th>
                <th style={{ textAlign: 'right' }}>Théorique Caisse</th>
                <th style={{ textAlign: 'center' }}>Statut</th>
                <th style={{ textAlign: 'center' }}>Action</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.72rem' }}>
              {canAccessAllNodes
                ? Object.entries(reportsByNode).flatMap(([nodeName, nodeReports]) => {
                    const nodeCash   = nodeReports.reduce((s, r) => s + parseFloat(r.total_cash_sales   || '0'), 0);
                    const nodeCredit = nodeReports.reduce((s, r) => s + parseFloat(r.total_credit_sales || '0'), 0);
                    const nodeTheo   = nodeReports.reduce((s, r) => s + parseFloat(r.theoretical_cash   || '0'), 0);
                    return [
                      <tr key={`hdr-${nodeName}`} style={{ backgroundColor: 'hsl(var(--accent-color) / 0.07)' }}>
                        <td colSpan={7} style={{ fontSize: '0.62rem', fontWeight: 800, color: 'hsl(var(--accent-color))', padding: '4px 8px', letterSpacing: '0.03em', textTransform: 'uppercase' }}>
                          {nodeName}
                        </td>
                      </tr>,
                      ...nodeReports.map(r => (
                        <tr key={r.id}>
                          <td style={{ paddingLeft: '16px' }}>
                            <span className="badge badge-info" style={{ fontSize: '0.52rem' }}>Éq. {r.team}</span>
                          </td>
                          <td />
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>{fmt(r.total_cash_sales)}</td>
                          <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(r.total_credit_sales)}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-warning))' }}>{fmt(r.theoretical_cash)}</td>
                          <td style={{ textAlign: 'center' }}>
                            <span className={`badge ${r.is_validated ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.52rem' }}>
                              {r.is_validated ? 'VALIDÉ' : 'EN ATTENTE'}
                            </span>
                          </td>
                          <td style={{ textAlign: 'center' }}>
                            {!r.is_validated && (
                              <button onClick={() => onValidate(r.id)} className="btn btn-primary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Valider</button>
                            )}
                          </td>
                        </tr>
                      )).flatMap(row => {
                        const r = nodeReports.find(rr => rr.id === row.key);
                        const detail = r ? renderReportCategoryDetail(r) : null;
                        return detail ? [row, detail] : [row];
                      }),
                      <tr key={`sub-${nodeName}`} style={{ fontWeight: 700, backgroundColor: 'hsl(var(--bg-secondary))', borderTop: '1px solid hsl(var(--border-color))' }}>
                        <td colSpan={2} style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))', paddingLeft: '8px' }}>Sous-total {nodeName}</td>
                        <td style={{ textAlign: 'right', color: 'hsl(var(--color-success))' }}>{reportsReady ? `${fmt(nodeCash)} FC` : '…'}</td>
                        <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{reportsReady ? `${fmt(nodeCredit)} FC` : '…'}</td>
                        <td style={{ textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{reportsReady ? `${fmt(nodeTheo)} FC` : '…'}</td>
                        <td colSpan={2} />
                      </tr>,
                    ];
                  })
                : reports.flatMap(r => {
                    const row = (
                      <tr key={r.id}>
                        <td style={{ fontWeight: 700 }}>{r.node_display || r.node}</td>
                        <td style={{ textAlign: 'center' }}>
                          <span className="badge badge-info" style={{ fontSize: '0.55rem' }}>Équipe {r.team}</span>
                        </td>
                        <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>{fmt(r.total_cash_sales)}</td>
                        <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(r.total_credit_sales)}</td>
                        <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-warning))' }}>{fmt(r.theoretical_cash)}</td>
                        <td style={{ textAlign: 'center' }}>
                          <span className={`badge ${r.is_validated ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.52rem' }}>
                            {r.is_validated ? 'VALIDÉ' : 'EN ATTENTE'}
                          </span>
                        </td>
                        <td style={{ textAlign: 'center' }}>
                          {!r.is_validated && (
                            <button onClick={() => onValidate(r.id)} className="btn btn-primary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>
                              Valider
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                    const detail = renderReportCategoryDetail(r);
                    return detail ? [row, detail] : [row];
                  })
              }
              {/* Grand total row */}
              <tr style={{ fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))' }}>
                <td colSpan={2} style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>TOTAUX DU JOUR</td>
                {reportsReady ? (
                  <>
                    <td style={{ textAlign: 'right', color: 'hsl(var(--color-success))' }}>{fmt(totalCash)} FC</td>
                    <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(totalCredit)} FC</td>
                    <td style={{ textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{fmt(theoreticalCash)} FC</td>
                  </>
                ) : (
                  <td colSpan={3} style={{ textAlign: 'right', fontSize: '0.62rem', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progress}</td>
                )}
                <td colSpan={2} />
              </tr>
            </tbody>
          </table>
        </div>
      )}
    </>
  );
};

interface PastReportsProps {
  reports: FacturierReport[];
  onValidate: (id: string) => void;
  onPrint: (r: FacturierReport) => void;
}

/** BUG-175 — Rapports rétroactifs (hors totaux et validation du jour). */
export const PastReportsTable: React.FC<PastReportsProps> = ({ reports, onValidate, onPrint }) => {
  if (reports.length === 0) return null;
  return (
    <div style={{ marginTop: '12px', overflowX: 'auto' }}>
      <div style={{ fontSize: '0.62rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
        Rapports rétroactifs (hors totaux et validation du jour)
      </div>
      <table className="premium-table">
        <thead>
          <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
            <th>Date</th><th>Boulangerie</th><th style={{ textAlign: 'center' }}>Équipe</th>
            <th style={{ textAlign: 'right' }}>Cash FC</th><th style={{ textAlign: 'right' }}>Crédit FC</th>
            <th style={{ textAlign: 'right' }}>Théorique Caisse</th><th style={{ textAlign: 'center' }}>Statut</th>
            <th style={{ textAlign: 'center' }}>Action</th>
          </tr>
        </thead>
        <tbody style={{ fontSize: '0.72rem' }}>
          {reports.map(r => (
            <tr key={r.id}>
              <td>{new Date(r.date).toLocaleDateString('fr-FR')}</td>
              <td style={{ fontWeight: 700 }}>{r.node_display || r.node}</td>
              <td style={{ textAlign: 'center' }}>Équipe {r.team}</td>
              <td style={{ textAlign: 'right' }}>{fmt(r.total_cash_sales)}</td>
              <td style={{ textAlign: 'right' }}>{fmt(r.total_credit_sales)}</td>
              <td style={{ textAlign: 'right' }}>{fmt(r.theoretical_cash)}</td>
              <td style={{ textAlign: 'center' }}>
                <span className={`badge ${r.is_validated ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.52rem' }}>
                  {r.is_validated ? 'VALIDÉ' : 'EN ATTENTE'}
                </span>
              </td>
              <td style={{ textAlign: 'center', whiteSpace: 'nowrap' }}>
                {!r.is_validated && (
                  <button onClick={() => onValidate(r.id)} className="btn btn-primary" style={{ padding: '2px 8px', fontSize: '0.62rem', marginRight: '4px' }}>Valider</button>
                )}
                <button onClick={() => onPrint(r)} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Imprimer</button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
};
