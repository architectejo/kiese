import React, { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import { Link } from 'react-router-dom';
import {
  FiBook, FiRefreshCw, FiCheckCircle, FiAlertTriangle,
  FiPlus, FiX, FiLock, FiFileText, FiDollarSign, FiPrinter, FiCalendar
} from 'react-icons/fi';
import {
  treasuryApi, salesApi, productionApi, coreApi,
  FacturierReport, CashClosure, LocalExpense,
  ProductionSession, BakeryNode, ExpenseCategory,
} from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import {
  isInvalidBillCount, parseBillCount, validateBillCounts,
  canConfirmClosures, treasuryErrorMessage,
} from '@/components/treasury/treasuryRules';
import {
  BILLS, PAGE_SIZE, progressLabel, fmt, renderReportCategoryDetail,
} from '@/components/treasury/treasuryShared';
import type { BillKey } from '@/components/treasury/treasuryShared';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { ExpenseHistoryModal } from '@/components/treasury/ExpenseHistoryModal';
import { ClosureDetailModal } from '@/components/treasury/ClosureDetailModal';
import { ClosureVersementReadOnly } from '@/components/treasury/ClosureVersementReadOnly';

/**
 * Options de CLÔTURE (remarque.md : « toutes les options de clôture dans Clôture Journalière »).
 * Déplacées depuis l'ancienne page « Clôture & Caisse » (Treasury.tsx, devenue « Caisse ») :
 * KPI du jour, Niveau 1 (rapports facturiers par équipe), Versement (billetage, écart),
 * dépenses locales du jour, synthèse des billetages, clôtures du jour (confirmer / infirmer).
 * Aucun appel d'API ni règle métier modifié : seul l'emplacement change.
 */
export const ClotureOperations: React.FC = () => {
  const { user } = useAuthStore();
  const today = useWorkDate();

  const [extraReports, setExtraReports] = useState<FacturierReport[]>([]);
  const [nodeFilter, setNodeFilter] = useState('');
  const [allNodes, setAllNodes]     = useState<BakeryNode[]>([]);
  const [todaySessions, setTodaySessions] = useState<ProductionSession[]>([]);
  const [breadSold, setBreadSold] = useState<{
    by_category: Array<{ unit_price: number; total_qty: number; total_fc: number }>;
    grand_total_qty: number; grand_total_fc: number;
  } | null>(null);
  const [auxLoading, setAuxLoading] = useState(true);

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

  // §5.1.2 — Historique mensuel des dépenses (modale ExpenseHistoryModal)
  const [expenseHistoryOpen, setExpenseHistoryOpen] = useState(false);

  const [generatingReport, setGeneratingReport] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateInfo, setGenerateInfo] = useState<string | null>(null);
  // BUG-086 : date rétroactive optionnelle pour la génération du rapport §5.1.1 — vide = aujourd'hui.
  const [reportDate, setReportDate] = useState('');
  const [detailClosure, setDetailClosure] = useState<CashClosure | null>(null);

  // BUG-231 / BUG-200 : confirmer, infirmer et inscrire au Livre de Caisse = siège (COMPTABLE/DIRECTION/ADMIN) ;
  // jamais le gérant. Le serveur reste l'autorité (403 affiché).
  const canConfirm = canConfirmClosures(user);
  const canViewVersementReadOnly = !!user && ['ADMIN', 'DIRECTION'].includes(user.role);
  const nodeParam: Record<string, string> = nodeFilter ? { node: nodeFilter } : {};

  const reportsQ = useProgressiveList<FacturierReport>({
    fetchPage: p => treasuryApi.reports.page({ date: today, ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `rep|${today}|${nodeFilter}`,
  });
  const closuresQ = useProgressiveList<CashClosure>({
    fetchPage: p => treasuryApi.closures.page({ date: today, ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `clo|${today}|${nodeFilter}`,
  });
  const expensesQ = useProgressiveList<LocalExpense>({
    fetchPage: p => treasuryApi.expenses.page({ date: today, ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `exp|${today}|${nodeFilter}`,
  });

  // BUG-175 : `reports` = rapports du JOUR uniquement (totaux, validation en masse, impression §5.1.1).
  // Les rapports rétroactifs (`pastReports`) sont affichés à part, à leur propre date, et n'entrent
  // jamais dans ces calculs. Ils ne sont gardés que pour la boulangerie consultée.
  const reports = useMemo(
    () => reportsQ.items.filter(r => r.date === today),
    [reportsQ.items, today],
  );
  const pastReports = useMemo(
    () => extraReports.filter(x => x.date !== today && (!nodeFilter || x.node === nodeFilter)),
    [extraReports, today, nodeFilter],
  );
  const closures = closuresQ.items;
  const expenses = expensesQ.items;

  // Aperçus de la journée (sessions, ventes par catégorie) : requêtes ciblées, hors listes.
  const loadAux = useCallback(async () => {
    setAuxLoading(true);
    const nf = nodeFilter || undefined;
    try {
      // BUG-230 : le résumé des ventes peut répondre 403 (boulangerie étrangère) ou 400 (date
      // invalide) : on l'isole pour ne pas perdre les sessions, sans planter l'écran.
      const [sessionRes, breadRes] = await Promise.all([
        productionApi.sessions.list({ date: today, ...(nf && { node: nf }) }),
        salesApi.breadSummary({ date: today, ...(nf && { node: nf }) }).catch((e: unknown) => {
          console.error('Résumé des ventes indisponible :', getErrorDetail(e, 'Résumé des ventes indisponible.'));
          return null;
        }),
      ]);
      setTodaySessions(Array.isArray(sessionRes.data) ? sessionRes.data : []);
      setBreadSold(breadRes?.data ?? null);
    } catch (err) {
      console.error('Treasury load failed', err);
    } finally {
      setAuxLoading(false);
    }
  }, [today, nodeFilter]);

  const reloadReports = reportsQ.reload;
  const reloadClosures = closuresQ.reload;
  const reloadExpenses = expensesQ.reload;
  // Rechargement complet après une action (valider, clôturer, dépense…).
  const loadData = useCallback(async () => {
    // BUG-175 : les rapports rétroactifs ajoutés localement ne survivent pas au rechargement
    // (la liste serveur fait alors foi, comme avant BUG-164).
    setExtraReports([]);
    reloadReports(); reloadClosures(); reloadExpenses();
    await loadAux();
  }, [reloadReports, reloadClosures, reloadExpenses, loadAux]);

  useEffect(() => { loadAux(); }, [loadAux]);

  // BUG-175 : changement de boulangerie ou de jour => aucun rapport rétroactif résiduel.
  useEffect(() => { setExtraReports([]); }, [nodeFilter, today]);

  // Totaux « du jour » : fiables seulement quand rapports ET dépenses sont complets.
  const reportsReady = reportsQ.isComplete;
  const expensesReady = expensesQ.isComplete;
  const [editingClosure, setEditingClosure] = useState<CashClosure | null>(null);
  const dayReady = reportsReady && expensesReady;
  const isLoading = auxLoading || reportsQ.isLoading || closuresQ.isLoading || expensesQ.isLoading;

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
  // BUG-298 : une clôture du jour déjà enregistrée fait foi (valeurs serveur, non modifiables) ;
  // sinon calcul prévisionnel = billetage − (espèces théoriques − dépenses locales).
  const closureRecorded = !!todayClosure && !editingClosure;
  const soldeComptable = closureRecorded ? parseFloat(todayClosure.net_cash || '0') : theoreticalCash - totalExpenses;
  const ecartCaisse = closureRecorded ? parseFloat(todayClosure.cash_gap || '0') : billTotal - soldeComptable;
  const billTotalShown = closureRecorded ? parseFloat(todayClosure.physical_cash_total || '0') : billTotal;
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
        setExtraReports(prev => [...res.data, ...prev.filter(r => !res.data.some(nr => nr.id === r.id))]);
        setGenerateInfo(`Rapport généré pour le ${new Date(targetDate).toLocaleDateString('fr-FR')} (date rétroactive) — n'apparaît pas dans le filtre "Clôtures du Jour".`);
      } else {
        await loadData();
      }
      const detail = (res.data as unknown as { detail?: string })?.detail;
      if (detail) setGenerateError(detail);
    } catch (err: unknown) {
      setGenerateError(getErrorDetail(err, 'Erreur lors de la génération.'));
    } finally {
      setGeneratingReport(false);
    }
  };

  // BUG-175 : validation / impression individuelles d'un rapport rétroactif (hors totaux du jour).
  const handleValidatePastReport = async (id: string) => {
    try {
      await treasuryApi.reports.validate(id);
      setExtraReports(prev => prev.map(r => (r.id === id ? { ...r, is_validated: true } : r)));
    } catch (err: unknown) {
      setGenerateError(getErrorDetail(err, 'Erreur lors de la validation.'));
    }
  };

  const handlePrintPastReport = (r: FacturierReport) => {
    const n = (v: string) => Math.round(parseFloat(v || '0')).toLocaleString('fr-FR');
    const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8">
      <title>Rapport facturier ${r.date}</title>
      <style>body{font-family:Arial,sans-serif;font-size:12px;margin:20px}td,th{border:1px solid #ddd;padding:4px 8px}table{border-collapse:collapse}</style></head><body>
      <h1 style="font-size:14px">Rapport facturier — ${new Date(r.date).toLocaleDateString('fr-FR')} (date rétroactive)</h1>
      <table><thead><tr><th>Boulangerie</th><th>Équipe</th><th>Cash</th><th>Crédit</th><th>Théorique</th><th>Statut</th></tr></thead>
      <tbody><tr><td>${r.node_display || r.node_origin || '—'}</td><td>Éq. ${r.team}</td><td>${n(r.total_cash_sales)} FC</td><td>${n(r.total_credit_sales)} FC</td><td>${n(r.theoretical_cash)} FC</td><td>${r.is_validated ? 'Validé' : 'En attente'}</td></tr></tbody></table>
      <script>window.onload=()=>{ window.print(); window.onafterprint=()=>window.close(); }</script></body></html>`;
    const w = window.open('', '_blank', 'width=800,height=600');
    if (w) { w.document.write(html); w.document.close(); }
  };

  const handleValidateReport = async (id: string) => {
    try {
      await treasuryApi.reports.validate(id);
      await loadData();
    } catch (err: unknown) {
      setGenerateError(getErrorDetail(err, 'Erreur lors de la validation du rapport.'));
    }
  };

  const handleCreateClosure = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setClosureError(null);
    setClosureInfo(null);
    setClosureBlockedByTransferGap(false);
    const billsProblem = validateBillCounts(bills);
    if (billsProblem) { setClosureError(billsProblem); return; }
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
        await treasuryApi.closures.update(editingClosure.id, { notes: closureNotes, ...bills });
        setEditingClosure(null);
      } else {
        const effectiveNode = user?.node || nodeFilter || null;
        if (!effectiveNode) { setClosureError('Sélectionnez une succursale dans le filtre avant de créer une clôture.'); return; }
        await treasuryApi.closures.create({
          date: targetClosureDate,
          notes: closureNotes,
          ...bills,
          ...(nodeFilter && !user?.node ? { node: nodeFilter } : {}),
        });
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
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { detail?: string; non_field_errors?: string[] } | undefined)
        : undefined;
      const detail = d?.detail;
      const fieldMsg = treasuryErrorMessage(err, '');
      // BUG-048 : message reçu tel quel du serveur (jamais inventé) — on ne fait que
      // repérer s'il décrit un transfert entrant en écart non résolu (CLAUDE.md §5.4)
      // pour proposer un renvoi vers la section Transferts de Production.tsx.
      setClosureBlockedByTransferGap(!!detail && /transfert/i.test(detail) && /écart/i.test(detail));
      setClosureError(detail || d?.non_field_errors?.[0] || fieldMsg || 'Erreur lors de la clôture.');
    }
  };

  const handleValidateClosure = async (closureId: string, notes?: string) => {
    if (closureActionLoading) return;
    setClosureActionLoading(true);
    try {
      await treasuryApi.closures.validate(closureId, notes);
      setDetailClosure(null);
      await loadData();
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Erreur lors de la confirmation.'));
    } finally {
      setClosureActionLoading(false);
    }
  };

  const [closureActionLoading, setClosureActionLoading] = useState(false);

  const handleRejectClosure = async (closureId: string, rejectReason: string) => {
    if (closureActionLoading) return;
    setClosureActionLoading(true);
    try {
      await treasuryApi.closures.reject(closureId, rejectReason);
      setDetailClosure(null);
      await loadData();
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Erreur lors du rejet.'));
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
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Erreur lors de la mise au Livre de Caisse.'));
    } finally {
      setClosureActionLoading(false);
    }
  };

  const handleAddExpense = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setExpError(null);
    if (!expDesc || !expAmount || !expCategory) { setExpError('Remplissez tous les champs.'); return; }
    if (!(parseFloat(expAmount) > 0)) { setExpError('Le montant de la dépense doit être supérieur à 0.'); return; }
    try {
      await treasuryApi.expenses.create({
        description: expDesc, category: Number(expCategory),
        amount: expAmount, date: today,
        ...(nodeFilter && !user?.node ? { node: nodeFilter } : {}),
      });
      setExpDesc(''); setExpAmount('');
      setShowExpenseForm(false);
      await loadData();
    } catch (err: unknown) {
      setExpError(getErrorDetail(err, "Erreur lors de l'enregistrement de la dépense."));
    }
  };

  const [confirmingDay, setConfirmingDay] = useState(false);
  const [confirmMsg, setConfirmMsg]       = useState<string | null>(null);

  const handleConfirmDay = async () => {
    // BUG-164 : ne jamais valider « les rapports en attente » d'une liste partielle.
    if (!reportsReady) { setConfirmMsg('Chargement des rapports en cours — patientez avant de confirmer la journée.'); return; }
    const pending = reports.filter(r => !r.is_validated);
    if (pending.length === 0) { setConfirmMsg('Tous les rapports sont déjà validés.'); return; }
    setConfirmingDay(true);
    setConfirmMsg(null);
    try {
      await Promise.all(pending.map(r => treasuryApi.reports.validate(r.id)));
      await loadData();
      setConfirmMsg(`${pending.length} rapport(s) validé(s). Procédez au billetage physique (§5.2) pour finaliser la clôture.`);
    } catch (err: unknown) {
      setConfirmMsg(getErrorDetail(err, 'Erreur lors de la validation.'));
    } finally {
      setConfirmingDay(false);
    }
  };

  const handlePrint511 = () => {
    // BUG-164 : l'impression porte sur la liste COMPLÈTE des rapports (bouton désactivé tant
    // que le chargement n'est pas terminé ; garde de sécurité ici aussi).
    if (!reportsReady) return;
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
  const _pendingReports = reportsReady ? reports.filter(r => !r.is_validated).length : 0;

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
          {!reportsReady && (
            <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>
              Rapports : {progressLabel(reportsQ)}
            </span>
          )}
          {reportsReady && _pendingReports === 0 && reports.length > 0 && (
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px', fontSize: '0.85rem' }}>
      {/* En-tête des opérations de clôture du jour (ex « Clôture & Caisse ») */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px' }}>
        <h2 style={{ fontSize: '1rem', fontWeight: 800 }}>Opérations de clôture du jour — {today}</h2>
        <button onClick={loadData} disabled={isLoading} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '4px' }}>
          <FiRefreshCw style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
          <span>Actualiser les opérations</span>
        </button>
      </div>

      {/* KPI Bar */}
      <div className="kpi-grid" style={{ gap: '12px' }}>
        {[
          { label: 'TOTAL CASH DU JOUR', value: reportsReady ? `${fmt(totalCash)} FC` : progressLabel(reportsQ), color: 'var(--color-success)', icon: <FiDollarSign /> },
          { label: 'TOTAL CRÉDIT DU JOUR', value: reportsReady ? `${fmt(totalCredit)} FC` : progressLabel(reportsQ), color: 'var(--color-info)', icon: <FiFileText /> },
          { label: 'SOLDE COMPTABLE CAISSE', value: (reportsReady || closureRecorded) ? `${fmt(soldeComptable)} FC` : progressLabel(reportsQ), color: 'var(--color-warning)', icon: <FiLock /> },
          { label: 'ÉCART BILLETAGE', value: dayReady ? `${ecartCaisse >= 0 ? '+' : ''}${fmt(ecartCaisse)} FC` : 'calcul en cours…', color: !dayReady ? 'var(--text-muted)' : ecartCaisse === 0 ? 'var(--color-success)' : 'var(--color-danger)', icon: <FiAlertTriangle /> },
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
              disabled={!reportsReady}
              className="btn btn-secondary"
              title={reportsReady ? 'Imprimer §5.1.1' : `Impression disponible une fois tous les rapports chargés (${reportsQ.loaded}/${reportsQ.total ?? '…'})`}
              style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <FiPrinter size={13} />
              {reportsReady ? 'Imprimer' : `Chargement ${reportsQ.loaded}/${reportsQ.total ?? '…'}`}
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
        {reportsQ.error && (
          <div role="alert" style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)', marginBottom: '8px', display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            {reportsQ.error}
            <button onClick={reloadReports} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
          </div>
        )}
        {reportsQ.isLoading && reports.length === 0 ? (
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
                  {reportsReady ? (
                    <>
                      <td style={{ textAlign: 'right', color: 'hsl(var(--color-success))' }}>{fmt(totalCash)} FC</td>
                      <td style={{ textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(totalCredit)} FC</td>
                      <td style={{ textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{fmt(theoreticalCash)} FC</td>
                    </>
                  ) : (
                    <td colSpan={3} style={{ textAlign: 'right', fontSize: '0.62rem', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progressLabel(reportsQ)}</td>
                  )}
                  <td colSpan={2} />
                </tr>
              </tbody>
            </table>
          </div>
        )}
        {pastReports.length > 0 && (
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
                {pastReports.map(r => (
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
                        <button onClick={() => handleValidatePastReport(r.id)} className="btn btn-primary" style={{ padding: '2px 8px', fontSize: '0.62rem', marginRight: '4px' }}>Valider</button>
                      )}
                      <button onClick={() => handlePrintPastReport(r)} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Imprimer</button>
                    </td>
                  </tr>
                ))}
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
          <form noValidate onSubmit={handleCreateClosure} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
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
                    type="number" inputMode="numeric"
                    value={bills[b.key] || ''}
                    placeholder="0"
                    aria-invalid={isInvalidBillCount(bills[b.key])}                    onChange={e => setBills(prev => ({ ...prev, [b.key]: parseBillCount(e.target.value) }))}
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
                <span style={{ color: 'hsl(var(--color-success))', fontSize: '0.9rem' }}>{billTotalShown.toLocaleString('fr-FR')} FC</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                <span>
                  Recette / Paiement :
                  <span style={{ fontSize: '0.58rem', color: 'hsl(var(--text-muted))', marginLeft: '4px' }}>
                    {!reportsReady ? `(${progressLabel(reportsQ)})` : reports.length > 0 ? `(§5.1.1 · ${reports.length} rapport(s))` : '(aucun rapport §5.1.1)'}
                  </span>
                </span>
                <span style={{ fontWeight: 700, color: reports.length > 0 ? 'inherit' : 'hsl(var(--color-warning))' }}>{reportsReady ? `${fmt(theoreticalCash)} FC` : '…'}</span>
              </div>
              {(totalExpenses > 0 || !expensesReady) && (
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                  <span>— Dépenses Locales :</span>
                  <span style={{ fontWeight: 700, color: 'hsl(var(--color-danger))' }}>{expensesReady ? `−${fmt(totalExpenses)} FC` : progressLabel(expensesQ)}</span>
                </div>
              )}
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                <span>Solde comptable caisse :</span>
                <span style={{ fontWeight: 800, color: 'hsl(var(--color-warning))' }}>{dayReady || closureRecorded ? `${fmt(soldeComptable)} FC` : '…'}</span>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800, padding: '5px 8px', borderRadius: 'var(--radius-sm)', backgroundColor: !dayReady ? 'hsl(var(--bg-tertiary))' : ecartCaisse === 0 ? 'hsl(var(--color-success) / 0.08)' : 'hsl(var(--color-danger) / 0.08)', border: `1px solid hsl(var(--${!dayReady ? 'border-color' : ecartCaisse === 0 ? 'color-success' : 'color-danger'}) / 0.3)` }}>
                <span>ÉCART DE CAISSE :</span>
                {dayReady ? (
                  <span style={{ color: ecartCaisse === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                    {ecartCaisse >= 0 ? '+' : ''}{ecartCaisse.toLocaleString('fr-FR')} FC
                    {ecartCaisse > 0 ? ' (Excédent)' : ecartCaisse < 0 ? ' (Manque)' : ' ✓ Équilibré'}
                  </span>
                ) : (
                  <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>calcul en cours…</span>
                )}
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
            {!closuresQ.isLoading && (!todayClosure || editingClosure) && !editingClosure?.is_validated && (
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

        {/* remarque.md : la section « Versement » est aussi visible par la direction centrale (ADMIN, DIRECTION),
            en lecture seule, par boulangerie (filtre de succursale). Le COMPTABLE n'y est pas ajouté : un retour
            précédent l'en avait retiré (à confirmer, voir rapport). Saisie réservée au gérant (formulaire ci-dessus). */}
        {canViewVersementReadOnly && (
          <ClosureVersementReadOnly
            nodeFilter={nodeFilter}
            nodeLabel={selectedNodeLabel}
            today={today}
            refreshKey={closures.map(c => `${c.id}:${c.is_validated}:${c.is_rejected}`).join('|')}
            style={{ order: 2 }}
          />
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
              <form noValidate onSubmit={handleAddExpense} style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '10px', padding: '10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
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
              {expensesQ.isLoading && <div style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '8px' }}>Chargement des dépenses…</div>}
              {expensesQ.error && <div role="alert" style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', padding: '8px' }}>{expensesQ.error}</div>}
              {!expensesQ.isLoading && !expensesQ.error && expenses.length === 0 && <div style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '8px' }}>Aucune dépense locale</div>}
            </div>

            {/* Net caisse */}
            <div style={{ marginTop: '8px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '6px', display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', fontWeight: 800 }}>
              <span>Caisse Nette Boulangerie :</span>
              {dayReady ? (
                <span style={{ color: netCaisse >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                  {fmt(netCaisse)} FC
                </span>
              ) : (
                <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>calcul en cours…</span>
              )}
            </div>
          </div>

          {/* Synthèse globale — billetage de toutes les boulangeries */}
          {user?.can_access_all_nodes && (
            <div className="glass-card" style={{ padding: '14px', overflowX: 'auto' }}>
              <h2 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '10px' }}>
                Synthèse Globale — Billetage de Toutes les Boulangeries ({today})
              </h2>
              {closuresQ.isLoading ? (
                <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement des clôtures…</div>
              ) : closures.length === 0 ? (
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
                      {closuresQ.isComplete ? (
                        <>
                          {BILLS.map(b => (
                            <td key={b.key} style={{ textAlign: 'right' }}>
                              {closures.reduce((s, c) => s + ((c[b.key as keyof CashClosure] as number) || 0), 0)}
                            </td>
                          ))}
                          <td style={{ textAlign: 'right' }}>{fmt(closures.reduce((s, c) => s + parseFloat(String(c.physical_cash_total || '0')), 0))}</td>
                          <td style={{ textAlign: 'right' }}>{fmt(closures.reduce((s, c) => s + parseFloat(String(c.cash_gap || '0')), 0))}</td>
                        </>
                      ) : (
                        <td colSpan={BILLS.length + 2} style={{ textAlign: 'right', fontWeight: 600, color: 'hsl(var(--text-muted))' }}>{progressLabel(closuresQ)}</td>
                      )}
                    </tr>
                  </tfoot>
                </table>
              )}
            </div>
          )}

          {/* Closures — validate + push to cashbook */}
          <div className="glass-card" style={{ padding: '14px' }}>
            <h2 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '10px' }}>Clôtures du Jour</h2>
            {closuresQ.isLoading ? (
              <div style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement des clôtures…</div>
            ) : closuresQ.error ? (
              <div role="alert" style={{ textAlign: 'center', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', padding: '10px' }}>{closuresQ.error}</div>
            ) : closures.length === 0 ? (
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
                      <span className={`badge ${c.is_validated ? 'badge-success' : c.is_rejected ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.52rem' }}>
                        {c.is_validated ? 'CONFIRMÉE' : c.is_rejected ? 'INFIRMÉE' : 'EN ATTENTE'}
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
                    {canConfirm && !c.is_validated && (
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
                      {c.is_validated && canConfirm && !c.has_cashbook_entry && (
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

      {detailClosure && (
        <ClosureDetailModal
          closure={detailClosure}
          onClose={() => setDetailClosure(null)}
          canConfirm={canConfirm}
          actionLoading={closureActionLoading}
          onValidate={handleValidateClosure}
          onReject={handleRejectClosure}
          onPush={id => { setDetailClosure(null); void handlePushToCashbook(id); }}
        />
      )}

      <ExpenseHistoryModal
        isOpen={expenseHistoryOpen}
        onClose={() => setExpenseHistoryOpen(false)}
        nodeFilter={nodeFilter}
        subtitle={selectedNodeLabel || (user?.can_access_all_nodes ? 'Toutes les succursales' : undefined)}
        showNode={!!user?.can_access_all_nodes}
      />

    </div>
  );
};
