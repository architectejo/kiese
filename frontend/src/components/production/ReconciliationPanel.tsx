import React, { useCallback, useEffect, useState } from 'react';
import { FiAlertTriangle, FiRefreshCw } from 'react-icons/fi';
import { useWorkDate } from '@/store/workDateStore';
import { productionApi, ProductionReconciliation, ProductionClosureSummary, BakeryNode } from '@/api/services';

const formatFC = (n: number) => n.toLocaleString('fr-FR') + ' FC';


interface ReconciliationPanelProps {
  /** Boulangerie actuellement affichée par le reste de la page (Direction : sélecteur en-tête ; gérant : fixe). */
  effectiveNode: string;
  /** Nœud assigné à l'utilisateur, utilisé comme repli si `effectiveNode` est vide. */
  canPickNode: boolean;
  nodes: BakeryNode[];
}

/**
 * BUG-051 — §3.4 : affiche l'écart entre la production déclarée et
 * (ventes livrées + retours), en pains et en FC, pour une boulangerie et
 * une période données (CLAUDE.md §5.4), en consommant
 * GET /api/production/sessions/reconciliation/.
 */
export const ReconciliationPanel: React.FC<ReconciliationPanelProps> = ({ effectiveNode, canPickNode, nodes }) => {
  const [recNode, setRecNode]       = useState(effectiveNode);
  // BUG-161 (F3) : bornes par défaut = 1er du mois et jour de la journée de travail du serveur
  // (plus de date UTC du navigateur) ; une date choisie par l'utilisateur prime.
  const workDate = useWorkDate();
  const [dateFromPicked, setDateFrom] = useState<string | null>(null);
  const [dateToPicked, setDateTo]     = useState<string | null>(null);
  const dateFrom = dateFromPicked ?? `${workDate.slice(0, 8)}01`;
  const dateTo   = dateToPicked ?? workDate;
  const [data, setData]             = useState<ProductionReconciliation | null>(null);
  const [loading, setLoading]       = useState(false);
  const [error, setError]           = useState<string | null>(null);

  // Keep the local node filter aligned with the page-level selector (Direction switches bakery).
  useEffect(() => { setRecNode(effectiveNode); }, [effectiveNode]);

  const fetchReconciliation = useCallback(async (node: string, from: string, to: string) => {
    setLoading(true);
    setError(null);
    try {
      const res = await productionApi.sessions.reconciliation({
        ...(node ? { node } : {}),
        date_from: from,
        date_to: to,
      });
      setData(res.data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Erreur lors du calcul de la réconciliation.');
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReconciliation(recNode, dateFrom, dateTo);
  }, [recNode, dateFrom, dateTo, fetchReconciliation]);

  const gapBreads = data ? data.gap.breads : 0;
  const gapFc     = data ? parseFloat(data.gap.fc) : 0;
  const gapColor  = gapBreads >= 0 ? 'var(--color-success)' : 'var(--color-danger)';

  return (
    <div style={{ marginBottom: '16px', paddingBottom: '14px', borderBottom: '1px solid hsl(var(--border-color))' }}>
      <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '8px', color: 'hsl(var(--text-secondary))' }}>
        Écart Production ↔ Ventes + Retours
      </h3>

      {/* Filtres boulangerie/période */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px', marginBottom: '10px', alignItems: 'flex-end' }}>
        {canPickNode && (
          <div>
            <label style={{ display: 'block', fontSize: '0.58rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Boulangerie</label>
            <select value={recNode} onChange={e => setRecNode(e.target.value)} className="form-input" style={{ fontSize: '0.68rem', height: '28px', minWidth: '140px' }}>
              <option value="">Toutes</option>
              {nodes.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
            </select>
          </div>
        )}
        <div>
          <label style={{ display: 'block', fontSize: '0.58rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Du</label>
          <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="form-input" style={{ fontSize: '0.68rem', height: '28px' }} />
        </div>
        <div>
          <label style={{ display: 'block', fontSize: '0.58rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Au</label>
          <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="form-input" style={{ fontSize: '0.68rem', height: '28px' }} />
        </div>
        <button
          type="button"
          onClick={() => fetchReconciliation(recNode, dateFrom, dateTo)}
          disabled={loading}
          className="btn btn-secondary"
          style={{ padding: '5px 10px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '4px', height: '28px' }}
        >
          <FiRefreshCw style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
          Actualiser
        </button>
      </div>

      {error && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '8px' }}>
          <FiAlertTriangle /> {error}
        </div>
      )}

      {loading && !data && (
        <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>Calcul en cours...</div>
      )}

      {!loading && !error && data && (
        <>
          <div className="kpi-grid" style={{ gap: '8px', marginBottom: '8px' }}>
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
              <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Produit déclaré</div>
              <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{data.production_declared.breads} pains</div>
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(parseFloat(data.production_declared.fc))}</div>
            </div>
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
              <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Ventes livrées</div>
              <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{data.sales.breads} pains</div>
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(parseFloat(data.sales.fc))}</div>
            </div>
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
              <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Retours (soldés/déclassés/invendus/dons)</div>
              <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{data.returns.breads} pains</div>
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(parseFloat(data.returns.fc))}</div>
            </div>
            <div style={{ backgroundColor: `hsl(${gapColor} / 0.1)`, border: `1px solid hsl(${gapColor} / 0.35)`, borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
              <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>
                {gapBreads >= 0 ? 'Écart (reste non valorisé)' : 'Écart (sorti plus que déclaré)'}
              </div>
              <div style={{ fontWeight: 800, fontSize: '0.8rem', color: `hsl(${gapColor})` }}>
                {gapBreads >= 0 ? '+' : ''}{gapBreads} pains
              </div>
              <div style={{ fontSize: '0.62rem', fontWeight: 700, color: `hsl(${gapColor})` }}>
                {gapFc >= 0 ? '+' : ''}{formatFC(gapFc)}
              </div>
            </div>
          </div>
          {gapBreads < 0 && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.62rem', color: 'hsl(var(--color-danger))' }}>
              <FiAlertTriangle /> Écart négatif : plus de pains sortis (ventes + retours) que de pains déclarés produits sur cette période — à investiguer.
            </div>
          )}
        </>
      )}
    </div>
  );
};

/**
 * BUG-108 — recoupement automatique figé par
 * `POST /api/production/sessions/{id}/close/` (clôture de fournée, CLAUDE.md §5.4).
 * Même présentation que `ReconciliationPanel` (grille KPI) pour une session unique,
 * plus le reliquat NV et l'avertissement d'anomalie (non bloquant côté serveur).
 */
export const ClosureSummaryCard: React.FC<{ summary: ProductionClosureSummary }> = ({ summary }) => {
  const gapBreads = summary.gap.breads;
  const gapFc     = parseFloat(summary.gap.fc);
  const gapColor  = gapBreads >= 0 ? 'var(--color-success)' : 'var(--color-danger)';

  return (
    <div>
      <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '8px', color: 'hsl(var(--text-secondary))' }}>
        Recoupement automatique à la clôture
      </h3>

      {summary.anomaly && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '10px', fontWeight: 700 }}>
          <FiAlertTriangle /> Anomalie : ventes + retours dépassent la production déclarée — à investiguer (la clôture n'a pas été bloquée).
        </div>
      )}

      <div className="kpi-grid" style={{ gap: '8px', marginBottom: '8px' }}>
        <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Produit déclaré</div>
          <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{summary.production_declared.breads} pains</div>
          <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(parseFloat(summary.production_declared.fc))}</div>
        </div>
        <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Vendu (livré ce jour)</div>
          <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{summary.sales.breads} pains</div>
          <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(parseFloat(summary.sales.fc))}</div>
        </div>
        <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Soldé/déclassé/invendu/don</div>
          <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{summary.returns.breads} pains</div>
          <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(parseFloat(summary.returns.fc))}</div>
        </div>
        <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>Reliquat NV (à reporter)</div>
          <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{summary.nv.breads} pains</div>
        </div>
        <div style={{ backgroundColor: `hsl(${gapColor} / 0.1)`, border: `1px solid hsl(${gapColor} / 0.35)`, borderRadius: 'var(--radius-sm)', padding: '8px 10px' }}>
          <div style={{ fontSize: '0.56rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase' }}>
            {gapBreads >= 0 ? 'Écart final (excédent)' : 'Écart final (manquant)'}
          </div>
          <div style={{ fontWeight: 800, fontSize: '0.8rem', color: `hsl(${gapColor})` }}>
            {gapBreads >= 0 ? '+' : ''}{gapBreads} pains
          </div>
          <div style={{ fontSize: '0.62rem', fontWeight: 700, color: `hsl(${gapColor})` }}>
            {gapFc >= 0 ? '+' : ''}{formatFC(gapFc)}
          </div>
        </div>
      </div>
    </div>
  );
};
