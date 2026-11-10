import React, { useCallback, useEffect, useState } from 'react';
import { FiRefreshCw, FiAlertTriangle, FiCalendar, FiDownload, FiPrinter } from 'react-icons/fi';
import { coreApi, productionApi, BakeryNode, DailyClosureReport } from '@/api/services';
import { useAuthStore } from '@/store/authStore';
import { Modal } from '@/components/shared/Modal';
import { CalendarPicker } from '@/components/shared/CalendarPicker';
import { exportClotureToExcel, printClotureReport } from '@/utils/clotureReportExport';

// BUG-120 (volet frontend) : écran dédié « Clôture Journalière », réunissant en un seul
// document le rapport consolidé par catégorie de pain exigé par le client (son document
// Excel réel), plutôt qu'une section ajoutée à Production.tsx/Treasury.tsx.
// Contrat d'API exact : docs/qa/rapports/dev-backend-2026-11-02-bug120-corrections-client.md
// (toujours relire ce rapport avant toute modification des champs ci-dessous).

// Exportées pour réutilisation par l'export Excel / l'impression (BUG-153)
// — affichage uniquement, aucun calcul métier.
export const formatFC = (value: string | number | null | undefined): string => {
  if (value === null || value === undefined || value === '') return '—';
  const n = typeof value === 'string' ? parseFloat(value) : value;
  if (Number.isNaN(n)) return '—';
  return Math.round(n).toLocaleString('fr-FR') + ' FC';
};

export const formatQty = (n: number | null | undefined): string => {
  if (n === null || n === undefined) return '—';
  return n.toLocaleString('fr-FR');
};

const todayIso = () => new Date().toISOString().slice(0, 10);

type RepartitionMode = 'QUANTITE' | 'VALEUR';

