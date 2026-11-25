import React, { useState, useEffect, useCallback, useMemo } from 'react';
import axios from 'axios';
import {
  FiRefreshCw, FiAlertTriangle, FiLock, FiFileText, FiDollarSign, FiPrinter,
} from 'react-icons/fi';
import {
  treasuryApi, salesApi, productionApi, coreApi,
  FacturierReport, CashClosure, LocalExpense,
  ProductionSession, BakeryNode,
} from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import {
  canConfirmClosures, treasuryErrorMessage, validateBillCounts,
} from '@/components/treasury/treasuryRules';
import {
  BILLS, EMPTY_BILLS, PAGE_SIZE, progressLabel, fmt,
} from '@/components/treasury/treasuryShared';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { ExpenseHistoryModal } from '@/components/treasury/ExpenseHistoryModal';
import { ClosureDetailModal } from '@/components/treasury/ClosureDetailModal';
import { ClosureVersementReadOnly } from '@/components/treasury/ClosureVersementReadOnly';
import { BilletageForm } from '@/components/treasury/BilletageForm';
import type { BillCounts } from '@/components/treasury/BilletageForm';
import { LocalExpensesCard } from '@/components/treasury/LocalExpensesCard';
import { BilletageSummaryTable, ClosuresList } from '@/components/treasury/ClosuresPanels';
import { FacturierReportsTable, PastReportsTable } from '@/components/treasury/FacturierReportsTables';
import { ProductionRecapPanel } from '@/components/treasury/ProductionRecapPanel';
import { computeProductionRecap, print511, printPastReport } from '@/components/treasury/clotureRecap';
import type { BreadSoldSummary } from '@/components/treasury/clotureRecap';


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
  const [breadSold, setBreadSold] = useState<BreadSoldSummary | null>(null);
  const [auxLoading, setAuxLoading] = useState(true);

  // §5.2 Billetage state
  const [bills, setBills] = useState<BillCounts>({
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
  const canViewVersementReadOnly = !!user && ['ADMIN', 'DIRECTION', 'COMPTABLE'].includes(user.role);
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

  // Passage en mode « correction » d'une clôture infirmée (préremplit le billetage).
  const handleEditClosure = (c: CashClosure) => {
    setEditingClosure(c);
    setBills({ bills_20000: c.bills_20000 || 0, bills_10000: c.bills_10000 || 0, bills_5000: c.bills_5000 || 0, bills_1000: c.bills_1000 || 0, bills_500: c.bills_500 || 0, bills_200: c.bills_200 || 0, bills_100: c.bills_100 || 0, bills_50: c.bills_50 || 0 });
    setClosureNotes(c.notes || '');
  };

  const handleCancelEdit = () => {
    setEditingClosure(null);
    setBills({ ...EMPTY_BILLS });
    setClosureNotes('');
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
    print511({ today, nodeLabel, recap: computeProductionRecap(todaySessions, breadSold), effectiveSacValueFc, reports });
  };

  // §5.1.1 — Production recap
  // Valeur théorique par sac : celle de la boulangerie courante (gérant : la
  // sienne ; HQ : celle sélectionnée dans le filtre), sinon repli sur la
  // valeur par défaut de la Configuration — jamais "200 000" en dur.
  const currentNodeId = user?.node || nodeFilter || null;
  const currentNode = currentNodeId ? allNodes.find(n => n.id === currentNodeId) : undefined;
  const effectiveSacValueFc = (currentNode?.sac_value_fc && parseFloat(currentNode.sac_value_fc) > 0)
    ? parseFloat(currentNode.sac_value_fc)
    : configSacValueFc;
  const recap = computeProductionRecap(todaySessions, breadSold);
  const pendingReports = reportsReady ? reports.filter(r => !r.is_validated).length : 0;


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
        <ProductionRecapPanel
          recap={recap}
          effectiveSacValueFc={effectiveSacValueFc}
          pendingReports={pendingReports}
          reportsReady={reportsReady}
          reportsCount={reports.length}
          reportsProgress={progressLabel(reportsQ)}
          confirmingDay={confirmingDay}
          confirmMsg={confirmMsg}
          onConfirmDay={handleConfirmDay}
        />
        <FacturierReportsTable
          reports={reports}
          isLoading={reportsQ.isLoading}
          error={reportsQ.error}
          onRetry={reloadReports}
          canAccessAllNodes={!!user?.can_access_all_nodes}
          reportsReady={reportsReady}
          progress={progressLabel(reportsQ)}
          totalCash={totalCash}
          totalCredit={totalCredit}
          theoreticalCash={theoreticalCash}
          onValidate={handleValidateReport}
        />
        <PastReportsTable reports={pastReports} onValidate={handleValidatePastReport} onPrint={printPastReport} />
      </div>

      {/* ═══ §5.1.2 + §5.2 — CLÔTURE GÉRANT : dépenses/encaissements saisis d'abord, puis billetage et dégagement des écarts ═══ */}
      <div className="split-grid" style={{ '--split-cols': user?.can_access_all_nodes ? '1fr' : '1fr 1.3fr', gap: '16px' } as React.CSSProperties}>

        {/* §5.2 — BILLETAGE PHYSIQUE — saisie du gérant uniquement (le comptable/Direction confirme, mais ne saisit pas le versement). Affiché en second (order 2) : dépend des dépenses déjà saisies pour calculer l'écart. */}
        {!user?.can_access_all_nodes && (
          <BilletageForm
            today={today}
            editingClosure={editingClosure}
            todayClosure={todayClosure}
            selectedNodeLabel={selectedNodeLabel}
            bills={bills}
            onBillsChange={setBills}
            closureNotes={closureNotes}
            onNotesChange={setClosureNotes}
            closureDate={closureDate}
            onClosureDateChange={setClosureDate}
            allowBackdatedSales={allowBackdatedSales}
            closureError={closureError}
            closureInfo={closureInfo}
            closureBlockedByTransferGap={closureBlockedByTransferGap}
            closuresLoading={closuresQ.isLoading}
            billTotalShown={billTotalShown}
            reportsReady={reportsReady}
            reportsProgress={progressLabel(reportsQ)}
            reportsCount={reports.length}
            theoreticalCash={theoreticalCash}
            totalExpenses={totalExpenses}
            expensesReady={expensesReady}
            expensesProgress={progressLabel(expensesQ)}
            dayReady={dayReady}
            closureRecorded={closureRecorded}
            soldeComptable={soldeComptable}
            ecartCaisse={ecartCaisse}
            onSubmit={handleCreateClosure}
            onCancelEdit={handleCancelEdit}
          />
        )}

        {/* remarque.md : la section « Versement » est aussi visible par la direction centrale et le comptable (ADMIN, DIRECTION, COMPTABLE),
            en lecture seule, par boulangerie (filtre de succursale). Décision client 2026-11-24 : le COMPTABLE valide aussi
            la clôture (BUG-1126). Saisie réservée au gérant (formulaire ci-dessus). */}
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
          <LocalExpensesCard
            today={today}
            nodeFilter={nodeFilter}
            userHasNode={!!user?.node}
            selectedNodeLabel={selectedNodeLabel}
            expenses={expenses}
            isLoading={expensesQ.isLoading}
            error={expensesQ.error}
            dayReady={dayReady}
            netCaisse={netCaisse}
            onOpenHistory={() => setExpenseHistoryOpen(true)}
            onAdded={loadData}
          />


          {user?.can_access_all_nodes && (
            <BilletageSummaryTable
              today={today}
              closures={closures}
              isLoading={closuresQ.isLoading}
              isComplete={closuresQ.isComplete}
              progress={progressLabel(closuresQ)}
            />
          )}


          <ClosuresList
            closures={closures}
            isLoading={closuresQ.isLoading}
            error={closuresQ.error}
            canConfirm={canConfirm}
            canAccessAllNodes={!!user?.can_access_all_nodes}
            onOpenDetail={setDetailClosure}
            onEdit={handleEditClosure}
            onPushToCashbook={handlePushToCashbook}
          />
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
