import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  FiGrid, FiAlertTriangle, FiCheckCircle,
  FiRefreshCw, FiPackage, FiTruck
} from 'react-icons/fi';
import {
  productionApi, coreApi, ConsumableStock, ConsumableCount, FlourHistoryEntry,
  ProductionSession, BreadTransfer, BreadDisposal, BreadStock, BakeryNode, BreadPrice, ServiceTeam
} from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { useAuthStore } from '@/store/authStore';
import { getWorkDate, useRotationActive, useSelectedWorkDay } from '@/store/workDateStore';
import { AllSessionsModal } from '@/components/production/AllSessionsModal';
import { SessionDetailModal } from '@/components/production/SessionDetailModal';
import { ApproModal } from '@/components/production/ApproModal';
import { DirectSendModal } from '@/components/production/DirectSendModal';
import { CloseSessionModal } from '@/components/production/CloseSessionModal';
import { IntrantsTab } from '@/components/production/IntrantsTab';
import { FourneesTab } from '@/components/production/FourneesTab';
import { FlourHistoryCard } from '@/components/production/FlourHistoryCard';
import { TransfersTab } from '@/components/production/TransfersTab';
import { ReconciliationTab } from '@/components/production/ReconciliationTab';
import {
  fetchDisposalsPage, fetchSessionTotals, fetchTransfersScoped,
} from '@/components/production/productionHelpers';