export const ClotureJournaliere: React.FC = () => {
  const { user } = useAuthStore();

  const [nodes, setNodes] = useState<BakeryNode[]>([]);
  // Le backend accepte un code boulangerie (`?node=K1`) — on travaille toujours avec le
  // code plutôt que le pk interne, qui n'est jamais exposé à l'utilisateur.
  const [selectedNodeCode, setSelectedNodeCode] = useState('');
  const [date, setDate] = useState(todayIso());
  const [report, setReport] = useState<DailyClosureReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [repartitionMode, setRepartitionMode] = useState<RepartitionMode>('QUANTITE');
  // BUG-128 : calendrier dans une boîte modale (remarque.md l.394) à la place du
  // sélecteur natif du navigateur, pour revoir les résultats des jours passés.
  const [calendarOpen, setCalendarOpen] = useState(false);

  const myNodeCode = nodes.find(n => n.id === user?.node)?.code || '';
  const effectiveNodeCode = user?.can_access_all_nodes ? selectedNodeCode : myNodeCode;

  // Chargement de la liste des boulangeries — nécessaire même pour un gérant (non-HQ)
  // afin de résoudre son propre code à partir de `user.node` (identifiant interne).
  useEffect(() => {
    coreApi.nodes.list()
      .then(res => {
        const list = Array.isArray(res.data) ? res.data : [];
        setNodes(list);
        if (user?.can_access_all_nodes && list.length > 0 && !selectedNodeCode) {
          setSelectedNodeCode(list[0].code);
        }
      })
      .catch(() => setError('Impossible de charger la liste des boulangeries.'));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.can_access_all_nodes]);

  const fetchReport = useCallback(async (nodeCode: string, reportDate: string) => {
    if (!nodeCode || !reportDate) return;
    setLoading(true);
    setError(null);
    try {
      const res = await productionApi.dailyClosure.get(nodeCode, reportDate);
      setReport(res.data);
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Erreur lors du chargement du rapport de clôture journalière.');
      setReport(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (effectiveNodeCode && date) {
      fetchReport(effectiveNodeCode, date);
    }
  }, [effectiveNodeCode, date, fetchReport]);

  const totals = report?.totals;
  const repartitionRows = totals
    ? (repartitionMode === 'QUANTITE' ? totals.repartition_pct_par_quantite : totals.repartition_pct_par_valeur)
    : [];

  // BUG-153 : export Excel / impression du rapport — remarque.md (après l.410).
  const currentNode = nodes.find(n => n.code === effectiveNodeCode);
  const nodeLabel = currentNode ? `${currentNode.code} — ${currentNode.name}` : (effectiveNodeCode || '—');

  const handleExportExcel = () => {
    if (!report) return;
    exportClotureToExcel(report, nodeLabel, repartitionMode);
  };

  const handlePrint = () => {
    if (!report) return;
    printClotureReport(
      report,
      nodeLabel,
      repartitionRows,
      repartitionMode === 'QUANTITE' ? 'par quantité' : 'par valeur (FC)',
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px', fontSize: '0.85rem' }}>

      {/* En-tête */}
      <div className="glass-card animate-fade-in" style={{ background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)', borderLeft: '4px solid hsl(var(--accent-color))', padding: '14px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '2px' }}>Clôture Journalière</h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem' }}>
              Rapport consolidé par catégorie de pain — facture, reste, approvisionnement, ventes cash/soldée,
              dispositions, transferts, régularisations et totaux (document réuni, CLAUDE.md §5.4)
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px', flexWrap: 'wrap' }}>
            {user?.can_access_all_nodes && (
              <select
                value={selectedNodeCode}
                onChange={e => setSelectedNodeCode(e.target.value)}
                className="form-input"
                style={{ height: '32px', fontSize: '0.75rem', minWidth: '160px' }}
              >
                {nodes.map(n => (
                  <option key={n.id} value={n.code}>{n.code} — {n.name}</option>
                ))}
              </select>
            )}
            <button
              type="button"
              onClick={() => setCalendarOpen(true)}
              className="btn btn-secondary"
              style={{ height: '32px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px', padding: '5px 10px' }}
            >
              <FiCalendar />
              <span>{new Date(date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' })}</span>
            </button>
            <button
              onClick={() => fetchReport(effectiveNodeCode, date)}
              disabled={loading || !effectiveNodeCode}
              className="btn btn-secondary"
              style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px', height: '32px' }}
            >
              <FiRefreshCw style={{ animation: loading ? 'spin 1s linear infinite' : 'none' }} />
              <span>Actualiser</span>
            </button>
            <button
              onClick={handleExportExcel}
              disabled={!report}
              title="Exporter le rapport complet (KPI, répartition, décomposition) en Excel"
              className="btn btn-secondary"
              style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px', height: '32px' }}
            >
              <FiDownload />
              <span>Exporter en Excel</span>
            </button>
            <button
              onClick={handlePrint}
              disabled={!report}
              title="Imprimer le rapport complet (KPI, répartition, décomposition)"
              className="btn btn-secondary"
              style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px', height: '32px' }}
            >
              <FiPrinter />
              <span>Imprimer</span>
            </button>
          </div>
        </div>
      </div>

      {error && (
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.78rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '10px 14px', borderRadius: 'var(--radius-md)', border: '1px solid hsl(var(--color-danger) / 0.25)' }}>
          <FiAlertTriangle /> {error}
        </div>
      )}

      {!effectiveNodeCode && !error && (
        <div className="glass-card" style={{ padding: '24px', textAlign: 'center', color: 'hsl(var(--text-muted))' }}>
          Aucune boulangerie assignée à ce compte — contactez un administrateur.
        </div>
      )}

      {loading && !report && (
        <div className="glass-card" style={{ padding: '24px', textAlign: 'center', color: 'hsl(var(--text-muted))' }}>
          Chargement du rapport de clôture…
        </div>
      )}

      {!loading && !error && report && report.categories.length === 0 && (
        <div className="glass-card" style={{ padding: '24px', textAlign: 'center', color: 'hsl(var(--text-muted))' }}>
          Aucune donnée pour cette boulangerie à la date du {new Date(date).toLocaleDateString('fr-FR')}.
        </div>
      )}

      {report && totals && (
        <>
          {/* Bloc de totaux */}
          <div className="kpi-grid" style={{ gap: '12px' }}>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Total du Jour</div>
              <div style={{ fontSize: '1rem', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{formatFC(totals.total_du_jour_fc)}</div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Net Produit</div>
              <div style={{ fontSize: '1rem', fontWeight: 800, color: 'hsl(var(--color-success))' }}>{formatFC(totals.net_produit_fc)}</div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Écart / Facture</div>
              <div style={{ fontSize: '1rem', fontWeight: 800, color: parseFloat(totals.ecart_facture_fc) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-primary))' }}>
                {formatFC(totals.ecart_facture_fc)}
              </div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Nombre de Sacs Produits</div>
              <div style={{ fontSize: '1rem', fontWeight: 800 }}>{totals.nombre_sacs_produits}</div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Moyenne Produit / Sac</div>
              <div style={{ fontSize: '1rem', fontWeight: 800 }}>{formatFC(totals.moyenne_produit_par_sac_fc)}</div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Tarif Vente (fixe)</div>
              <div style={{ fontSize: '1rem', fontWeight: 800 }}>{formatFC(totals.tarif_vente_fc)}</div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Écart / Production</div>
              <div style={{ fontSize: '1rem', fontWeight: 800, color: parseFloat(totals.ecart_production_fc) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                {formatFC(totals.ecart_production_fc)}
              </div>
            </div>
            <div className="glass-card" style={{ padding: '10px 12px' }}>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>Pains Produits / Facturés</div>
              <div style={{ fontSize: '1rem', fontWeight: 800 }}>{formatQty(totals.total_breads_produced)} / {formatQty(totals.total_breads_billed)}</div>
            </div>
          </div>

          {/* Répartition en % — sélecteur quantité/valeur, aucun rechargement serveur */}
          <div className="glass-card" style={{ padding: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px', marginBottom: '10px' }}>
              <h2 style={{ fontSize: '0.88rem', fontWeight: 800 }}>Répartition par Catégorie</h2>
              <select
                value={repartitionMode}
                onChange={e => setRepartitionMode(e.target.value as RepartitionMode)}
                className="form-input"
                style={{ height: '30px', fontSize: '0.72rem', minWidth: '200px' }}
              >
                <option value="QUANTITE">Répartition par quantité</option>
                <option value="VALEUR">Répartition par valeur (FC)</option>
              </select>
            </div>
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table">
                <thead>
                  <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                    <th>Catégorie</th>
                    <th style={{ textAlign: 'right' }}>Part (%)</th>
                  </tr>
                </thead>
                <tbody style={{ fontSize: '0.72rem' }}>
                  {repartitionRows.length === 0 ? (
                    <tr><td colSpan={2} style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '12px' }}>Aucune donnée.</td></tr>
                  ) : (
                    repartitionRows.map(row => (
                      <tr key={row.bread_price}>
                        <td style={{ fontWeight: 700 }}>{row.label}</td>
                        <td style={{ textAlign: 'right', fontWeight: 800 }}>{row.pct} %</td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>

          {/* Tableau décomposé par catégorie de pain */}
          <div className="glass-card" style={{ padding: '14px' }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '10px' }}>
              Décomposition par Catégorie de Pain
              {report.node && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>{report.node}</span>}
            </h2>
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table" style={{ minWidth: '1600px' }}>
                <thead>
                  <tr style={{ fontSize: '0.58rem', textTransform: 'uppercase' }}>
                    <th>Catégorie</th>
                    <th style={{ textAlign: 'right' }}>Produit</th>
                    <th style={{ textAlign: 'right' }}>Facture/Jr</th>
                    <th style={{ textAlign: 'right' }}>CM/Jr</th>
                    <th style={{ textAlign: 'right' }}>Reste Jour (A)</th>
                    <th style={{ textAlign: 'right' }}>Reste Jour (B)</th>
                    <th style={{ textAlign: 'right' }}>Reste Hier (A)</th>
                    <th style={{ textAlign: 'right' }}>Reste Hier (B)</th>
                    <th style={{ textAlign: 'right' }}>Appro Effectué</th>
                    <th style={{ textAlign: 'right' }}>Appro Reçu</th>
                    <th style={{ textAlign: 'right' }}>Non Servi</th>
                    <th style={{ textAlign: 'right' }}>Régularisation</th>
                    <th style={{ textAlign: 'right' }}>Vente Cash/Soldée</th>
                    <th style={{ textAlign: 'right' }}>Perte (Soldée)</th>
                    <th style={{ textAlign: 'right' }}>Facture Mvm Interne</th>
                    <th style={{ textAlign: 'right' }}>Non Vendu (NV)</th>
                    <th style={{ textAlign: 'right' }}>Déclassés</th>
                    <th style={{ textAlign: 'right' }}>Sorties Gratuites</th>
                  </tr>
                </thead>
                <tbody style={{ fontSize: '0.7rem' }}>
                  {report.categories.map(cat => (
                    <tr key={cat.bread_price}>
                      <td style={{ fontWeight: 700, whiteSpace: 'nowrap' }}>{cat.label}</td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.produit.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.produit.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.facture_jr.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.facture_jr.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>{formatFC(cat.commission_jr.fc)}</td>
                      <td style={{ textAlign: 'right' }}>{formatQty(cat.reste_du_jour.A)}</td>
                      <td style={{ textAlign: 'right' }}>{formatQty(cat.reste_du_jour.B)}</td>
                      <td style={{ textAlign: 'right' }}>{formatQty(cat.reste_du_hier.A)}</td>
                      <td style={{ textAlign: 'right' }}>{formatQty(cat.reste_du_hier.B)}</td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.appro_effectue.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.appro_effectue.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.appro_recu.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.appro_recu.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.non_servi.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.non_servi.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.regularisation.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.regularisation.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.vente_cash_soldee.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.vente_cash_soldee.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right', color: parseFloat(cat.vente_cash_soldee.perte_fc) > 0 ? 'hsl(var(--color-danger))' : undefined }}>
                        {formatFC(cat.vente_cash_soldee.perte_fc)}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{formatFC(cat.facture_mvm_interne.fc)}</td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.non_vendu_nv.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.non_vendu_nv.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.declasses.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.declasses.fc)}</div>
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        {formatQty(cat.sorties_gratuites.quantity)}
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{formatFC(cat.sorties_gratuites.fc)}</div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <p style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '8px' }}>
              Excédent et manquant pains ne sont pas encore décomposés par catégorie dans le modèle actuel
              (uniquement disponibles au niveau global via « Écart / Production » ci-dessus) — voir
              docs/qa/rapports/dev-backend-2026-11-02-bug120-corrections-client.md.
            </p>
          </div>
        </>
      )}

      <Modal
        isOpen={calendarOpen}
        onClose={() => setCalendarOpen(false)}
        title="Choisir une date"
        subtitle="Consultez le rapport de clôture d'un jour passé."
        maxWidth="360px"
        contentPadding="12px 16px 16px"
      >
        <CalendarPicker
          value={date}
          onSelect={(iso) => {
            setDate(iso);
            setCalendarOpen(false);
          }}
        />
      </Modal>
    </div>
  );
};
