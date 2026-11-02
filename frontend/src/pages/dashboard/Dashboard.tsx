import React, { useState, useEffect } from 'react';
import { TrendChart, YieldDoughnut, DualTrendChart, ChartDataPoint, DoughnutDataPoint, DualChartDataPoint } from '@/components/shared/Charts';
import {
  FiShoppingBag, FiUsers,
  FiActivity, FiAlertTriangle, FiCheckCircle, FiRefreshCw,
  FiChevronRight, FiCalendar, FiPrinter
} from 'react-icons/fi';
import { salesApi, clientsApi, productionApi, Client, Invoice, ProductionSession } from '@/api/services';
import { useAuthStore } from '@/store/authStore';
import { ThermalReceipt, ReceiptData } from '@/components/shared/ThermalReceipt';
import { Modal } from '@/components/shared/Modal';

const buildReceipt = (inv: Invoice): ReceiptData => ({
  receiptNumber: inv.receipt_number,
  boulangerie: inv.node_display || inv.node || '—',
  agentName: inv.facturier_display || 'Facturier',
  team: inv.team || '—',
  clientCode: inv.client_code || '—',
  clientName: inv.client_display || inv.client,
  lines: (inv.lines || []).map(l => ({
    label: l.bread_price_display || l.bread_price,
    qty: l.quantity,
    unitPrice: parseFloat(l.unit_price || '0'),
  })),
  orderTotal: parseFloat(inv.order_total) || 0,
  versement: parseFloat(inv.payment_amount) || 0,
  commissionRate: inv.commission_rate != null ? parseFloat(inv.commission_rate) : 0,
  debtBefore: parseFloat(inv.debt_before) || 0,
  newDebt: parseFloat(inv.debt_after || '0'),
  isSoldee: inv.is_soldee === true,
});

interface DashboardData {
  totalClients: number;
  activeClients: number;
  clients: Client[];
  riskAlerts: Client[];
  invoices: Invoice[];
  dailySummaryRows: any[];
  dailySummary: { total: number; cash: number; credit: number };
  todaySessions: ProductionSession[];
}

type KpiModalKey = 'ca' | 'volume' | 'risk' | 'clients' | null;

const PALETTE = ['#f59e0b', '#10b981', '#3b82f6', '#ec4899', '#8b5cf6', '#ef4444', '#06b6d4', '#84cc16'];