export const Production: React.FC = () => {
  const { user } = useAuthStore();

  const [stocks, setStocks]           = useState<ConsumableStock[]>([]);
  const [breadStocks, setBreadStocks] = useState<BreadStock[]>([]);
  const [sessions, setSessions]       = useState<ProductionSession[]>([]);
  const [transfers, setTransfers]     = useState<BreadTransfer[]>([]);
  const [disposals, setDisposals]     = useState<BreadDisposal[]>([]);
  const [todayDispoQty, setTodayDispoQty] = useState(0);
  const [sessionTotals, setSessionTotals] = useState<{ count: number; totalFc: number } | null>(null);
  const loadSeqRef = useRef(0);
  const [nodes, setNodes]             = useState<BakeryNode[]>([]);
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
  const [sacValueFc, setSacValueFc]   = useState<number | null>(null); // BUG-311 : null tant que la config n'est pas chargée
  const [isLoading, setIsLoading]     = useState(true);

  // Direction Générale (multi-node access) must pick one branch to view —
  // stocks/sessions are otherwise mixed across all 8 bakeries with no indication.
  const [viewNode, setViewNode]       = useState('');

  // BUG-094 : onglets explicites (la section « Intrants » existait déjà mais était noyée
  // au milieu d'une page de 1500+ lignes sans libellé visible pour le client).
  const [activeTab, setActiveTab] = useState<'fournees' | 'intrants' | 'transferts' | 'reconciliation'>('fournees');

  const [showAllSessionsModal, setShowAllSessionsModal] = useState(false);
  const [selectedSession, setSelectedSession] = useState<ProductionSession | null>(null);
  const [sessionNotes, setSessionNotes] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  // BUG-108 : clôture automatisée de la fournée (POST .../close/)
  // BUG-154 : la clôture elle-même (avec saisie du « Reste du Jour » par catégorie) se fait
  // désormais dans CloseSessionModal, qui gère son propre état de soumission/erreur.
  const [closeSessionModalOpen, setCloseSessionModalOpen] = useState(false);
  // BUG-145 (remarque.md l.397) : un seul sélecteur de date pilote « Stock Pains du Jour »
  // ET « Historique des Fournées ». `sessions` (KPI, formulaire de sortie non standard —
  // filtré à "aujourd'hui" indépendamment de ce sélecteur) reste intentionnellement
  // inchangé ; seul l'affichage de l'historique des fournées utilise `historySessions`.
  const [selectedDate, setSelectedDate, workDate] = useSelectedWorkDay();
  const rotationActive = useRotationActive();
  // BUG-195 : en rotation, l'équipe de la fournée est l'équipe de service désignée du jour
  // (le serveur la lit ; le formulaire n'envoie ni `team` ni `date`). `undefined` = pas encore
  // lue ; `null` = aucune équipe désignée.
  const [serviceTeam, setServiceTeam] = useState<ServiceTeam | null | undefined>(undefined);
  const assignmentTick = useTeamAssignmentStore(st => st.requestTick);
  useEffect(() => {
    if (!rotationActive) { setServiceTeam(undefined); return; }
    let cancelled = false;
    const read = () => {
      productionApi.teamAssignment.get()
        .then(({ data }) => { if (!cancelled) setServiceTeam(data.team); })
        .catch(() => { /* le sondage du layout réessaie ; la création relit de toute façon */ });
    };
    read();
    const id = setInterval(read, 10000);
    return () => { cancelled = true; clearInterval(id); };
  }, [rotationActive, assignmentTick]);
  const [historySessions, setHistorySessions] = useState<ProductionSession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);
  // BUG-315 : incrémenté après déclaration / modification des sacs / clôture pour relire l'historique.
  const [historyTick, setHistoryTick] = useState(0);

  // §3.2 Approvisionnement
  const [showApproModal, setShowApproModal] = useState(false);
  const [approStock, setApproStock]     = useState('');
  const [approQty, setApproQty]         = useState('');
  const [approPrice, setApproPrice]     = useState('');
  const [approDesc, setApproDesc]       = useState('');
  const [approSupplier, setApproSupplier] = useState('');
  const [approError, setApproError]     = useState<string | null>(null);
  const [approSaving, setApproSaving]   = useState(false);

  // §3.2 Inventaire physique
  const [countValues, setCountValues]   = useState<Record<string, string>>({});
  const [countError, setCountError]     = useState<string | null>(null);
  const [countSubmitting, setCountSubmitting] = useState(false);
  const [lastCounts, setLastCounts]     = useState<ConsumableCount[]>([]);

  // §3.2 Achats Farine (DIRECTION)
  const [flourHistory, setFlourHistory]   = useState<FlourHistoryEntry[]>([]);
  const [flourLoading, setFlourLoading]   = useState(false);

  // §3.3 Transfer forms
  // A requests FROM a bakery (from_node = the supplier, to_node = user's own node)
  const [tFromNode, setTFromNode] = useState('');
  const [tLines, setTLines]       = useState<Record<number, number>>({});
  const [tNotes, setTNotes]       = useState('');
  const [tError, setTError]       = useState<string | null>(null);
  const [tSending, setTSending]   = useState(false);
  const [tSuccess, setTSuccess]   = useState<string | null>(null);
  const [transferNotice, setTransferNotice] = useState<string | null>(null);
  // BUG-382 : envoi direct de pains (modale) et message de succès persistant.
  const [showDirectSend, setShowDirectSend] = useState(false);
  const [directNotice, setDirectNotice] = useState<string | null>(null);
  const [transferActionError, setTransferActionError] = useState<string | null>(null);
  // respondQtys: transferId → { breadPriceId → qty_sent } (B fills when responding)
  const [respondQtys, setRespondQtys] = useState<Record<string, Record<number, number>>>({});
  // confirmQtys: transferId → { breadPriceId → qty_received } (A fills when confirming receipt)
  const [confirmQtys, setConfirmQtys] = useState<Record<string, Record<number, number>>>({});

  // §3.4 Disposal form
  const [dSession, setDSession]       = useState('');
  const [dType, setDType]             = useState<BreadDisposal['disposal_type']>('DECLASSED');
  const [dBreadPrice, setDBreadPrice] = useState('');
  const [dQty, setDQty]               = useState(0);
  const [dUnitPrice, setDUnitPrice]   = useState(0);
  const [dNotes, setDNotes]           = useState('');
  const [dError, setDError]           = useState<string | null>(null);

  // BUG-174 : boulangerie consultée, relue par `loadData()` appelé sans argument après une action
  // (sinon la direction lit les 3 derniers confirmés de tout le groupe : bloc vide).
  const viewNodeRef = useRef(viewNode);
  viewNodeRef.current = viewNode;

  const loadData = useCallback(async (nodeFilterArg?: string) => {
    const nodeFilter = nodeFilterArg || viewNodeRef.current || undefined;
    setIsLoading(true);
    // Un changement de boulangerie / un « Actualiser » rapide invalide les réponses en vol.
    loadSeqRef.current += 1;
    const seq = loadSeqRef.current;
    try {
      const scopedParams = nodeFilter ? { node: nodeFilter } : undefined;
      const scopedStrings: Record<string, string> = nodeFilter ? { node: nodeFilter } : {};
      const [stockRes, sessionRes, transferList, disposalRes, nodeRes, bpRes, configRes, breadStockRes, totalsRes] = await Promise.all([
        productionApi.stocks.list(scopedParams),
        // BUG-164 : 15 fournées demandées directement au serveur (tri -date).
        productionApi.sessions.page({ ...scopedStrings, page: '1', page_size: '15' }),
        fetchTransfersScoped(nodeFilter || user?.node || undefined),
        fetchDisposalsPage(scopedStrings, getWorkDate()),
        coreApi.nodes.list(),
        coreApi.breadPrices.list(),
        coreApi.config.get(),
        productionApi.breadStocks.list(scopedParams),
        fetchSessionTotals(scopedStrings).catch(() => null),
      ]);
      if (seq !== loadSeqRef.current) return;
      setSessionTotals(totalsRes);
      setStocks(Array.isArray(stockRes.data) ? stockRes.data : []);
      setBreadStocks(Array.isArray(breadStockRes.data) ? breadStockRes.data : []);
      setSessions((sessionRes.data.results ?? []).slice(0, 15));
      setTransfers(transferList);
      setDisposals(disposalRes.shown);
      setTodayDispoQty(disposalRes.todayQty);
      const nodeList = Array.isArray(nodeRes.data) ? nodeRes.data : [];
      setNodes(nodeList);
      const activePrices = Array.isArray(bpRes.data) ? bpRes.data.filter(b => b.is_active) : [];
      setBreadPrices(activePrices);
      // Per-node sac_value_fc takes priority; fall back to global Config if absent or zero.
      const activeNodeId = nodeFilter || user?.node || null;
      const activeNode = activeNodeId ? nodeList.find(n => String(n.id) === String(activeNodeId)) : null;
      const nodeSacVal = activeNode?.sac_value_fc ? parseFloat(activeNode.sac_value_fc) : 0;
      setSacValueFc(nodeSacVal > 0 ? nodeSacVal : (configRes.data.sac_value_fc ?? 200000));
      const initRespond: Record<string, Record<number, number>> = {};
      const initConfirm: Record<string, Record<number, number>> = {};
      transferList.forEach((t: BreadTransfer) => {
        if (t.transfer_status === 'PENDING') {
          // B pre-fills respond form with originally requested quantities
          initRespond[t.id] = {};
          (t.lines || []).forEach(line => { initRespond[t.id][line.bread_price] = line.quantity_sent; });
        }
        if (t.transfer_status === 'RESPONDED') {
          // A pre-fills confirm form with what B said they'd send
          initConfirm[t.id] = {};
          (t.lines || []).forEach(line => { initConfirm[t.id][line.bread_price] = line.quantity_sent; });
        }
      });
      setRespondQtys(initRespond);
      setConfirmQtys(initConfirm);
    } catch (err) {
      if (seq !== loadSeqRef.current) return;
      console.error('Failed to load production data', err);
    } finally {
      if (seq === loadSeqRef.current) setIsLoading(false);
    }
  }, [user]);

  // Initial mount: for DG, fetch the node list first so the first data load is already filtered.
  // For Gérant, the backend scopes data automatically — call loadData() directly.
  useEffect(() => {
    if (user?.can_access_all_nodes) {
      setIsLoading(true);
      coreApi.nodes.list()
        .then(res => {
          const nodeList = Array.isArray(res.data) ? res.data : [];
          setNodes(nodeList);
          if (nodeList.length > 0) {
            setViewNode(String(nodeList[0].id)); // triggers the viewNode effect below → loadData(firstNode)
          } else {
            setIsLoading(false);
          }
        })
        .catch(() => setIsLoading(false));
    } else {
      loadData();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [loadData]);

  useEffect(() => {
    if (viewNode) loadData(viewNode);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewNode]);

  // §3.2 Load last counts + flour history
  useEffect(() => {
    const nodeFilter = viewNode || user?.node || undefined;
    if (nodeFilter) {
      productionApi.counts.list({ node: nodeFilter }).then(r => setLastCounts(Array.isArray(r.data) ? r.data : [])).catch(() => {});
    }
    if (user?.can_access_all_nodes) {
      setFlourLoading(true);
      productionApi.movements.flourHistory(nodeFilter ? { node: nodeFilter } : undefined)
        .then(r => setFlourHistory(Array.isArray(r.data) ? r.data : []))
        .catch(() => {})
        .finally(() => setFlourLoading(false));
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewNode, user?.node]);

  // BUG-145 : « Historique des Fournées » filtré par `selectedDate`
  // (GET /api/production/sessions/?date=...&node=... — filtre déjà existant côté backend,
  // BUG-144, volet backend). Indépendant de `sessions`, voir commentaire sur son état.
  useEffect(() => {
    const nodeFilter = viewNode || user?.node || undefined;
    setHistoryLoading(true);
    setHistoryError(null);
    productionApi.sessions.list(nodeFilter ? { node: nodeFilter, date: selectedDate } : { date: selectedDate })
      .then(r => setHistorySessions(Array.isArray(r.data) ? r.data : []))
      .catch(err => setHistoryError(getErrorDetail(err, "Erreur lors du chargement de l'historique des fournées.")))
      .finally(() => setHistoryLoading(false));
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [viewNode, user?.node, selectedDate, historyTick]);

  const handleInventoryCount = async () => {
    setCountError(null);
    const entries = Object.entries(countValues).filter(([, v]) => v !== '');
    if (entries.length === 0) { setCountError('Saisissez au moins une quantité physique.'); return; }
    setCountSubmitting(true);
    const today = getWorkDate();
    const nodeId = viewNode || user?.node || '';
    try {
      await Promise.all(entries.map(([ct, qty]) =>
        productionApi.counts.create({
          node: nodeId,
          consumable_type: ct,
          count_date: today,
          physical_quantity: qty,
          notes: '',
        })
      ));
      setCountValues({});
      const r = await productionApi.counts.list({ node: nodeId });
      setLastCounts(Array.isArray(r.data) ? r.data : []);
    } catch (err: unknown) {
      setCountError(getErrorDetail(err, 'Erreur lors du comptage.'));
    } finally {
      setCountSubmitting(false);
    }
  };

  const handleAppro = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (approSaving) return;
    setApproError(null);
    if (!approStock) { setApproError('Sélectionnez un consommable.'); return; }
    if (!approQty || parseFloat(approQty) <= 0) { setApproError('Quantité invalide.'); return; }
    setApproSaving(true);
    try {
      await productionApi.movements.create({
        stock: approStock, movement_type: 'ENTRY',
        quantity: approQty,
        unit_price: approPrice || '0',
        supplier: approSupplier,
        description: approDesc || 'Approvisionnement',
      });
      setApproStock(''); setApproQty(''); setApproPrice(''); setApproDesc(''); setApproSupplier('');
      setShowApproModal(false);
      await loadData();
    } catch (err: unknown) {
      setApproError(getErrorDetail(err, 'Erreur.'));
    } finally {
      setApproSaving(false);
    }
  };

  const handleCreateTransfer = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (tSending) return;
    setTError(null);
    setTSuccess(null);
    if (!user?.node) { setTError('Compte non assigné à une boulangerie.'); return; }
    if (!tFromNode) { setTError('Sélectionnez la boulangerie à qui vous faites la demande.'); return; }
    const lines = Object.entries(tLines)
      .filter(([, qty]) => qty > 0)
      .map(([bp_id, qty]) => ({ bread_price: Number(bp_id), quantity_sent: qty }));
    if (lines.length === 0) { setTError('Indiquez au moins une quantité de pain demandée.'); return; }
    setTSending(true);
    try {
      // from_node = the supplier (tFromNode), to_node = user's own node (set server-side)
      await productionApi.transfers.create({ from_node: tFromNode, notes: tNotes, lines });
      const total = lines.reduce((sum, l) => sum + l.quantity_sent, 0);
      const target = nodes.find(n => String(n.id) === tFromNode);
      setTSuccess(`Demande envoyée à ${target ? `${target.code} — ${target.name}` : 'la boulangerie sollicitée'} : ${total} pain${total > 1 ? 's' : ''} demandé${total > 1 ? 's' : ''} — en attente de réponse.`);
      setTFromNode(''); setTLines({}); setTNotes('');
      await loadData();
    } catch (err: unknown) {
      setTError(getErrorDetail(err, 'Erreur.'));
    } finally {
      setTSending(false);
    }
  };

  // B (from_node) responds to A's request — approved=true sends quantities, false rejects
  const handleRespondToTransfer = async (transferId: string, approved: boolean) => {
    const transfer = transfers.find(t => t.id === transferId);
    if (!transfer) return;
    setTransferActionError(null); setTransferNotice(null);
    if (approved) {
      const qtys = respondQtys[transferId] || {};
      const lines = (transfer.lines || []).map(line => ({
        bread_price: line.bread_price,
        quantity_sent: qtys[line.bread_price] ?? line.quantity_sent,
      }));
      try {
        await productionApi.transfers.respond(transferId, true, lines);
        await loadData();
      } catch (err: unknown) { setTransferActionError(getErrorDetail(err, "Impossible d'envoyer les pains.")); }
    } else {
      try {
        await productionApi.transfers.respond(transferId, false);
        await loadData();
      } catch (err: unknown) { setTransferActionError(getErrorDetail(err, 'Impossible de refuser la demande.')); }
    }
  };

  // A (to_node) confirms receipt of bread from B
  const handleConfirmReceipt = async (transferId: string) => {
    const transfer = transfers.find(t => t.id === transferId);
    if (!transfer) return;
    setTransferActionError(null); setTransferNotice(null);
    const qtys = confirmQtys[transferId] || {};
    const lines = (transfer.lines || []).map(line => ({
      bread_price: line.bread_price,
      quantity_received: qtys[line.bread_price] ?? line.quantity_sent,
    }));
    try {
      await productionApi.transfers.confirm(transferId, lines);
      await loadData();
    } catch (err: unknown) { setTransferActionError(getErrorDetail(err, 'Impossible de confirmer la réception.')); }
  };

  const handleDisposal = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setDError(null);
    if (!user?.node) { setDError('Compte non assigné.'); return; }
    if (!dSession) { setDError('Sélectionnez la session de production liée.'); return; }
    if (!dBreadPrice || dQty <= 0) { setDError('Remplissez les champs obligatoires.'); return; }
    try {
      await productionApi.disposals.create({
        session: dSession,
        bread_price: Number(dBreadPrice), disposal_type: dType,
        quantity: dQty, unit_price_sold: dUnitPrice.toString(), notes: dNotes,
      });
      setDQty(0); setDUnitPrice(0); setDNotes(''); setDSession('');
      await loadData();
    } catch (err: unknown) {
      setDError(getErrorDetail(err, 'Erreur.'));
    }
  };

  const currentNodeLabel = user?.can_access_all_nodes
    ? nodes.find(n => String(n.id) === viewNode)?.code
    : undefined;

  // BUG-243 : les identifiants de boulangerie sont comparés en chaîne (l'API peut renvoyer un
  // entier, le <select> renvoie toujours une chaîne).
  const effectiveNode  = String(viewNode || user?.node || '');
  const isNode = (id: string | number | null | undefined) => String(id ?? '') === effectiveNode;
  const hasLowStock    = stocks.some(s => parseFloat(s.quantity) < 10);
  // B (from_node) sees PENDING requests — bread is being requested FROM them
  const pendingRequests  = transfers.filter(t => t.transfer_status === 'PENDING' && (!effectiveNode || isNode(t.from_node)));
  // A (to_node) sees RESPONDED transfers — B confirmed quantity, A must confirm receipt
  const respondedToMe    = transfers.filter(t => t.transfer_status === 'RESPONDED' && (!effectiveNode || isNode(t.to_node)));
  const disputedTrans    = transfers.filter(t => t.transfer_status === 'DISPUTED' && (!effectiveNode || isNode(t.from_node) || isNode(t.to_node)));
  const actionCount      = pendingRequests.length + respondedToMe.length;
  // BUG-382 : mes envois directs encore à valider par la réceptrice (lecture seule).
  const outgoingDirect    = transfers.filter(t => t.flow === 'DIRECT' && t.transfer_status === 'RESPONDED' && isNode(t.from_node));
  const canDirectSend     = !!user && user.role !== 'FACTURIER' && user.role !== 'LIVREUR';

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '18px', fontSize: '0.85rem' }}>

      {/* Header */}
      <div className="glass-card animate-fade-in" style={{ background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)', borderLeft: '4px solid hsl(var(--accent-color))', padding: '14px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '2px' }}>Production, Stocks & Transferts</h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem' }}>
              Déclaration fournée · Rendement théorique · Approvisionnements · Transferts inter-boulangeries · Réconciliation
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            {user?.can_access_all_nodes && (
              <select
                value={viewNode}
                onChange={e => setViewNode(e.target.value)}
                className="form-input"
                style={{ height: '32px', fontSize: '0.75rem', minWidth: '160px' }}
              >
                {nodes.map(n => (
                  <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                ))}
              </select>
            )}
            {hasLowStock && <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', fontSize: '1.4rem' }} />}
            {actionCount > 0 && (
              <span className="badge badge-warning" style={{ fontSize: '0.65rem' }}>
                {actionCount} transfert{actionCount > 1 ? 's' : ''} à traiter
              </span>
            )}
            <button onClick={() => loadData(viewNode || undefined)} disabled={isLoading} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}>
              <FiRefreshCw style={{ animation: isLoading ? 'spin 1s linear infinite' : 'none' }} />
              <span>Actualiser</span>
            </button>
          </div>
        </div>
      </div>

      {/* KPI bar */}
      <div className="kpi-grid" style={{ gap: '12px' }}>
        {[
          { label: 'FOURNÉES ENREGISTRÉES', value: sessionTotals ? sessionTotals.count.toLocaleString('fr-FR') : '…', icon: '🔥', color: 'var(--accent-color)' },
          {
            label: 'VALEUR FC PRODUITE', icon: '💰', color: 'var(--color-success)',
            value: sessionTotals ? sessionTotals.totalFc.toLocaleString('fr-FR') + ' FC' : '…',
          },
          { label: 'TRANSFERTS EN ATTENTE', value: actionCount, icon: '🚚', color: actionCount > 0 ? 'var(--color-warning)' : 'var(--text-muted)' },
          { label: 'PAINS NON VALORISÉS', value: todayDispoQty.toLocaleString('fr-FR'), icon: '📦', color: todayDispoQty > 0 ? 'var(--color-warning)' : 'var(--text-muted)' },
        ].map((k, i) => (
          <div key={i} className="glass-card" style={{ padding: '10px 12px', display: 'flex', alignItems: 'center', gap: '10px' }}>
            <span style={{ fontSize: '1.4rem' }}>{k.icon}</span>
            <div>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>{k.label}</div>
              <div style={{ fontSize: '1rem', fontWeight: 800, color: `hsl(${k.color})` }}>{k.value}</div>
            </div>
          </div>
        ))}
      </div>

      {/* ═══ BUG-094 — Onglets de navigation ═══ */}
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        <button onClick={() => setActiveTab('fournees')} className={`btn ${activeTab === 'fournees' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '7px 16px', fontSize: '0.78rem', height: '36px', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <FiGrid /><span>Fournées</span>
        </button>
        <button onClick={() => setActiveTab('intrants')} className={`btn ${activeTab === 'intrants' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '7px 16px', fontSize: '0.78rem', height: '36px', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <FiPackage /><span>Intrants</span>
          {hasLowStock && <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
        </button>
        <button onClick={() => setActiveTab('transferts')} className={`btn ${activeTab === 'transferts' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '7px 16px', fontSize: '0.78rem', height: '36px', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <FiTruck /><span>Transferts</span>
          {actionCount > 0 && <span className="badge badge-warning" style={{ fontSize: '0.6rem' }}>{actionCount}</span>}
        </button>
        <button onClick={() => setActiveTab('reconciliation')} className={`btn ${activeTab === 'reconciliation' ? 'btn-primary' : 'btn-secondary'}`} style={{ padding: '7px 16px', fontSize: '0.78rem', height: '36px', display: 'flex', alignItems: 'center', gap: '5px' }}>
          <FiCheckCircle /><span>Réconciliation</span>
        </button>
      </div>

      {/* ═══ §3.2 — INTRANTS (Stocks Consommables) ═══ BUG-094 : libellé explicite demandé par le client */}
      {activeTab === 'intrants' && <IntrantsTab stocks={stocks} isLoading={isLoading} setShowApproModal={setShowApproModal} countValues={countValues} setCountValues={setCountValues} countError={countError} countSubmitting={countSubmitting} lastCounts={lastCounts} user={user} currentNodeLabel={currentNodeLabel} hasLowStock={hasLowStock} handleInventoryCount={handleInventoryCount} />}

      {/* ═══ §3.1 — FOURNÉES (Déclaration & Historique) ═══ */}
      {activeTab === 'fournees' && <FourneesTab breadStocks={breadStocks} sacValueFc={sacValueFc} viewNode={viewNode} setShowAllSessionsModal={setShowAllSessionsModal} setSelectedSession={setSelectedSession} setSessionNotes={setSessionNotes} serviceTeam={serviceTeam} setServiceTeam={setServiceTeam} historySessions={historySessions} historyLoading={historyLoading} historyError={historyError} setHistoryTick={setHistoryTick} user={user} workDate={workDate} rotationActive={rotationActive} selectedDate={selectedDate} setSelectedDate={setSelectedDate} currentNodeLabel={currentNodeLabel} loadData={loadData} />}

      {/* ═══ §3.2b — Intrants : Achats Farine (DIRECTION uniquement) ═══ */}
      {activeTab === 'intrants' && user?.can_access_all_nodes && <FlourHistoryCard viewNode={viewNode} flourHistory={flourHistory} setFlourHistory={setFlourHistory} flourLoading={flourLoading} setFlourLoading={setFlourLoading} />}

      {/* ═══ §3.3 — TRANSFERTS INTER-BOULANGERIES ═══ */}
      {activeTab === 'transferts' && <TransfersTab transfers={transfers} nodes={nodes} breadPrices={breadPrices} tFromNode={tFromNode} setTFromNode={setTFromNode} tLines={tLines} setTLines={setTLines} tNotes={tNotes} setTNotes={setTNotes} tError={tError} tSending={tSending} tSuccess={tSuccess} setTSuccess={setTSuccess} transferNotice={transferNotice} setTransferNotice={setTransferNotice} setShowDirectSend={setShowDirectSend} directNotice={directNotice} setDirectNotice={setDirectNotice} transferActionError={transferActionError} setTransferActionError={setTransferActionError} respondQtys={respondQtys} setRespondQtys={setRespondQtys} confirmQtys={confirmQtys} setConfirmQtys={setConfirmQtys} user={user} effectiveNode={effectiveNode} isNode={isNode} pendingRequests={pendingRequests} respondedToMe={respondedToMe} disputedTrans={disputedTrans} outgoingDirect={outgoingDirect} canDirectSend={canDirectSend} loadData={loadData} handleCreateTransfer={handleCreateTransfer} handleRespondToTransfer={handleRespondToTransfer} handleConfirmReceipt={handleConfirmReceipt} />}

      {/* ═══ §3.4 — RÉCONCILIATION & PAINS NON VALORISÉS ═══ */}
      {activeTab === 'reconciliation' && <ReconciliationTab sessions={sessions} disposals={disposals} nodes={nodes} breadPrices={breadPrices} dSession={dSession} setDSession={setDSession} dType={dType} setDType={setDType} dBreadPrice={dBreadPrice} setDBreadPrice={setDBreadPrice} dQty={dQty} setDQty={setDQty} dNotes={dNotes} setDNotes={setDNotes} dError={dError} user={user} workDate={workDate} effectiveNode={effectiveNode} handleDisposal={handleDisposal} />}

      {/* ═══ MODAL VOIR PLUS — Toutes les fournées ═══ */}
      <DirectSendModal
        isOpen={showDirectSend}
        onClose={() => setShowDirectSend(false)}
        nodes={nodes}
        senderNodeId={effectiveNode}
        breadPrices={breadPrices}
        breadStocks={breadStocks}
        onSent={async (msg) => { setDirectNotice(msg); await loadData(); }}
      />

      <AllSessionsModal showAllSessionsModal={showAllSessionsModal} setShowAllSessionsModal={setShowAllSessionsModal} setSelectedSession={setSelectedSession} setSessionNotes={setSessionNotes} historySessions={historySessions} />

      {/* ═══ MODAL DÉTAIL FOURNÉE — avec commentaires ═══ */}
      {selectedSession && <SessionDetailModal selectedSession={selectedSession} setSelectedSession={setSelectedSession} sessionNotes={sessionNotes} setSessionNotes={setSessionNotes} savingNotes={savingNotes} setSavingNotes={setSavingNotes} setCloseSessionModalOpen={setCloseSessionModalOpen} setHistorySessions={setHistorySessions} />}

      {/* ═══ MODAL CLÔTURE — Reste du Jour par catégorie (BUG-154) ═══ */}
      <CloseSessionModal
        isOpen={closeSessionModalOpen}
        session={selectedSession}
        onClose={() => setCloseSessionModalOpen(false)}
        onClosed={(updated) => {
          setHistorySessions(prev => prev.map(s => s.id === updated.id ? updated : s));
          setSelectedSession(updated);
          setSessionNotes(updated.notes || '');
          setHistoryTick(t => t + 1);
          void loadData();
        }}
      />

      {/* ═══ MODAL APPROVISIONNEMENT ═══ */}
      <ApproModal stocks={stocks} showApproModal={showApproModal} setShowApproModal={setShowApproModal} approStock={approStock} setApproStock={setApproStock} approQty={approQty} setApproQty={setApproQty} approPrice={approPrice} setApproPrice={setApproPrice} approDesc={approDesc} setApproDesc={setApproDesc} approSupplier={approSupplier} setApproSupplier={setApproSupplier} approError={approError} approSaving={approSaving} handleAppro={handleAppro} />

    </div>
  );
};
