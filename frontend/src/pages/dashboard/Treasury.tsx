import React, { useState, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  FiBook, FiRefreshCw, FiCheckCircle, FiAlertTriangle,
  FiPlus, FiX, FiLock, FiFileText, FiDollarSign, FiPrinter, FiCalendar
} from 'react-icons/fi';
import {
  treasuryApi, salesApi, productionApi, coreApi,
  FacturierReport, CashClosure, LocalExpense, CashbookEntry, JournalEntry, DailySavings,
  ProductionSession, BakeryNode, ExpenseCategory, DisbursementVoucher, SuggestedCa,
  DirectionCashCount
} from '@/api/services';
import { useAuthStore } from '@/store/authStore';
import { Modal } from '@/components/shared/Modal';

// ── Bill denominations — §5.2 ────────────────────────────────────────────────
const BILLS = [
  { key: 'bills_20000', face: 20000, label: '20 000 FC' },
  { key: 'bills_10000', face: 10000, label: '10 000 FC' },
  { key: 'bills_5000',  face: 5000,  label: '5 000 FC'  },
  { key: 'bills_1000',  face: 1000,  label: '1 000 FC'  },
  { key: 'bills_500',   face: 500,   label: '500 FC'    },
  { key: 'bills_200',   face: 200,   label: '200 FC'    },
  { key: 'bills_100',   face: 100,   label: '100 FC'    },
  { key: 'bills_50',    face: 50,    label: '50 FC'     },
] as const;

type BillKey = typeof BILLS[number]['key'];

const JOURNAL_IMPUT = [
  { value: 'CA',        label: 'Recettes du jour (CA)' },
  { value: 'PAY_BLG',  label: 'Paye boulangers' },
  { value: 'RATION',   label: 'Ration boulangers' },
  { value: 'LIVRAISON',label: 'Livraison inter-site' },
  { value: 'EAU',      label: 'Eau' },
  { value: 'APPRO',    label: "Frais d'appro" },
  { value: 'DEPOT',    label: 'Dépôt rapport direction' },
  { value: 'TRANSPORT',label: 'Transport' },
  { value: 'CREDIT',   label: 'Crédit personnel' },
  { value: 'PRIME',    label: 'Prime personnel' },
  { value: 'CARBURANT',label: 'Essence / Mazout' },
  { value: 'ACHAT',    label: 'Achat matériel / fourniture' },
  { value: 'AUTRE',    label: 'Autre' },
];

const fmt = (v: string | number | undefined) =>
  parseFloat(String(v || '0')).toLocaleString('fr-FR');

// BUG-045 — quantités décimales (sacs de farine) affichées proprement (ex. 2,25 sacs), sans arrondi agressif.
const fmtDecimal = (v: string | number | undefined, maxDecimals = 2) =>
  parseFloat(String(v ?? '0')).toLocaleString('fr-FR', { minimumFractionDigits: 0, maximumFractionDigits: maxDecimals });