export const Dashboard: React.FC = () => {
  const { user } = useAuthStore();
  const isHQ = !!user?.can_access_all_nodes;
  const [data, setData] = useState<DashboardData | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  const [kpiModal, setKpiModal] = useState<KpiModalKey>(null);
  const [invoicesModalOpen, setInvoicesModalOpen] = useState(false);
  const [riskModalOpen, setRiskModalOpen] = useState(false);
  const [selectedInvoice, setSelectedInvoice] = useState<Invoice | null>(null);
  const [selectedRiskClient, setSelectedRiskClient] = useState<Client | null>(null);
  const [reprintReceipt, setReprintReceipt] = useState<ReceiptData | null>(null);
  const [invoiceFilterQuery, setInvoiceFilterQuery] = useState('');
  const [invoiceFilterDate, setInvoiceFilterDate] = useState('');

  const loadDashboard = async () => {
    setIsLoading(true);
    const sevenDaysAgo = new Date(Date.now() - 7 * 24 * 60 * 60 * 1000).toISOString().slice(0, 10);
    try {
      const [clientsRes, riskRes, invoicesRes, summaryRes, sessionsRes, activeRes] = await Promise.all([
        clientsApi.list(),
        clientsApi.riskAlerts(),
        salesApi.list({ status: 'DELIVERED' }),
        salesApi.dailySummary(),
        productionApi.sessions.list({ date_from: sevenDaysAgo, page_size: '200' }),
        clientsApi.activeLastMonth(),
      ]);

      const summaryRaw: any[] = Array.isArray(summaryRes.data) ? summaryRes.data : [];
      const dailyCash = summaryRaw.filter(s => s.payment_type === 'CASH').reduce((a, s) => a + parseFloat(s.total || 0), 0);
      const dailyCredit = summaryRaw.filter(s => s.payment_type === 'CREDIT').reduce((a, s) => a + parseFloat(s.total || 0), 0);

      const sortedInvoices = [...invoicesRes.data].sort((a, b) =>
        new Date(b.invoice_date || b.created_at).getTime() - new Date(a.invoice_date || a.created_at).getTime()
      );

      setData({
        totalClients: clientsRes.data.length,
        activeClients: (activeRes.data as any).count ?? clientsRes.data.filter(c => c.is_active).length,
        clients: clientsRes.data,
        riskAlerts: riskRes.data,
        invoices: sortedInvoices,
        dailySummaryRows: summaryRaw,
        dailySummary: { total: dailyCash + dailyCredit, cash: dailyCash, credit: dailyCredit },
        todaySessions: sessionsRes.data,
      });
    } catch (err) {
      console.error('Dashboard load failed', err);
    } finally {
      setIsLoading(false);
    }
  };

  useEffect(() => { loadDashboard(); }, []);

  // Build flour doughnut from sessions (grouped by node)
  const flourByNode: Record<string, number> = {};
  (data?.todaySessions || []).forEach(s => {
    const key = s.node_display || s.node;
    flourByNode[key] = (flourByNode[key] || 0) + parseFloat(s.flour_sacks_used || '0');
  });
  const flourYieldData: DoughnutDataPoint[] = Object.entries(flourByNode).map(([label, value], i) => ({
    label, value, color: PALETTE[i % PALETTE.length],
  }));
  const flourFallback: DoughnutDataPoint[] = [{ label: 'Aucune session', value: 1, color: 'hsl(var(--border-color))' }];

  // Build sales trend from recent invoices — "Paiement" (actual cash/payment
  // collected per day, not the full order value: a partially-paid CREDIT
  // invoice must only count what was actually versé) vs "Commande" (total
  // order value invoiced per day, regardless of how much was paid).
  const trendMap: Record<string, number> = {};
  const commandeMap: Record<string, number> = {};
  (data?.invoices || []).forEach(inv => {
    const day = inv.invoice_date || inv.created_at?.split('T')[0] || '?';
    trendMap[day] = (trendMap[day] || 0) + parseFloat(inv.payment_amount || '0');
    commandeMap[day] = (commandeMap[day] || 0) + parseFloat(inv.order_total || '0');
  });
  const allDays = Array.from(new Set([...Object.keys(trendMap), ...Object.keys(commandeMap)])).sort().slice(-6);
  const dualTrendData: DualChartDataPoint[] = allDays.map(label => ({
    label,
    actual:   trendMap[label]    || 0,
    expected: commandeMap[label] || 0,
  }));
  const dualFallback: DualChartDataPoint[] = [{ label: 'Aujourd\'hui', actual: data?.dailySummary.total || 0, expected: 0 }];

  const caJour = data?.dailySummary.total ?? 0;

  // Daily bread volume (last 7 days) grouped by date
  const dailyPainsMap: Record<string, number> = {};
  (data?.todaySessions || []).forEach(s => {
    const d = s.date || '?';
    dailyPainsMap[d] = (dailyPainsMap[d] || 0) + (s.total_breads || 0);
  });
  const dailyPainsData: ChartDataPoint[] = Object.entries(dailyPainsMap)
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([label, value]) => ({ label, value }));
  const totalPains = Object.values(dailyPainsMap).reduce((a, b) => a + b, 0);
  const todayStr = new Date().toISOString().slice(0, 10);
  const todayPains = dailyPainsMap[todayStr] || 0;

  const recentInvoices = (data?.invoices || []).slice(0, 5);
  const riskAlertsPreview = (data?.riskAlerts || []).slice(0, 4);

  // ── Per-boulangerie breakdowns for KPI detail modals ──────────────────────
  const caByNode: Record<string, { cash: number; credit: number }> = {};
  (data?.dailySummaryRows || []).forEach((r: any) => {
    const key = r.node__code || '—';
    if (!caByNode[key]) caByNode[key] = { cash: 0, credit: 0 };
    if (r.payment_type === 'CASH') caByNode[key].cash += parseFloat(r.total || 0);
    else caByNode[key].credit += parseFloat(r.total || 0);
  });

  const volumeByNode: Record<string, { breads: number; flour: number; sessions: number }> = {};
  (data?.todaySessions || []).forEach(s => {
    const key = s.node_display || s.node;
    if (!volumeByNode[key]) volumeByNode[key] = { breads: 0, flour: 0, sessions: 0 };
    volumeByNode[key].breads += s.total_breads || 0;
    volumeByNode[key].flour += parseFloat(s.flour_sacks_used || '0');
    volumeByNode[key].sessions += 1;
  });

  // Pains par catégorie (référence Configuration → Grille Tarifaire — Prix des Pains),
  // au global et par boulangerie.
  const volumeByCategory: Record<string, { label: string; qty: number; price: number }> = {};
  const volumeByNodeCategory: Record<string, Record<string, number>> = {};
  (data?.todaySessions || []).forEach(s => {
    const nodeKey = s.node_display || s.node;
    (s.lines || []).forEach(l => {
      const key = String(l.unit_price ?? l.bread_price);
      if (!volumeByCategory[key]) volumeByCategory[key] = { label: l.bread_price_display || key, qty: 0, price: l.unit_price ?? 0 };
      volumeByCategory[key].qty += l.quantity || 0;
      if (!volumeByNodeCategory[nodeKey]) volumeByNodeCategory[nodeKey] = {};
      volumeByNodeCategory[nodeKey][key] = (volumeByNodeCategory[nodeKey][key] || 0) + (l.quantity || 0);
    });
  });
  const volumeByCategoryRows = Object.values(volumeByCategory).sort((a, b) => b.qty - a.qty);
  const volumeCategoryKeys = Object.keys(volumeByCategory).sort((a, b) => volumeByCategory[a].price - volumeByCategory[b].price);

  const riskByNode: Record<string, number> = {};
  (data?.riskAlerts || []).forEach(c => {
    const key = c.node_display || c.node;
    riskByNode[key] = (riskByNode[key] || 0) + 1;
  });

  const clientsByNode: Record<string, { total: number; active: number }> = {};
  (data?.clients || []).forEach(c => {
    const key = c.node_display || c.node;
    if (!clientsByNode[key]) clientsByNode[key] = { total: 0, active: 0 };
    clientsByNode[key].total += 1;
    if (c.is_active) clientsByNode[key].active += 1;
  });

  // ── Invoices grouped by month for the "Voir Plus" modal — filtrable par client, N° Reçu ou date ──
  const filteredModalInvoices = (data?.invoices || []).filter(inv => {
    const q = invoiceFilterQuery.trim().toLowerCase();
    const matchesQuery = !q ||
      inv.receipt_number.toLowerCase().includes(q) ||
      (inv.client_display || '').toLowerCase().includes(q) ||
      (inv.client_code || '').toLowerCase().includes(q);
    const matchesDate = !invoiceFilterDate || (inv.invoice_date || '').slice(0, 10) === invoiceFilterDate;
    return matchesQuery && matchesDate;
  });
  const invoicesByMonth: Record<string, Invoice[]> = {};
  filteredModalInvoices.forEach(inv => {
    const d = new Date(inv.invoice_date || inv.created_at);
    const key = d.toLocaleString('fr-FR', { month: 'long', year: 'numeric' });
    if (!invoicesByMonth[key]) invoicesByMonth[key] = [];
    invoicesByMonth[key].push(inv);
  });

  const closeKpiModal = () => setKpiModal(null);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>

      {/* Refresh */}
      <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
        <button
          onClick={loadDashboard}
          disabled={isLoading}
          className="btn btn-secondary"
          style={{ display: 'flex', alignItems: 'center', gap: '6px', padding: '6px 14px', fontSize: '0.78rem' }}
        >
          <FiRefreshCw style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
          <span>Actualiser</span>
        </button>
      </div>

      {/* KPI Stats Grid */}
      <div className="kpi-grid" style={{ gap: '16px' }}>
        {[
          {
            key: 'ca' as KpiModalKey,
            label: "Chiffre d'Affaires du Jour",
            value: isLoading ? '—' : `${caJour.toLocaleString('fr-FR')} FC`,
            change: `Cash: ${(data?.dailySummary.cash ?? 0).toLocaleString('fr-FR')} FC`,
            icon: <FiShoppingBag />, color: 'hsl(var(--accent-color))'
          },
          {
            key: 'volume' as KpiModalKey,
            label: 'Volume de Pains Distribués',
            value: isLoading ? '—' : `${todayPains.toLocaleString('fr-FR')} pains`,
            change: totalPains !== todayPains ? `7 jours : ${totalPains.toLocaleString('fr-FR')} pains` : `${data?.todaySessions.length ?? 0} fournée(s) du jour`,
            icon: <FiActivity />, color: 'hsl(var(--color-info))'
          },
          {
            key: 'risk' as KpiModalKey,
            label: 'Alertes Risques Actives',
            value: isLoading ? '—' : `${data?.riskAlerts.length ?? 0} clients`,
            change: 'Dépassement de plafond',
            icon: <FiAlertTriangle />, color: 'hsl(var(--color-danger))'
          },
          {
            key: 'clients' as KpiModalKey,
            label: 'Clients Actifs du Groupe',
            value: isLoading ? '—' : `${data?.activeClients ?? 0} clients`,
            change: `Actifs ce mois — total fiches : ${data?.totalClients ?? 0}`,
            icon: <FiUsers />, color: 'hsl(var(--text-primary))'
          },
        ].map((stat, idx) => (
          <div
            key={idx}
            className="glass-card"
            onClick={() => setKpiModal(stat.key)}
            style={{ display: 'flex', alignItems: 'center', gap: '12px', padding: '12px 14px', cursor: 'pointer' }}
          >
            <div style={{
              width: '44px', height: '44px', borderRadius: 'var(--radius-md)',
              backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: stat.color, fontSize: '1.2rem', flexShrink: 0
            }}>
              {stat.icon}
            </div>
            <div style={{ minWidth: 0 }}>
              <p style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '2px', textTransform: 'uppercase', letterSpacing: '0.02em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                {stat.label}
              </p>
              <h3 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '1px', letterSpacing: '-0.02em', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', color: 'hsl(var(--text-primary))' }}>
                {stat.value}
              </h3>
              <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>
                {stat.change}
              </span>
            </div>
          </div>
        ))}
      </div>

      {/* Dynamic Visual Graphs Section */}
      <div className="panel-grid">
        <div className="glass-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 800 }}>Chiffre d'Affaires du Mois</h2>
              <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))' }}>Payements reçus et commandes par date</p>
            </div>
            <span className="badge badge-success">Live CDF</span>
          </div>
          <div style={{ padding: '8px' }}>
            <DualTrendChart data={dualTrendData.length > 0 ? dualTrendData : dualFallback} />
          </div>
        </div>

        <div className="glass-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '20px' }}>
            <div>
              <h2 style={{ fontSize: '1.1rem', fontWeight: 800 }}>Farine Consommée par Nœud</h2>
              <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))' }}>Sacs 50 kg par boulangerie (sessions récentes)</p>
            </div>
            <span className="badge badge-info">Farine</span>
          </div>
          <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', height: '200px' }}>
            <YieldDoughnut data={flourYieldData.length > 0 ? flourYieldData : flourFallback} />
          </div>
        </div>
      </div>

      {/* Main Bottom Panels */}
      <div className="panel-grid">

        {/* Recent Transactions */}
        <div className="glass-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '10px' }}>
              <FiCheckCircle style={{ color: 'hsl(var(--color-success))' }} />
              Dernières Factures Livrées
            </h2>
            {(data?.invoices.length ?? 0) > 5 && (
              <button onClick={() => setInvoicesModalOpen(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span>Voir Plus</span>
                <FiChevronRight size={12} />
              </button>
            )}
          </div>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.85rem' }}>Chargement...</div>
          ) : recentInvoices.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.85rem' }}>Aucune facture livrée.</div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table" style={{ fontSize: '0.66rem' }}>
                <thead>
                  <tr style={{ fontSize: '0.58rem', textTransform: 'uppercase' }}>
                    <th>N° Reçu</th>
                    <th>Client</th>
                    <th>Date</th>
                    <th style={{ textAlign: 'right' }}>Montant</th>
                    <th></th>
                  </tr>
                </thead>
                <tbody style={{ fontSize: '0.64rem' }}>
                  {recentInvoices.map(inv => (
                    <tr key={inv.id} onClick={() => setSelectedInvoice(inv)} style={{ cursor: 'pointer' }}>
                      <td>
                        <span className="badge badge-info" style={{ fontSize: '0.54rem' }}>{inv.receipt_number}</span>
                      </td>
                      <td style={{ fontWeight: 700 }}>{inv.client_display || inv.client}</td>
                      <td style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.6rem' }}>{inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('fr-FR') : '—'}</td>
                      <td style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', textAlign: 'right' }}>
                        {parseFloat(inv.order_total).toLocaleString('fr-FR')} FC
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <button
                          onClick={e => { e.stopPropagation(); setReprintReceipt(buildReceipt(inv)); }}
                          title="Réimprimer"
                          style={{ padding: '3px 5px', borderRadius: '4px', border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-secondary))', cursor: 'pointer' }}
                        >
                          <FiPrinter size={10} />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>

        {/* Risk Alerts */}
        <div className="glass-card">
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '16px' }}>
            <h2 style={{ fontSize: '1.1rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '10px' }}>
              <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />
              Alertes Risques Clients
            </h2>
            {(data?.riskAlerts.length ?? 0) > 4 && (
              <button onClick={() => setRiskModalOpen(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
                <span>Voir Plus</span>
                <FiChevronRight size={12} />
              </button>
            )}
          </div>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.85rem' }}>Chargement...</div>
          ) : riskAlertsPreview.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--color-success))', fontSize: '0.85rem', fontWeight: 700 }}>
              <FiCheckCircle style={{ fontSize: '1.5rem', display: 'block', margin: '0 auto 8px' }} />
              Aucun client à risque — Portefeuille sain.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              {riskAlertsPreview.map(client => (
                <div key={client.id} onClick={() => setSelectedRiskClient(client)} style={{
                  backgroundColor: 'hsl(var(--color-danger) / 0.08)',
                  border: '1px solid hsl(var(--color-danger) / 0.2)',
                  borderRadius: 'var(--radius-md)', padding: '9px 11px',
                  display: 'flex', alignItems: 'flex-start', gap: '10px', cursor: 'pointer'
                }}>
                  <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', fontSize: '1rem', flexShrink: 0, marginTop: '2px' }} />
                  <div>
                    <h4 style={{ fontWeight: 800, fontSize: '0.74rem', marginBottom: '2px' }}>
                      [{client.code}] {client.full_name}
                    </h4>
                    <p style={{ fontSize: '0.66rem', color: 'hsl(var(--text-secondary))', marginBottom: '5px' }}>
                      Encours débiteur critique
                    </p>
                    <span className="badge badge-danger" style={{ fontSize: '0.54rem' }}>
                      Dette : {parseFloat(client.current_debt).toLocaleString('fr-FR')} FC
                    </span>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── KPI Detail Modal ─────────────────────────────────────────────── */}
      <Modal isOpen={!!kpiModal} onClose={closeKpiModal} maxWidth="680px">
            {kpiModal === 'ca' && (
              <>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '4px' }}>Chiffre d'Affaires du Jour</h2>
                <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '18px' }}>
                  {isHQ ? 'Détail consolidé par boulangerie.' : 'Détail de votre boulangerie.'}
                </p>
                <div style={{ overflowX: 'auto' }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                        <th>Boulangerie</th>
                        <th style={{ textAlign: 'right' }}>Cash</th>
                        <th style={{ textAlign: 'right' }}>Crédit</th>
                        <th style={{ textAlign: 'right' }}>Total</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.78rem' }}>
                      {Object.entries(caByNode).length === 0 ? (
                        <tr><td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune vente aujourd'hui.</td></tr>
                      ) : Object.entries(caByNode).map(([node, v]) => (
                        <tr key={node}>
                          <td style={{ fontWeight: 700 }}>{node}</td>
                          <td style={{ textAlign: 'right' }}>{v.cash.toLocaleString('fr-FR')} FC</td>
                          <td style={{ textAlign: 'right' }}>{v.credit.toLocaleString('fr-FR')} FC</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{(v.cash + v.credit).toLocaleString('fr-FR')} FC</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {kpiModal === 'volume' && (
              <>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '4px' }}>Volume de Pains Distribués</h2>
                <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '18px' }}>
                  {isHQ ? 'Production par jour (7 derniers jours) et par boulangerie.' : 'Production par jour (7 derniers jours).'}
                </p>

                {/* Daily volume chart */}
                {dailyPainsData.length > 0 && (
                  <div style={{ marginBottom: '20px' }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '8px', textTransform: 'uppercase' }}>
                      Pains distribués par jour
                    </div>
                    <TrendChart data={dailyPainsData} color="hsl(var(--color-info))" height={140} />
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '4px' }}>
                      <span>Total 7j : <strong style={{ color: 'hsl(var(--text-primary))' }}>{totalPains.toLocaleString('fr-FR')} pains</strong></span>
                      <span>Aujourd'hui : <strong style={{ color: 'hsl(var(--color-info))' }}>{todayPains.toLocaleString('fr-FR')} pains</strong></span>
                    </div>
                  </div>
                )}

                {/* Par catégorie — référence Configuration > Grille Tarifaire */}
                {volumeByCategoryRows.length > 0 && (
                  <div style={{ marginBottom: '20px' }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '8px', textTransform: 'uppercase' }}>
                      Pains par catégorie (7 derniers jours)
                    </div>
                    <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(volumeByCategoryRows.length, 4)}, 1fr)`, gap: '8px' }}>
                      {volumeByCategoryRows.map(row => (
                        <div key={row.label} style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '8px 10px', textAlign: 'center' }}>
                          <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>{row.label}</div>
                          <div style={{ fontSize: '0.95rem', fontWeight: 800, color: 'hsl(var(--color-info))' }}>{row.qty.toLocaleString('fr-FR')}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Per-bakery breakdown, avec le détail par catégorie de pain */}
                <div style={{ overflowX: 'auto' }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                        <th>Boulangerie</th>
                        <th style={{ textAlign: 'right' }}>Fournées</th>
                        <th style={{ textAlign: 'right' }}>Sacs de Farine</th>
                        {volumeCategoryKeys.map(key => (
                          <th key={key} style={{ textAlign: 'right' }}>{volumeByCategory[key].label}</th>
                        ))}
                        <th style={{ textAlign: 'right' }}>Total Pains</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.78rem' }}>
                      {Object.entries(volumeByNode).length === 0 ? (
                        <tr><td colSpan={4 + volumeCategoryKeys.length} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune fournée sur la période.</td></tr>
                      ) : Object.entries(volumeByNode).map(([node, v]) => (
                        <tr key={node}>
                          <td style={{ fontWeight: 700 }}>{node}</td>
                          <td style={{ textAlign: 'right' }}>{v.sessions}</td>
                          <td style={{ textAlign: 'right' }}>{v.flour.toLocaleString('fr-FR')}</td>
                          {volumeCategoryKeys.map(key => (
                            <td key={key} style={{ textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>
                              {(volumeByNodeCategory[node]?.[key] || 0).toLocaleString('fr-FR')}
                            </td>
                          ))}
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-info))' }}>{v.breads.toLocaleString('fr-FR')}</td>
                        </tr>
                      ))}
                    </tbody>
                    {volumeCategoryKeys.length > 0 && Object.entries(volumeByNode).length > 0 && (
                      <tfoot>
                        <tr style={{ fontWeight: 800, borderTop: '2px solid hsl(var(--border-color))' }}>
                          <td colSpan={3}>TOTAL</td>
                          {volumeCategoryKeys.map(key => (
                            <td key={key} style={{ textAlign: 'right' }}>{volumeByCategory[key].qty.toLocaleString('fr-FR')}</td>
                          ))}
                          <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{totalPains.toLocaleString('fr-FR')}</td>
                        </tr>
                      </tfoot>
                    )}
                  </table>
                </div>
              </>
            )}

            {kpiModal === 'risk' && (
              <>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '4px' }}>Alertes Risques Actives</h2>
                <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '18px' }}>
                  {isHQ ? 'Répartition des clients à risque par boulangerie.' : 'Clients à risque de votre boulangerie.'}
                </p>
                <div style={{ overflowX: 'auto' }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                        <th>Boulangerie</th>
                        <th style={{ textAlign: 'right' }}>Clients à risque</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.78rem' }}>
                      {Object.entries(riskByNode).length === 0 ? (
                        <tr><td colSpan={2} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune alerte.</td></tr>
                      ) : Object.entries(riskByNode).map(([node, count]) => (
                        <tr key={node}>
                          <td style={{ fontWeight: 700 }}>{node}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-danger))' }}>{count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {kpiModal === 'clients' && (
              <>
                <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '4px' }}>Clients Actifs du Groupe</h2>
                <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '18px' }}>
                  Un client est actif s'il a effectué au moins une commande au cours des 30 derniers jours.{' '}
                  {isHQ ? 'Répartition par boulangerie.' : 'Fichier client de votre boulangerie.'}
                </p>
                <div style={{ overflowX: 'auto' }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                        <th>Boulangerie</th>
                        <th style={{ textAlign: 'right' }}>Total Fiches</th>
                        <th style={{ textAlign: 'right' }}>Actifs</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.78rem' }}>
                      {Object.entries(clientsByNode).length === 0 ? (
                        <tr><td colSpan={3} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucun client.</td></tr>
                      ) : Object.entries(clientsByNode).map(([node, v]) => (
                        <tr key={node}>
                          <td style={{ fontWeight: 700 }}>{node}</td>
                          <td style={{ textAlign: 'right' }}>{v.total}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>{v.active}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}
      </Modal>

      {/* ── "Voir Plus" Modal: All Delivered Invoices grouped by month ───── */}
      <Modal isOpen={invoicesModalOpen} onClose={() => setInvoicesModalOpen(false)} maxWidth="680px">
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '4px' }}>Factures Livrées — Historique</h2>
            <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
              Classées par mois. Cliquez sur une facture pour voir le détail.
            </p>
            <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', marginBottom: '16px' }}>
              <input
                type="text"
                value={invoiceFilterQuery}
                onChange={e => setInvoiceFilterQuery(e.target.value)}
                placeholder="Client ou N° Reçu..."
                className="form-input"
                style={{ flex: '1 1 220px', height: '34px', fontSize: '0.78rem', padding: '0 10px' }}
              />
              <input
                type="date"
                value={invoiceFilterDate}
                onChange={e => setInvoiceFilterDate(e.target.value)}
                className="form-input"
                style={{ height: '34px', fontSize: '0.78rem', padding: '0 10px' }}
              />
              {(invoiceFilterQuery || invoiceFilterDate) && (
                <button
                  onClick={() => { setInvoiceFilterQuery(''); setInvoiceFilterDate(''); }}
                  className="btn btn-secondary"
                  style={{ padding: '0 12px', fontSize: '0.75rem', height: '34px' }}
                >
                  Réinitialiser
                </button>
              )}
            </div>
            <div style={{ overflowY: 'auto', flex: 1 }}>
              {filteredModalInvoices.length === 0 && (
                <div style={{ textAlign: 'center', padding: '32px', color: 'hsl(var(--text-muted))', fontSize: '0.8rem' }}>
                  Aucune facture ne correspond à ce filtre.
                </div>
              )}
              {Object.entries(invoicesByMonth).map(([month, invs]) => (
                <div key={month} style={{ marginBottom: '18px' }}>
                  <h4 style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--accent-color))', textTransform: 'uppercase', marginBottom: '8px' }}>
                    <FiCalendar size={12} /> {month}
                  </h4>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.66rem', textTransform: 'uppercase' }}>
                        <th>N° Reçu</th>
                        <th>Client</th>
                        <th>Date</th>
                        <th style={{ textAlign: 'right' }}>Montant</th>
                        <th></th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.72rem' }}>
                      {invs.map(inv => (
                        <tr key={inv.id} onClick={() => setSelectedInvoice(inv)} style={{ cursor: 'pointer' }}>
                          <td><span className="badge badge-info" style={{ fontSize: '0.6rem' }}>{inv.receipt_number}</span></td>
                          <td style={{ fontWeight: 700 }}>{inv.client_display || inv.client}</td>
                          <td style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.68rem' }}>{inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('fr-FR') : '—'}</td>
                          <td style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', textAlign: 'right' }}>{parseFloat(inv.order_total).toLocaleString('fr-FR')} FC</td>
                          <td style={{ textAlign: 'right' }}>
                            <button
                              onClick={e => { e.stopPropagation(); setReprintReceipt(buildReceipt(inv)); }}
                              title="Réimprimer"
                              style={{ padding: '3px 5px', borderRadius: '4px', border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-secondary))', cursor: 'pointer' }}
                            >
                              <FiPrinter size={11} />
                            </button>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ))}
            </div>
          </div>
      </Modal>

      {/* ── "Voir Plus" Modal: All Risk Clients ──────────────────────────── */}
      <Modal isOpen={riskModalOpen} onClose={() => setRiskModalOpen(false)} maxWidth="680px">
          <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '4px' }}>Clients à Risque — Liste Complète</h2>
            <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '18px' }}>
              Cliquez sur un client pour voir le détail.
            </p>
            <div style={{ overflowY: 'auto', flex: 1, display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {(data?.riskAlerts || []).map(client => (
                <div key={client.id} onClick={() => setSelectedRiskClient(client)} style={{
                  backgroundColor: 'hsl(var(--color-danger) / 0.08)',
                  border: '1px solid hsl(var(--color-danger) / 0.2)',
                  borderRadius: 'var(--radius-md)', padding: '12px 14px',
                  display: 'flex', alignItems: 'flex-start', gap: '12px', cursor: 'pointer'
                }}>
                  <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', fontSize: '1.2rem', flexShrink: 0, marginTop: '2px' }} />
                  <div>
                    <h4 style={{ fontWeight: 800, fontSize: '0.88rem', marginBottom: '2px' }}>
                      [{client.code}] {client.full_name} <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>— {client.node_display}</span>
                    </h4>
                    <span className="badge badge-danger" style={{ fontSize: '0.6rem' }}>
                      Dette : {parseFloat(client.current_debt).toLocaleString('fr-FR')} FC
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </div>
      </Modal>

      {/* ── Invoice Detail Sub-Modal ──────────────────────────────────────── */}
      {selectedInvoice && (
        <Modal isOpen={true} onClose={() => setSelectedInvoice(null)} maxWidth="680px">
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: '12px' }}>
              <div>
                <h2 style={{ fontSize: '1.2rem', fontWeight: 800, marginBottom: '4px' }}>
                  Facture {selectedInvoice.receipt_number}
                </h2>
                <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginBottom: '16px' }}>
                  {selectedInvoice.client_display || selectedInvoice.client} — {selectedInvoice.node_display} — {new Date(selectedInvoice.invoice_date).toLocaleDateString('fr-FR')}
                </p>
              </div>
              <button
                onClick={() => setReprintReceipt(buildReceipt(selectedInvoice))}
                className="btn btn-secondary"
                style={{ padding: '6px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0, marginRight: '24px' }}
              >
                <FiPrinter /> Réimprimer
              </button>
            </div>
            <table className="premium-table" style={{ marginBottom: '16px' }}>
              <thead>
                <tr style={{ fontSize: '0.66rem', textTransform: 'uppercase' }}>
                  <th>Pain</th>
                  <th style={{ textAlign: 'right' }}>Qté</th>
                  <th style={{ textAlign: 'right' }}>P.U.</th>
                  <th style={{ textAlign: 'right' }}>Total</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.78rem' }}>
                {selectedInvoice.lines.map((line, i) => (
                  <tr key={line.id || i}>
                    <td>{line.bread_price_display}</td>
                    <td style={{ textAlign: 'right' }}>{line.quantity}</td>
                    <td style={{ textAlign: 'right' }}>{parseFloat(line.unit_price || '0').toLocaleString('fr-FR')} FC</td>
                    <td style={{ textAlign: 'right', fontWeight: 700 }}>{parseFloat(line.line_total || '0').toLocaleString('fr-FR')} FC</td>
                  </tr>
                ))}
              </tbody>
            </table>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', fontSize: '0.78rem', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '12px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Valeur Commande :</span><strong>{parseFloat(selectedInvoice.order_total).toLocaleString('fr-FR')} FC</strong></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Versement :</span><strong>{parseFloat(selectedInvoice.payment_amount).toLocaleString('fr-FR')} FC</strong></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>BP Avant :</span><strong>{parseFloat(selectedInvoice.debt_before).toLocaleString('fr-FR')} FC</strong></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>BP Après :</span><strong>{parseFloat(selectedInvoice.debt_after).toLocaleString('fr-FR')} FC</strong></div>
            </div>
        </Modal>
      )}

      {/* ── Risk Client Detail Sub-Modal ─────────────────────────────────── */}
      {selectedRiskClient && (
        <Modal
          isOpen={true}
          onClose={() => setSelectedRiskClient(null)}
          title={`[${selectedRiskClient.code}] ${selectedRiskClient.full_name}`}
          subtitle={selectedRiskClient.node_display}
          maxWidth="680px"
        >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.82rem' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Téléphone :</span><strong>{selectedRiskClient.phone}</strong></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Adresse :</span><strong>{selectedRiskClient.address}</strong></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}><span>Plafond Crédit :</span><strong>{parseFloat(selectedRiskClient.credit_limit).toLocaleString('fr-FR')} FC</strong></div>
              <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                <span>Dette Actuelle (BP) :</span>
                <strong style={{ color: 'hsl(var(--color-danger))' }}>{parseFloat(selectedRiskClient.current_debt).toLocaleString('fr-FR')} FC</strong>
              </div>
            </div>
        </Modal>
      )}

      {/* ── Reprint Receipt ──────────────────────────────────────────────── */}
      {reprintReceipt && (
        <ThermalReceipt receipt={reprintReceipt} printId="dashboard" onClose={() => setReprintReceipt(null)} />
      )}

    </div>
  );
};
