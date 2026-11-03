import React, { useState, useEffect, useCallback } from 'react';
import {
  FiFileText, FiTrendingUp, FiArrowUpRight, FiArrowDownRight,
  FiDownload, FiDollarSign, FiBarChart2
} from 'react-icons/fi';
import { TripleTrendChart, TripleChartDataPoint } from '@/components/shared/Charts';
import {
  financeApi, commissionsApi, coreApi,
  FinancialYear, IncomeStatement, BalanceSheet, Cashflow,
  Doc1Row, CmHistoryRow, BakeryNode,
} from '@/api/services';
import { useAuthStore } from '@/store/authStore';

export const Finance: React.FC = () => {
  const { user } = useAuthStore();
  const [activeTab, setActiveTab] = useState<'p&l' | 'balance' | 'cashflow' | 'doc1' | 'history'>('p&l');
  const [years, setYears] = useState<FinancialYear[]>([]);
  const [selectedYearId, setSelectedYearId] = useState<string>('');
  const [incomeData, setIncomeData] = useState<IncomeStatement | null>(null);
  const [balanceData, setBalanceData] = useState<BalanceSheet | null>(null);
  const [cashflowData, setCashflowData] = useState<Cashflow | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isCreatingYear, setIsCreatingYear] = useState(false);

  // DOC 1 state
  const today = new Date();
  const [doc1Node, setDoc1Node]     = useState('');
  const [doc1Month, setDoc1Month]   = useState(today.getMonth() + 1);
  const [doc1Year, setDoc1Year]     = useState(today.getFullYear());
  const [doc1Data, setDoc1Data]     = useState<Doc1Row[]>([]);
  const [doc1Loading, setDoc1Loading] = useState(false);
  const [doc1Exporting, setDoc1Exporting] = useState(false);
  const [allNodes, setAllNodes]     = useState<BakeryNode[]>([]);

  // CM history state
  const [histNode, setHistNode]     = useState('');
  const [histMonths, setHistMonths] = useState(12);
  const [histData, setHistData]     = useState<CmHistoryRow[]>([]);
  const [histLoading, setHistLoading] = useState(false);

  const loadYears = () => {
    setIsLoading(true);
    financeApi.years.list().then(res => {
      setYears(res.data);
      const current = res.data.find(y => y.is_current) || res.data[0];
      if (current) {
        setSelectedYearId(current.id);
      } else {
        setIsLoading(false);
      }
    }).catch(err => { console.error(err); setIsLoading(false); });
  };

  useEffect(() => { loadYears(); }, []);

  const handleCreateCurrentYear = async () => {
    setIsCreatingYear(true);
    try {
      await financeApi.years.create({ year: new Date().getFullYear(), is_current: true });
      loadYears();
    } catch (err) {
      console.error('Failed to create financial year', err);
    } finally {
      setIsCreatingYear(false);
    }
  };

  useEffect(() => {
    if (!selectedYearId) return;
    setIsLoading(true);
    Promise.all([
      financeApi.incomeStatement(selectedYearId),
      financeApi.balanceSheet(selectedYearId),
      financeApi.cashflow(selectedYearId),
    ]).then(([incRes, balRes, cfRes]) => {
      setIncomeData(incRes.data);
      setBalanceData(balRes.data);
      setCashflowData(cfRes.data);
    }).catch(console.error)
      .finally(() => setIsLoading(false));
  }, [selectedYearId]);

  // Load nodes once
  useEffect(() => {
    coreApi.nodes.list().then(res => {
      setAllNodes(res.data);
      if (!doc1Node && res.data.length > 0) setDoc1Node(res.data[0].id);
      if (!histNode && res.data.length > 0) setHistNode(res.data[0].id);
    }).catch(() => {});
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // If user has a fixed node, pre-set filters
  useEffect(() => {
    if (user?.node && !doc1Node) setDoc1Node(user.node);
    if (user?.node && !histNode) setHistNode(user.node);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const loadDoc1 = useCallback(async () => {
    if (!doc1Node) return;
    setDoc1Loading(true);
    try {
      const res = await financeApi.doc1Report({ node: doc1Node, month: String(doc1Month), year: String(doc1Year) });
      setDoc1Data(Array.isArray(res.data) ? res.data : []);
    } catch { setDoc1Data([]); }
    finally { setDoc1Loading(false); }
  }, [doc1Node, doc1Month, doc1Year]);

  useEffect(() => { if (activeTab === 'doc1') loadDoc1(); }, [activeTab, loadDoc1]);

  const handleDoc1Export = async () => {
    if (!doc1Node) return;
    setDoc1Exporting(true);
    try {
      const res = await financeApi.doc1Export({ node: doc1Node, month: String(doc1Month), year: String(doc1Year) });
      const url = URL.createObjectURL(new Blob([res.data as BlobPart], { type: 'text/csv;charset=utf-8;' }));
      const a = document.createElement('a');
      a.href = url;
      a.download = `DOC1_${doc1Year}_${String(doc1Month).padStart(2, '0')}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch { /* ignore */ }
    finally { setDoc1Exporting(false); }
  };

  const loadHistory = useCallback(async () => {
    setHistLoading(true);
    try {
      const params: Record<string, string> = { months: String(histMonths) };
      if (histNode) params.node = histNode;
      const res = await commissionsApi.periods.history(params);
      setHistData(Array.isArray(res.data) ? res.data : []);
    } catch { setHistData([]); }
    finally { setHistLoading(false); }
  }, [histNode, histMonths]);

  useEffect(() => { if (activeTab === 'history') loadHistory(); }, [activeTab, loadHistory]);

  const fmt = (v: string | number | undefined) =>
    v !== undefined ? parseFloat(v as string).toLocaleString('fr-FR') : '—';

  const pct = (cur: string, prev: string) => {
    const c = parseFloat(cur), p = parseFloat(prev);
    if (!p) return null;
    return Math.round(((c - p) / Math.abs(p)) * 1000) / 10;
  };

  const plRows = incomeData ? [
    {
      code: '70', label: "Chiffre d'Affaires (Ventes de Pain)",
      current: parseFloat(incomeData.total_revenue),
      previous: parseFloat(incomeData.previous_year?.total_revenue || '0'),
      change: pct(incomeData.total_revenue, incomeData.previous_year?.total_revenue || '0'),
    },
    {
      code: '60', label: 'Coût Matières Premières (Farine, Sel, Levure, Huile)',
      current: -(parseFloat(incomeData.cost_flour) + parseFloat(incomeData.cost_yeast || '0') + parseFloat(incomeData.cost_salt || '0') + parseFloat(incomeData.cost_oil || '0')),
      previous: -(parseFloat(incomeData.previous_year?.cost_flour || '0') + parseFloat(incomeData.previous_year?.cost_yeast || '0') + parseFloat(incomeData.previous_year?.cost_salt || '0') + parseFloat(incomeData.previous_year?.cost_oil || '0')),
      change: null,
    },
    {
      code: '65', label: 'Commissions de Vente Accordées',
      current: -parseFloat(incomeData.commissions_paid),
      previous: -parseFloat(incomeData.previous_year?.commissions_paid || '0'),
      change: null,
    },
    {
      code: '61', label: 'Charges Locales & Exploitation',
      current: -parseFloat(incomeData.operational_expenses),
      previous: -parseFloat(incomeData.previous_year?.operational_expenses || '0'),
      change: null,
    },
    {
      code: 'RESULTAT', label: "Résultat Net d'Exploitation Consolidé",
      current: parseFloat(incomeData.net_result),
      previous: parseFloat(incomeData.previous_year?.net_result || '0'),
      change: pct(incomeData.net_result, incomeData.previous_year?.net_result || '0'),
    },
  ] : [];

  const balRows = balanceData ? [
    {
      code: 'CREANCES-CLT', label: 'Créances Clients (Dettes à recouvrer)',
      current: parseFloat(balanceData.receivables),
      previous: parseFloat(balanceData.previous_year?.receivables || '0'),
      change: pct(balanceData.receivables, balanceData.previous_year?.receivables || '0'),
    },
    {
      code: 'DISPO-CAISSE', label: 'Disponibilités en Caisse',
      current: parseFloat(balanceData.cash_position),
      previous: parseFloat(balanceData.previous_year?.cash_position || '0'),
      change: pct(balanceData.cash_position, balanceData.previous_year?.cash_position || '0'),
    },
    {
      code: 'TOTAL-ACTIF', label: 'Total Actif Consolidé',
      current: parseFloat(balanceData.total_assets),
      previous: parseFloat(balanceData.previous_year?.total_assets || '0'),
      change: pct(balanceData.total_assets, balanceData.previous_year?.total_assets || '0'),
    },
  ] : [];

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', fontSize: '0.85rem' }}>

      {/* Header Banner */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '16px 20px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '2px' }}>
              États Financiers Consolidés
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem' }}>
              Compte de Résultat et Bilan comparatifs (N / N-1) — données réelles.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
            <select
              value={selectedYearId}
              onChange={e => setSelectedYearId(e.target.value)}
              className="form-input"
              style={{ height: '34px', fontSize: '0.8rem', minWidth: '120px' }}
            >
              {years.map(y => (
                <option key={y.id} value={y.id}>Exercice {y.year}{y.is_current ? ' (Courant)' : ''}</option>
              ))}
            </select>
            <FiTrendingUp style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
          </div>
        </div>
      </div>

      {/* Empty state — no fiscal year exists yet */}
      {!isLoading && years.length === 0 && (
        <div className="glass-card" style={{ padding: '32px 20px', textAlign: 'center' }}>
          <FiFileText style={{ fontSize: '2rem', color: 'hsl(var(--text-muted))', marginBottom: '8px' }} />
          <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.85rem', marginBottom: '14px' }}>
            Aucun exercice financier n'a encore été créé. Créez l'exercice {new Date().getFullYear()} pour générer les états financiers à partir des données existantes (factures, caisse, commissions).
          </p>
          <button onClick={handleCreateCurrentYear} disabled={isCreatingYear} className="btn btn-primary" style={{ padding: '8px 18px', fontSize: '0.8rem' }}>
            {isCreatingYear ? 'Création...' : `Créer l'exercice ${new Date().getFullYear()}`}
          </button>
        </div>
      )}

      {/* KPI Stats */}
      {incomeData && balanceData && (
        <div className="kpi-grid" style={{ gap: '14px' }}>
          <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--color-success) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--color-success))' }}>
              <FiTrendingUp />
            </div>
            <div>
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>CROISSANCE C.A.</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>
                {incomeData.revenue_growth_pct != null ? `${incomeData.revenue_growth_pct}%` : '—'}
              </h3>
            </div>
          </div>
          <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--color-info) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--color-info))' }}>
              <FiDollarSign />
            </div>
            <div>
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>RÉSULTAT NET</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{fmt(incomeData.net_result)} FC</h3>
            </div>
          </div>
          <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
            <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--accent-color) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--accent-color))' }}>
              <FiFileText />
            </div>
            <div>
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>CRÉANCES ACTIVES</div>
              <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{fmt(balanceData.receivables)} FC</h3>
            </div>
          </div>
        </div>
      )}

      {/* Tabs & Export */}
      {years.length > 0 && (
      <>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '12px' }}>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
          <button onClick={() => setActiveTab('p&l')} className={`btn ${activeTab === 'p&l' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '6px 16px', fontSize: '0.78rem', height: '34px' }}>
            §5.3.2 Compte de Résultat
          </button>
          <button onClick={() => setActiveTab('balance')} className={`btn ${activeTab === 'balance' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '6px 16px', fontSize: '0.78rem', height: '34px' }}>
            §5.3.3 Bilan Consolidé
          </button>
          <button onClick={() => setActiveTab('cashflow')} className={`btn ${activeTab === 'cashflow' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '6px 16px', fontSize: '0.78rem', height: '34px' }}>
            §5.3.4 Cash-Flow
          </button>
          <button onClick={() => setActiveTab('doc1')} className={`btn ${activeTab === 'doc1' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '6px 16px', fontSize: '0.78rem', height: '34px', display: 'flex', alignItems: 'center', gap: '5px' }}>
            <FiFileText /><span>DOC 1</span>
          </button>
          <button onClick={() => setActiveTab('history')} className={`btn ${activeTab === 'history' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '6px 16px', fontSize: '0.78rem', height: '34px', display: 'flex', alignItems: 'center', gap: '5px' }}>
            <FiBarChart2 /><span>Historique CM</span>
          </button>
        </div>
      </div>

      {/* Main Table */}
      <div className="glass-card" style={{ padding: '16px 20px' }}>
        <h2 style={{ fontSize: '0.95rem', fontWeight: 800, marginBottom: '12px' }}>
          {activeTab === 'p&l' ? '§5.3.2 Compte de Résultat — ETS. KIESE (Comparatif N / N-1)' :
           activeTab === 'balance' ? '§5.3.3 Bilan Consolidé (Actif)' :
           activeTab === 'cashflow' ? '§5.3.4 Tableau des Flux de Trésorerie (Cash-Flow)' :
           activeTab === 'doc1' ? '§5.3.1 DOC 1 — Rapport Mensuel par Client' :
           '§5.3.5 Historique Commissions (CM)'}
        </h2>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))' }}>Chargement...</div>
        ) : activeTab === 'cashflow' ? (
          /* §5.3.4 — CASH-FLOW */
          cashflowData ? (
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table">
                <thead>
                  <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                    <th style={{ padding: '8px 10px', width: '80px' }}>Rubrique</th>
                    <th style={{ padding: '8px 10px' }}>Nature du Flux</th>
                    <th style={{ padding: '8px 10px', textAlign: 'right' }}>Exercice N (FC)</th>
                    <th style={{ padding: '8px 10px', textAlign: 'right' }}>Exercice N-1 (FC)</th>
                    <th style={{ padding: '8px 10px', textAlign: 'right' }}>Variation</th>
                  </tr>
                </thead>
                <tbody style={{ fontSize: '0.72rem' }}>
                  {[
                    { code: 'F.EXPL', label: 'Flux d\'Exploitation — Encaissements Clients (+)', current: parseFloat(cashflowData.total_entries), previous: parseFloat(cashflowData.previous_year?.total_entries || '0'), sign: 1 },
                    { code: 'F.SORT', label: 'Flux d\'Exploitation — Décaissements Sortants (-)', current: -parseFloat(cashflowData.total_exits), previous: -parseFloat(cashflowData.previous_year?.total_exits || '0'), sign: -1 },
                    { code: 'F.NET',  label: 'Flux Net de Trésorerie', current: parseFloat(cashflowData.net_cashflow), previous: parseFloat(cashflowData.previous_year?.net_cashflow || '0'), sign: 1 },
                    { code: 'SOLDE',  label: 'Trésorerie Nette de Clôture (Solde)', current: parseFloat(cashflowData.closing_balance), previous: parseFloat(cashflowData.previous_year?.closing_balance || '0'), sign: 1 },
                  ].map(row => {
                    const isKey = row.code === 'SOLDE' || row.code === 'F.NET';
                    const growth = row.previous !== 0 ? ((row.current - row.previous) / Math.abs(row.previous) * 100).toFixed(1) : null;
                    return (
                      <tr key={row.code} style={{ fontWeight: isKey ? 800 : 'normal', backgroundColor: isKey ? 'hsl(var(--bg-tertiary))' : 'transparent' }}>
                        <td style={{ padding: '8px 10px', color: 'hsl(var(--text-muted))', fontFamily: 'monospace', fontSize: '0.65rem' }}>{row.code}</td>
                        <td style={{ padding: '8px 10px', color: isKey ? 'hsl(var(--accent-color))' : 'hsl(var(--text-primary))' }}>{row.label}</td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: row.current < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>
                          {row.current.toLocaleString('fr-FR')} FC
                        </td>
                        <td style={{ padding: '8px 10px', textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>
                          {row.previous.toLocaleString('fr-FR')} FC
                        </td>
                        <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                          {growth !== null ? (
                            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '4px', color: parseFloat(growth) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                              {parseFloat(growth) > 0 ? <FiArrowUpRight /> : <FiArrowDownRight />}
                              <span>{Math.abs(parseFloat(growth))}%</span>
                            </div>
                          ) : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          ) : <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))' }}>Données de flux non disponibles pour cet exercice.</div>
        ) : activeTab === 'doc1' ? (
          /* §5.3.1 — DOC 1 */
          <div>
            {/* Filters */}
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
              {allNodes.length > 0 && (
                <div>
                  <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Succursale</label>
                  <select value={doc1Node} onChange={e => setDoc1Node(e.target.value)}
                    style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.82rem' }}>
                    {allNodes.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Mois</label>
                <select value={doc1Month} onChange={e => setDoc1Month(Number(e.target.value))}
                  style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.82rem' }}>
                  {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                    <option key={m} value={m}>{new Date(2000, m - 1).toLocaleString('fr-FR', { month: 'long' })}</option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Année</label>
                <select value={doc1Year} onChange={e => setDoc1Year(Number(e.target.value))}
                  style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.82rem' }}>
                  {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
                </select>
              </div>
              <button onClick={loadDoc1} style={{ padding: '5px 14px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.82rem', height: 32 }}>
                Charger
              </button>
              <button onClick={handleDoc1Export} disabled={doc1Exporting || doc1Data.length === 0}
                style={{ padding: '5px 14px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', color: 'hsl(var(--text-primary))', fontWeight: 600, cursor: 'pointer', fontSize: '0.82rem', height: 32, display: 'flex', alignItems: 'center', gap: 5, opacity: doc1Data.length === 0 ? 0.4 : 1 }}>
                <FiDownload />{doc1Exporting ? 'Export…' : 'Export CSV'}
              </button>
            </div>
            {doc1Loading ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
            ) : doc1Data.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-muted))', fontSize: '0.85rem' }}>
                Aucune facture pour ce filtre. Cliquez "Charger".
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="premium-table" style={{ fontSize: '0.75rem' }}>
                  <thead>
                    <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                      {['Code', 'Client', '200', '300', '500', '1000', 'Commande (FC)', 'Paiement (FC)', 'BP fin mois (FC)', 'Taux', 'CM (FC)'].map(h => (
                        <th key={h} style={{ padding: '7px 8px', textAlign: ['200','300','500','1000','Commande (FC)','Paiement (FC)','BP fin mois (FC)','Taux','CM (FC)'].includes(h) ? 'right' : 'left' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {doc1Data.map((row, i) => (
                      <tr key={i} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                        <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{row.client_code}</td>
                        <td style={{ padding: '6px 8px' }}>{row.client_name}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{row.qty_200 || '—'}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{row.qty_300 || '—'}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{row.qty_500 || '—'}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right' }}>{row.qty_1000 || '—'}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 600 }}>{fmt(row.invoice_total)}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{fmt(row.payment_amount)}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: parseFloat(row.debt_after) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>{fmt(row.debt_after)}</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>{(parseFloat(row.commission_rate) * 100).toFixed(1)}%</td>
                        <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--accent-color))', fontWeight: 700 }}>{fmt(row.cm_amount)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr style={{ fontWeight: 800, background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))' }}>
                      <td colSpan={2} style={{ padding: '7px 8px' }}>{doc1Data.length} client(s)</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{doc1Data.reduce((s, r) => s + r.qty_200, 0)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{doc1Data.reduce((s, r) => s + r.qty_300, 0)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{doc1Data.reduce((s, r) => s + r.qty_500, 0)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{doc1Data.reduce((s, r) => s + r.qty_1000, 0)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{doc1Data.reduce((s, r) => s + parseFloat(r.invoice_total), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{doc1Data.reduce((s, r) => s + parseFloat(r.payment_amount), 0).toLocaleString('fr-FR')}</td>
                      <td />
                      <td />
                      <td style={{ padding: '7px 8px', textAlign: 'right', color: 'hsl(var(--accent-color))' }}>{doc1Data.reduce((s, r) => s + parseFloat(r.cm_amount), 0).toLocaleString('fr-FR')}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        ) : activeTab === 'history' ? (
          /* §5.3.5 — Historique CM */
          <div>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
              {allNodes.length > 0 && (
                <div>
                  <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Succursale</label>
                  <select value={histNode} onChange={e => setHistNode(e.target.value)}
                    style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.82rem' }}>
                    <option value="">Toutes</option>
                    {allNodes.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
                  </select>
                </div>
              )}
              <div>
                <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Périodes</label>
                <select value={histMonths} onChange={e => setHistMonths(Number(e.target.value))}
                  style={{ padding: '5px 8px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.82rem' }}>
                  {[6, 12, 24].map(n => <option key={n} value={n}>Derniers {n} mois</option>)}
                </select>
              </div>
              <button onClick={loadHistory} style={{ padding: '5px 14px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.82rem', height: 32 }}>
                Actualiser
              </button>
            </div>
            {histLoading ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
            ) : histData.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-muted))', fontSize: '0.85rem' }}>
                Aucune période CM trouvée.
              </div>
            ) : (
              <>
              {/* 3-curve chart: COMMANDE / PAIEMENT / CM brut */}
              {(() => {
                const sorted = [...histData].sort((a, b) => a.year !== b.year ? a.year - b.year : a.month - b.month);
                const chartData: TripleChartDataPoint[] = sorted.map(r => ({
                  label: `${String(r.month).padStart(2,'0')}/${r.year}`,
                  commande: parseFloat(r.total_orders || '0'),
                  paiement: parseFloat(r.total_payments || '0'),
                  cm:       parseFloat(r.total_cm || '0'),
                }));
                return chartData.length > 0 ? (
                  <div style={{ marginBottom: '20px', padding: '12px', background: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
                    <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '8px' }}>
                      Chiffre d'Affaires du Mois — Commande / Paiement / CM Brut
                    </div>
                    <TripleTrendChart data={chartData} height={220} />
                  </div>
                ) : null;
              })()}
              <div style={{ overflowX: 'auto' }}>
                <table className="premium-table" style={{ fontSize: '0.78rem' }}>
                  <thead>
                    <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                      {['Période', 'Succursale', 'Clients', 'Commande (FC)', 'CM Brut (FC)', 'CM Net (FC)', 'CM Payé (FC)', 'Statut'].map(h => (
                        <th key={h} style={{ padding: '7px 8px', textAlign: ['Clients','Commande (FC)','CM Brut (FC)','CM Net (FC)','CM Payé (FC)'].includes(h) ? 'right' : 'left' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {histData.map(row => {
                      const net = parseFloat(row.total_net);
                      const paid = parseFloat(row.total_paid);
                      const unpaidPct = net > 0 ? Math.round((net - paid) / net * 100) : 0;
                      return (
                        <tr key={row.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                          <td style={{ padding: '7px 8px', fontWeight: 700 }}>
                            {new Date(row.year, row.month - 1).toLocaleString('fr-FR', { month: 'long', year: 'numeric' })}
                          </td>
                          <td style={{ padding: '7px 8px', color: 'hsl(var(--accent-color))', fontWeight: 600 }}>{row.node_code}</td>
                          <td style={{ padding: '7px 8px', textAlign: 'right' }}>{row.client_count}</td>
                          <td style={{ padding: '7px 8px', textAlign: 'right', fontWeight: 600 }}>{fmt(row.total_orders)}</td>
                          <td style={{ padding: '7px 8px', textAlign: 'right' }}>{fmt(row.total_cm)}</td>
                          <td style={{ padding: '7px 8px', textAlign: 'right', fontWeight: 700 }}>{fmt(row.total_net)}</td>
                          <td style={{ padding: '7px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{fmt(row.total_paid)}</td>
                          <td style={{ padding: '7px 8px' }}>
                            <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
                              <span style={{ padding: '2px 7px', borderRadius: 10, fontSize: '0.7rem', fontWeight: 700, background: row.is_closed ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))', color: '#fff' }}>
                                {row.is_closed ? 'Clôturée' : 'Ouverte'}
                              </span>
                              {unpaidPct > 0 && (
                                <span style={{ fontSize: '0.68rem', color: 'hsl(var(--color-warning))' }}>
                                  {unpaidPct}% impayé
                                </span>
                              )}
                            </div>
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                  <tfoot>
                    <tr style={{ fontWeight: 800, background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))' }}>
                      <td colSpan={2} style={{ padding: '7px 8px' }}>{histData.length} période(s)</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{histData.reduce((s, r) => s + r.client_count, 0)}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{histData.reduce((s, r) => s + parseFloat(r.total_orders || '0'), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{histData.reduce((s, r) => s + parseFloat(r.total_cm), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right' }}>{histData.reduce((s, r) => s + parseFloat(r.total_net), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{histData.reduce((s, r) => s + parseFloat(r.total_paid), 0).toLocaleString('fr-FR')}</td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
              </>
            )}
          </div>
        ) : (
          /* §5.3.2 P&L + §5.3.3 Bilan */
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                  <th style={{ padding: '8px 10px', width: '100px' }}>Compte</th>
                  <th style={{ padding: '8px 10px' }}>Libellé financier</th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>Exercice N (FC)</th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>Exercice N-1 (FC)</th>
                  <th style={{ padding: '8px 10px', textAlign: 'right' }}>Variation</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {(activeTab === 'p&l' ? plRows : balRows).map(row => {
                  const isNeg = row.current < 0;
                  const isResult = row.code === 'RESULTAT' || row.code === 'TOTAL-ACTIF';
                  return (
                    <tr key={row.code} style={{ fontWeight: isResult ? 800 : 'normal', backgroundColor: isResult ? 'hsl(var(--bg-tertiary))' : 'transparent' }}>
                      <td style={{ padding: '8px 10px', color: 'hsl(var(--text-muted))', fontFamily: 'monospace' }}>{row.code}</td>
                      <td style={{ padding: '8px 10px', color: isResult ? 'hsl(var(--accent-color))' : 'hsl(var(--text-primary))' }}>{row.label}</td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: isNeg ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>
                        {row.current.toLocaleString('fr-FR')} FC
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'right', color: row.previous < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-secondary))' }}>
                        {row.previous.toLocaleString('fr-FR')} FC
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                        {row.change != null ? (
                          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'flex-end', gap: '4px', color: row.change > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                            {row.change > 0 ? <FiArrowUpRight /> : <FiArrowDownRight />}
                            <span>{Math.abs(row.change)}%</span>
                          </div>
                        ) : '—'}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      </>
      )}
    </div>
  );
};