// BUG-045 — détail par catégorie de pain (§5.1.1) ajouté par la correction backend BUG-033.
const renderReportCategoryDetail = (r: FacturierReport) => {
  const produced = r.breads_produced_by_category || {};
  const sold = r.breads_sold_by_category || {};
  const categories = Array.from(new Set([...Object.keys(produced), ...Object.keys(sold)]));
  const hasSacks = r.sacks_consumed !== undefined && r.sacks_consumed !== null;
  const hasGap = r.sacks_value_gap !== undefined && r.sacks_value_gap !== null;
  if (categories.length === 0 && !hasSacks && !hasGap) return null;
  const gap = parseFloat(r.sacks_value_gap || '0');
  return (
    <tr key={`detail-${r.id}`} style={{ backgroundColor: 'hsl(var(--bg-tertiary))' }}>
      <td colSpan={7} style={{ padding: '6px 10px 10px 16px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', alignItems: 'flex-start' }}>
          {hasSacks && (
            <div><strong>Sacs consommés :</strong> {fmtDecimal(r.sacks_consumed)}</div>
          )}
          {categories.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
              <strong>Pains par catégorie — produits / vendus :</strong>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {categories.map(cat => (
                  <span key={cat} style={{ padding: '2px 6px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap' }}>
                    {cat} : {produced[cat] ?? 0} / {sold[cat] ?? 0}
                  </span>
                ))}
              </div>
            </div>
          )}
          {hasGap && (
            <div>
              <strong>Écart valeur sacs / ventes :</strong>{' '}
              <span style={{ fontWeight: 700, color: gap === 0 ? 'hsl(var(--text-secondary))' : gap > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                {gap >= 0 ? '+' : ''}{fmt(r.sacks_value_gap)} FC{gap === 0 ? '' : gap > 0 ? ' (excédent)' : ' (manquant)'}
              </span>
            </div>
          )}
        </div>
      </td>
    </tr>
  );
};

export const Treasury: React.FC = () => {
  const { user } = useAuthStore();
  const today = new Date().toISOString().split('T')[0];

  // ── Data state ─────────────────────────────────────────────────────────────
  const [reports, setReports]   = useState<FacturierReport[]>([]);
  const [closures, setClosures] = useState<CashClosure[]>([]);
  const [expenses, setExpenses] = useState<LocalExpense[]>([]);
  const [cashbook, setCashbook] = useState<CashbookEntry[]>([]);
  const [nodeFilter, setNodeFilter] = useState('');
  const [allNodes, setAllNodes]     = useState<BakeryNode[]>([]);
  const [todaySessions, setTodaySessions] = useState<ProductionSession[]>([]);
  const [breadSold, setBreadSold] = useState<{
    by_category: Array<{ unit_price: number; total_qty: number; total_fc: number }>;
    grand_total_qty: number; grand_total_fc: number;
  } | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  // §5.2 Billetage state
  const [bills, setBills] = useState<Record<BillKey, number>>({
    bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0,
    bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0,
  });
  const [closureNotes, setClosureNotes] = useState('');
  const [closureError, setClosureError] = useState<string | null>(null);
  const [closureInfo, setClosureInfo] = useState<string | null>(null);
  // BUG-086 : date de clôture rétroactive optionnelle (nouvelle clôture uniquement) — vide = aujourd'hui.
  const [closureDate, setClosureDate] = useState('');
  // BUG-048 : vrai quand le refus de clôture vient d'un transfert de pains entrant
  // présentant un écart de quantité non résolu (message serveur, jamais inventé) —
  // permet d'afficher un renvoi vers la section Transferts de Production.tsx.
  const [closureBlockedByTransferGap, setClosureBlockedByTransferGap] = useState(false);

  // §5.1.2 Expense form
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [expDesc, setExpDesc]       = useState('');
  const [expCategory, setExpCategory] = useState('');
  const [expAmount, setExpAmount]   = useState('');
  const [expError, setExpError]     = useState<string | null>(null);
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);

  // §5.1.2 — Historique mensuel des dépenses
  const [expenseHistoryOpen, setExpenseHistoryOpen] = useState(false);
  const [expenseHistoryMonth, setExpenseHistoryMonth] = useState(() => new Date().getMonth() + 1);
  const [expenseHistoryYear, setExpenseHistoryYear] = useState(() => new Date().getFullYear());
  const [expenseHistoryEntries, setExpenseHistoryEntries] = useState<LocalExpense[]>([]);
  const [expenseHistoryLoading, setExpenseHistoryLoading] = useState(false);

  const loadExpenseHistory = useCallback(async () => {
    setExpenseHistoryLoading(true);
    try {
      const params: Record<string, string> = { month: String(expenseHistoryMonth), year: String(expenseHistoryYear) };
      if (nodeFilter) params.node = nodeFilter;
      const res = await treasuryApi.expenses.list(params);
      setExpenseHistoryEntries(Array.isArray(res.data) ? res.data : []);
    } catch { setExpenseHistoryEntries([]); }
    finally { setExpenseHistoryLoading(false); }
  }, [expenseHistoryMonth, expenseHistoryYear, nodeFilter]);

  useEffect(() => { if (expenseHistoryOpen) loadExpenseHistory(); }, [expenseHistoryOpen, loadExpenseHistory]);

  const [generatingReport, setGeneratingReport] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateInfo, setGenerateInfo] = useState<string | null>(null);
  // BUG-086 : date rétroactive optionnelle pour la génération du rapport §5.1.1 — vide = aujourd'hui.
  const [reportDate, setReportDate] = useState('');
  const [detailClosure, setDetailClosure] = useState<CashClosure | null>(null);
  const [detailEntry, setDetailEntry] = useState<CashbookEntry | null>(null);

  // §5.1.3 Cashbook filter
  const [dateFrom, setDateFrom] = useState(() => {
    const d = new Date();
    d.setDate(1);
    return d.toISOString().split('T')[0];
  });
  const [dateTo, setDateTo] = useState(today);
  const [integrityResult, setIntegrityResult] = useState<{chain_valid: boolean; tampered_count: number} | null>(null);
  const [checkingIntegrity, setCheckingIntegrity] = useState(false);

  // §5.1.3b — Bordereaux de Versement (Direction)
  const [vouchers, setVouchers] = useState<DisbursementVoucher[]>([]);
  const [vouchersLoading, setVouchersLoading] = useState(false);
  const [showVoucherForm, setShowVoucherForm] = useState(false);
  const [voucherMotif, setVoucherMotif] = useState('');
  const [voucherBeneficiary, setVoucherBeneficiary] = useState('');
  const [voucherBills, setVoucherBills] = useState<Record<BillKey, number>>({
    bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0,
    bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0,
  });
  const [voucherError, setVoucherError] = useState<string | null>(null);
  const [voucherSubmitting, setVoucherSubmitting] = useState(false);

  // §5.1.3c — BUG-119 : Comptage physique Livre de Caisse Direction (contrôle
  // annexe, séparé du chaînage SHA-256 — voir backend/treasury/models.py::DirectionCashCount).
  const [directionCashCounts, setDirectionCashCounts] = useState<DirectionCashCount[]>([]);
  const [dccLoading, setDccLoading] = useState(false);
  const [showDccForm, setShowDccForm] = useState(false);
  const [dccDate, setDccDate] = useState(today);
  const [dccBills, setDccBills] = useState<Record<BillKey, number>>({
    bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0,
    bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0,
  });
  const [dccNotes, setDccNotes] = useState('');
  const [dccError, setDccError] = useState<string | null>(null);
  const [dccSubmitting, setDccSubmitting] = useState(false);

  // §5.1.4 Journal de Caisse par Boulangerie
  const [journalEntries, setJournalEntries] = useState<JournalEntry[]>([]);
  const [journalLoading, setJournalLoading] = useState(false);
  const [journalMonth, setJournalMonth] = useState(() => new Date().getMonth() + 1);
  const [journalYear, setJournalYear]   = useState(() => new Date().getFullYear());
  const [journalReport, setJournalReport] = useState<{
    month_carried: string; total_entries: string; total_exits: string; final_balance: string;
  } | null>(null);
  const [jImput, setJImput]       = useState('CA');
  const [jLabel, setJLabel]       = useState('');
  const [jEntry, setJEntry]       = useState('');
  const [jExit, setJExit]         = useState('');
  const [jDate, setJDate]         = useState(today);
  const [jError, setJError]       = useState<string | null>(null);
  const [jSubmitting, setJSubmitting] = useState(false);
  // BUG-105 — pré-remplissage/confrontation « Recettes du jour (CA) » avec la Clôture (Niveau 2)
  const [jSuggestedCa, setJSuggestedCa] = useState<SuggestedCa | null>(null);
  const [jSuggestedCaLoading, setJSuggestedCaLoading] = useState(false);
  const [jLastResult, setJLastResult] = useState<JournalEntry | null>(null);

  // §5.1.5 Épargne Journalière
  const [savingsEntries, setSavingsEntries] = useState<DailySavings[]>([]);
  const [savingsLoading, setSavingsLoading] = useState(false);
  const [savingsMonth, setSavingsMonth] = useState(() => new Date().getMonth() + 1);
  const [savingsYear, setSavingsYear]   = useState(() => new Date().getFullYear());
  const [savingsTotal, setSavingsTotal] = useState<{
    total_flour_sacks: string; total_revenue: string; total_savings: string;
  } | null>(null);
  const [sDate, setSDate]         = useState(today);
  const [sFlour, setSFlour]       = useState('');
  const [sRevenue, setSRevenue]   = useState('');
  const [sRate, setSRate]         = useState('0.1580');
  const [sError, setSError]       = useState<string | null>(null);
  const [sSubmitting, setSSubmitting] = useState(false);
  const [savingsDayFilter, setSavingsDayFilter] = useState('');

  const loadData = useCallback(async () => {
    setIsLoading(true);
    const nf = nodeFilter || undefined;
    // BUG-044 : le Livre de Caisse Direction (`treasuryApi.cashbook.list`) est réservé au
    // siège (`IsHeadquarters`, cf. BUG-026) — on ne l'appelle même pas pour un rôle non-HQ,
    // au lieu de laisser la requête échouer en 403.
    const isHq = !!user?.can_access_all_nodes;
    try {
      const [reportRes, closureRes, expRes, cashRes, sessionRes, breadRes] = await Promise.all([
        treasuryApi.reports.list({ date: today,  ...(nf && { node: nf }) }),
        treasuryApi.closures.list({ date: today, ...(nf && { node: nf }) }),
        treasuryApi.expenses.list({ date: today, ...(nf && { node: nf }) }),
        isHq ? treasuryApi.cashbook.list({ date_from: dateFrom, date_to: dateTo, ...(nf && { node: nf }) }) : Promise.resolve({ data: [] as CashbookEntry[] }),
        productionApi.sessions.list({ date: today, ...(nf && { node: nf }) }),
        salesApi.breadSummary({ date: today, ...(nf && { node: nf }) }),
      ]);
      setReports(Array.isArray(reportRes.data) ? reportRes.data : []);
      setClosures(Array.isArray(closureRes.data) ? closureRes.data : []);
      setExpenses(Array.isArray(expRes.data) ? expRes.data : []);
      setCashbook(Array.isArray(cashRes.data) ? cashRes.data : []);
      setTodaySessions(Array.isArray(sessionRes.data) ? sessionRes.data : []);
      setBreadSold(breadRes.data ?? null);
    } catch (err) {
      console.error('Treasury load failed', err);
    } finally {
      setIsLoading(false);
    }
  }, [today, dateFrom, dateTo, nodeFilter, user?.can_access_all_nodes]);

  useEffect(() => { loadData(); }, [loadData]);

  // Load nodes list (HQ needs it for the bakery filter; every role needs it
  // to resolve their own node's "Valeur Théorique par Sac de Farine (FC)" —
  // NodeViewSet.list() is open to any authenticated user).
  useEffect(() => {
    coreApi.nodes.list().then(res => setAllNodes(res.data)).catch(() => {});
  }, []);

  // Global Config default sac_value_fc — fallback when a bakery has none set.
  const [configSacValueFc, setConfigSacValueFc] = useState<number>(200000);
  // BUG-086 : réglage global — visible seulement si activé par ADMIN/DIRECTION (Settings.tsx),
  // même réglage que BUG-083 (Sales.tsx/Clients.tsx), consommé ici pour les deux champs de date
  // rétroactive (§5.1.1 Génération de rapport, §5.2 Clôture & Caisse).
  const [allowBackdatedSales, setAllowBackdatedSales] = useState(false);
  useEffect(() => {
    coreApi.config.get().then(res => {
      setConfigSacValueFc(res.data.sac_value_fc || 200000);
      setAllowBackdatedSales(!!res.data.allow_backdated_sales);
    }).catch(() => {});
  }, []);

  // Load expense categories once (§5.1.2 — managed from Configuration)
  useEffect(() => {
    coreApi.expenseCategories.list().then(res => {
      const active = (res.data || []).filter(ec => ec.is_active);
      setExpenseCategories(active);
      if (active.length > 0) setExpCategory(prev => prev || String(active[0].id));
    }).catch(() => {});
  }, []);

  // §5.1.4 — Journal de Caisse load
  const loadJournal = useCallback(async () => {
    setJournalLoading(true);
    const params: Record<string, string> = { month: String(journalMonth), year: String(journalYear) };
    if (nodeFilter) params.node = nodeFilter;
    try {
      const [entriesRes, reportRes] = await Promise.all([
        treasuryApi.journal.list(params),
        treasuryApi.journal.monthlyReport(params),
      ]);
      setJournalEntries(Array.isArray(entriesRes.data) ? entriesRes.data : []);
      setJournalReport(reportRes.data ?? null);
    } catch { /* ignore */ }
    finally { setJournalLoading(false); }
  }, [journalMonth, journalYear, nodeFilter]);

  useEffect(() => { loadJournal(); }, [loadJournal]);

  // BUG-105 — pré-remplissage/confrontation du montant « Recettes du jour (CA) »
  // avec la Clôture (Niveau 2) du même (nœud, date) — ne bloque jamais la saisie :
  // la valeur suggérée ne fait que remplir le champ, qui reste librement modifiable.
  useEffect(() => {
    const effectiveNode = user?.node || nodeFilter;
    if (jImput !== 'CA' || !effectiveNode || !jDate) {
      setJSuggestedCa(null);
      return;
    }
    let cancelled = false;
    setJSuggestedCaLoading(true);
    treasuryApi.journal.suggestedCa({ node: effectiveNode, date: jDate })
      .then(res => {
        if (cancelled) return;
        setJSuggestedCa(res.data);
        if (res.data.available && res.data.amount) {
          setJEntry(String(Math.round(parseFloat(res.data.amount))));
        }
      })
      .catch(() => { if (!cancelled) setJSuggestedCa(null); })
      .finally(() => { if (!cancelled) setJSuggestedCaLoading(false); });
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jImput, jDate, user?.node, nodeFilter]);

  // §5.1.5 — Épargne Journalière load
  const loadSavings = useCallback(async () => {
    setSavingsLoading(true);
    const params: Record<string, string> = { month: String(savingsMonth), year: String(savingsYear) };
    if (nodeFilter) params.node = nodeFilter;
    try {
      const [entriesRes, totalRes] = await Promise.all([
        treasuryApi.savings.list(params),
        treasuryApi.savings.monthlyTotal(params),
      ]);
      setSavingsEntries(Array.isArray(entriesRes.data) ? entriesRes.data : []);
      setSavingsTotal(totalRes.data ?? null);
    } catch { /* ignore */ }
    finally { setSavingsLoading(false); }
  }, [savingsMonth, savingsYear, nodeFilter]);

  useEffect(() => { loadSavings(); }, [loadSavings]);

  const handleSavingsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSError(null);
    const rev = parseFloat(sRevenue) || 0;
    if (rev <= 0) { setSError('Indiquez le revenu du jour.'); return; }
    setSSubmitting(true);
    try {
      const payload: Record<string, string> = {
        date: sDate,
        flour_sacks: sFlour || '0',
        daily_revenue: String(rev),
        savings_rate: sRate,
      };
      if (nodeFilter) payload.node = nodeFilter;
      await treasuryApi.savings.create(payload as any);
      setSFlour(''); setSRevenue('');
      await loadSavings();
    } catch (err: unknown) {
      const d = (err as any)?.response?.data;
      setSError(d?.detail || d?.node?.[0] || d?.non_field_errors?.[0] || "Erreur lors de l'enregistrement.");
    } finally {
      setSSubmitting(false);
    }
  };

  // §5.1.5 — filtre par jour + impression journalière
  const savingsDaysAvailable = Array.from(new Set(savingsEntries.map(s => s.date.split('-')[2]))).sort();
  const filteredSavingsEntries = savingsDayFilter
    ? savingsEntries.filter(s => s.date.split('-')[2] === savingsDayFilter)
    : savingsEntries;
  const filteredSavingsTotals = savingsDayFilter
    ? {
        total_flour_sacks: String(filteredSavingsEntries.reduce((a, s) => a + parseFloat(s.flour_sacks || '0'), 0)),
        total_revenue:     String(filteredSavingsEntries.reduce((a, s) => a + parseFloat(s.daily_revenue || '0'), 0)),
        total_savings:     String(filteredSavingsEntries.reduce((a, s) => a + parseFloat(s.savings_amount || '0'), 0)),
      }
    : savingsTotal;

  const handlePrintSavingsDay = (day: string) => {
    const entries = savingsEntries.filter(s => s.date.split('-')[2] === day);
    if (entries.length === 0) return;
    const dateLabel = new Date(entries[0].date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
    const totalRevenue = entries.reduce((a, s) => a + parseFloat(s.daily_revenue || '0'), 0);
    const totalSavings = entries.reduce((a, s) => a + parseFloat(s.savings_amount || '0'), 0);
    const rows = entries.map(s => `
      <tr>
        <td>${s.node_display || s.node}</td>
        <td style="text-align:right">${fmt(s.flour_sacks)}</td>
        <td style="text-align:right">${fmt(s.daily_revenue)} FC</td>
        <td style="text-align:right">${(parseFloat(s.savings_rate) * 100).toFixed(2)}%</td>
        <td style="text-align:right;font-weight:700">${fmt(s.savings_amount)} FC</td>
      </tr>`).join('');
    const html = `
      <html><head><title>Épargne Journalière — ${dateLabel}</title>
      <style>
        body { font-family: Arial, sans-serif; padding: 24px; color: #111; }
        h1 { font-size: 18px; border-bottom: 2px solid #000; padding-bottom: 8px; }
        table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }
        th, td { border: 1px solid #999; padding: 6px 8px; }
        th { background: #eee; text-align: left; }
        tfoot td { font-weight: bold; background: #f3f4f6; }
      </style></head>
      <body>
        <h1>ÉPARGNE JOURNALIÈRE — ETS. KIESE</h1>
        <p>Date : ${dateLabel}</p>
        <table>
          <thead><tr><th>Boulangerie</th><th style="text-align:right">Sacs PROD</th><th style="text-align:right">Revenu</th><th style="text-align:right">Taux</th><th style="text-align:right">Épargne</th></tr></thead>
          <tbody>${rows}</tbody>
          <tfoot><tr><td colspan="2">TOTAL</td><td style="text-align:right">${fmt(totalRevenue)} FC</td><td></td><td style="text-align:right">${fmt(totalSavings)} FC</td></tr></tfoot>
        </table>
        <script>window.onload = () => window.print();</script>
      </body></html>`;
    const w = window.open('', '_blank', 'width=700,height=900');
    if (w) { w.document.write(html); w.document.close(); }
  };

  const handleJournalSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setJError(null);
    const ea = parseFloat(jEntry) || 0;
    const xa = parseFloat(jExit)  || 0;
    if (ea === 0 && xa === 0) { setJError('Indiquez une entrée ou une sortie.'); return; }
    setJSubmitting(true);
    try {
      const payload: Partial<JournalEntry> & { node?: string } = {
        imput: jImput, label: jLabel, date: jDate,
        entry_amount: ea ? String(ea) : '0',
        exit_amount:  xa ? String(xa) : '0',
      };
      if (nodeFilter) payload.node = nodeFilter;
      const res = await treasuryApi.journal.create(payload);
      // BUG-105 — confrontation à la Clôture renvoyée par le serveur pour
      // l'imputation CA (jamais calculée/forcée côté client).
      setJLastResult(jImput === 'CA' ? res.data : null);
      setJLabel(''); setJEntry(''); setJExit('');
      setJSuggestedCa(null);
      await loadJournal();
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string; node?: string[] } } })?.response?.data;
      setJError(d?.detail || d?.node?.[0] || "Erreur lors de l'enregistrement.");
    } finally {
      setJSubmitting(false);
    }
  };

  // ── Computed values ────────────────────────────────────────────────────────
  // §5.2 — Total billetage
  const billTotal = BILLS.reduce((sum, b) => sum + bills[b.key] * b.face, 0);

  // §5.1.2 — Total dépenses locales du jour (declared first — used in ecartCaisse)
  const totalExpenses = expenses.reduce((sum, e) => sum + parseFloat(e.amount || '0'), 0);

  // §5.1.1 — Solde comptable caisse = somme des theoretical_cash des rapports facturiers
  const todayClosure = closures[0];
  const totalCash        = reports.reduce((sum, r) => sum + parseFloat(r.total_cash_sales   || '0'), 0);
  const totalCredit      = reports.reduce((sum, r) => sum + parseFloat(r.total_credit_sales || '0'), 0);
  const theoreticalCash  = reports.reduce((sum, r) => sum + parseFloat(r.theoretical_cash   || '0'), 0);

  // §5.2 — Écart caisse (physical bills vs net theoretical = theoretical - local expenses)
  const ecartCaisse = billTotal - (theoreticalCash - totalExpenses);
  const netCaisse = totalCash - totalExpenses;

  // Active node label for visual indicators
  const selectedNode = allNodes.find(n => n.id === nodeFilter);
  const selectedNodeLabel = selectedNode
    ? `${selectedNode.code} — ${selectedNode.name}`
    : (!user?.can_access_all_nodes && user?.node_display)
      ? user.node_display
      : null;

  // §5.1.1 — Group reports by bakery for DIRECTION view
  const reportsByNode: Record<string, FacturierReport[]> = {};
  reports.forEach(r => {
    const key = r.node_display || r.node;
    if (!reportsByNode[key]) reportsByNode[key] = [];
    reportsByNode[key].push(r);
  });

  // ── Handlers ───────────────────────────────────────────────────────────────

  const handleGenerateReport = async () => {
    setGeneratingReport(true);
    setGenerateError(null);
    setGenerateInfo(null);
    // BUG-086 : date rétroactive optionnelle (réglage ADMIN/DIRECTION). Vide ou date du jour →
    // comportement inchangé (payload { date: today }, comme avant ce ticket).
    const targetDate = allowBackdatedSales && reportDate && reportDate !== today ? reportDate : today;
    try {
      const payload: { date: string; node?: string } = { date: targetDate };
      if (nodeFilter && !user?.node) payload.node = nodeFilter;
      const res = await treasuryApi.reports.generate(payload);
      if (targetDate !== today) {
        // La liste du jour (`loadData`) est filtrée sur la date d'aujourd'hui — un rapport
        // rétroactif n'y apparaîtrait pas. On l'ajoute localement pour que le facturier/gérant
        // voie immédiatement le résultat de la génération.
        setReports(prev => [...res.data, ...prev.filter(r => !res.data.some(nr => nr.id === r.id))]);
        setGenerateInfo(`Rapport généré pour le ${new Date(targetDate).toLocaleDateString('fr-FR')} (date rétroactive) — n'apparaît pas dans le filtre "Clôtures du Jour".`);
      } else {
        await loadData();
      }
      const detail = (res.data as unknown as { detail?: string })?.detail;
      if (detail) setGenerateError(detail);
    } catch (err: any) {
      const d = err?.response?.data;
      setGenerateError(d?.detail || JSON.stringify(d) || 'Erreur lors de la génération.');
    } finally {
      setGeneratingReport(false);
    }
  };

  const handleValidateReport = async (id: string) => {
    try {
      await treasuryApi.reports.validate(id);
      await loadData();
    } catch (err: any) {
      console.error('Validate report failed', err?.response?.data);
    }
  };

  const handleCreateClosure = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setClosureError(null);
    setClosureInfo(null);
    setClosureBlockedByTransferGap(false);
    if (billTotal === 0) { setClosureError('Effectuez le billetage (entrez les coupures).'); return; }
    // BUG-046 : une clôture déjà confirmée par le comptable est figée côté serveur (400) —
    // on évite même la requête si l'état local sait déjà que la clôture est confirmée
    // (ex. confirmée entre-temps dans un autre onglet pendant que ce formulaire était ouvert).
    if (editingClosure?.is_validated) {
      setClosureError('Cette clôture a déjà été confirmée par le comptable : elle ne peut plus être modifiée.');
      setEditingClosure(null);
      await loadData();
      return;
    }
    // BUG-086 : date de clôture rétroactive optionnelle (réglage ADMIN/DIRECTION, nouvelle
    // clôture uniquement). Vide ou date du jour → comportement inchangé (payload { date: today }).
    const targetClosureDate = allowBackdatedSales && closureDate && closureDate !== today ? closureDate : today;
    try {
      if (editingClosure) {
        await treasuryApi.closures.update(editingClosure.id, { notes: closureNotes, ...bills } as any);
        setEditingClosure(null);
      } else {
        const effectiveNode = user?.node || nodeFilter || null;
        if (!effectiveNode) { setClosureError('Sélectionnez une succursale dans le filtre avant de créer une clôture.'); return; }
        await treasuryApi.closures.create({
          date: targetClosureDate,
          notes: closureNotes,
          ...bills,
          ...(nodeFilter && !user?.node ? { node: nodeFilter } : {}),
        } as any);
        if (targetClosureDate !== today) {
          // La liste "Clôtures du Jour" (`loadData`) est filtrée sur aujourd'hui — une clôture
          // rétroactive n'y apparaîtrait pas. On informe clairement le gérant du résultat.
          setClosureInfo(`Clôture créée pour le ${new Date(targetClosureDate).toLocaleDateString('fr-FR')} (date rétroactive) — n'apparaît pas dans la liste "Clôtures du Jour".`);
        }
      }
      setBills({ bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0, bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0 });
      setClosureNotes('');
      setClosureDate('');
      await loadData();
    } catch (err: any) {
      const d = err?.response?.data;
      const detail: string | undefined = d?.detail;
      // BUG-048 : message reçu tel quel du serveur (jamais inventé) — on ne fait que
      // repérer s'il décrit un transfert entrant en écart non résolu (CLAUDE.md §5.4)
      // pour proposer un renvoi vers la section Transferts de Production.tsx.
      setClosureBlockedByTransferGap(!!detail && /transfert/i.test(detail) && /écart/i.test(detail));
      setClosureError(detail || d?.non_field_errors?.[0] || JSON.stringify(d) || 'Erreur lors de la clôture.');
    }
  };

  const handleValidateClosure = async (closureId: string, notes?: string) => {
    if (closureActionLoading) return;
    setClosureActionLoading(true);
    try {
      await treasuryApi.closures.validate(closureId, notes);
      setValidatingClosureId(null);
      setValidateNotes('');
      setDetailClosure(null);
      await loadData();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Erreur lors de la confirmation.');
    } finally {
      setClosureActionLoading(false);
    }
  };

  const [rejectReason, setRejectReason] = useState('');
  const [rejectingClosureId, setRejectingClosureId] = useState<string | null>(null);
  const [validateNotes, setValidateNotes] = useState('');
  const [validatingClosureId, setValidatingClosureId] = useState<string | null>(null);
  const [editingClosure, setEditingClosure] = useState<CashClosure | null>(null);
  const [closureActionLoading, setClosureActionLoading] = useState(false);

  const handleRejectClosure = async (closureId: string) => {
    if (closureActionLoading) return;
    setClosureActionLoading(true);
    try {
      await treasuryApi.closures.reject(closureId, rejectReason);
      setRejectingClosureId(null);
      setRejectReason('');
      setDetailClosure(null);
      await loadData();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Erreur lors du rejet.');
    } finally {
      setClosureActionLoading(false);
    }
  };

  const handlePushToCashbook = async (closureId: string) => {
    if (closureActionLoading) return;
    setClosureActionLoading(true);
    try {
      await treasuryApi.closures.pushToCashbook(closureId);
      await loadData();
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Erreur lors de la mise au Livre de Caisse.');
    } finally {
      setClosureActionLoading(false);
    }
  };

  const handleAddExpense = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setExpError(null);
    if (!expDesc || !expAmount || parseFloat(expAmount) <= 0 || !expCategory) { setExpError('Remplissez tous les champs.'); return; }
    try {
      await treasuryApi.expenses.create({
        description: expDesc, category: Number(expCategory) as any,
        amount: expAmount, date: today,
        ...(nodeFilter && !user?.node ? { node: nodeFilter } : {}),
      } as any);
      setExpDesc(''); setExpAmount('');
      setShowExpenseForm(false);
      await loadData();
    } catch (err: any) {
      setExpError(err?.response?.data?.detail || 'Erreur.');
    }
  };

  const [confirmingDay, setConfirmingDay] = useState(false);
  const [confirmMsg, setConfirmMsg]       = useState<string | null>(null);

  const handleConfirmDay = async () => {
    const pending = reports.filter(r => !r.is_validated);
    if (pending.length === 0) { setConfirmMsg('Tous les rapports sont déjà validés.'); return; }
    setConfirmingDay(true);
    setConfirmMsg(null);
    try {
      await Promise.all(pending.map(r => treasuryApi.reports.validate(r.id)));
      await loadData();
      setConfirmMsg(`${pending.length} rapport(s) validé(s). Procédez au billetage physique (§5.2) pour finaliser la clôture.`);
    } catch (err: any) {
      setConfirmMsg(err?.response?.data?.detail || 'Erreur lors de la validation.');
    } finally {
      setConfirmingDay(false);
    }
  };

  const handlePrint511 = () => {
    const nodeLabel = allNodes.find(n => n.id === nodeFilter)
      ? `${allNodes.find(n => n.id === nodeFilter)!.code} — ${allNodes.find(n => n.id === nodeFilter)!.name}`
      : user?.node_display || 'Toutes les succursales';

    const totalSacs    = todaySessions.reduce((s, sess) => s + parseFloat(sess.flour_sacks_used || '0'), 0);
    const totalTheorFC = todaySessions.reduce((s, sess) => s + (sess.theoretical_yield || 0), 0);
    const prodMap: Record<number, number> = {};
    todaySessions.forEach(sess => (sess.lines || []).forEach(ln => {
      const up = ln.unit_price ?? 0;
      prodMap[up] = (prodMap[up] || 0) + (ln.quantity || 0);
    }));
    const soldMap: Record<number, { qty: number; fc: number }> = {};
    (breadSold?.by_category || []).forEach(c => { soldMap[c.unit_price] = { qty: c.total_qty, fc: c.total_fc }; });
    const cats = Array.from(new Set([...Object.keys(prodMap).map(Number), ...Object.keys(soldMap).map(Number)])).sort((a, b) => a - b);
    const actualFC = breadSold?.grand_total_fc ?? 0;
    const ecart    = actualFC - totalTheorFC;
    const fmtN = (n: number) => Math.round(n).toLocaleString('fr-FR');

    const reportRows = reports.map(r => `
      <tr>
        <td>${r.node_display || r.node_origin || '—'}</td>
        <td>Éq. ${r.team}</td>
        <td style="text-align:right;font-weight:700">${fmtN(parseFloat(r.total_cash_sales || '0'))} FC</td>
        <td style="text-align:right">${fmtN(parseFloat(r.total_credit_sales || '0'))} FC</td>
        <td style="text-align:right;font-weight:700">${fmtN(parseFloat(r.theoretical_cash || '0'))} FC</td>
        <td style="text-align:center">${r.is_validated ? '✓ Validé' : 'En attente'}</td>
      </tr>`).join('');

    const catRows = cats.map(cat => {
      const prod = prodMap[cat] ?? 0;
      const s    = soldMap[cat] ?? { qty: 0, fc: 0 };
      const rest = prod - s.qty;
      return `<tr>
        <td style="font-weight:700">${fmtN(cat)} FC</td>
        <td style="text-align:right">${fmtN(s.qty)} × ${fmtN(cat)} FC = <strong>${fmtN(s.fc)} FC</strong></td>
        <td style="text-align:right">${prod > 0 ? fmtN(prod) : '—'}</td>
        <td style="text-align:right;font-weight:700;color:${rest < 0 ? '#dc2626' : rest > 0 ? '#374151' : '#16a34a'}">${rest > 0 ? '+' : ''}${fmtN(rest)}</td>
      </tr>`;
    }).join('');

    const html = `<!DOCTYPE html><html lang="fr"><head>
      <meta charset="UTF-8"><title>§5.1.1 — Rapport Facturier ${today}</title>
      <style>
        body { font-family: Arial, sans-serif; font-size: 11px; color: #111; margin: 20px; }
        h1 { font-size: 14px; margin: 0 0 4px; }
        .sub { font-size: 10px; color: #666; margin-bottom: 16px; }
        .section { border: 1px solid #ddd; border-radius: 4px; padding: 10px 12px; margin-bottom: 14px; }
        .section-title { font-size: 9px; text-transform: uppercase; letter-spacing: .05em; color: #888; font-weight: 700; margin-bottom: 6px; }
        .formula { font-size: 14px; font-weight: 700; }
        table { width: 100%; border-collapse: collapse; margin-top: 6px; }
        th { background: #f3f4f6; font-size: 9px; text-transform: uppercase; padding: 4px 6px; border: 1px solid #ddd; }
        td { padding: 4px 6px; border: 1px solid #e5e7eb; font-size: 10px; }
        .balance { padding: 10px 14px; border-radius: 4px; display: flex; justify-content: space-between; align-items: center;
          border: 1px solid ${ecart === 0 ? '#16a34a' : Math.abs(ecart) < 10000 ? '#d97706' : '#dc2626'};
          background: ${ecart === 0 ? '#f0fdf4' : Math.abs(ecart) < 10000 ? '#fffbeb' : '#fef2f2'}; }
        @media print { body { margin: 10px; } }
      </style></head><body>
      <h1>§5.1.1 — Rapport Journalier des Facturiers</h1>
      <div class="sub">Date : ${today} &nbsp;|&nbsp; Succursale : ${nodeLabel} &nbsp;|&nbsp; Imprimé le ${new Date().toLocaleString('fr-FR')}</div>

      ${totalSacs > 0 ? `<div class="section">
        <div class="section-title">Facturier — Montant Attendu (Sacs)</div>
        <div class="formula">${fmtN(totalSacs)} sac${totalSacs > 1 ? 's' : ''} × ${fmtN(totalSacs > 0 ? totalTheorFC / totalSacs : _effectiveSacValueFc)} FC = <span style="color:#b45309">${fmtN(totalTheorFC)} FC</span></div>
      </div>` : ''}

      ${cats.length > 0 ? `<div class="section">
        <div class="section-title">Ventes du Jour — Résultat</div>
        <table>
          <thead><tr><th>Catégorie</th><th>Ventes (qté × prix = total)</th><th style="text-align:right">Produits</th><th style="text-align:right">Restant</th></tr></thead>
          <tbody>${catRows}</tbody>
          <tfoot><tr style="background:#f3f4f6;font-weight:700">
            <td>TOTAL VENTES</td><td style="text-align:right;font-size:12px;color:#16a34a">${fmtN(actualFC)} FC</td><td></td><td></td>
          </tr></tfoot>
        </table>
      </div>` : ''}

      <div class="balance">
        <div><strong>Attendu :</strong> ${fmtN(totalTheorFC)} FC &nbsp;&nbsp; <strong>Obtenu :</strong> ${fmtN(actualFC)} FC</div>
        <div style="font-size:14px;font-weight:700;color:${ecart === 0 ? '#16a34a' : Math.abs(ecart) < 10000 ? '#d97706' : '#dc2626'}">
          ${ecart === 0 ? 'ÉQUILIBRÉ — PCC' : `Écart : ${ecart > 0 ? '+' : ''}${fmtN(ecart)} FC`}
        </div>
      </div>

      ${reports.length > 0 ? `<div class="section" style="margin-top:14px">
        <div class="section-title">Rapports par Facturier</div>
        <table>
          <thead><tr><th>Boulangerie</th><th>Équipe</th><th style="text-align:right">Cash</th><th style="text-align:right">Crédit</th><th style="text-align:right">Théorique</th><th style="text-align:center">Statut</th></tr></thead>
          <tbody>${reportRows}</tbody>
        </table>
      </div>` : ''}
      <script>window.onload=()=>{ window.print(); window.onafterprint=()=>window.close(); }</script>
    </body></html>`;

    const w = window.open('', '_blank', 'width=800,height=600');
    if (w) { w.document.write(html); w.document.close(); }
  };

  const handleIntegrityCheck = async () => {
    setCheckingIntegrity(true);
    try {
      const res = await treasuryApi.cashbook.integrityCheck();
      setIntegrityResult(res.data as any);
    } catch (err) {
      console.error('Integrity check failed', err);
    } finally {
      setCheckingIntegrity(false);
    }
  };

  // §5.1.3b — Bordereaux de Versement
  const loadVouchers = useCallback(async () => {
    if (!user?.can_access_all_nodes) return;
    setVouchersLoading(true);
    try {
      const res = await treasuryApi.vouchers.list({ date_from: dateFrom, date_to: dateTo });
      setVouchers(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setVouchersLoading(false); }
  }, [user?.can_access_all_nodes, dateFrom, dateTo]);

  useEffect(() => { loadVouchers(); }, [loadVouchers]);

  // Current consolidated balance — cashbook is ordered newest-first, so [0] is the latest entry
  const consolidatedBalance = cashbook.length > 0 ? parseFloat(cashbook[0].running_balance) : 0;
  const voucherBillTotal = BILLS.reduce((sum, b) => sum + voucherBills[b.key] * b.face, 0);

  // §5.1.3c — BUG-119 : Comptage physique Direction
  const loadDirectionCashCounts = useCallback(async () => {
    if (!user?.can_access_all_nodes) return;
    setDccLoading(true);
    try {
      const res = await treasuryApi.directionCashCounts.list({ date_from: dateFrom, date_to: dateTo });
      setDirectionCashCounts(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setDccLoading(false); }
  }, [user?.can_access_all_nodes, dateFrom, dateTo]);

  useEffect(() => { loadDirectionCashCounts(); }, [loadDirectionCashCounts]);

  const dccBillTotal = BILLS.reduce((sum, b) => sum + dccBills[b.key] * b.face, 0);

  const handleCreateDirectionCashCount = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setDccError(null);
    if (dccBillTotal <= 0) { setDccError('Effectuez le billetage (entrez les coupures).'); return; }
    setDccSubmitting(true);
    try {
      await treasuryApi.directionCashCounts.create({
        date: dccDate, notes: dccNotes,
        ...dccBills,
      });
      setDccBills({ bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0, bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0 });
      setDccNotes('');
      setDccDate(today);
      setShowDccForm(false);
      await loadDirectionCashCounts();
    } catch (err: unknown) {
      const d = (err as { response?: { data?: { detail?: string } } })?.response?.data;
      setDccError(d?.detail || "Erreur lors de l'enregistrement du comptage.");
    } finally {
      setDccSubmitting(false);
    }
  };

  const handleCreateVoucher = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setVoucherError(null);
    if (!voucherMotif) { setVoucherError('Indiquez le motif du bordereau.'); return; }
    if (voucherBillTotal <= 0) { setVoucherError('Saisissez au moins un billet.'); return; }
    setVoucherSubmitting(true);
    try {
      await treasuryApi.vouchers.create({
        date: today, motif: voucherMotif, beneficiary: voucherBeneficiary,
        ...voucherBills,
      });
      setVoucherMotif(''); setVoucherBeneficiary('');
      setVoucherBills({ bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0, bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0 });
      setShowVoucherForm(false);
      await Promise.all([loadVouchers(), loadData()]);
    } catch (err: any) {
      setVoucherError(err?.response?.data?.detail || 'Erreur lors de la création du bordereau.');
    } finally {
      setVoucherSubmitting(false);
    }
  };

  const handleFinalReport = async () => {
    try {
      const res = await treasuryApi.vouchers.finalReport({ date_from: dateFrom, date_to: dateTo });
      const { vouchers: periodVouchers, total_disbursed, remaining_balance } = res.data;
      const rows = periodVouchers.map(v => `
        <tr>
          <td>${new Date(v.date).toLocaleDateString('fr-FR')}</td>
          <td>${v.piece_number}</td>
          <td>${v.motif}${v.beneficiary ? ' — ' + v.beneficiary : ''}</td>
          <td style="text-align:right">${fmt(v.physical_cash_total)} FC</td>
        </tr>`).join('');
      const html = `
        <html><head><title>Bordereau Final de Versement</title>
        <style>
          body { font-family: Arial, sans-serif; padding: 24px; color: #111; }
          h1 { font-size: 18px; border-bottom: 2px solid #000; padding-bottom: 8px; }
          table { width: 100%; border-collapse: collapse; margin-top: 12px; font-size: 12px; }
          th, td { border: 1px solid #999; padding: 6px 8px; }
          th { background: #eee; text-align: left; }
          tfoot td { font-weight: bold; background: #f3f4f6; }
          .summary { margin-top: 16px; font-size: 13px; }
          .summary div { display: flex; justify-content: space-between; padding: 4px 0; }
          .sign { margin-top: 60px; display: flex; justify-content: space-between; font-size: 12px; }
          .sign div { width: 40%; border-top: 1px solid #000; text-align: center; padding-top: 6px; }
        </style></head>
        <body>
          <h1>BORDEREAU FINAL DE VERSEMENT — ETS. KIESE</h1>
          <p>Période : ${dateFrom} au ${dateTo}</p>
          <table>
            <thead><tr><th>Date</th><th>N° Pièce</th><th>Motif</th><th style="text-align:right">Montant</th></tr></thead>
            <tbody>${rows || '<tr><td colspan="4" style="text-align:center">Aucun bordereau sur la période</td></tr>'}</tbody>
            <tfoot><tr><td colspan="3">TOTAL DÉCAISSÉ</td><td style="text-align:right">${fmt(total_disbursed)} FC</td></tr></tfoot>
          </table>
          <div class="summary">
            <div><span>Solde restant (Livre de Caisse Direction)</span><strong>${fmt(remaining_balance)} FC</strong></div>
          </div>
          <div class="sign">
            <div>Le Comptable</div>
            <div>La Direction</div>
          </div>
          <script>window.onload = () => window.print();</script>
        </body></html>`;
      const w = window.open('', '_blank', 'width=800,height=1000');
      if (w) { w.document.write(html); w.document.close(); }
    } catch (err: any) {
      alert(err?.response?.data?.detail || 'Erreur lors de la génération du bordereau final.');
    }
  };

  // §5.1.1 — Production recap
  // Valeur théorique par sac : celle de la boulangerie courante (gérant : la
  // sienne ; HQ : celle sélectionnée dans le filtre), sinon repli sur la
  // valeur par défaut de la Configuration — jamais "200 000" en dur.
  const _currentNodeId = user?.node || nodeFilter || null;
  const _currentNode = _currentNodeId ? allNodes.find(n => n.id === _currentNodeId) : undefined;
  const _effectiveSacValueFc = (_currentNode?.sac_value_fc && parseFloat(_currentNode.sac_value_fc) > 0)
    ? parseFloat(_currentNode.sac_value_fc)
    : configSacValueFc;
  const _totalSacs = todaySessions.reduce((s, sess) => s + parseFloat(sess.flour_sacks_used || '0'), 0);
  const _totalTheorFC = todaySessions.reduce((s, sess) => s + (sess.theoretical_yield || 0), 0);
  const _prodMap: Record<number, number> = {};
  todaySessions.forEach(sess => {
    (sess.lines || []).forEach(ln => {
      const up = ln.unit_price ?? 0;
      _prodMap[up] = (_prodMap[up] || 0) + (ln.quantity || 0);
    });
  });
  const _soldMap: Record<number, { qty: number; fc: number }> = {};
  (breadSold?.by_category || []).forEach(c => {
    _soldMap[c.unit_price] = { qty: c.total_qty, fc: c.total_fc };
  });
  const _cats = Array.from(new Set([...Object.keys(_prodMap).map(Number), ...Object.keys(_soldMap).map(Number)])).sort((a, b) => a - b);
  const _actualSalesFC = breadSold?.grand_total_fc ?? 0;
  const _ecart = _actualSalesFC - _totalTheorFC;
  const _balanceOk = Math.abs(_ecart) === 0;
  const _pendingReports = reports.filter(r => !r.is_validated).length;

  let productionRecap: React.ReactElement | null = null;
  if (_totalSacs > 0 || _cats.length > 0) {
    productionRecap = (
      <div style={{ marginTop: '16px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '14px' }}>

        {/* ── Header ── */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
            Rapport Journalier · Clôture du Jour
          </span>
          {_pendingReports > 0 && (
            <button
              onClick={handleConfirmDay}
              disabled={confirmingDay}
              className="btn btn-primary"
              style={{ padding: '5px 12px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '5px' }}
            >
              <FiCheckCircle size={13} />
              {confirmingDay ? 'Validation...' : `Confirmer & Clôturer (${_pendingReports} rapport${_pendingReports > 1 ? 's' : ''})`}
            </button>
          )}
          {_pendingReports === 0 && reports.length > 0 && (
            <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-success))', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiCheckCircle size={12} /> Tous les rapports validés
            </span>
          )}
        </div>

        {confirmMsg && (
          <div style={{ fontSize: '0.65rem', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '10px', backgroundColor: 'hsl(var(--color-info) / 0.1)', color: 'hsl(var(--color-info))' }}>
            {confirmMsg}
          </div>
        )}

        {/* ── Section FACTURIER : sacs × valeur ── */}
        <div style={{ backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', padding: '10px 12px', marginBottom: '10px' }}>
          <div style={{ fontSize: '0.6rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '6px', letterSpacing: '0.06em' }}>
            Facturier — Montant Attendu (Sacs)
          </div>
          <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', fontSize: '0.8rem', fontWeight: 700 }}>
            <span style={{ color: 'hsl(var(--color-info))' }}>{_totalSacs.toLocaleString('fr-FR')} sac{_totalSacs > 1 ? 's' : ''}</span>
            <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>×</span>
            <span style={{ color: 'hsl(var(--text-secondary))' }}>{fmt(_totalSacs > 0 ? _totalTheorFC / _totalSacs : _effectiveSacValueFc)} FC</span>
            <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>=</span>
            <span style={{ color: 'hsl(var(--color-warning))', fontSize: '0.9rem', fontWeight: 800 }}>{fmt(_totalTheorFC)} FC</span>
          </div>
        </div>

        {/* ── Section VENTES : qty × prix = total par catégorie ── */}
        <div style={{ backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', padding: '10px 12px', marginBottom: '10px' }}>
          <div style={{ fontSize: '0.6rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '8px', letterSpacing: '0.06em' }}>
            Ventes du Jour — Résultat
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {_cats.map(cat => {
              const prod = _prodMap[cat] ?? 0;
              const s = _soldMap[cat] ?? { qty: 0, fc: 0 };
              const restant = prod - s.qty;
              return (
                <div key={cat} style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center', gap: '8px' }}>
                  <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px', fontSize: '0.78rem' }}>
                    <span style={{ fontWeight: 800, color: s.qty > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))' }}>
                      {s.qty > 0 ? s.qty.toLocaleString('fr-FR') : '0'}
                    </span>
                    <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}>×</span>
                    <span style={{ fontWeight: 700, color: 'hsl(var(--text-secondary))' }}>{cat.toLocaleString('fr-FR')} FC</span>
                    <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}>=</span>
                    <span style={{ fontWeight: 800, color: 'hsl(var(--color-success))' }}>{fmt(s.fc)} FC</span>
                  </div>
                  <div style={{ display: 'flex', gap: '6px', fontSize: '0.6rem', justifyContent: 'flex-end' }}>
                    {prod > 0 && (
                      <span style={{ color: 'hsl(var(--color-info))' }}>produit : {prod.toLocaleString('fr-FR')}</span>
                    )}
                    {prod > 0 && (
                      <span style={{
                        color: restant < 0 ? 'hsl(var(--color-danger))' : restant > 0 ? 'hsl(var(--text-muted))' : 'hsl(var(--color-success))',
                        fontWeight: restant !== 0 ? 700 : 400,
                      }}>
                        restant : {restant > 0 ? '+' : ''}{restant.toLocaleString('fr-FR')}
                      </span>
                    )}
                  </div>
                </div>
              );
            })}
            {/* Separator + total */}
            <div style={{ borderTop: '2px solid hsl(var(--border-color))', marginTop: '4px', paddingTop: '6px', display: 'flex', alignItems: 'baseline', gap: '6px', fontSize: '0.82rem', fontWeight: 800 }}>
              <span style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.65rem', textTransform: 'uppercase' }}>Total Ventes</span>
              <span style={{ color: 'hsl(var(--color-success))' }}>{fmt(_actualSalesFC)} FC</span>
            </div>
          </div>
        </div>

        {/* ── Balance / Résultat ── */}
        <div style={{
          padding: '10px 14px',
          borderRadius: 'var(--radius-sm)',
          border: `1px solid hsl(var(--${_balanceOk ? 'color-success' : Math.abs(_ecart) < 10000 ? 'color-warning' : 'color-danger'}) / 0.4)`,
          backgroundColor: `hsl(var(--${_balanceOk ? 'color-success' : Math.abs(_ecart) < 10000 ? 'color-warning' : 'color-danger'}) / 0.06)`,
          display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px',
        }}>
          <div>
            <div style={{ fontSize: '0.62rem', fontWeight: 700, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>Résultat</div>
            <div style={{ fontSize: '0.72rem', fontWeight: 700 }}>
              <span style={{ color: 'hsl(var(--color-warning))' }}>{fmt(_totalTheorFC)} FC</span>
              <span style={{ color: 'hsl(var(--text-muted))', margin: '0 6px' }}>=</span>
              <span style={{ color: 'hsl(var(--color-success))' }}>{fmt(_actualSalesFC)} FC</span>
            </div>
          </div>
          <div style={{ textAlign: 'right' }}>
            <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>
              {_balanceOk ? 'Balance Nulle ✓' : Math.abs(_ecart) < 10000 ? 'Écart Tolérable' : 'Écart Significatif'}
            </div>
            <div style={{
              fontSize: '0.8rem', fontWeight: 800,
              color: `hsl(var(--${_balanceOk ? 'color-success' : Math.abs(_ecart) < 10000 ? 'color-warning' : 'color-danger'}))`,
            }}>
              {_balanceOk ? 'PCC — ÉQUILIBRÉ' : `${_ecart > 0 ? '+' : ''}${fmt(_ecart)} FC`}
            </div>
          </div>
        </div>

      </div>
    );
  }

  let entryModal: React.ReactElement | null = null;
  if (detailEntry) {
    const en = detailEntry;
    const isEntry = parseFloat(en.entry_amount) > 0;
    entryModal = (
      <Modal isOpen={true} onClose={() => setDetailEntry(null)} maxWidth="460px">
          {en.is_tampered && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '5px 10px', marginBottom: '12px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
              <FiAlertTriangle /> ATTENTION — Écriture potentiellement altérée !
            </div>
          )}
          <h3 style={{ fontSize: '1rem', fontWeight: 800, marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FiLock style={{ color: isEntry ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))', fontSize: '0.9rem' }} />
            {en.piece_number}
            {en.is_correction && (
              <span className="badge badge-warning" style={{ fontSize: '0.56rem', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                <FiRefreshCw style={{ fontSize: '0.65rem' }} /> Correction
              </span>
            )}
          </h3>
          <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginBottom: '16px' }}>
            {new Date(en.date).toLocaleDateString('fr-FR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
            {en.node_display ? ` · ${en.node_display}` : ''}
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {[
              { label: 'Libellé', value: en.label },
              { label: 'Imputation', value: en.imputation || '—' },
              { label: 'Entrée FC', value: parseFloat(en.entry_amount) > 0 ? `+${fmt(en.entry_amount)} FC` : '—', color: 'hsl(var(--color-success))' },
              { label: 'Sortie FC', value: parseFloat(en.exit_amount) > 0 ? `−${fmt(en.exit_amount)} FC` : '—', color: 'hsl(var(--color-danger))' },
              { label: 'Solde Cumulé', value: `${fmt(en.running_balance)} FC`, color: parseFloat(en.running_balance) >= 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--color-danger))' },
            ].map(row => (
              <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', fontSize: '0.72rem' }}>
                <span style={{ color: 'hsl(var(--text-secondary))' }}>{row.label}</span>
                <strong style={{ color: row.color || 'hsl(var(--text-primary))' }}>{row.value}</strong>
              </div>
            ))}
          </div>
          {en.is_correction && (
            <div style={{ marginTop: '14px', padding: '8px 10px', backgroundColor: 'hsl(var(--color-warning) / 0.08)', border: '1px solid hsl(var(--color-warning) / 0.3)', borderRadius: 'var(--radius-sm)', fontSize: '0.68rem' }}>
              <div style={{ fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <FiRefreshCw /> Écriture de correction — traçabilité
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Motif : </span>
                  <strong>{en.correction_reason || '—'}</strong>
                </div>
                <div>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Corrigé par : </span>
                  <strong>{en.corrected_by_display || '—'}</strong>
                </div>
                <div>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Facture d'origine : </span>
                  {en.correction_source_invoice ? (
                    <strong style={{ fontFamily: 'monospace', fontSize: '0.6rem' }} title={en.correction_source_invoice}>
                      {en.correction_source_invoice.slice(0, 8)}…
                    </strong>
                  ) : (
                    <strong>—</strong>
                  )}
                </div>
              </div>
            </div>
          )}
          <div style={{ marginTop: '14px', padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', fontSize: '0.6rem', fontFamily: 'monospace', color: 'hsl(var(--text-muted))', wordBreak: 'break-all' }}>
            <div style={{ fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', fontSize: '0.62rem' }}>
              <FiLock style={{ marginRight: '4px', verticalAlign: 'middle' }} />
              Empreinte Blockchain
            </div>
            {en.block_hash || '—'}
          </div>
          <button onClick={() => setDetailEntry(null)} className="btn btn-secondary" style={{ width: '100%', marginTop: '14px', padding: '6px', fontSize: '0.75rem' }}>
            Fermer
          </button>
      </Modal>
    );
  }

  let closureModal: React.ReactElement | null = null;
  if (detailClosure) {
    const cl = detailClosure;
    const gap = parseFloat(cl.cash_gap);
    closureModal = (
      <Modal
        isOpen={true}
        onClose={() => setDetailClosure(null)}
        title={`Rapport de caisse — ${cl.node_display || cl.node}`}
        subtitle={`Date : ${cl.date} · Gérant : ${(cl as any).gerant_display || '—'}`}
        maxWidth="480px"
      >
          <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '6px' }}>Versement du jour</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginBottom: '12px' }}>
            {BILLS.map(b => {
              const qty = cl[b.key as keyof CashClosure] as number;
              if (!qty) return null;
              return (
                <div key={b.key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', padding: '2px 6px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px' }}>
                  <span>{b.label}</span>
                  <span>× {qty} = <strong>{(qty * b.face).toLocaleString('fr-FR')} FC</strong></span>
                </div>
              );
            })}
            {BILLS.every(b => !(cl[b.key as keyof CashClosure] as number)) && (
              <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '4px 6px' }}>Aucun billet saisi</div>
            )}
          </div>
          <div style={{ borderTop: '1px solid hsl(var(--border-color))', paddingTop: '10px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
            {[
              { label: 'Total Espèces Physiques', value: fmt(cl.physical_cash_total) + ' FC', color: 'hsl(var(--color-success))' },
              { label: 'Total Entrées Cash (Ventes)', value: fmt(cl.total_entries) + ' FC', color: 'hsl(var(--text-primary))' },
              { label: 'Total Dépenses Locales', value: '−' + fmt(cl.total_expenses) + ' FC', color: 'hsl(var(--color-danger))' },
              { label: 'Caisse Nette (Net Cash)', value: fmt(cl.net_cash) + ' FC', color: 'hsl(var(--color-warning))' },
            ].map(row => (
              <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem' }}>
                <span style={{ color: 'hsl(var(--text-secondary))' }}>{row.label}</span>
                <strong style={{ color: row.color }}>{row.value}</strong>
              </div>
            ))}
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', fontWeight: 800, padding: '6px 8px', marginTop: '4px', borderRadius: 'var(--radius-sm)', backgroundColor: gap === 0 ? 'hsl(var(--color-success) / 0.08)' : 'hsl(var(--color-danger) / 0.08)', border: `1px solid hsl(var(--${gap === 0 ? 'color-success' : 'color-danger'}) / 0.3)` }}>
              <span>ÉCART DE CAISSE</span>
              <span style={{ color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                {gap >= 0 ? '+' : ''}{fmt(cl.cash_gap)} FC{gap === 0 ? ' ✓ Équilibré' : gap > 0 ? ' (Excédent)' : ' (Manque)'}
              </span>
            </div>
          </div>
          {(cl as any).notes && (
            <div style={{ marginTop: '10px', fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', backgroundColor: 'hsl(var(--bg-tertiary))', padding: '6px 10px', borderRadius: 'var(--radius-sm)', whiteSpace: 'pre-line' }}>
              <strong>Notes :</strong> {(cl as any).notes}
            </div>
          )}
          {/* Rejection notice */}
          {cl.is_rejected && (
            <div style={{ marginTop: '10px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.08)', border: '1px solid hsl(var(--color-danger) / 0.3)', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
              <strong>INFIRMÉE</strong> — Motif : {cl.rejection_reason || 'Non précisé'}
            </div>
          )}

          <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              <span className={`badge ${cl.is_validated ? 'badge-success' : cl.is_rejected ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.62rem' }}>
                {cl.is_validated ? 'CONFIRMÉE' : cl.is_rejected ? 'INFIRMÉE' : 'EN ATTENTE'}
              </span>

              {/* HQ only: confirm / reject */}
              {user?.can_access_all_nodes && !cl.is_validated && (
                <>
                  <button
                    onClick={() => { setValidatingClosureId(validatingClosureId === cl.id ? null : cl.id); setRejectingClosureId(null); }}
                    className="btn btn-primary"
                    style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                  >
                    <FiCheckCircle /> Confirmer
                  </button>
                  <button
                    onClick={() => { setRejectingClosureId(rejectingClosureId === cl.id ? null : cl.id); setValidatingClosureId(null); }}
                    className="btn btn-secondary"
                    style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.4)' }}
                  >
                    <FiX /> Infirmer
                  </button>
                </>
              )}

              {/* HQ: push to cashbook after validation */}
              {cl.is_validated && user?.can_access_all_nodes && (
                <button
                  onClick={() => { handlePushToCashbook(cl.id); setDetailClosure(null); }}
                  disabled={closureActionLoading}
                  className="btn btn-secondary"
                  style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', opacity: closureActionLoading ? 0.6 : 1 }}
                >
                  <FiBook /> Inscrire au Livre de Caisse
                </button>
              )}
            </div>

            {/* Confirm form (inline, HQ only) */}
            {validatingClosureId === cl.id && (
              <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start', flexDirection: 'column' }}>
                <textarea
                  value={validateNotes}
                  onChange={e => setValidateNotes(e.target.value)}
                  placeholder="Commentaire du comptable (facultatif)…"
                  className="form-input"
                  rows={2}
                  style={{ fontSize: '0.7rem', resize: 'vertical', width: '100%' }}
                />
                <button
                  onClick={() => handleValidateClosure(cl.id, validateNotes)}
                  disabled={closureActionLoading}
                  className="btn btn-primary"
                  style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', opacity: closureActionLoading ? 0.6 : 1 }}
                >
                  <FiCheckCircle /> {closureActionLoading ? 'Confirmation...' : 'Confirmer la clôture'}
                </button>
              </div>
            )}

            {/* Reject form (inline, HQ only) */}
            {rejectingClosureId === cl.id && (
              <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start', flexDirection: 'column' }}>
                <textarea
                  value={rejectReason}
                  onChange={e => setRejectReason(e.target.value)}
                  placeholder="Motif du rejet (facultatif)…"
                  className="form-input"
                  rows={2}
                  style={{ fontSize: '0.7rem', resize: 'vertical', width: '100%' }}
                />
                <button
                  onClick={() => handleRejectClosure(cl.id)}
                  disabled={closureActionLoading}
                  className="btn btn-primary"
                  style={{ padding: '4px 12px', fontSize: '0.7rem', backgroundColor: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger))', opacity: closureActionLoading ? 0.6 : 1 }}
                >
                  {closureActionLoading ? 'Rejet...' : 'Confirmer le rejet'}
                </button>
              </div>
            )}
          </div>
      </Modal>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px', fontSize: '0.85rem' }}>

      {/* Header */}
      <div className="glass-card animate-fade-in" style={{ background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)', borderLeft: '4px solid hsl(var(--accent-color))', padding: '14px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '2px' }}>Clôture & Caisse — 3 Niveaux</h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem' }}>
              §5.1 Rapports journaliers · §5.2 Versement · §5.3 Livre de Caisse Direction
            </p>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
            <button onClick={loadData} disabled={isLoading} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiRefreshCw style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
              <span>Actualiser</span>
            </button>
            <FiBook style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
          </div>
        </div>
      </div>

      {/* KPI Bar */}
      <div className="kpi-grid" style={{ gap: '12px' }}>
        {[
          { label: 'TOTAL CASH DU JOUR', value: `${fmt(totalCash)} FC`, color: 'var(--color-success)', icon: <FiDollarSign /> },
          { label: 'TOTAL CRÉDIT DU JOUR', value: `${fmt(totalCredit)} FC`, color: 'var(--color-info)', icon: <FiFileText /> },
          { label: 'SOLDE COMPTABLE CAISSE', value: `${fmt(theoreticalCash)} FC`, color: 'var(--color-warning)', icon: <FiLock /> },
          { label: 'ÉCART BILLETAGE', value: `${ecartCaisse >= 0 ? '+' : ''}${fmt(ecartCaisse)} FC`, color: ecartCaisse === 0 ? 'var(--color-success)' : 'var(--color-danger)', icon: <FiAlertTriangle /> },
        ].map((k, i) => (
          <div key={i} className="glass-card" style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: `hsl(${k.color} / 0.1)`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: `hsl(${k.color})`, flexShrink: 0 }}>{k.icon}</div>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>{k.label}</div>
              <div style={{ fontSize: '0.9rem', fontWeight: 800, color: `hsl(${k.color})` }}>{k.value}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ═══ §5.1.1 — NIVEAU 1 : RAPPORTS FACTURIERS ═══ */}
      <div className="glass-card" style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiFileText style={{ color: 'hsl(var(--accent-color))' }} />
            §5.1.1 — Niveau 1 · Rapports Journaliers des Facturiers
          </h2>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>Aujourd'hui : {today}</span>
            {user?.can_access_all_nodes && allNodes.length > 0 && (
              <select
                value={nodeFilter}
                onChange={e => setNodeFilter(e.target.value)}
                className="form-input"
                style={{ height: '28px', fontSize: '0.68rem', padding: '0 6px', minWidth: '140px' }}
              >
                <option value="">Toutes les succursales</option>
                {allNodes.map(n => (
                  <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                ))}
              </select>
            )}
            {/* BUG-086 : date rétroactive optionnelle pour la génération — visible seulement si activée en Configuration */}
            {allowBackdatedSales && (
              <input
                type="date"
                max={today}
                value={reportDate}
                onChange={e => setReportDate(e.target.value)}
                title="Date du rapport (optionnel — vide = aujourd'hui, jamais une date future)"
                className="form-input"
                style={{ height: '28px', fontSize: '0.68rem', padding: '0 6px', width: '128px' }}
              />
            )}
            <button
              onClick={handlePrint511}
              className="btn btn-secondary"
              title="Imprimer §5.1.1"
              style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <FiPrinter size={13} />
              Imprimer
            </button>
            <button
              onClick={handleGenerateReport}
              disabled={generatingReport}
              className="btn btn-primary"
              style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <FiRefreshCw style={{ animation: generatingReport ? 'spin 1s linear infinite' : 'none' }} />
              {generatingReport
                ? 'Génération...'
                : (allowBackdatedSales && reportDate && reportDate !== today)
                  ? `Générer Rapport du ${new Date(reportDate).toLocaleDateString('fr-FR')}`
                  : 'Générer Rapport du Jour'}
            </button>
          </div>
        </div>
        {generateError && (
          <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)', marginBottom: '8px' }}>
            {generateError}
          </div>
        )}
        {generateInfo && (
          <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-info))', backgroundColor: 'hsl(var(--color-info) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)', marginBottom: '8px' }}>
            {generateInfo}
          </div>
        )}
        {productionRecap}
        {reports.length === 0 ? (
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
                {user?.can_access_all_nodes
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
                                <button onClick={() => handleValidateReport(r.id)} className="btn btn-primary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Valider</button>
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
                          <td style={{ textAlign: 'right', color: 'hsl(var(--color-success))' }}>{fmt(nodeCash)} FC</td>
                          <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(nodeCredit)} FC</td>
                          <td style={{ textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{fmt(nodeTheo)} FC</td>
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
                              <button onClick={() => handleValidateReport(r.id)} className="btn btn-primary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>
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
                  <td style={{ textAlign: 'right', color: 'hsl(var(--color-success))' }}>{fmt(totalCash)} FC</td>
                  <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(totalCredit)} FC</td>
                  <td style={{ textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{fmt(theoreticalCash)} FC</td>
                  <td colSpan={2} />
                </tr>
              </tbody>
            </table>
          </div>
        )}
      </div>

      {/* ═══ §5.1.2 + §5.2 — CLÔTURE GÉRANT : dépenses/encaissements saisis d'abord, puis billetage et dégagement des écarts ═══ */}
      <div className="split-grid" style={{ '--split-cols': user?.can_access_all_nodes ? '1fr' : '1fr 1.3fr', gap: '16px' } as React.CSSProperties}>

        {/* §5.2 — BILLETAGE PHYSIQUE — saisie du gérant uniquement (le comptable/Direction confirme, mais ne saisit pas le versement). Affiché en second (order 2) : dépend des dépenses déjà saisies pour calculer l'écart. */}
        {!user?.can_access_all_nodes && (
        <div className="glass-card" style={{ padding: '16px', order: 2 }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiDollarSign style={{ color: editingClosure ? 'hsl(var(--color-warning))' : 'hsl(var(--accent-color))' }} />
            {editingClosure ? 'Corriger la Clôture Infirmée' : 'Versement'}
          </h2>
          {editingClosure && (
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-warning))', fontWeight: 700, marginBottom: '6px', padding: '5px 8px', backgroundColor: 'hsl(var(--color-warning) / 0.08)', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--color-warning) / 0.3)' }}>
              Motif du rejet : {editingClosure.rejection_reason || 'Non précisé'} &nbsp;
              <button type="button" onClick={() => { setEditingClosure(null); setBills({ bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0, bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0 }); setClosureNotes(''); }} style={{ marginLeft: '8px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Annuler</button>
            </div>
          )}
          {!editingClosure && selectedNodeLabel && (
            <div style={{ fontSize: '0.62rem', color: 'hsl(var(--accent-color))', fontWeight: 700, marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiLock size={10} />
              {selectedNodeLabel}
            </div>
          )}
          <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
            Saisir le nombre de coupures physiques — le système calcule et compare au solde théorique.
          </p>
          <form onSubmit={handleCreateClosure} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {/* Header row */}
            <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 1fr', gap: '8px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase', marginBottom: '2px', paddingBottom: '4px', borderBottom: '1px solid hsl(var(--border-color))' }}>
              <span>Valeur Faciale</span><span style={{ textAlign: 'right' }}>Quantité</span><span style={{ textAlign: 'right' }}>Sous-Total FC</span>
            </div>
            {BILLS.map(b => {
              const subtotal = bills[b.key] * b.face;
              return (
                <div key={b.key} style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 1fr', gap: '8px', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.75rem', fontWeight: 700 }}>{b.label}</span>
                  <input
                    type="number" min={0}
                    value={bills[b.key] || ''}
                    placeholder="0"
                    onChange={e => setBills(prev => ({ ...prev, [b.key]: Math.max(0, Number(e.target.value)) }))}
                    className="form-input"
                    disabled={!!editingClosure?.is_validated}
                    style={{ fontSize: '0.78rem', height: '26px', padding: '0 6px', textAlign: 'right', fontWeight: 700 }}
                  />
                  <span style={{ textAlign: 'right', fontSize: '0.73rem', fontWeight: subtotal > 0 ? 800 : 400, color: subtotal > 0 ? 'hsl(var(--text-primary))' : 'hsl(var(--text-muted))' }}>
                    {subtotal > 0 ? subtotal.toLocaleString('fr-FR') : '—'}
                  </span>
                </div>
              );
            })}

            {/* Totals comparison */}
            <div style={{ borderTop: '2px solid hsl(var(--border-color))', marginTop: '4px', paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800 }}>
                <span>TOTAL GÉNÉRAL ESPÈCES :</span>
                <span style={{ color: 'hsl(var(--color-success))', fontSize: '0.9rem' }}>{billTotal.toLocaleString('fr-FR')} FC</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                <span>
                  Recette / Paiement :
                  <span style={{ fontSize: '0.58rem', color: 'hsl(var(--text-muted))', marginLeft: '4px' }}>
                    {reports.length > 0 ? `(§5.1.1 · ${reports.length} rapport(s))` : '(aucun rapport §5.1.1)'}
                  </span>
                </span>
                <span style={{ fontWeight: 700, color: reports.length > 0 ? 'inherit' : 'hsl(var(--color-warning))' }}>{fmt(theoreticalCash)} FC</span>
              </div>
              {totalExpenses > 0 && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                  <span>— Dépenses Locales :</span>
                  <span style={{ fontWeight: 700, color: 'hsl(var(--color-danger))' }}>−{fmt(totalExpenses)} FC</span>
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                <span>Solde comptable caisse :</span>
                <span style={{ fontWeight: 800, color: 'hsl(var(--color-warning))' }}>{fmt(theoreticalCash - totalExpenses)} FC</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800, padding: '5px 8px', borderRadius: 'var(--radius-sm)', backgroundColor: ecartCaisse === 0 ? 'hsl(var(--color-success) / 0.08)' : 'hsl(var(--color-danger) / 0.08)', border: `1px solid hsl(var(--${ecartCaisse === 0 ? 'color-success' : 'color-danger'}) / 0.3)` }}>
                <span>ÉCART DE CAISSE :</span>
                <span style={{ color: ecartCaisse === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                  {ecartCaisse >= 0 ? '+' : ''}{ecartCaisse.toLocaleString('fr-FR')} FC
                  {ecartCaisse > 0 ? ' (Excédent)' : ecartCaisse < 0 ? ' (Manque)' : ' ✓ Équilibré'}
                </span>
              </div>
            </div>

            {/* BUG-086 : date de clôture rétroactive optionnelle (nouvelle clôture uniquement) —
                visible seulement si activée en Configuration. */}
            {allowBackdatedSales && !editingClosure && (
              <div>
                <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '3px', textTransform: 'uppercase' }}>
                  Date de la clôture (optionnel)
                </label>
                <span style={{ display: 'block', fontSize: '0.58rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                  Laisser vide = aujourd'hui. Jamais une date future.
                </span>
                <input
                  type="date"
                  max={today}
                  value={closureDate}
                  onChange={e => setClosureDate(e.target.value)}
                  className="form-input"
                  style={{ fontSize: '0.72rem', height: '28px', padding: '0 8px' }}
                />
              </div>
            )}

            <div>
              <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Notes (optionnel)</label>
              <input type="text" value={closureNotes} onChange={e => setClosureNotes(e.target.value)} placeholder="Observations, écart justifié..." className="form-input" disabled={!!editingClosure?.is_validated} style={{ fontSize: '0.72rem', height: '28px', padding: '0 8px' }} />
            </div>

            {closureError && (
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <span>{closureError}</span>
                {closureBlockedByTransferGap && (
                  <Link
                    to="/production"
                    style={{ alignSelf: 'flex-start', fontWeight: 700, color: 'hsl(var(--accent-color))', textDecoration: 'underline' }}
                  >
                    Voir les transferts inter-boulangeries (§3.3) →
                  </Link>
                )}
              </div>
            )}
            {closureInfo && (
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-info))', backgroundColor: 'hsl(var(--color-info) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)' }}>
                {closureInfo}
              </div>
            )}

            {/* BUG-046 : une clôture déjà confirmée par le comptable est figée — pas de bouton de soumission dans ce cas. */}
            {(!todayClosure || editingClosure) && !editingClosure?.is_validated && (
              <button type="submit" className="btn btn-primary" style={{ padding: '7px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px', ...(editingClosure ? { backgroundColor: 'hsl(var(--color-warning))', borderColor: 'hsl(var(--color-warning))' } : {}) }}>
                <FiLock /> {editingClosure
                  ? 'Corriger et Re-soumettre'
                  : (allowBackdatedSales && closureDate && closureDate !== today)
                    ? `Valider la Clôture du ${new Date(closureDate).toLocaleDateString('fr-FR')}`
                    : 'Valider la Clôture de Caisse du Jour'}
              </button>
            )}
            {todayClosure && !editingClosure && (
              <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-success))', fontWeight: 700, textAlign: 'center', padding: '6px' }}>
                <FiCheckCircle style={{ marginRight: '4px' }} />Clôture créée — Physical total: {fmt(todayClosure.physical_cash_total)} FC · Écart: {fmt(todayClosure.cash_gap)} FC
              </div>
            )}
          </form>
        </div>
        )}

        {/* §5.1.2 — NIVEAU 2 : CLÔTURE GÉRANT — dépenses & encaissements. Affiché en premier (order 1). */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', order: 1 }}>
          {/* Expenses */}
          <div className="glass-card" style={{ padding: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
              <h2 style={{ fontSize: '0.85rem', fontWeight: 800 }}>
                §5.1.2 — Dépenses Locales
                {selectedNodeLabel && (
                  <span style={{ fontSize: '0.58rem', color: 'hsl(var(--accent-color))', fontWeight: 700, marginLeft: '6px' }}>
                    · {selectedNodeLabel}
                  </span>
                )}
              </h2>
              <div style={{ display: 'flex', gap: '6px' }}>
                <button onClick={() => setExpenseHistoryOpen(true)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
                  <FiCalendar /> Historique
                </button>
                <button onClick={() => setShowExpenseForm(!showExpenseForm)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
                  {showExpenseForm ? <FiX /> : <FiPlus />}
                  {showExpenseForm ? 'Annuler' : 'Ajouter'}
                </button>
              </div>
            </div>

            {showExpenseForm && (
              <form onSubmit={handleAddExpense} style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '10px', padding: '10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>Catégorie</label>
                    <select value={expCategory} onChange={e => setExpCategory(e.target.value)} className="form-input" style={{ fontSize: '0.7rem', height: '28px' }}>
                      {expenseCategories.length === 0 && <option value="">Aucune catégorie — voir Configuration</option>}
                      {expenseCategories.map(ec => <option key={ec.id} value={ec.id}>{ec.label}</option>)}
                    </select>
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>Montant (FC)</label>
                    <input type="number" min={1} value={expAmount} onChange={e => setExpAmount(e.target.value)} placeholder="0" className="form-input" style={{ fontSize: '0.75rem', height: '28px', padding: '0 6px' }} />
                  </div>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>Description</label>
                  <input type="text" value={expDesc} onChange={e => setExpDesc(e.target.value)} placeholder="Nature de la dépense..." className="form-input" style={{ fontSize: '0.7rem', height: '28px', padding: '0 6px' }} />
                </div>
                {expError && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-danger))' }}>{expError}</div>}
                <button type="submit" className="btn btn-primary" style={{ padding: '5px', fontSize: '0.72rem' }}>Enregistrer la Dépense</button>
              </form>
            )}

            <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '150px', overflowY: 'auto' }}>
              {expenses.map(e => (
                <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', padding: '4px 6px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px' }}>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>{e.description} <em>({e.category_display || e.category})</em></span>
                  <strong style={{ color: 'hsl(var(--color-danger))' }}>-{fmt(e.amount)} FC</strong>
                </div>
              ))}
              {expenses.length === 0 && <div style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '8px' }}>Aucune dépense locale</div>}
            </div>

            {/* Net caisse */}
            <div style={{ marginTop: '8px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '6px', display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', fontWeight: 800 }}>
              <span>Caisse Nette Boulangerie :</span>
              <span style={{ color: netCaisse >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                {fmt(netCaisse)} FC
              </span>
            </div>
          </div>

          {/* Synthèse globale — billetage de toutes les boulangeries */}
          {user?.can_access_all_nodes && (
            <div className="glass-card" style={{ padding: '14px', overflowX: 'auto' }}>
              <h2 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '10px' }}>
                Synthèse Globale — Billetage de Toutes les Boulangeries ({today})
              </h2>
              {closures.length === 0 ? (
                <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucune clôture aujourd'hui.</div>
              ) : (
                <table className="premium-table" style={{ fontSize: '0.66rem', minWidth: '720px' }}>
                  <thead>
                    <tr style={{ textTransform: 'uppercase', fontSize: '0.6rem' }}>
                      <th style={{ textAlign: 'left' }}>Boulangerie</th>
                      {BILLS.map(b => (
                        <th key={b.key} style={{ textAlign: 'right' }}>{b.label}</th>
                      ))}
                      <th style={{ textAlign: 'right' }}>Total Physique</th>
                      <th style={{ textAlign: 'right' }}>Écart</th>
                    </tr>
                  </thead>
                  <tbody>
                    {closures.map(c => (
                      <tr key={c.id}>
                        <td style={{ fontWeight: 700 }}>{c.node_display || c.node}</td>
                        {BILLS.map(b => (
                          <td key={b.key} style={{ textAlign: 'right' }}>{(c[b.key as keyof CashClosure] as number) || 0}</td>
                        ))}
                        <td style={{ textAlign: 'right', fontWeight: 700 }}>{fmt(c.physical_cash_total)}</td>
                        <td style={{ textAlign: 'right', color: parseFloat(c.cash_gap) === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(c.cash_gap)}</td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr style={{ fontWeight: 800, borderTop: '2px solid hsl(var(--border-color))' }}>
                      <td>TOTAL</td>
                      {BILLS.map(b => (
                        <td key={b.key} style={{ textAlign: 'right' }}>
                          {closures.reduce((s, c) => s + ((c[b.key as keyof CashClosure] as number) || 0), 0)}
                        </td>
                      ))}
                      <td style={{ textAlign: 'right' }}>{fmt(closures.reduce((s, c) => s + parseFloat(String(c.physical_cash_total || '0')), 0))}</td>
                      <td style={{ textAlign: 'right' }}>{fmt(closures.reduce((s, c) => s + parseFloat(String(c.cash_gap || '0')), 0))}</td>
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>
          )}

          {/* Closures — validate + push to cashbook */}
          <div className="glass-card" style={{ padding: '14px' }}>
            <h2 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '10px' }}>Clôtures du Jour</h2>
            {closures.length === 0 ? (
              <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucune clôture créée</div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {closures.map(c => (
                  <div
                    key={c.id}
                    onClick={() => setDetailClosure(c)}
                    style={{ padding: '8px 10px', border: `1px solid hsl(var(--${c.is_validated ? 'color-success' : 'border-color'}) / 0.4)`, borderRadius: 'var(--radius-sm)', backgroundColor: c.is_validated ? 'hsl(var(--color-success) / 0.04)' : 'hsl(var(--bg-secondary))', cursor: 'pointer' }}
                  >
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                      <div style={{ fontSize: '0.7rem' }}>
                        <strong>{c.node_display || c.node}</strong>
                        <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>{c.date}</span>
                      </div>
                      <span className={`badge ${c.is_validated ? 'badge-success' : (c as any).is_rejected ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.52rem' }}>
                        {c.is_validated ? 'CONFIRMÉE' : (c as any).is_rejected ? 'INFIRMÉE' : 'EN ATTENTE'}
                      </span>
                    </div>
                    <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>
                      Espèces physiques: <strong>{fmt(c.physical_cash_total)} FC</strong> · Écart: <strong style={{ color: parseFloat(c.cash_gap) === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(c.cash_gap)} FC</strong>
                    </div>
                    {c.is_rejected && !c.is_validated && (
                      <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-danger))', margin: '4px 0', padding: '4px 8px', backgroundColor: 'hsl(var(--color-danger) / 0.08)', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--color-danger) / 0.25)' }}>
                        Motif : {c.rejection_reason || 'Non précisé'}
                      </div>
                    )}
                    {user?.can_access_all_nodes && !c.is_validated && (
                      <div style={{ fontSize: '0.62rem', textAlign: 'center', color: 'hsl(var(--text-muted))' }}>
                        Cliquez pour confirmer / infirmer
                      </div>
                    )}
                    <div style={{ display: 'flex', gap: '6px' }} onClick={e => e.stopPropagation()}>
                      {c.is_rejected && !c.is_validated && !user?.can_access_all_nodes && (
                        <button
                          onClick={() => {
                            setEditingClosure(c);
                            setBills({ bills_20000: c.bills_20000 || 0, bills_10000: c.bills_10000 || 0, bills_5000: c.bills_5000 || 0, bills_1000: c.bills_1000 || 0, bills_500: c.bills_500 || 0, bills_200: c.bills_200 || 0, bills_100: c.bills_100 || 0, bills_50: c.bills_50 || 0 });
                            setClosureNotes(c.notes || '');
                          }}
                          className="btn btn-primary"
                          style={{ flex: 1, padding: '4px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', backgroundColor: 'hsl(var(--color-warning))', borderColor: 'hsl(var(--color-warning))' }}
                        >
                          <FiRefreshCw size={11} /> Corriger et re-soumettre
                        </button>
                      )}
                      {c.is_validated && user?.can_access_all_nodes && !c.has_cashbook_entry && (
                        <button onClick={() => handlePushToCashbook(c.id)} className="btn btn-secondary" style={{ flex: 1, padding: '4px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                          <FiBook /> Inscrire au Livre de Caisse
                        </button>
                      )}
                      {c.has_cashbook_entry && (
                        <div style={{ flex: 1, padding: '4px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', color: 'hsl(var(--color-success))', fontWeight: 600 }}>
                          <FiBook size={11} /> Inscrit au grand livre
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ═══ Bordereaux de Versement — Décaissements Direction ═══ */}
      {user?.can_access_all_nodes && (
        <div className="glass-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
            <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
              Bordereaux de Versement — Décaissements Direction
            </h2>
            <div style={{ display: 'flex', gap: '8px' }}>
              <button onClick={handleFinalReport} className="btn btn-secondary" style={{ padding: '5px 12px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <FiPrinter /> Générer bordereau final
              </button>
              <button onClick={() => setShowVoucherForm(v => !v)} className="btn btn-primary" style={{ padding: '5px 12px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <FiPlus /> {showVoucherForm ? 'Annuler' : 'Nouveau bordereau'}
              </button>
            </div>
          </div>

          <div style={{ marginBottom: '12px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.75rem', display: 'flex', justifyContent: 'space-between' }}>
            <span style={{ color: 'hsl(var(--text-secondary))' }}>Solde consolidé disponible (Livre de Caisse)</span>
            <strong style={{ color: consolidatedBalance >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(consolidatedBalance)} FC</strong>
          </div>

          {showVoucherForm && (
            <form onSubmit={handleCreateVoucher} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '14px', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '2fr 1fr', gap: '8px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Motif *</label>
                  <input type="text" value={voucherMotif} onChange={e => setVoucherMotif(e.target.value)} placeholder="Ex: Achat matériel, salaire..." className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', width: '100%' }} required />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Bénéficiaire</label>
                  <input type="text" value={voucherBeneficiary} onChange={e => setVoucherBeneficiary(e.target.value)} placeholder="optionnel" className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', width: '100%' }} />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '5px' }}>Billetage (sortie)</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                  {BILLS.map(b => (
                    <div key={b.key}>
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>{b.label}</div>
                      <input
                        type="number" min={0} value={voucherBills[b.key]}
                        onChange={e => setVoucherBills(prev => ({ ...prev, [b.key]: Math.max(0, parseInt(e.target.value) || 0) }))}
                        className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '100%' }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', padding: '6px 8px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)' }}>
                <span>Total du bordereau</span>
                <strong style={{ color: voucherBillTotal > consolidatedBalance ? 'hsl(var(--color-danger))' : 'hsl(var(--accent-color))' }}>{fmt(voucherBillTotal)} FC</strong>
              </div>
              {voucherBillTotal > consolidatedBalance && (
                <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
                  Montant supérieur au solde disponible — la création sera refusée.
                </div>
              )}

              {voucherError && <div style={{ fontSize: '0.7rem', color: 'hsl(var(--color-danger))' }}>{voucherError}</div>}
              <button type="submit" disabled={voucherSubmitting} className="btn btn-primary" style={{ padding: '7px', fontSize: '0.75rem' }}>
                {voucherSubmitting ? 'Enregistrement...' : 'Enregistrer le bordereau'}
              </button>
            </form>
          )}

          {/* Vouchers list */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {vouchersLoading ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement...</div>
            ) : vouchers.length === 0 ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucun bordereau sur la période.</div>
            ) : (
              vouchers.map(v => (
                <div key={v.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-secondary))' }}>
                  <div>
                    <div style={{ fontSize: '0.75rem', fontWeight: 700 }}>{v.motif}{v.beneficiary ? ` — ${v.beneficiary}` : ''}</div>
                    <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>{v.piece_number} · {new Date(v.date).toLocaleDateString('fr-FR')} · {v.created_by_display || '—'}</div>
                  </div>
                  <strong style={{ fontSize: '0.78rem', color: 'hsl(var(--color-danger))' }}>−{fmt(v.physical_cash_total)} FC</strong>
                </div>
              ))
            )}
          </div>
        </div>
      )}

      {/* ═══ §5.1.3 — NIVEAU 3 : LIVRE DE CAISSE DIRECTION ═══ */}
      {/* BUG-044 : réservé au siège (IsHeadquarters côté API depuis BUG-026) — masqué pour GERANT/FACTURIER/LIVREUR plutôt que de laisser les appels échouer en 403. */}
      {user?.can_access_all_nodes && (
      <div className="glass-card" style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiBook style={{ color: 'hsl(var(--accent-color))' }} />
            §5.1.3 — Livre de Caisse Direction (Grand Livre Immuable)
          </h2>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '4px', fontSize: '0.7rem' }}>
              <label style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Du</label>
              <input type="date" value={dateFrom} onChange={e => setDateFrom(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px' }} />
              <label style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Au</label>
              <input type="date" value={dateTo} onChange={e => setDateTo(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px' }} />
              <button onClick={loadData} className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.68rem' }}>Filtrer</button>
            </div>
            {user?.can_access_all_nodes && (
              <button
                onClick={handleIntegrityCheck}
                disabled={checkingIntegrity}
                className={`btn ${integrityResult ? (integrityResult.chain_valid ? 'btn-secondary' : 'btn-danger') : 'btn-secondary'}`}
                style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
              >
                <FiLock />
                {checkingIntegrity ? 'Vérification...' : 'Vérifier Intégrité SHA-256'}
              </button>
            )}
          </div>
        </div>

        {/* Integrity result */}
        {integrityResult && (
          <div style={{ marginBottom: '12px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', border: `1px solid hsl(var(--${integrityResult.chain_valid ? 'color-success' : 'color-danger'}) / 0.4)`, backgroundColor: `hsl(var(--${integrityResult.chain_valid ? 'color-success' : 'color-danger'}) / 0.06)`, fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '8px' }}>
            {integrityResult.chain_valid ? <FiCheckCircle style={{ color: 'hsl(var(--color-success))' }} /> : <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
            <span style={{ fontWeight: 700, color: integrityResult.chain_valid ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
              {integrityResult.chain_valid ? 'Chaîne intègre — Aucune altération détectée' : `ALTÉRATIONS DÉTECTÉES — ${integrityResult.tampered_count} écriture(s) compromise(s)`}
            </span>
          </div>
        )}

        {/* Cashbook table — §5.1.3 structure */}
        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                <th style={{ textAlign: 'center', width: '90px' }}>Date</th>
                <th style={{ width: '110px' }}>N° Pièce</th>
                <th style={{ width: '70px' }}>Imputation</th>
                <th>Libellés (Origine / Nature)</th>
                <th style={{ textAlign: 'right', width: '110px' }}>Entrée FC</th>
                <th style={{ textAlign: 'right', width: '110px' }}>Sortie FC</th>
                <th style={{ textAlign: 'right', width: '120px' }}>Solde Consolidé FC</th>
                <th style={{ textAlign: 'center', width: '50px' }}>Intégrité</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.7rem' }}>
              {cashbook.map(entry => (
                <tr key={entry.id} onClick={() => setDetailEntry(entry)} style={{ backgroundColor: entry.is_tampered ? 'hsl(var(--color-danger) / 0.08)' : 'transparent', cursor: 'pointer' }}>
                  <td style={{ textAlign: 'center', color: 'hsl(var(--text-secondary))', fontFamily: 'monospace', fontSize: '0.65rem' }}>
                    {new Date(entry.date).toLocaleDateString('fr-FR')}
                  </td>
                  <td style={{ fontWeight: 700, color: 'hsl(var(--accent-color))', fontSize: '0.65rem', fontFamily: 'monospace' }}>
                    {entry.piece_number}
                  </td>
                  <td style={{ color: 'hsl(var(--text-muted))', fontSize: '0.62rem', fontFamily: 'monospace' }}>
                    {entry.imputation || '—'}
                  </td>
                  <td style={{ color: 'hsl(var(--text-primary))', maxWidth: '240px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {entry.is_correction && (
                      <span
                        className="badge badge-warning"
                        title={`Écriture de correction${entry.correction_reason ? ` — ${entry.correction_reason}` : ''}`}
                        style={{ fontSize: '0.52rem', marginRight: '6px', display: 'inline-flex', alignItems: 'center', gap: '3px' }}
                      >
                        <FiRefreshCw style={{ fontSize: '0.6rem' }} /> Correction
                      </span>
                    )}
                    <span title={entry.label}>{entry.label}</span>
                    {entry.node_display && (
                      <span style={{ marginLeft: '6px', fontSize: '0.58rem', color: 'hsl(var(--text-muted))' }}>({entry.node_display})</span>
                    )}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 800, color: parseFloat(entry.entry_amount) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))' }}>
                    {parseFloat(entry.entry_amount) > 0 ? `${fmt(entry.entry_amount)}` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 800, color: parseFloat(entry.exit_amount) > 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))' }}>
                    {parseFloat(entry.exit_amount) > 0 ? `${fmt(entry.exit_amount)}` : '—'}
                  </td>
                  <td style={{ textAlign: 'right', fontWeight: 800, color: parseFloat(entry.running_balance) >= 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--color-danger))' }}>
                    {fmt(entry.running_balance)}
                  </td>
                  <td style={{ textAlign: 'center' }}>
                    {entry.is_tampered ? (
                      <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', fontSize: '0.85rem' }} title="ALTÉRÉ !" />
                    ) : (
                      <FiLock style={{ color: 'hsl(var(--color-success))', fontSize: '0.75rem', opacity: 0.6 }} title="Intègre" />
                    )}
                  </td>
                </tr>
              ))}
              {cashbook.length === 0 && !isLoading && (
                <tr>
                  <td colSpan={8} style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.75rem' }}>
                    <FiBook style={{ fontSize: '1.8rem', opacity: 0.2, display: 'block', margin: '0 auto 8px' }} />
                    Aucune écriture dans le Livre de Caisse pour cette période.
                    <br />Pousser des clôtures validées pour alimenter le grand livre.
                  </td>
                </tr>
              )}
            </tbody>
            {cashbook.length > 0 && (
              <tfoot>
                <tr style={{ fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.72rem' }}>
                  <td colSpan={4} style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>TOTAUX PÉRIODE</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                    {fmt(cashbook.reduce((a, e) => a + parseFloat(e.entry_amount || '0'), 0))} FC
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>
                    {fmt(cashbook.reduce((a, e) => a + parseFloat(e.exit_amount || '0'), 0))} FC
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--accent-color))' }}>
                    {cashbook.length > 0 ? fmt(cashbook[cashbook.length - 1].running_balance) : '—'} FC
                  </td>
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>

        {/* §5.1.3c — BUG-119 : Comptage physique de caisse Direction (contrôle
            annexe, cahier D1-4...xlsx — même logique de billetage/écart que la
            Clôture Gérant §5.2, mais consolidée au niveau du Livre de Caisse). */}
        <div style={{ marginTop: '18px', paddingTop: '16px', borderTop: '1px solid hsl(var(--border-color))' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '10px' }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
              Comptage Physique de Caisse — Direction
            </h3>
            <button
              type="button"
              onClick={() => setShowDccForm(v => !v)}
              className="btn btn-primary"
              style={{ padding: '5px 12px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}
            >
              <FiPlus /> {showDccForm ? 'Annuler' : 'Nouveau comptage'}
            </button>
          </div>

          {showDccForm && (
            <form onSubmit={handleCreateDirectionCashCount} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '14px', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Date du comptage *</label>
                <input
                  type="date" value={dccDate} onChange={e => setDccDate(e.target.value)}
                  className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', maxWidth: '200px' }} required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '5px' }}>Billetage (comptage physique)</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                  {BILLS.map(b => (
                    <div key={b.key}>
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>{b.label}</div>
                      <input
                        type="number" min={0} value={dccBills[b.key]}
                        onChange={e => setDccBills(prev => ({ ...prev, [b.key]: Math.max(0, parseInt(e.target.value) || 0) }))}
                        className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '100%' }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Observations</label>
                <input
                  type="text" value={dccNotes} onChange={e => setDccNotes(e.target.value)}
                  placeholder="optionnel" className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', width: '100%' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', padding: '6px 8px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)' }}>
                <span>Total compté</span>
                <strong style={{ color: 'hsl(var(--accent-color))' }}>{fmt(dccBillTotal)} FC</strong>
              </div>
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>
                Le solde théorique du Livre de Caisse Direction à cette date et l'écart sont calculés automatiquement par le serveur à l'enregistrement.
              </div>

              {dccError && <div style={{ fontSize: '0.7rem', color: 'hsl(var(--color-danger))' }}>{dccError}</div>}
              <button type="submit" disabled={dccSubmitting} className="btn btn-primary" style={{ padding: '7px', fontSize: '0.75rem' }}>
                {dccSubmitting ? 'Enregistrement...' : 'Enregistrer le comptage'}
              </button>
            </form>
          )}

          {/* Historique des comptages — écart coloré comme §5.2 (Clôture Gérant) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {dccLoading ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement...</div>
            ) : directionCashCounts.length === 0 ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucun comptage physique Direction sur la période.</div>
            ) : (
              directionCashCounts.map(c => {
                const gap = parseFloat(c.cash_gap || '0');
                return (
                  <div key={c.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-secondary))', flexWrap: 'wrap', gap: '8px' }}>
                    <div>
                      <div style={{ fontSize: '0.75rem', fontWeight: 700 }}>
                        {new Date(c.date).toLocaleDateString('fr-FR')}
                      </div>
                      <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>
                        Compté : {fmt(c.physical_cash_total)} FC · Théorique : {fmt(c.theoretical_balance)} FC · {c.counted_by_display || '—'}
                        {c.notes && ` · ${c.notes}`}
                      </div>
                    </div>
                    <strong style={{ fontSize: '0.78rem', color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                      {gap >= 0 ? '+' : ''}{fmt(c.cash_gap)} FC{gap === 0 ? ' (sans écart)' : gap > 0 ? ' (excédent)' : ' (manquant)'}
                    </strong>
                  </div>
                );
              })
            )}
          </div>
        </div>
      </div>
      )}

      {/* ═══ §5.1.4 — JOURNAL DE CAISSE PAR BOULANGERIE ═══ */}
      <div className="glass-card" style={{ padding: '16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '14px', flexWrap: 'wrap', gap: '10px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiFileText style={{ color: 'hsl(var(--accent-color))' }} />
            §5.1.4 — Journal de Caisse par Boulangerie
          </h2>
          {/* Month/Year navigation */}
          <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap' }}>
            <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Mois</label>
            <select
              value={journalMonth}
              onChange={e => setJournalMonth(Number(e.target.value))}
              className="form-input"
              style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '110px' }}
            >
              {['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'].map((m, i) => (
                <option key={i + 1} value={i + 1}>{m}</option>
              ))}
            </select>
            <input
              type="number"
              value={journalYear}
              onChange={e => setJournalYear(Math.min(2035, Math.max(2024, Number(e.target.value) || 2024)))}
              className="form-input"
              style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '72px' }}
              min={2024} max={2035}
            />
            <button onClick={loadJournal} className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiRefreshCw size={11} /> Actualiser
            </button>
          </div>
        </div>

        {/* Report mois précédent */}
        {journalReport && (
          <div style={{ marginBottom: '12px', padding: '8px 14px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', gap: '24px', flexWrap: 'wrap', fontSize: '0.72rem' }}>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Report mois précédent : </span>
              <span style={{ fontWeight: 800, color: parseFloat(journalReport.month_carried) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--accent-color))' }}>
                {fmt(journalReport.month_carried)} FC
              </span>
            </span>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Total Entrées : </span>
              <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>{fmt(journalReport.total_entries)} FC</span>
            </span>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Total Sorties : </span>
              <span style={{ fontWeight: 700, color: 'hsl(var(--color-danger))' }}>{fmt(journalReport.total_exits)} FC</span>
            </span>
            <span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Solde Final : </span>
              <span style={{ fontWeight: 800, color: parseFloat(journalReport.final_balance) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                {fmt(journalReport.final_balance)} FC
              </span>
            </span>
          </div>
        )}

        {/* Form — new entry */}
        <form onSubmit={handleJournalSubmit} style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'flex-end', marginBottom: '14px', padding: '12px 14px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>Date</label>
            <input type="date" value={jDate} onChange={e => setJDate(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '130px' }} required />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>Imputation</label>
            <select value={jImput} onChange={e => setJImput(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '180px' }} required>
              {JOURNAL_IMPUT.map(opt => (
                <option key={opt.value} value={opt.value}>{opt.label}</option>
              ))}
            </select>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', flex: 1, minWidth: '120px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>Libellé</label>
            <input type="text" value={jLabel} onChange={e => setJLabel(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 8px' }} placeholder="Description (optionnel)" maxLength={200} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--color-success))', textTransform: 'uppercase' }}>Entrée (FC)</label>
            <input type="number" value={jEntry} onChange={e => setJEntry(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '120px' }} placeholder="0" min={0} step={1} />
            {/* BUG-105 — pré-remplissage/confrontation CA avec la Clôture (Niveau 2) */}
            {jImput === 'CA' && (
              <div style={{ fontSize: '0.6rem', fontWeight: 600, whiteSpace: 'nowrap' }}>
                {jSuggestedCaLoading ? (
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Vérification de la Clôture...</span>
                ) : jSuggestedCa?.available ? (
                  <>
                    <span style={{ color: 'hsl(var(--color-success))' }}>✓ Rapproché à la Clôture ({fmt(jSuggestedCa.amount || '0')} FC)</span>
                    {(() => {
                      const liveGap = parseFloat(jEntry || '0') - parseFloat(jSuggestedCa!.amount || '0');
                      return liveGap !== 0 ? (
                        <div style={{ color: 'hsl(var(--color-warning))' }}>
                          Écart avec la Clôture : {liveGap >= 0 ? '+' : ''}{fmt(String(liveGap))} FC
                        </div>
                      ) : null;
                    })()}
                  </>
                ) : (
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>{jSuggestedCa?.message || 'Aucune Clôture (Niveau 2) pour ce jour — écriture non rapprochée.'}</span>
                )}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
            <label style={{ fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--color-danger))', textTransform: 'uppercase' }}>Sortie (FC)</label>
            <input type="number" value={jExit} onChange={e => setJExit(e.target.value)} className="form-input" style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', width: '120px' }} placeholder="0" min={0} step={1} />
          </div>
          <button type="submit" disabled={jSubmitting} className="btn btn-primary" style={{ height: '30px', padding: '0 14px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
            <FiPlus size={13} />{jSubmitting ? 'Enregistrement...' : 'Enregistrer'}
          </button>
          {jError && (
            <div style={{ width: '100%', padding: '6px 10px', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)', borderRadius: 'var(--radius-sm)', color: 'hsl(var(--color-danger))', fontSize: '0.7rem', fontWeight: 600 }}>
              {jError}
            </div>
          )}
          {jLastResult && (
            <div style={{
              width: '100%', padding: '6px 10px', borderRadius: 'var(--radius-sm)', fontSize: '0.7rem', fontWeight: 600,
              backgroundColor: jLastResult.is_reconciled
                ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0 ? 'hsl(var(--color-success) / 0.1)' : 'hsl(var(--color-warning) / 0.1)')
                : 'hsl(var(--bg-tertiary))',
              border: `1px solid hsl(var(--${jLastResult.is_reconciled ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0 ? 'color-success' : 'color-warning') : 'border-color'}) / 0.4)`,
              color: jLastResult.is_reconciled
                ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))')
                : 'hsl(var(--text-secondary))',
            }}>
              {jLastResult.is_reconciled
                ? (parseFloat(jLastResult.reconciliation_gap || '0') === 0
                    ? 'Écriture enregistrée — rapprochée à la Clôture, aucun écart.'
                    : `Écriture enregistrée — écart de ${parseFloat(jLastResult.reconciliation_gap || '0') >= 0 ? '+' : ''}${fmt(jLastResult.reconciliation_gap || '0')} FC avec la Clôture (notification envoyée).`)
                : 'Écriture enregistrée — non rapprochée (aucune Clôture pour ce jour).'}
            </div>
          )}
        </form>

        {/* Entries table */}
        {journalLoading ? (
          <p style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Chargement...</p>
        ) : journalEntries.length === 0 ? (
          <p style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>
            Aucune écriture pour ce mois.
          </p>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                  <th style={{ width: '90px', textAlign: 'center' }}>Date</th>
                  <th style={{ width: '140px' }}>Imputation</th>
                  <th>Libellé</th>
                  <th style={{ textAlign: 'right', width: '110px', color: 'hsl(var(--color-success))' }}>Entrée (FC)</th>
                  <th style={{ textAlign: 'right', width: '110px', color: 'hsl(var(--color-danger))' }}>Sortie (FC)</th>
                  <th style={{ textAlign: 'right', width: '120px' }}>Solde Courant</th>
                  <th style={{ textAlign: 'center', width: '150px' }}>Rapprochement</th>
                </tr>
              </thead>
              <tbody>
                {journalEntries.map(entry => {
                  const balance = parseFloat(entry.running_balance || '0');
                  const gap = parseFloat(entry.reconciliation_gap || '0');
                  return (
                    <tr key={entry.id} style={{ fontSize: '0.72rem' }}>
                      <td style={{ textAlign: 'center', fontWeight: 600 }}>
                        {new Date(entry.date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short' })}
                      </td>
                      <td>
                        <span style={{ fontWeight: 700, color: 'hsl(var(--accent-color))', fontSize: '0.68rem' }}>
                          {entry.imput_display || entry.imput}
                        </span>
                      </td>
                      <td style={{ color: 'hsl(var(--text-secondary))' }}>
                        {entry.label || <span style={{ fontStyle: 'italic', opacity: 0.5 }}>—</span>}
                      </td>
                      <td style={{ textAlign: 'right', color: parseFloat(entry.entry_amount) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-secondary))', fontWeight: parseFloat(entry.entry_amount) > 0 ? 700 : 400 }}>
                        {parseFloat(entry.entry_amount) > 0 ? fmt(entry.entry_amount) : '—'}
                      </td>
                      <td style={{ textAlign: 'right', color: parseFloat(entry.exit_amount) > 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-secondary))', fontWeight: parseFloat(entry.exit_amount) > 0 ? 700 : 400 }}>
                        {parseFloat(entry.exit_amount) > 0 ? fmt(entry.exit_amount) : '—'}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: balance < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>
                        {fmt(entry.running_balance)} FC
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        {/* BUG-105 — rapprochement CA ↔ Clôture (Niveau 2), autres imputations non concernées */}
                        {entry.imput === 'CA' ? (
                          entry.is_reconciled ? (
                            <span style={{
                              fontSize: '0.62rem', fontWeight: 700, padding: '2px 6px', borderRadius: 'var(--radius-sm)',
                              backgroundColor: gap === 0 ? 'hsl(var(--color-success) / 0.12)' : 'hsl(var(--color-warning) / 0.12)',
                              color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))',
                            }}>
                              Rapproché{gap !== 0 ? ` (écart ${gap >= 0 ? '+' : ''}${fmt(entry.reconciliation_gap || '0')} FC)` : ''}
                            </span>
                          ) : (
                            <span style={{ fontSize: '0.62rem', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>Non rapproché</span>
                          )
                        ) : (
                          <span style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
              <tfoot>
                <tr style={{ fontSize: '0.68rem', fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))' }}>
                  <td colSpan={3} style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>
                    {journalEntries.length} écriture(s)
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                    {fmt(journalEntries.reduce((a, e) => a + parseFloat(e.entry_amount || '0'), 0))} FC
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>
                    {fmt(journalEntries.reduce((a, e) => a + parseFloat(e.exit_amount || '0'), 0))} FC
                  </td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: journalReport && parseFloat(journalReport.final_balance) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                    {journalReport ? `${fmt(journalReport.final_balance)} FC` : '—'}
                  </td>
                  <td></td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {/* ═══ §5.1.5 — ÉPARGNE JOURNALIÈRE ═══ */}
      <div style={{ background: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))', borderRadius: 12, padding: 24, marginTop: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <h3 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: 'hsl(var(--text-primary))' }}>
            §5.1.5 — Épargne Journalière
          </h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <button onClick={() => { const d = new Date(savingsYear, savingsMonth - 2); setSavingsMonth(d.getMonth() + 1); setSavingsYear(d.getFullYear()); setSavingsDayFilter(''); }} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}>◀</button>
            <span style={{ fontWeight: 600, fontSize: '0.9rem', minWidth: 100, textAlign: 'center' }}>
              {new Date(savingsYear, savingsMonth - 1).toLocaleString('fr-FR', { month: 'long', year: 'numeric' })}
            </span>
            <button onClick={() => { const d = new Date(savingsYear, savingsMonth); setSavingsMonth(d.getMonth() + 1); setSavingsYear(d.getFullYear()); setSavingsDayFilter(''); }} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}>▶</button>
            <select
              value={savingsDayFilter}
              onChange={e => setSavingsDayFilter(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.85rem' }}
            >
              <option value="">Tous les jours</option>
              {savingsDaysAvailable.map(d => <option key={d} value={d}>Jour {d}</option>)}
            </select>
            {savingsDayFilter && (
              <button
                onClick={() => handlePrintSavingsDay(savingsDayFilter)}
                title={`Imprimer le ${savingsDayFilter}`}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))', display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.8rem' }}
              >
                <FiPrinter /> Imprimer
              </button>
            )}
          </div>
        </div>

        {/* Totaux */}
        {filteredSavingsTotals && (
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            {[
              { label: 'Total Sacs Farine', value: `${fmt(filteredSavingsTotals.total_flour_sacks)} sacs`, color: 'hsl(var(--text-secondary))' },
              { label: 'Total Revenu', value: `${fmt(filteredSavingsTotals.total_revenue)} FC`, color: 'hsl(var(--color-success))' },
              { label: 'Total Épargne', value: `${fmt(filteredSavingsTotals.total_savings)} FC`, color: 'hsl(var(--accent-color))' },
            ].map(kpi => (
              <div key={kpi.label} style={{ flex: '1 1 160px', background: 'hsl(var(--bg-tertiary))', borderRadius: 8, padding: '10px 14px', border: '1px solid hsl(var(--border-color))' }}>
                <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Formulaire saisie */}
        <form onSubmit={handleSavingsSubmit} style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20, alignItems: 'flex-end' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Date</label>
            <input type="date" value={sDate} onChange={e => setSDate(e.target.value)} required
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Sacs farine (PROD)</label>
            <input type="number" step="0.01" min="0" value={sFlour} onChange={e => setSFlour(e.target.value)} placeholder="0"
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem', width: 100 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Revenu du jour (FC) *</label>
            <input type="number" step="1" min="0" value={sRevenue} onChange={e => setSRevenue(e.target.value)} placeholder="0" required
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem', width: 130 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Taux épargne</label>
            <input type="number" step="0.0001" min="0" max="1" value={sRate} onChange={e => setSRate(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem', width: 90 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Épargne calculée</label>
            <div style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--accent-color))', fontSize: '0.875rem', width: 130, fontWeight: 700, minHeight: 32, display: 'flex', alignItems: 'center' }}>
              {sRevenue && sRate ? `${fmt(parseFloat(sRevenue) * parseFloat(sRate))} FC` : '—'}
            </div>
          </div>
          <button type="submit" disabled={sSubmitting}
            style={{ padding: '7px 18px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: sSubmitting ? 'not-allowed' : 'pointer', opacity: sSubmitting ? 0.6 : 1, whiteSpace: 'nowrap' }}>
            {sSubmitting ? 'Enregistrement…' : '+ Enregistrer'}
          </button>
          {sError && <div style={{ color: 'hsl(var(--color-danger))', fontSize: '0.8rem', alignSelf: 'center' }}>{sError}</div>}
        </form>

        {/* Table mensuelle */}
        {savingsLoading ? (
          <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
        ) : filteredSavingsEntries.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
            {savingsDayFilter ? `Aucune épargne enregistrée pour le jour ${savingsDayFilter}.` : 'Aucune épargne enregistrée pour ce mois.'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                  {['Date', user?.can_access_all_nodes ? 'Succursale' : null, 'Sacs PROD', 'Revenu (FC)', 'Taux', 'Épargne (FC)', ''].filter(h => h !== null).map((h, i) => (
                    <th key={h || `col-${i}`} style={{ padding: '8px 10px', textAlign: h === 'Date' || h === 'Succursale' ? 'left' : 'right', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredSavingsEntries.map(s => (
                  <tr key={s.id} style={{ borderBottom: '1px solid hsl(var(--border-color))', transition: 'background 0.15s' }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'hsl(var(--bg-tertiary))')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}>
                    <td style={{ padding: '8px 10px' }}>{new Date(s.date).toLocaleDateString('fr-FR')}</td>
                    {user?.can_access_all_nodes && <td style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{s.node_display || s.node}</td>}
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>{fmt(s.flour_sacks)}</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>{fmt(s.daily_revenue)}</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{(parseFloat(s.savings_rate) * 100).toFixed(2)}%</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{fmt(s.savings_amount)} FC</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>
                      <button
                        onClick={() => handlePrintSavingsDay(s.date.split('-')[2])}
                        title={`Imprimer le ${s.date.split('-')[2]}`}
                        style={{ padding: '3px 5px', borderRadius: 4, border: '1px solid hsl(var(--border-color))', background: 'none', color: 'hsl(var(--text-secondary))', cursor: 'pointer' }}
                      >
                        <FiPrinter size={11} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 700 }}>
                  <td colSpan={user?.can_access_all_nodes ? 2 : 1} style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{filteredSavingsEntries.length} entrée(s)</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px' }}>{filteredSavingsTotals ? fmt(filteredSavingsTotals.total_flour_sacks) : '—'}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>{filteredSavingsTotals ? `${fmt(filteredSavingsTotals.total_revenue)} FC` : '—'}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px' }}></td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--accent-color))' }}>{filteredSavingsTotals ? `${fmt(filteredSavingsTotals.total_savings)} FC` : '—'}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {closureModal}
      {entryModal}

      {/* §5.1.2 — Historique mensuel des Dépenses Locales, jour par jour */}
      <Modal
        isOpen={expenseHistoryOpen}
        onClose={() => setExpenseHistoryOpen(false)}
        title="Historique des Dépenses Locales"
        subtitle={selectedNodeLabel || (user?.can_access_all_nodes ? 'Toutes les succursales' : undefined)}
        maxWidth="620px"
      >
        <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
          <button
            onClick={() => { const d = new Date(expenseHistoryYear, expenseHistoryMonth - 2); setExpenseHistoryMonth(d.getMonth() + 1); setExpenseHistoryYear(d.getFullYear()); }}
            style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}
          >◀</button>
          <span style={{ fontWeight: 700, fontSize: '0.85rem', minWidth: '120px', textAlign: 'center' }}>
            {new Date(expenseHistoryYear, expenseHistoryMonth - 1).toLocaleString('fr-FR', { month: 'long', year: 'numeric' })}
          </span>
          <button
            onClick={() => { const d = new Date(expenseHistoryYear, expenseHistoryMonth); setExpenseHistoryMonth(d.getMonth() + 1); setExpenseHistoryYear(d.getFullYear()); }}
            style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}
          >▶</button>
        </div>

        {expenseHistoryLoading ? (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))', fontSize: '0.82rem' }}>Chargement...</div>
        ) : expenseHistoryEntries.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.82rem' }}>Aucune dépense pour ce mois.</div>
        ) : (() => {
          const byDay: Record<string, LocalExpense[]> = {};
          expenseHistoryEntries.forEach(e => {
            byDay[e.date] = byDay[e.date] || [];
            byDay[e.date].push(e);
          });
          const days = Object.keys(byDay).sort((a, b) => b.localeCompare(a));
          const monthTotal = expenseHistoryEntries.reduce((s, e) => s + parseFloat(e.amount || '0'), 0);
          return (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', fontWeight: 800, padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
                <span>Total du mois ({expenseHistoryEntries.length} dépense{expenseHistoryEntries.length > 1 ? 's' : ''})</span>
                <span style={{ color: 'hsl(var(--color-danger))' }}>−{monthTotal.toLocaleString('fr-FR')} FC</span>
              </div>
              {days.map(day => {
                const dayEntries = byDay[day];
                const dayTotal = dayEntries.reduce((s, e) => s + parseFloat(e.amount || '0'), 0);
                return (
                  <div key={day}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.72rem', fontWeight: 800, color: 'hsl(var(--accent-color))', marginBottom: '6px', borderBottom: '1px solid hsl(var(--border-color))', paddingBottom: '4px' }}>
                      <span>{new Date(day).toLocaleDateString('fr-FR', { weekday: 'long', day: '2-digit', month: 'long' })}</span>
                      <span>−{dayTotal.toLocaleString('fr-FR')} FC</span>
                    </div>
                    <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                      {dayEntries.map(e => (
                        <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', padding: '5px 8px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px' }}>
                          <span style={{ color: 'hsl(var(--text-secondary))' }}>
                            {e.description} <em>({e.category_display || e.category})</em>
                            {user?.can_access_all_nodes && e.node_display && (
                              <span style={{ color: 'hsl(var(--text-muted))' }}> · {e.node_display}</span>
                            )}
                          </span>
                          <strong style={{ color: 'hsl(var(--color-danger))', whiteSpace: 'nowrap', marginLeft: '8px' }}>-{fmt(e.amount)} FC</strong>
                        </div>
                      ))}
                    </div>
                  </div>
                );
              })}
            </div>
          );
        })()}
      </Modal>

    </div>
  );
};
