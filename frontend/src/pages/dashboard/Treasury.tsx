import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  FiBook, FiRefreshCw, FiAlertTriangle, FiCheckCircle, FiFileText,
  FiPlus, FiLock, FiDollarSign, FiPrinter
} from 'react-icons/fi';
import {
  treasuryApi, coreApi,
  CashbookEntry, JournalEntry, DailySavings,
  BakeryNode, DisbursementVoucher, SuggestedCa,
  DirectionCashCount
} from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import {
  isInvalidBillCount, parseBillCount, validateBillCounts,
  isGerantOrAbove, treasuryErrorMessage,
} from '@/components/treasury/treasuryRules';
import {
  BILLS, PAGE_SIZE, progressLabel, fmt,
} from '@/components/treasury/treasuryShared';
import type { BillKey } from '@/components/treasury/treasuryShared';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { Modal } from '@/components/shared/Modal';
import { useProgressiveList } from '@/hooks/useProgressiveList';

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

// Page « Caisse » (ex « Clôture & Caisse », remarque.md) : livre de caisse direction, bordereaux de
// versement (décaissements), comptage physique, journal de caisse et épargne journalière.
// Les options de clôture (rapports facturiers, versement/billetage, dépenses locales, clôtures du
// jour) sont dans « Clôture Journalière » (components/treasury/ClotureOperations.tsx).
export const Treasury: React.FC = () => {
  const { user } = useAuthStore();
  // BUG-161 (F3) : « aujourd'hui » = jour calendaire du serveur (repli : date locale, jamais UTC).
  const today = useWorkDate();

  const [nodeFilter, setNodeFilter] = useState('');
  const [allNodes, setAllNodes]     = useState<BakeryNode[]>([]);
  const [detailEntry, setDetailEntry] = useState<CashbookEntry | null>(null);

  // §5.1.3 Cashbook filter
  const [dateFrom, setDateFrom] = useState(() => `${today.slice(0, 8)}01`);
  const [dateTo, setDateTo] = useState(today);
  const [integrityResult, setIntegrityResult] = useState<{chain_valid: boolean; tampered_count: number} | null>(null);
  const [checkingIntegrity, setCheckingIntegrity] = useState(false);

  // §5.1.3b — Bordereaux de Versement (Direction)
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

  // BUG-044 : le Livre de Caisse Direction (`treasuryApi.cashbook.list`) est réservé au
  // siège (`IsHeadquarters`, cf. BUG-026) — on ne l'appelle même pas pour un rôle non-HQ,
  // au lieu de laisser la requête échouer en 403.
  const isHq = !!user?.can_access_all_nodes;
  // Écriture journal/épargne = gérant et au-dessus. Le serveur reste l'autorité (403 affiché).
  const canWriteTreasury = isGerantOrAbove(user);
  const nodeParam: Record<string, string> = nodeFilter ? { node: nodeFilter } : {};

  const cashbookQ = useProgressiveList<CashbookEntry>({
    fetchPage: p => treasuryApi.cashbook.page({ date_from: dateFrom, date_to: dateTo, ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `cb|${dateFrom}|${dateTo}|${nodeFilter}`,
    enabled: isHq,
  });
  const vouchersQ = useProgressiveList<DisbursementVoucher>({
    fetchPage: p => treasuryApi.vouchers.page({ date_from: dateFrom, date_to: dateTo, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `vou|${dateFrom}|${dateTo}`,
    enabled: isHq,
  });
  const journalQ = useProgressiveList<JournalEntry>({
    fetchPage: p => treasuryApi.journal.page({ month: String(journalMonth), year: String(journalYear), ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `jrn|${journalMonth}|${journalYear}|${nodeFilter}`,
  });
  const savingsQ = useProgressiveList<DailySavings>({
    fetchPage: p => treasuryApi.savings.page({ month: String(savingsMonth), year: String(savingsYear), ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `sav|${savingsMonth}|${savingsYear}|${nodeFilter}`,
  });

  const cashbook = cashbookQ.items;
  const vouchers = vouchersQ.items;
  const vouchersLoading = vouchersQ.isLoading;
  const journalEntries = journalQ.items;
  const journalLoading = journalQ.isLoading;
  const savingsEntries = savingsQ.items;
  const savingsLoading = savingsQ.isLoading;

  const reloadCashbook = cashbookQ.reload;
  const reloadVouchers = vouchersQ.reload;
  // Rechargement après une action (bordereau, filtre de dates).
  const loadData = useCallback(async () => {
    reloadCashbook(); reloadVouchers();
  }, [reloadCashbook, reloadVouchers]);
  const isLoading = cashbookQ.isLoading;

  // BUG-161 (F3) : à la relève (passage de minuit), les sélecteurs de jour qui
  // étaient sur l'ancienne journée courante suivent la nouvelle.
  const prevTodayRef = useRef(today);
  useEffect(() => {
    const previous = prevTodayRef.current;
    if (previous === today) return;
    prevTodayRef.current = today;
    setDateTo(d => (d === previous ? today : d));
    setDccDate(d => (d === previous ? today : d));
    setJDate(d => (d === previous ? today : d));
    setSDate(d => (d === previous ? today : d));
  }, [today]);

  // Load nodes list (HQ needs it for the bakery filter; every role needs it
  // to resolve their own node's "Valeur Théorique par Sac de Farine (FC)" —
  // NodeViewSet.list() is open to any authenticated user).
  useEffect(() => {
    coreApi.nodes.list().then(res => setAllNodes(res.data)).catch(() => {});
  }, []);

  // §5.1.4 — Journal de Caisse load
  // Les écritures sont lues par `journalQ` (progressif) ; le rapport mensuel (totaux
  // calculés par le serveur) est lu à part.
  const reloadJournalEntries = journalQ.reload;
  const loadJournalReport = useCallback(async () => {
    const params: Record<string, string> = { month: String(journalMonth), year: String(journalYear) };
    if (nodeFilter) params.node = nodeFilter;
    try {
      const reportRes = await treasuryApi.journal.monthlyReport(params);
      setJournalReport(reportRes.data ?? null);
    } catch { /* ignore */ }
  }, [journalMonth, journalYear, nodeFilter]);
  const loadJournal = useCallback(async () => {
    reloadJournalEntries();
    await loadJournalReport();
  }, [reloadJournalEntries, loadJournalReport]);

  useEffect(() => { loadJournalReport(); }, [loadJournalReport]);

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
  const reloadSavingsEntries = savingsQ.reload;
  const loadSavingsTotal = useCallback(async () => {
    const params: Record<string, string> = { month: String(savingsMonth), year: String(savingsYear) };
    if (nodeFilter) params.node = nodeFilter;
    try {
      const totalRes = await treasuryApi.savings.monthlyTotal(params);
      setSavingsTotal(totalRes.data ?? null);
    } catch { /* ignore */ }
  }, [savingsMonth, savingsYear, nodeFilter]);
  const loadSavings = useCallback(async () => {
    reloadSavingsEntries();
    await loadSavingsTotal();
  }, [reloadSavingsEntries, loadSavingsTotal]);

  useEffect(() => { loadSavingsTotal(); }, [loadSavingsTotal]);

  const handleSavingsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSError(null);
    if (!canWriteTreasury) { setSError("Enregistrement réservé au gérant et aux rôles supérieurs."); return; }
    const rev = parseFloat(sRevenue) || 0;
    if (rev <= 0) { setSError('Indiquez le revenu du jour.'); return; }
    const flour = parseFloat(sFlour || '0');
    if (!Number.isFinite(flour) || flour < 0) { setSError('Le nombre de sacs ne peut pas être négatif.'); return; }
    const rate = parseFloat(sRate);
    if (!Number.isFinite(rate) || rate < 0 || rate > 1) { setSError("Le taux d'épargne doit être compris entre 0 et 1 (ex. 0,158)."); return; }
    setSSubmitting(true);
    try {
      const payload: Record<string, string> = {
        date: sDate,
        flour_sacks: sFlour || '0',
        daily_revenue: String(rev),
        savings_rate: sRate,
      };
      // BUG-231 / BUG-206 : `node` n'est envoyé que par le siège (le serveur l'ignore sinon).
      if (isHq && nodeFilter) payload.node = nodeFilter;
      await treasuryApi.savings.create(payload);
      setSFlour(''); setSRevenue('');
      await loadSavings();
    } catch (err: unknown) {
      setSError(treasuryErrorMessage(err, "Erreur lors de l'enregistrement."));
    } finally {
      setSSubmitting(false);
    }
  };

  // §5.1.5 — filtre par jour + impression journalière
  // BUG-164 : jours disponibles, totaux filtrés par jour et impression journalière =
  // calculés sur la liste chargée -> disponibles seulement quand elle est complète.
  const savingsReady = savingsQ.isComplete;
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
  const savingsTotalsReady = savingsDayFilter ? savingsReady : true;

  const handlePrintSavingsDay = (day: string) => {
    if (!savingsReady) return;
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
    if (!canWriteTreasury) { setJError("Écriture réservée au gérant et aux rôles supérieurs."); return; }
    if (ea < 0 || xa < 0) { setJError('Les montants ne peuvent pas être négatifs.'); return; }
    if (ea === 0 && xa === 0) { setJError('Indiquez une entrée ou une sortie.'); return; }
    setJSubmitting(true);
    try {
      const payload: Partial<JournalEntry> & { node?: string } = {
        imput: jImput, label: jLabel, date: jDate,
        entry_amount: ea ? String(ea) : '0',
        exit_amount:  xa ? String(xa) : '0',
      };
      if (isHq && nodeFilter) payload.node = nodeFilter;
      const res = await treasuryApi.journal.create(payload);
      // BUG-105 — confrontation à la Clôture renvoyée par le serveur pour
      // l'imputation CA (jamais calculée/forcée côté client).
      setJLastResult(jImput === 'CA' ? res.data : null);
      setJLabel(''); setJEntry(''); setJExit('');
      setJSuggestedCa(null);
      await loadJournal();
    } catch (err: unknown) {
      setJError(treasuryErrorMessage(err, "Erreur lors de l'enregistrement."));
    } finally {
      setJSubmitting(false);
    }
  };

  // Active node label for visual indicators
  const selectedNode = allNodes.find(n => n.id === nodeFilter);
  const selectedNodeLabel = selectedNode
    ? `${selectedNode.code} — ${selectedNode.name}`
    : (!user?.can_access_all_nodes && user?.node_display)
      ? user.node_display
      : null;

  const handleIntegrityCheck = async () => {
    setCheckingIntegrity(true);
    try {
      const res = await treasuryApi.cashbook.integrityCheck();
      setIntegrityResult(res.data);
    } catch (err) {
      console.error('Integrity check failed', err);
    } finally {
      setCheckingIntegrity(false);
    }
  };

  // §5.1.3b — Bordereaux de Versement
  const loadVouchers = useCallback(async () => { reloadVouchers(); }, [reloadVouchers]);

  // Current consolidated balance — cashbook is ordered newest-first, so [0] is the latest entry
  // BUG-164 : `consolidatedBalance` = `running_balance` de la 1re écriture. Le serveur trie
  // (-date, -created_at) AVANT de paginer : la page 1 contient donc exactement la même
  // écriture [0] que la liste complète, et `running_balance` est une valeur stockée dans
  // l'écriture (aucune somme côté client) -> fiable dès la page 1, sans attendre la
  // complétude. Elle dépend en revanche du tri serveur : ne jamais re-trier ici.
  const consolidatedBalance = cashbook.length > 0 ? parseFloat(cashbook[0].running_balance) : 0;
  const consolidatedBalanceReady = !cashbookQ.isLoading && cashbookQ.error === null;
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
    const dccProblem = validateBillCounts(dccBills);
    if (dccProblem) { setDccError(dccProblem); return; }
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
      setDccError(treasuryErrorMessage(err, "Erreur lors de l'enregistrement du comptage."));
    } finally {
      setDccSubmitting(false);
    }
  };

  const handleCreateVoucher = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setVoucherError(null);
    if (!voucherMotif) { setVoucherError('Indiquez le motif du bordereau.'); return; }
    const voucherProblem = validateBillCounts(voucherBills);
    if (voucherProblem) { setVoucherError(voucherProblem); return; }
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
    } catch (err: unknown) {
      setVoucherError(treasuryErrorMessage(err, 'Erreur lors de la création du bordereau.'));
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
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Erreur lors de la génération du bordereau final.'));
    }
  };

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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px', fontSize: '0.85rem' }}>

      {/* Header */}
      <div className="glass-card animate-fade-in" style={{ background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)', borderLeft: '4px solid hsl(var(--accent-color))', padding: '14px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '10px' }}>
          <div>
            <h1 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '2px' }}>Caisse</h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem' }}>
              Livre de Caisse Direction · Bordereaux de Versement · Journal de Caisse · Épargne Journalière
              {selectedNodeLabel ? ` — ${selectedNodeLabel}` : ''}
            </p>
          </div>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            {user?.can_access_all_nodes && allNodes.length > 0 && (
              <select
                value={nodeFilter}
                onChange={e => setNodeFilter(e.target.value)}
                aria-label="Boulangerie"
                className="form-input"
                style={{ height: '30px', fontSize: '0.72rem', padding: '0 6px', minWidth: '160px' }}
              >
                <option value="">Toutes les succursales</option>
                {allNodes.map(n => (
                  <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                ))}
              </select>
            )}
            <button onClick={loadData} disabled={isLoading} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
              <FiRefreshCw style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
              <span>Actualiser</span>
            </button>
            <FiBook style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
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
            {consolidatedBalanceReady ? (
              <strong style={{ color: consolidatedBalance >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(consolidatedBalance)} FC</strong>
            ) : (
              <strong style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>{cashbookQ.error ? 'indisponible' : 'chargement…'}</strong>
            )}
          </div>

          {showVoucherForm && (
            <form noValidate onSubmit={handleCreateVoucher} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '14px', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
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
                        type="number" inputMode="numeric" value={voucherBills[b.key]} aria-invalid={isInvalidBillCount(voucherBills[b.key])}
                        onChange={e => setVoucherBills(prev => ({ ...prev, [b.key]: parseBillCount(e.target.value) }))}
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
              {consolidatedBalanceReady && voucherBillTotal > consolidatedBalance && (
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
            ) : vouchersQ.error ? (
              <div role="alert" style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--color-danger))', padding: '10px' }}>{vouchersQ.error}</div>
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
            {!vouchersQ.isLoading && !vouchersQ.isComplete && !vouchersQ.error && (
              <div style={{ textAlign: 'center', fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>
                {vouchersQ.loaded} / {vouchersQ.total ?? '…'} bordereaux chargés…
              </div>
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
              {cashbookQ.isLoading && (
                <tr><td colSpan={8} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))', fontSize: '0.75rem' }}>Chargement du livre de caisse…</td></tr>
              )}
              {cashbookQ.error && (
                <tr><td colSpan={8} role="alert" style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--color-danger))', fontSize: '0.72rem' }}>
                  {cashbookQ.error}{' '}
                  <button onClick={reloadCashbook} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
                </td></tr>
              )}
              {cashbook.length === 0 && !cashbookQ.isLoading && !cashbookQ.error && (
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
                  {cashbookQ.isComplete ? (
                    <>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                        {fmt(cashbook.reduce((a, e) => a + parseFloat(e.entry_amount || '0'), 0))} FC
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>
                        {fmt(cashbook.reduce((a, e) => a + parseFloat(e.exit_amount || '0'), 0))} FC
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--accent-color))' }}>
                        {fmt(cashbook[cashbook.length - 1].running_balance)} FC
                      </td>
                    </>
                  ) : (
                    <td colSpan={3} style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progressLabel(cashbookQ)}</td>
                  )}
                  <td />
                </tr>
              </tfoot>
            )}
          </table>
        </div>

        {!cashbookQ.isLoading && !cashbookQ.isComplete && !cashbookQ.error && (
          <div style={{ marginTop: '6px', fontSize: '0.65rem', color: 'hsl(var(--text-muted))', textAlign: 'center' }} aria-live="polite">
            {cashbookQ.loaded} / {cashbookQ.total ?? '…'} écritures chargées — totaux de la période en cours de calcul…
          </div>
        )}

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
            <form noValidate onSubmit={handleCreateDirectionCashCount} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '14px', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
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
                        type="number" inputMode="numeric" value={dccBills[b.key]} aria-invalid={isInvalidBillCount(dccBills[b.key])}
                        onChange={e => setDccBills(prev => ({ ...prev, [b.key]: parseBillCount(e.target.value) }))}
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

        {/* Form — new entry (BUG-231 : ajout seul, gérant et au-dessus ; aucune édition/suppression de ligne, le serveur répond 405) */}
        {canWriteTreasury ? (
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
        ) : (
          <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginBottom: '14px', padding: '8px 12px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)' }}>
            Le journal est en lecture seule pour votre rôle : la saisie est réservée au gérant et aux rôles supérieurs.
          </div>
        )}

        {/* Entries table */}
        {journalQ.error && (
          <p role="alert" style={{ textAlign: 'center', padding: '8px', color: 'hsl(var(--color-danger))', fontSize: '0.75rem' }}>
            {journalQ.error}{' '}
            <button onClick={reloadJournalEntries} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
          </p>
        )}
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
                    {journalQ.total ?? journalEntries.length} écriture(s)
                  </td>
                  {journalQ.isComplete ? (
                    <>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                        {fmt(journalEntries.reduce((a, e) => a + parseFloat(e.entry_amount || '0'), 0))} FC
                      </td>
                      <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>
                        {fmt(journalEntries.reduce((a, e) => a + parseFloat(e.exit_amount || '0'), 0))} FC
                      </td>
                    </>
                  ) : (
                    <td colSpan={2} style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progressLabel(journalQ)}</td>
                  )}
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
              disabled={!savingsReady}
              title={savingsReady ? undefined : `Filtre par jour disponible une fois la liste chargée (${savingsQ.loaded}/${savingsQ.total ?? '…'})`}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.85rem' }}
            >
              <option value="">Tous les jours</option>
              {savingsDaysAvailable.map(d => <option key={d} value={d}>Jour {d}</option>)}
            </select>
            {savingsDayFilter && savingsReady && (
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
              { label: 'Total Sacs Farine', value: savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_flour_sacks)} sacs` : progressLabel(savingsQ), color: 'hsl(var(--text-secondary))' },
              { label: 'Total Revenu', value: savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_revenue)} FC` : progressLabel(savingsQ), color: 'hsl(var(--color-success))' },
              { label: 'Total Épargne', value: savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_savings)} FC` : progressLabel(savingsQ), color: 'hsl(var(--accent-color))' },
            ].map(kpi => (
              <div key={kpi.label} style={{ flex: '1 1 160px', background: 'hsl(var(--bg-tertiary))', borderRadius: 8, padding: '10px 14px', border: '1px solid hsl(var(--border-color))' }}>
                <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Formulaire saisie (BUG-231 : gérant et au-dessus) */}
        {canWriteTreasury && (
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
        )}

        {/* Table mensuelle */}
        {savingsQ.error && (
          <div role="alert" style={{ textAlign: 'center', padding: 8, color: 'hsl(var(--color-danger))', fontSize: '0.8rem' }}>
            {savingsQ.error}{' '}
            <button onClick={reloadSavingsEntries} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
          </div>
        )}
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
                        disabled={!savingsReady}
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
                  <td colSpan={user?.can_access_all_nodes ? 2 : 1} style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{savingsDayFilter ? filteredSavingsEntries.length : (savingsQ.total ?? filteredSavingsEntries.length)} entrée(s)</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px' }}>{filteredSavingsTotals && savingsTotalsReady ? fmt(filteredSavingsTotals.total_flour_sacks) : '…'}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>{filteredSavingsTotals && savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_revenue)} FC` : '…'}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px' }}></td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--accent-color))' }}>{filteredSavingsTotals && savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_savings)} FC` : '…'}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {entryModal}
    </div>
  );
};
