import React, { useState, useEffect, useCallback } from 'react';
import axios from 'axios';
import {
  FiGrid, FiPlus, FiAlertTriangle, FiArrowRight, FiCheckCircle,
  FiRefreshCw, FiPackage, FiTruck, FiX
} from 'react-icons/fi';
import {
  productionApi, coreApi, ConsumableStock, ConsumableCount, FlourHistoryEntry,
  ProductionSession, BreadTransfer, BreadDisposal, BreadStock, BakeryNode, BreadPrice
} from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useAuthStore } from '@/store/authStore';
import { Modal } from '@/components/shared/Modal';
import { ReconciliationPanel, ClosureSummaryCard } from '@/components/production/ReconciliationPanel';
import { StockDuJourSection } from '@/components/production/StockDuJourSection';
import { OpeningConfirmationManualSection } from '@/components/production/OpeningConfirmationManualSection';
import { CloseSessionModal } from '@/components/production/CloseSessionModal';

const STOCK_ICONS: Record<string, string> = { FLOUR: '🌾', YEAST: '💥', SALT: '🧂', OIL: '💧' };

const formatFC = (n: number) => n.toLocaleString('fr-FR') + ' FC';
const displayStock = (s: string) => (s || '').replace(/\s*\(Sac \d+\s*kg\)/i, '').trim() || s;
const todayIso = (): string => new Date().toISOString().slice(0, 10);

const DISPOSAL_LABELS: Record<string, string> = {
  SOLD_DISCOUNT: 'Pains Soldés',
  DECLASSED:     'Pains Déclassés (non conformes)',
  UNSOLD:        'Pains Invendus (perte sèche)',
  FREE_DIST:     'Sorties gratuite (NV)',
  REMAINING:     'Stock Restant',
};
// BUG-092/BUG-096 (volet frontend) : le backend refuse désormais la création d'un nouveau
// BreadDisposal de type SOLD_DISCOUNT (la vente soldée se fait dans Facturation/Gestion
// Clientèle via `Invoice.is_soldee`, avec calcul de la perte). On ne retire SOLD_DISCOUNT que
// de la liste proposée pour une NOUVELLE saisie — les entrées historiques déjà créées avec ce
// type restent affichées normalement via DISPOSAL_LABELS/DISPOSAL_COLORS (non filtrées).
const DISPOSAL_CREATE_LABELS: Record<string, string> = Object.fromEntries(
  Object.entries(DISPOSAL_LABELS).filter(([k]) => k !== 'SOLD_DISCOUNT')
);
// BUG-050 : POST /api/production/sessions/ et /api/production/movements/ renvoient
// désormais ce message distinct (BUG-041) quand une sortie de consommable dépasserait
// le stock disponible — affiché avec une icône dédiée plutôt que comme une erreur générique.
const isStockInsufficientError = (msg: string | null) => !!msg && /stock insuffisant/i.test(msg);

const DISPOSAL_COLORS: Record<string, string> = {
  SOLD_DISCOUNT: 'var(--color-info)',
  DECLASSED:     'var(--color-warning)',
  UNSOLD:        'var(--color-danger)',
  FREE_DIST:     'var(--color-success)',
  REMAINING:     'var(--accent-color)',
};

export const Production: React.FC = () => {
  const { user } = useAuthStore();

  const [stocks, setStocks]           = useState<ConsumableStock[]>([]);
  const [breadStocks, setBreadStocks] = useState<BreadStock[]>([]);
  const [sessions, setSessions]       = useState<ProductionSession[]>([]);
  const [transfers, setTransfers]     = useState<BreadTransfer[]>([]);
  const [disposals, setDisposals]     = useState<BreadDisposal[]>([]);
  const [nodes, setNodes]             = useState<BakeryNode[]>([]);
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
  const [sacValueFc, setSacValueFc]   = useState(200000);
  const [isLoading, setIsLoading]     = useState(true);

  // Direction Générale (multi-node access) must pick one branch to view —
  // stocks/sessions are otherwise mixed across all 8 bakeries with no indication.
  const [viewNode, setViewNode]       = useState('');

  // BUG-094 : onglets explicites (la section « Intrants » existait déjà mais était noyée
  // au milieu d'une page de 1500+ lignes sans libellé visible pour le client).
  const [activeTab, setActiveTab] = useState<'fournees' | 'intrants' | 'transferts' | 'reconciliation'>('fournees');

  // §3.1 Production form — quantities keyed by BreadPrice.id (integer)
  const [selTeam, setSelTeam]         = useState<'A' | 'B'>('A');
  const [flourSacks, setFlourSacks]   = useState(4);
  const [quantities, setQuantities]   = useState<Record<number, number>>({});
  const [prodError, setProdError]     = useState<string | null>(null);
  const [consumablesUsed, setConsumablesUsed] = useState<Record<string, string>>({ SALT: '', YEAST: '', OIL: '' });
  const [showAllSessionsModal, setShowAllSessionsModal] = useState(false);
  const [selectedSession, setSelectedSession] = useState<ProductionSession | null>(null);
  const [sessionNotes, setSessionNotes] = useState('');
  const [savingNotes, setSavingNotes] = useState(false);
  // BUG-108 : clôture automatisée de la fournée (POST .../close/)
  // BUG-154 : la clôture elle-même (avec saisie du « Reste du Jour » par catégorie) se fait
  // désormais dans CloseSessionModal, qui gère son propre état de soumission/erreur.
  const [closeSessionModalOpen, setCloseSessionModalOpen] = useState(false);
  const [selectedBreadStock, setSelectedBreadStock] = useState<BreadStock | null>(null);
  // BUG-145 (remarque.md l.397) : un seul sélecteur de date pilote « Stock Pains du Jour »
  // ET « Historique des Fournées ». `sessions` (KPI, formulaire de sortie non standard —
  // filtré à "aujourd'hui" indépendamment de ce sélecteur) reste intentionnellement
  // inchangé ; seul l'affichage de l'historique des fournées utilise `historySessions`.
  const [selectedDate, setSelectedDate] = useState(todayIso());
  const [historySessions, setHistorySessions] = useState<ProductionSession[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState<string | null>(null);

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

  const loadData = useCallback(async (nodeFilter?: string) => {
    setIsLoading(true);
    try {
      const scopedParams = nodeFilter ? { node: nodeFilter } : undefined;
      const [stockRes, sessionRes, transferRes, disposalRes, nodeRes, bpRes, configRes, breadStockRes] = await Promise.all([
        productionApi.stocks.list(scopedParams),
        productionApi.sessions.list(scopedParams),
        productionApi.transfers.list(),
        productionApi.disposals.list(scopedParams),
        coreApi.nodes.list(),
        coreApi.breadPrices.list(),
        coreApi.config.get(),
        productionApi.breadStocks.list(scopedParams),
      ]);
      setStocks(Array.isArray(stockRes.data) ? stockRes.data : []);
      setBreadStocks(Array.isArray(breadStockRes.data) ? breadStockRes.data : []);
      setSessions(Array.isArray(sessionRes.data) ? sessionRes.data.slice(0, 15) : []);
      setTransfers(Array.isArray(transferRes.data) ? transferRes.data : []);
      setDisposals(Array.isArray(disposalRes.data) ? disposalRes.data.slice(0, 20) : []);
      const nodeList = Array.isArray(nodeRes.data) ? nodeRes.data : [];
      setNodes(nodeList);
      const activePrices = Array.isArray(bpRes.data) ? bpRes.data.filter(b => b.is_active) : [];
      setBreadPrices(activePrices);
      // Per-node sac_value_fc takes priority; fall back to global Config if absent or zero.
      const activeNodeId = nodeFilter || user?.node || null;
      const activeNode = activeNodeId ? nodeList.find(n => n.id === activeNodeId) : null;
      const nodeSacVal = activeNode?.sac_value_fc ? parseFloat(activeNode.sac_value_fc) : 0;
      setSacValueFc(nodeSacVal > 0 ? nodeSacVal : (configRes.data.sac_value_fc ?? 200000));
      const initRespond: Record<string, Record<number, number>> = {};
      const initConfirm: Record<string, Record<number, number>> = {};
      (Array.isArray(transferRes.data) ? transferRes.data : []).forEach((t: BreadTransfer) => {
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
      console.error('Failed to load production data', err);
    } finally {
      setIsLoading(false);
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
            setViewNode(nodeList[0].id); // triggers the viewNode effect below → loadData(firstNode)
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
  }, [viewNode, user?.node, selectedDate]);

  const handleInventoryCount = async () => {
    setCountError(null);
    const entries = Object.entries(countValues).filter(([, v]) => v !== '');
    if (entries.length === 0) { setCountError('Saisissez au moins une quantité physique.'); return; }
    setCountSubmitting(true);
    const today = new Date().toISOString().split('T')[0];
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

  // §3.1 Rendement monétaire (en FC)
  const totalBreads   = breadPrices.reduce((s, bp) => s + (quantities[bp.id] || 0), 0);
  const totalFcProd   = breadPrices.reduce((s, bp) => s + (quantities[bp.id] || 0) * bp.unit_price, 0);
  const theoreticalFc = flourSacks * sacValueFc;
  const ecartFc       = totalFcProd - theoreticalFc;
  const rendementPct  = theoreticalFc > 0 ? (totalFcProd / theoreticalFc) * 100 : 0;
  const rendementColor = rendementPct >= 90 ? 'var(--color-success)' : rendementPct >= 75 ? 'var(--color-warning)' : 'var(--color-danger)';

  const handleAddSession = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setProdError(null);
    if (!user?.node) { setProdError('Compte non assigné à une boulangerie.'); return; }
    if (flourSacks <= 0) { setProdError('Indiquez le nombre de sacs de farine.'); return; }
    const lines = breadPrices
      .filter(bp => (quantities[bp.id] || 0) > 0)
      .map(bp => ({ bread_price: bp.id, quantity: quantities[bp.id] }));
    if (lines.length === 0) { setProdError('Déclarez au moins une catégorie de pains.'); return; }
    try {
      const consumablesPayload = Object.entries(consumablesUsed)
        .filter(([, qty]) => qty !== '' && parseFloat(qty.replace(',', '.')) > 0)
        .map(([ct, qty]) => ({ consumable_type: ct, quantity: parseFloat(qty.replace(',', '.')) }));
      await productionApi.sessions.create({
        flour_sacks_used: flourSacks.toString(),
        date: new Date().toISOString().split('T')[0],
        team: selTeam,
        lines,
        consumables_used: consumablesPayload,
      });
      setQuantities({});
      setConsumablesUsed({ SALT: '', YEAST: '', OIL: '' });
      await loadData();
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { detail?: string; non_field_errors?: string[] } | undefined)
        : undefined;
      setProdError(d?.detail || d?.non_field_errors?.[0] || (d ? JSON.stringify(d) : undefined) || 'Erreur.');
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
    setTError(null);
    if (!user?.node) { setTError('Compte non assigné à une boulangerie.'); return; }
    if (!tFromNode) { setTError('Sélectionnez la boulangerie à qui vous faites la demande.'); return; }
    const lines = Object.entries(tLines)
      .filter(([, qty]) => qty > 0)
      .map(([bp_id, qty]) => ({ bread_price: Number(bp_id), quantity_sent: qty }));
    if (lines.length === 0) { setTError('Indiquez au moins une quantité de pain demandée.'); return; }
    try {
      // from_node = the supplier (tFromNode), to_node = user's own node (set server-side)
      await productionApi.transfers.create({ from_node: tFromNode, notes: tNotes, lines });
      setTFromNode(''); setTLines({}); setTNotes('');
      await loadData();
    } catch (err: unknown) {
      setTError(getErrorDetail(err, 'Erreur.'));
    }
  };

  // B (from_node) responds to A's request — approved=true sends quantities, false rejects
  const handleRespondToTransfer = async (transferId: string, approved: boolean) => {
    const transfer = transfers.find(t => t.id === transferId);
    if (!transfer) return;
    if (approved) {
      const qtys = respondQtys[transferId] || {};
      const lines = (transfer.lines || []).map(line => ({
        bread_price: line.bread_price,
        quantity_sent: qtys[line.bread_price] ?? line.quantity_sent,
      }));
      try {
        await productionApi.transfers.respond(transferId, true, lines);
        await loadData();
      } catch (err) { console.error('Respond to transfer failed', err); }
    } else {
      try {
        await productionApi.transfers.respond(transferId, false);
        await loadData();
      } catch (err) { console.error('Reject transfer failed', err); }
    }
  };

  // A (to_node) confirms receipt of bread from B
  const handleConfirmReceipt = async (transferId: string) => {
    const transfer = transfers.find(t => t.id === transferId);
    if (!transfer) return;
    const qtys = confirmQtys[transferId] || {};
    const lines = (transfer.lines || []).map(line => ({
      bread_price: line.bread_price,
      quantity_received: qtys[line.bread_price] ?? line.quantity_sent,
    }));
    try {
      await productionApi.transfers.confirm(transferId, lines);
      await loadData();
    } catch (err) { console.error('Confirm receipt failed', err); }
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
    ? nodes.find(n => n.id === viewNode)?.code
    : undefined;

  const effectiveNode  = viewNode || user?.node || '';
  const hasLowStock    = stocks.some(s => parseFloat(s.quantity) < 10);
  // B (from_node) sees PENDING requests — bread is being requested FROM them
  const pendingRequests  = transfers.filter(t => t.transfer_status === 'PENDING' && (!effectiveNode || t.from_node === effectiveNode));
  // A (to_node) sees RESPONDED transfers — B confirmed quantity, A must confirm receipt
  const respondedToMe    = transfers.filter(t => t.transfer_status === 'RESPONDED' && (!effectiveNode || t.to_node === effectiveNode));
  const disputedTrans    = transfers.filter(t => t.transfer_status === 'DISPUTED' && (!effectiveNode || t.from_node === effectiveNode || t.to_node === effectiveNode));
  const actionCount      = pendingRequests.length + respondedToMe.length;
  const todayDispoQty  = disposals.filter(d => d.created_at?.startsWith(new Date().toISOString().split('T')[0])).reduce((a, d) => a + (d.quantity || 0), 0);

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
          { label: 'FOURNÉES ENREGISTRÉES', value: sessions.length, icon: '🔥', color: 'var(--accent-color)' },
          {
            label: 'VALEUR FC PRODUITE', icon: '💰', color: 'var(--color-success)',
            value: sessions.reduce((a, s) => a + (s.total_fc_produced || 0), 0).toLocaleString('fr-FR') + ' FC',
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
      {activeTab === 'intrants' && (
        <div className="glass-card" style={{ padding: '14px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 800 }}>
              Intrants — Stocks Consommables (§3.2)
              {currentNodeLabel && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>{currentNodeLabel}</span>}
            </h2>
            {user?.can_access_all_nodes && (
              <button onClick={() => setShowApproModal(true)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
                <FiPlus /> Approvisionner
              </button>
            )}
          </div>
          {isLoading ? (
            <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Chargement...</div>
          ) : (
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                  <th>Intrant</th><th style={{ textAlign: 'right' }}>Qté</th><th>Unité</th>
                  <th style={{ textAlign: 'right' }} title="Coût Unitaire Moyen Pondéré, recalculé à chaque entrée de stock">CUMP</th>
                  <th style={{ textAlign: 'center' }}>Statut</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {stocks.map(st => {
                  const qty = parseFloat(st.quantity);
                  const isLow = qty < 10;
                  const cump = st.average_unit_cost != null ? parseFloat(st.average_unit_cost) : null;
                  return (
                    <tr key={st.id}>
                      <td style={{ fontWeight: 700 }}>{STOCK_ICONS[st.consumable_type] || '📦'} {displayStock(st.consumable_type_display || st.consumable_type)}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: isLow ? 'hsl(var(--color-danger))' : undefined }}>{qty}</td>
                      <td style={{ color: 'hsl(var(--text-muted))' }}>{st.unit}</td>
                      <td
                        style={{ textAlign: 'right', color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}
                        title="Coût Unitaire Moyen Pondéré (CUMP) : coût d'achat moyen par unité, recalculé à chaque entrée de stock. Utilisé pour valoriser la consommation réelle au Compte de Résultat."
                      >
                        {cump != null ? `${cump.toLocaleString('fr-FR')} FC` : '—'}
                      </td>
                      <td style={{ textAlign: 'center' }}>
                        <span className={`badge ${isLow ? 'badge-danger' : 'badge-success'}`} style={{ fontSize: '0.5rem' }}>{isLow ? 'ALERTE' : 'OK'}</span>
                      </td>
                    </tr>
                  );
                })}
                {stocks.length === 0 && <tr><td colSpan={5} style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))' }}>Aucun stock</td></tr>}
              </tbody>
            </table>
          )}
          {hasLowStock && (
            <div style={{ marginTop: '10px', backgroundColor: 'hsl(var(--color-danger) / 0.08)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', display: 'flex', gap: '8px', alignItems: 'center' }}>
              <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))', flexShrink: 0 }} />
              <div>
                <strong style={{ fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>Alerte Stock Critique</strong>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))' }}>Approvisionnement urgent requis</div>
              </div>
            </div>
          )}

          {/* ── Inventaire physique (non-FLOUR) ── */}
          {stocks.filter(s => s.consumable_type !== 'FLOUR').length > 0 && (
            <div style={{ marginTop: '14px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '12px' }}>
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '8px' }}>
                Inventaire Physique
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                {stocks.filter(s => s.consumable_type !== 'FLOUR').map(st => {
                  const lastCount = lastCounts
                    .filter(c => c.consumable_type === st.consumable_type)
                    .sort((a, b) => b.count_date.localeCompare(a.count_date))[0];
                  const gap = lastCount ? parseFloat(lastCount.gap) : null;
                  return (
                    <div key={st.id} style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.7rem' }}>
                      <span style={{ width: '100px', fontWeight: 700 }}>
                        {STOCK_ICONS[st.consumable_type] || '📦'} {displayStock(st.consumable_type_display || st.consumable_type)}
                      </span>
                      <input
                        type="number" step="any" min={0}
                        placeholder={`Sys: ${parseFloat(st.quantity)}`}
                        value={countValues[st.consumable_type] || ''}
                        onChange={e => setCountValues(prev => ({ ...prev, [st.consumable_type]: e.target.value }))}
                        className="form-input"
                        style={{ width: '80px', height: '26px', fontSize: '0.7rem', padding: '0 6px' }}
                      />
                      <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.62rem' }}>{st.unit}</span>
                      {gap !== null && (
                        <span style={{ fontSize: '0.62rem', fontWeight: 700, color: gap < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                          {gap < 0 ? `Écart: ${gap}` : `OK (${lastCount!.count_date})`}
                        </span>
                      )}
                    </div>
                  );
                })}
              </div>
              {countError && (
                <div style={{ marginTop: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>{countError}</div>
              )}
              <button
                onClick={handleInventoryCount}
                disabled={countSubmitting || Object.keys(countValues).length === 0}
                className="btn btn-secondary"
                style={{ marginTop: '8px', padding: '4px 12px', fontSize: '0.68rem', width: '100%' }}
              >
                {countSubmitting ? 'Validation...' : 'Valider le Comptage'}
              </button>
            </div>
          )}
        </div>
      )}

      {/* ═══ §3.1 — FOURNÉES (Déclaration & Historique) ═══ */}
      {activeTab === 'fournees' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
          <div className="glass-card" style={{ padding: '14px' }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '12px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiGrid style={{ color: 'hsl(var(--accent-color))' }} /> §3.1 — Déclaration de Fournée
            </h2>
            <form onSubmit={handleAddSession} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Équipe</label>
                  <select value={selTeam} onChange={e => setSelTeam(e.target.value as 'A' | 'B')} className="form-input" style={{ fontSize: '0.75rem', height: '30px' }}>
                    <option value="A">Équipe A</option>
                    <option value="B">Équipe B</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Nbre sac farine consommer *</label>
                  <input type="number" step="0.5" min={0.5} value={flourSacks} onChange={e => setFlourSacks(Number(e.target.value))} className="form-input" style={{ fontSize: '0.75rem', height: '30px', padding: '0 8px' }} />
                </div>
              </div>

              {/* Dynamic bread quantity inputs from BreadPrice API */}
              <div>
                <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '5px', textTransform: 'uppercase' }}>
                  Projection coupe
                  <span style={{ marginLeft: '6px', fontWeight: 400, color: 'hsl(var(--text-muted))' }}>Prix sac = {formatFC(sacValueFc)}</span>
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(breadPrices.length, 4)}, 1fr)`, gap: '6px' }}>
                  {breadPrices.map(bp => (
                    <div key={bp.id}>
                      <div style={{ fontSize: '0.58rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px', textAlign: 'center' }}>{bp.label}</div>
                      <input
                        type="number" min={0}
                        value={quantities[bp.id] || ''}
                        placeholder="0"
                        onChange={e => setQuantities(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) }))}
                        className="form-input"
                        style={{ fontSize: '0.78rem', height: '28px', padding: '0 4px', textAlign: 'center', fontWeight: 700 }}
                      />
                      {quantities[bp.id] > 0 && (
                        <div style={{ fontSize: '0.52rem', textAlign: 'center', color: 'hsl(var(--color-info))', marginTop: '1px' }}>
                          = {((quantities[bp.id] || 0) * bp.unit_price).toLocaleString('fr-FR')} FC
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* §3.1 Rendement monétaire — calcul automatique en FC */}
              {totalBreads > 0 && flourSacks > 0 && (
                <div style={{ backgroundColor: `hsl(${rendementColor} / 0.06)`, border: `1px solid hsl(${rendementColor} / 0.35)`, borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                  <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '8px' }}>
                    Rendement Monétaire (§3.1) — Valeur FC produite vs théorique
                  </div>
                  {/* Main KPIs */}
                  <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '8px', fontSize: '0.7rem', marginBottom: '8px' }}>
                    <div>
                      <div style={{ color: 'hsl(var(--text-secondary))' }}>Valeur réelle</div>
                      <div style={{ fontWeight: 800, color: `hsl(${rendementColor})`, fontSize: '0.82rem' }}>{formatFC(totalFcProd)}</div>
                    </div>
                    <div>
                      <div style={{ color: 'hsl(var(--text-secondary))' }}>Théorique ({flourSacks} sacs)</div>
                      <div style={{ fontWeight: 800 }}>{formatFC(theoreticalFc)}</div>
                    </div>
                    <div>
                      <div style={{ color: 'hsl(var(--text-secondary))' }}>Efficacité</div>
                      <div style={{ fontWeight: 800, color: `hsl(${rendementColor})` }}>
                        {rendementPct.toFixed(1)}%
                      </div>
                    </div>
                  </div>
                  {/* Progress bar */}
                  <div style={{ height: '6px', borderRadius: '3px', backgroundColor: 'hsl(var(--border-color))', overflow: 'hidden', marginBottom: '8px' }}>
                    <div style={{ height: '100%', width: `${Math.min(Math.max(rendementPct, 0), 100)}%`, backgroundColor: `hsl(${rendementColor})`, transition: 'width 0.3s ease' }} />
                  </div>
                  {/* Écart manquant / excédent */}
                  <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', borderTop: `1px solid hsl(${rendementColor} / 0.2)`, paddingTop: '8px', marginBottom: '8px' }}>
                    <span style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))' }}>
                      {ecartFc >= 0 ? '▲ EXCÉDENT' : '▼ MANQUANT'}
                    </span>
                    <span style={{ fontSize: '0.9rem', fontWeight: 800, color: ecartFc >= 0 ? `hsl(${rendementColor})` : 'hsl(var(--color-danger))' }}>
                      {ecartFc >= 0 ? '+' : ''}{formatFC(ecartFc)}
                    </span>
                  </div>
                  {/* Breakdown per bread type */}
                  <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(breadPrices.length, 4)}, 1fr)`, gap: '4px', fontSize: '0.6rem' }}>
                    {breadPrices.filter(bp => (quantities[bp.id] || 0) > 0).map(bp => {
                      const qty = quantities[bp.id] || 0;
                      const fcLine = qty * bp.unit_price;
                      return (
                        <div key={bp.id} style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px', padding: '4px 5px' }}>
                          <div style={{ color: 'hsl(var(--text-muted))', fontWeight: 700 }}>{bp.label}</div>
                          <div style={{ fontWeight: 800 }}>{qty} pains</div>
                          <div style={{ color: `hsl(${rendementColor})`, fontWeight: 700 }}>{fcLine.toLocaleString('fr-FR')} FC</div>
                        </div>
                      );
                    })}
                  </div>
                  {/* Equivalences display */}
                  <div style={{ fontSize: '0.58rem', marginTop: '6px', color: 'hsl(var(--text-muted))', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '5px' }}>
                    Équivalences théoriques (1 sac = {formatFC(sacValueFc)}) : &nbsp;
                    {breadPrices.map(bp => `${Math.round(sacValueFc / bp.unit_price)} × ${bp.label}`).join(' = ')}
                  </div>
                </div>
              )}

              {/* Consommables utilisés pendant la fournée */}
              <div style={{ borderTop: '1px solid hsl(var(--border-color))', paddingTop: '10px' }}>
                <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '5px', textTransform: 'uppercase' }}>
                  Consommables Utilisés <span style={{ fontWeight: 400, color: 'hsl(var(--text-muted))' }}>(réduit les stocks)</span>
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: '6px' }}>
                  {[
                    { key: 'SALT',  label: 'Sel',    icon: '🧂', unit: 'g',       step: '1',    placeholder: '500' },
                    { key: 'YEAST', label: 'Levure', icon: '💥', unit: 'paquets', step: '0.01', placeholder: '0.50' },
                    { key: 'OIL',   label: 'Huile',  icon: '💧', unit: 'litres',  step: '0.01', placeholder: '0.25' },
                  ].map(({ key, label, icon, unit, step, placeholder }) => (
                    <div key={key}>
                      <div style={{ fontSize: '0.58rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px', textAlign: 'center' }}>{icon} {label} ({unit})</div>
                      <input
                        type="number" min="0" step={step}
                        value={consumablesUsed[key]}
                        placeholder={placeholder}
                        onChange={e => setConsumablesUsed(prev => ({ ...prev, [key]: e.target.value }))}
                        className="form-input"
                        style={{ fontSize: '0.75rem', height: '28px', padding: '0 6px', textAlign: 'center' }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              {prodError && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
                  {isStockInsufficientError(prodError) && <FiAlertTriangle style={{ flexShrink: 0 }} />}
                  <span>{prodError}</span>
                </div>
              )}
              <button type="submit" className="btn btn-primary" style={{ padding: '6px', fontSize: '0.78rem' }}>Enregistrer la Fournée</button>
            </form>
          </div>

          {/* BUG-151 : accès manuel à la confirmation du reste d'hier pour une AUTRE
              équipe que celle déjà confirmée (même garde de rôle que la boîte modale
              automatique dans DashboardLayout.tsx). */}
          {user && (user.role === 'GERANT' || user.role === 'FACTURIER') && !user.can_access_all_nodes && (
            <OpeningConfirmationManualSection onConfirmed={() => loadData(viewNode || undefined)} />
          )}

          {/* Stock Pains du Jour — BUG-145 : extrait dans StockDuJourSection.tsx, piloté par
              `selectedDate`, qui pilote AUSSI « Historique des Fournées » ci-dessous. */}
          <StockDuJourSection
            selectedDate={selectedDate}
            onSelectDate={setSelectedDate}
            liveBreadStocks={breadStocks}
            nodeFilter={viewNode || undefined}
            currentNodeLabel={currentNodeLabel}
            onSelectBreadStock={setSelectedBreadStock}
          />

          {/* Session history — BUG-145 : filtrée par la même `selectedDate` que ci-dessus. */}
          <div className="glass-card" style={{ padding: '12px 14px' }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 800, marginBottom: '8px' }}>
              Historique des Fournées
              {currentNodeLabel && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginLeft: '8px' }}>{currentNodeLabel}</span>}
            </h3>
            {historyError && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '6px' }}>
                {historyError}
              </div>
            )}
            {historyLoading && (
              <div style={{ textAlign: 'center', padding: '10px', color: 'hsl(var(--text-secondary))', fontSize: '0.68rem' }}>Chargement...</div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              {!historyLoading && historySessions.slice(0, 2).map(sess => {
                const tFC  = sess.total_fc_produced || 0;
                const thFC = sess.theoretical_yield || 0;
                const rPct = thFC > 0 ? (tFC / thFC) * 100 : 0;
                const gap  = sess.yield_gap || 0;
                const rColor = rPct >= 90 ? 'hsl(var(--color-success))' : rPct >= 75 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                return (
                  <div
                    key={sess.id}
                    onClick={() => { setSelectedSession(sess); setSessionNotes(sess.notes || ''); }}
                    style={{ padding: '6px 8px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.68rem', cursor: 'pointer', transition: 'background-color 0.15s' }}
                    onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'hsl(var(--bg-tertiary))')}
                    onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                  >
                    <div>
                      <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{sess.node_display || sess.node}</span>
                      <span style={{ marginLeft: '6px', color: 'hsl(var(--text-secondary))' }}>{sess.date} — Éq.{sess.team}</span>
                      {sess.is_closed && <span className="badge badge-info" style={{ fontSize: '0.55rem', marginLeft: '6px' }}>Clôturée</span>}
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginTop: '1px' }}>
                        {sess.total_breads} pains · {sess.flour_sacks_used} sacs · {tFC.toLocaleString('fr-FR')} FC
                        {sess.notes && <span style={{ marginLeft: '4px', color: 'hsl(var(--accent-color))' }}>💬</span>}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontWeight: 800, fontSize: '0.72rem', color: rColor }}>{rPct.toFixed(0)}%</div>
                      <div style={{ fontSize: '0.55rem', fontWeight: 700, color: gap >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                        {gap >= 0 ? '+' : ''}{gap.toLocaleString('fr-FR')} FC
                      </div>
                    </div>
                  </div>
                );
              })}
              {historySessions.length === 0 && !historyLoading && (
                <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>Aucune fournée ce jour-là</div>
              )}
              {historySessions.length > 2 && (
                <button
                  type="button"
                  onClick={() => setShowAllSessionsModal(true)}
                  style={{ marginTop: '4px', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--accent-color))', background: 'none', border: 'none', cursor: 'pointer', padding: '4px 0', textAlign: 'center' }}
                >
                  ▼ Voir plus ({historySessions.length - 2} autres fournées)
                </button>
              )}
            </div>
          </div>
        </div>
      )}

      {/* ═══ §3.2b — Intrants : Achats Farine (DIRECTION uniquement) ═══ */}
      {activeTab === 'intrants' && user?.can_access_all_nodes && (
        <div className="glass-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
            <h2 style={{ fontSize: '0.88rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              🌾 §3.2b — Historique Achats Farine
            </h2>
            <button
              onClick={() => {
                setFlourLoading(true);
                const nf = viewNode || undefined;
                productionApi.movements.flourHistory(nf ? { node: nf } : undefined)
                  .then(r => setFlourHistory(Array.isArray(r.data) ? r.data : []))
                  .catch(() => {})
                  .finally(() => setFlourLoading(false));
              }}
              className="btn btn-secondary"
              style={{ padding: '4px 10px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '4px' }}
            >
              <FiRefreshCw size={11} /> Actualiser
            </button>
          </div>
          {flourLoading ? (
            <p style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Chargement...</p>
          ) : flourHistory.length === 0 ? (
            <p style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Aucun achat de farine enregistré.</p>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table">
                <thead>
                  <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                    <th style={{ width: '90px' }}>Date</th>
                    <th style={{ width: '60px' }}>Site</th>
                    <th style={{ width: '90px' }}>Fournisseur</th>
                    <th style={{ textAlign: 'right', width: '80px' }}>Sacs</th>
                    <th style={{ textAlign: 'right', width: '110px' }}>PU (FC/sac)</th>
                    <th style={{ textAlign: 'right', width: '120px' }}>Total FC</th>
                    <th>Description</th>
                  </tr>
                </thead>
                <tbody>
                  {flourHistory.map(h => (
                    <tr key={h.id} style={{ fontSize: '0.72rem' }}>
                      <td>{new Date(h.date).toLocaleDateString('fr-FR', { day: '2-digit', month: 'short', year: '2-digit' })}</td>
                      <td><span className="badge badge-info" style={{ fontSize: '0.55rem' }}>{h.node}</span></td>
                      <td style={{ fontWeight: 700 }}>
                        {h.supplier ? <span style={{ color: 'hsl(var(--accent-color))' }}>{h.supplier}</span> : <span style={{ color: 'hsl(var(--text-muted))', fontStyle: 'italic' }}>—</span>}
                      </td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}>{parseFloat(h.quantity)}</td>
                      <td style={{ textAlign: 'right' }}>{parseFloat(h.unit_price) > 0 ? parseFloat(h.unit_price).toLocaleString('fr-FR') : '—'}</td>
                      <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>
                        {parseFloat(h.total_cost) > 0 ? parseFloat(h.total_cost).toLocaleString('fr-FR') : '—'}
                      </td>
                      <td style={{ color: 'hsl(var(--text-secondary))' }}>{h.description || '—'}</td>
                    </tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr style={{ fontSize: '0.68rem', fontWeight: 800, backgroundColor: 'hsl(var(--bg-tertiary))' }}>
                    <td colSpan={3} style={{ padding: '8px 10px', textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>TOTAUX</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>
                      {flourHistory.reduce((a, h) => a + parseFloat(h.quantity), 0)} sacs
                    </td>
                    <td />
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>
                      {flourHistory.reduce((a, h) => a + parseFloat(h.total_cost || '0'), 0).toLocaleString('fr-FR')} FC
                    </td>
                    <td />
                  </tr>
                </tfoot>
              </table>
            </div>
          )}
        </div>
      )}

      {/* ═══ §3.3 — TRANSFERTS INTER-BOULANGERIES ═══ */}
      {activeTab === 'transferts' && (
      <div className="glass-card" style={{ padding: '16px' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FiTruck style={{ color: 'hsl(var(--accent-color))' }} />
          §3.3 — Transferts Inter-Boulangeries (Règle d'Or Comptable)
          {disputedTrans.length > 0 && (
            <span className="badge badge-danger" style={{ fontSize: '0.6rem' }}>{disputedTrans.length} LITIGE{disputedTrans.length > 1 ? 'S' : ''}</span>
          )}
        </h2>
        <div className="split-grid" style={{ '--split-cols': '1fr 1.6fr', gap: '16px' } as React.CSSProperties}>

          {/* STEP 1 — A creates request FROM B */}
          <div>
            <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '4px', color: 'hsl(var(--text-secondary))' }}>Faire une Demande de Pains</h3>
            <p style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '8px' }}>
              Sélectionnez la boulangerie qui vous enverra les pains et indiquez les quantités souhaitées.
            </p>
            <form onSubmit={handleCreateTransfer} style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Demander à *</label>
                <select value={tFromNode} onChange={e => setTFromNode(e.target.value)} className="form-input" style={{ fontSize: '0.73rem', height: '30px' }}>
                  <option value="">— Boulangerie source —</option>
                  {nodes.filter(n => n.id !== (effectiveNode || user?.node)).map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>Quantités demandées par catégorie *</label>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                  {breadPrices.map(bp => (
                    <div key={bp.id} style={{ display: 'grid', gridTemplateColumns: '1fr 80px', gap: '6px', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>{bp.label}</span>
                      <input
                        type="number" min={0}
                        value={tLines[bp.id] || ''}
                        placeholder="0"
                        onChange={e => setTLines(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) }))}
                        className="form-input"
                        style={{ fontSize: '0.73rem', height: '26px', padding: '0 6px', textAlign: 'right' }}
                      />
                    </div>
                  ))}
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Notes</label>
                <input type="text" value={tNotes} onChange={e => setTNotes(e.target.value)} placeholder="Motif, urgence..." className="form-input" style={{ fontSize: '0.72rem', height: '28px', padding: '0 6px' }} />
              </div>
              {tError && <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)' }}>{tError}</div>}
              <button type="submit" className="btn btn-primary" style={{ padding: '6px', fontSize: '0.73rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}>
                <FiArrowRight /> Envoyer la demande
              </button>
            </form>
          </div>

          {/* RIGHT COLUMN — Steps 2 & 3 */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>

            {/* STEP 2 — B (from_node) responds to pending requests */}
            {pendingRequests.length > 0 && (
              <div>
                <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '6px', color: 'hsl(var(--text-secondary))' }}>
                  Demandes à Traiter
                  <span className="badge badge-warning" style={{ marginLeft: '6px', fontSize: '0.55rem' }}>{pendingRequests.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {pendingRequests.map(t => (
                    <div key={t.id} style={{ backgroundColor: 'hsl(var(--color-warning) / 0.05)', border: '1px solid hsl(var(--color-warning) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <div style={{ fontSize: '0.72rem' }}>
                          <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{t.to_node_display || t.to_node}</span>
                          <span style={{ color: 'hsl(var(--text-muted))', margin: '0 4px' }}>demande à</span>
                          <span style={{ fontWeight: 800 }}>{t.from_node_display || t.from_node}</span>
                        </div>
                        <span className="badge badge-warning" style={{ fontSize: '0.52rem' }}>EN ATTENTE</span>
                      </div>
                      {t.notes && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '6px', fontStyle: 'italic' }}>{t.notes}</div>}

                      {/* B fills in qty they can actually send (may differ from what was requested) */}
                      <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', marginBottom: '4px', textTransform: 'uppercase' }}>
                        Quantités demandées → Quantités envoyées
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
                        {(t.lines || []).map(line => {
                          const bQtys = respondQtys[t.id] || {};
                          const sendQty = bQtys[line.bread_price] ?? line.quantity_sent;
                          const hasGap = sendQty !== line.quantity_sent;
                          return (
                            <div key={line.bread_price} style={{ display: 'grid', gridTemplateColumns: '1fr 50px 70px', gap: '6px', alignItems: 'center', fontSize: '0.65rem' }}>
                              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                                {line.bread_price_display || `Pain ${line.unit_price} FC`}
                                <span style={{ marginLeft: '4px', color: 'hsl(var(--text-muted))' }}>demandé: {line.quantity_sent}</span>
                              </span>
                              <input
                                type="number" min={0}
                                value={sendQty}
                                onChange={e => setRespondQtys(prev => ({
                                  ...prev,
                                  [t.id]: { ...(prev[t.id] || {}), [line.bread_price]: Number(e.target.value) }
                                }))}
                                className="form-input"
                                style={{
                                  fontSize: '0.73rem', height: '24px', padding: '0 5px', textAlign: 'right', fontWeight: 800,
                                  borderColor: hasGap ? 'hsl(var(--color-warning) / 0.7)' : 'hsl(var(--color-success) / 0.5)',
                                }}
                              />
                              {hasGap && (
                                <span style={{ fontSize: '0.55rem', color: 'hsl(var(--color-warning))', fontWeight: 700 }}>
                                  ajusté ⚠
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
                        <button
                          onClick={() => handleRespondToTransfer(t.id, true)}
                          className="btn btn-primary"
                          style={{ padding: '5px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                        >
                          <FiCheckCircle /> Envoyer les pains
                        </button>
                        <button
                          onClick={() => handleRespondToTransfer(t.id, false)}
                          className="btn btn-secondary"
                          style={{ padding: '5px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px', color: 'hsl(var(--color-danger))' }}
                        >
                          <FiX /> Pas de stock
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* STEP 3 — A (to_node) confirms receipt of responded transfers */}
            {respondedToMe.length > 0 && (
              <div>
                <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '6px', color: 'hsl(var(--text-secondary))' }}>
                  Réceptions à Confirmer
                  <span className="badge badge-info" style={{ marginLeft: '6px', fontSize: '0.55rem' }}>{respondedToMe.length}</span>
                </h3>
                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                  {respondedToMe.map(t => (
                    <div key={t.id} style={{ backgroundColor: 'hsl(var(--color-info) / 0.05)', border: '1px solid hsl(var(--color-info) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                      <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                        <div style={{ fontSize: '0.72rem' }}>
                          <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{t.from_node_display || t.from_node}</span>
                          <FiArrowRight style={{ margin: '0 4px' }} />
                          <span style={{ fontWeight: 800 }}>{t.to_node_display || t.to_node}</span>
                        </div>
                        <span className="badge badge-info" style={{ fontSize: '0.52rem' }}>RÉCEPTIONNÉ</span>
                      </div>
                      {t.notes && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '6px', fontStyle: 'italic' }}>{t.notes}</div>}

                      <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', marginBottom: '4px', textTransform: 'uppercase' }}>
                        Envoyé par {t.from_node_display || t.from_node} → Quantités reçues
                      </div>
                      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', marginBottom: '8px' }}>
                        {(t.lines || []).map(line => {
                          const aQtys = confirmQtys[t.id] || {};
                          const recvd = aQtys[line.bread_price] ?? line.quantity_sent;
                          const hasGap = recvd !== line.quantity_sent;
                          return (
                            <div key={line.bread_price} style={{ display: 'grid', gridTemplateColumns: '1fr 50px 70px', gap: '6px', alignItems: 'center', fontSize: '0.65rem' }}>
                              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                                {line.bread_price_display || `Pain ${line.unit_price} FC`}
                                <span style={{ marginLeft: '4px', color: 'hsl(var(--text-muted))' }}>envoyé: {line.quantity_sent}</span>
                              </span>
                              <input
                                type="number" min={0}
                                value={recvd}
                                onChange={e => setConfirmQtys(prev => ({
                                  ...prev,
                                  [t.id]: { ...(prev[t.id] || {}), [line.bread_price]: Number(e.target.value) }
                                }))}
                                className="form-input"
                                style={{
                                  fontSize: '0.73rem', height: '24px', padding: '0 5px', textAlign: 'right', fontWeight: 800,
                                  borderColor: hasGap ? 'hsl(var(--color-danger) / 0.7)' : 'hsl(var(--color-success) / 0.5)',
                                }}
                              />
                              {hasGap && (
                                <span style={{ fontSize: '0.58rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                                  écart {recvd - line.quantity_sent} ⚠
                                </span>
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <button
                        onClick={() => handleConfirmReceipt(t.id)}
                        className="btn btn-primary"
                        style={{ width: '100%', padding: '5px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '4px' }}
                      >
                        <FiCheckCircle /> Confirmer la Réception
                      </button>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {/* Empty state */}
            {pendingRequests.length === 0 && respondedToMe.length === 0 && disputedTrans.length === 0 && (
              <div style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
                <FiCheckCircle style={{ fontSize: '1.4rem', opacity: 0.3, display: 'block', margin: '0 auto 5px' }} />
                Aucune action en attente.
              </div>
            )}

            {/* DISPUTES */}
            {disputedTrans.map(t => (
              <div key={t.id} style={{ backgroundColor: 'hsl(var(--color-danger) / 0.06)', border: '1px solid hsl(var(--color-danger) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', fontSize: '0.68rem' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginBottom: '2px' }}>
                  <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />
                  <strong style={{ color: 'hsl(var(--color-danger))' }}>LITIGE D'ÉCART — Signalé à la Direction</strong>
                </div>
                <div style={{ color: 'hsl(var(--text-secondary))' }}>
                  {t.from_node_display} → {t.to_node_display}
                  {(t.lines || []).map(l => (
                    <span key={l.bread_price} style={{ marginLeft: '6px' }}>
                      {l.bread_price_display}: {l.quantity_sent}→{l.quantity_received ?? '?'}{l.quantity_gap !== 0 && l.quantity_gap !== undefined && <span style={{ color: 'hsl(var(--color-danger))' }}> (écart {l.quantity_gap})</span>}
                    </span>
                  ))}
                </div>
              </div>
            ))}

            {/* Confirmed history */}
            {transfers.filter(t => t.transfer_status === 'CONFIRMED' && (!effectiveNode || t.from_node === effectiveNode || t.to_node === effectiveNode)).slice(0, 3).length > 0 && (
              <div>
                <h4 style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-muted))', marginBottom: '5px', textTransform: 'uppercase' }}>Transferts Récents Confirmés</h4>
                {transfers.filter(t => t.transfer_status === 'CONFIRMED' && (!effectiveNode || t.from_node === effectiveNode || t.to_node === effectiveNode)).slice(0, 3).map(t => (
                  <div key={t.id} style={{ fontSize: '0.62rem', color: 'hsl(var(--text-secondary))', display: 'flex', justifyContent: 'space-between', padding: '3px 6px', backgroundColor: 'hsl(var(--color-success) / 0.04)', borderRadius: '3px', marginBottom: '2px' }}>
                    <span>
                      {t.from_node_display} → {t.to_node_display}
                      {(t.lines || []).map(l => <span key={l.bread_price} style={{ marginLeft: '5px' }}>{l.bread_price_display}: {l.quantity_received ?? l.quantity_sent}</span>)}
                    </span>
                    <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>✓</span>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>
      )}

      {/* ═══ §3.4 — RÉCONCILIATION & PAINS NON VALORISÉS ═══ */}
      {activeTab === 'reconciliation' && (
      <div className="glass-card" style={{ padding: '16px' }}>
        <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '8px' }}>
          <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
          §3.4 — Réconciliation & Pains Non Valorisés
        </h2>

        {/* BUG-051 : écart production déclarée vs ventes livrées + retours (CLAUDE.md §5.4) */}
        <ReconciliationPanel
          effectiveNode={effectiveNode}
          canPickNode={!!user?.can_access_all_nodes}
          nodes={nodes}
        />

        <div className="split-grid" style={{ '--split-cols': '1.1fr 1.9fr', gap: '16px' } as React.CSSProperties}>

          {/* DISPOSAL FORM — only for bakery-level users (node assigned) */}
          <div>
            <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '8px', color: 'hsl(var(--text-secondary))' }}>Enregistrer une Sortie Non Standard</h3>
            {!user?.node ? (
              <p style={{ fontSize: '0.7rem', color: 'hsl(var(--text-muted))', fontStyle: 'italic' }}>
                Disponible uniquement pour les gérants de boulangerie.
              </p>
            ) : (
            <form onSubmit={handleDisposal} style={{ display: 'flex', flexDirection: 'column', gap: '7px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '3px', textTransform: 'uppercase' }}>Session de Production *</label>
                <select value={dSession} onChange={e => setDSession(e.target.value)} className="form-input" style={{ fontSize: '0.68rem', height: '30px' }}>
                  <option value="">— Sélectionner la fournée —</option>
                  {sessions.filter(s => s.date === new Date().toISOString().slice(0, 10)).map(s => (
                    <option key={s.id} value={s.id}>
                      Éq.{s.team} · {s.node_display || s.node} · {s.total_breads} pains
                    </option>
                  ))}
                </select>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Nature de la Sortie *</label>
                <select value={dType} onChange={e => setDType(e.target.value as BreadDisposal['disposal_type'])} className="form-input" style={{ fontSize: '0.72rem', height: '30px' }}>
                  {Object.entries(DISPOSAL_CREATE_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                </select>
                {dType === 'REMAINING' && (
                  <p style={{ fontSize: '0.6rem', color: 'hsl(var(--accent-color))', margin: '3px 0 0' }}>
                    Ces pains restent dans le stock — ils s'ajouteront automatiquement à la prochaine fournée.
                  </p>
                )}
                <p style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', margin: '5px 0 0', fontStyle: 'italic' }}>
                  Pour une vente soldée avec un client, utilisez Facturation / Gestion Clientèle
                  (« Vente Soldée ») — la perte y est calculée automatiquement par rapport au prix catalogue.
                </p>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '6px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Catégorie Pain *</label>
                  <select value={dBreadPrice} onChange={e => setDBreadPrice(e.target.value)} className="form-input" style={{ fontSize: '0.72rem', height: '30px' }}>
                    <option value="">—</option>
                    {breadPrices.map(b => <option key={b.id} value={b.id}>{b.label}</option>)}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Qté *</label>
                  <input type="number" min={1} value={dQty || ''} placeholder="0" onChange={e => setDQty(Math.max(0, Number(e.target.value)))} className="form-input" style={{ fontSize: '0.75rem', height: '30px', padding: '0 6px', width: '70px' }} />
                </div>
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Notes / Bénéficiaire</label>
                <input type="text" value={dNotes} onChange={e => setDNotes(e.target.value)} placeholder="Motif, destinataire..." className="form-input" style={{ fontSize: '0.7rem', height: '28px', padding: '0 6px' }} />
              </div>
              {dError && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)' }}>{dError}</div>}
              <button type="submit" className="btn btn-primary" style={{ padding: '6px', fontSize: '0.73rem' }}>Enregistrer</button>
            </form>
            )}
          </div>

          {/* DISPOSAL LOG */}
          <div>
            <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '8px', color: 'hsl(var(--text-secondary))' }}>Journal des Sorties Non Valorisées</h3>
            {disposals.length === 0 ? (
              <div style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>Aucune sortie enregistrée.</div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table className="premium-table">
                  <thead>
                    <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                      <th>Type</th><th>Catégorie</th><th style={{ textAlign: 'right' }}>Qté</th><th style={{ textAlign: 'right' }}>Valeur FC</th><th>Date</th>
                    </tr>
                  </thead>
                  <tbody style={{ fontSize: '0.68rem' }}>
                    {disposals.map(d => (
                      <tr key={d.id}>
                        <td>
                          <span style={{ fontSize: '0.58rem', fontWeight: 700, color: `hsl(${DISPOSAL_COLORS[d.disposal_type]})` }}>
                            {d.disposal_type.replace('_', ' ')}
                          </span>
                        </td>
                        <td style={{ color: 'hsl(var(--text-secondary))' }}>{d.bread_price_display || '—'}</td>
                        <td style={{ textAlign: 'right', fontWeight: 800 }}>{d.quantity}</td>
                        <td style={{ textAlign: 'right', color: parseFloat(d.total_value) > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))' }}>
                          {parseFloat(d.total_value) > 0 ? `${parseFloat(d.total_value).toLocaleString('fr-FR')}` : '—'}
                        </td>
                        <td style={{ color: 'hsl(var(--text-muted))', fontSize: '0.6rem' }}>{d.created_at?.split('T')[0]}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
      )}

      {/* ═══ MODAL DÉTAIL STOCK PAIN ═══ */}
      {selectedBreadStock && (() => {
        const bs = selectedBreadStock;
        const total = bs.qty_produced + bs.qty_received;
        const pctProd = total > 0 ? Math.round((bs.qty_produced / total) * 100) : 0;
        const pctRecu = total > 0 ? Math.round((bs.qty_received / total) * 100) : 0;
        const valDispo = bs.qty_available * bs.unit_price;
        return (
          <Modal
            isOpen={true}
            onClose={() => setSelectedBreadStock(null)}
            title={`Détail Stock — ${bs.bread_price_display}`}
            subtitle={bs.node_display || bs.node}
            maxWidth="440px"
          >
              {/* Disponible */}
              <div style={{ textAlign: 'center', padding: '14px', borderRadius: 'var(--radius-sm)', background: `hsl(${bs.qty_available > 0 ? 'var(--color-success)' : 'var(--color-danger)'} / 0.1)`, border: `1px solid hsl(${bs.qty_available > 0 ? 'var(--color-success)' : 'var(--color-danger)'} / 0.3)`, marginBottom: '16px' }}>
                <div style={{ fontSize: '2rem', fontWeight: 800, color: `hsl(${bs.qty_available > 0 ? 'var(--color-success)' : 'var(--color-danger)'})` }}>{bs.qty_available}</div>
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))' }}>PAINS DISPONIBLES</div>
                <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>{valDispo.toLocaleString('fr-FR')} FC</div>
              </div>

              {/* Breakdown */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '16px' }}>
                {[
                  { label: 'Produits (propre production)', value: bs.qty_produced, pct: pctProd, color: 'var(--accent-color)', icon: '🔥' },
                  { label: 'Reçus (transferts entrants)', value: bs.qty_received, pct: pctRecu, color: 'var(--color-info)', icon: '📦' },
                  { label: 'Expédiés (transferts sortants)', value: bs.qty_sent, color: 'var(--color-warning)', icon: '🚚', subtract: true },
                  { label: 'Disposés (ventes soldées / pertes)', value: bs.qty_disposed, color: 'var(--color-danger)', icon: '📉', subtract: true },
                ].map(row => (
                  <div key={row.label} style={{ display: 'grid', gridTemplateColumns: '1.6fr auto', alignItems: 'center', gap: '8px' }}>
                    <div style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))' }}>
                      <span style={{ marginRight: '5px' }}>{row.icon}</span>{row.label}
                      {row.pct !== undefined && row.pct > 0 && <span style={{ marginLeft: '6px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>({row.pct}%)</span>}
                    </div>
                    <div style={{ textAlign: 'right', fontWeight: 800, fontSize: '0.85rem', color: `hsl(${row.color})` }}>
                      {row.subtract ? '−' : '+'}{row.value}
                    </div>
                  </div>
                ))}
                <div style={{ borderTop: '1px solid hsl(var(--border-color))', paddingTop: '6px', display: 'grid', gridTemplateColumns: '1.6fr auto', alignItems: 'center' }}>
                  <div style={{ fontSize: '0.7rem', fontWeight: 800 }}>= Disponible</div>
                  <div style={{ textAlign: 'right', fontWeight: 800, fontSize: '0.9rem', color: `hsl(${bs.qty_available >= 0 ? 'var(--color-success)' : 'var(--color-danger)'})` }}>{bs.qty_available}</div>
                </div>
              </div>

              <button onClick={() => setSelectedBreadStock(null)} className="btn btn-secondary" style={{ width: '100%', padding: '8px', fontSize: '0.8rem' }}>Fermer</button>
          </Modal>
        );
      })()}

      {/* ═══ MODAL VOIR PLUS — Toutes les fournées ═══ */}
      <Modal
        isOpen={showAllSessionsModal}
        onClose={() => setShowAllSessionsModal(false)}
        title={`Toutes les Fournées (${historySessions.length})`}
        maxWidth="560px"
        contentPadding="10px 14px"
        footer={<button onClick={() => setShowAllSessionsModal(false)} className="btn btn-secondary" style={{ width: '100%', fontSize: '0.8rem', padding: '7px' }}>Fermer</button>}
      >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
              {historySessions.map(sess => {
                const tFC  = sess.total_fc_produced || 0;
                const thFC = sess.theoretical_yield || 0;
                const rPct = thFC > 0 ? (tFC / thFC) * 100 : 0;
                const gap  = sess.yield_gap || 0;
                const rColor = rPct >= 90 ? 'hsl(var(--color-success))' : rPct >= 75 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                return (
                  <div
                    key={sess.id}
                    onClick={() => { setShowAllSessionsModal(false); setSelectedSession(sess); setSessionNotes(sess.notes || ''); }}
                    style={{ padding: '7px 10px', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.68rem', cursor: 'pointer', transition: 'background-color 0.15s' }}
                    onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'hsl(var(--bg-tertiary))')}
                    onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                  >
                    <div>
                      <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{sess.node_display || sess.node}</span>
                      <span style={{ marginLeft: '6px', color: 'hsl(var(--text-secondary))' }}>{sess.date} — Éq.{sess.team}</span>
                      {sess.is_closed && <span className="badge badge-info" style={{ fontSize: '0.55rem', marginLeft: '6px' }}>Clôturée</span>}
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginTop: '1px' }}>
                        {sess.total_breads} pains · {sess.flour_sacks_used} sacs · {tFC.toLocaleString('fr-FR')} FC
                        {sess.notes && <span style={{ marginLeft: '4px', color: 'hsl(var(--accent-color))' }}>💬</span>}
                      </div>
                    </div>
                    <div style={{ textAlign: 'right' }}>
                      <div style={{ fontWeight: 800, fontSize: '0.72rem', color: rColor }}>{rPct.toFixed(0)}%</div>
                      <div style={{ fontSize: '0.55rem', fontWeight: 700, color: gap >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                        {gap >= 0 ? '+' : ''}{gap.toLocaleString('fr-FR')} FC
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
      </Modal>

      {/* ═══ MODAL DÉTAIL FOURNÉE — avec commentaires ═══ */}
      {selectedSession && (
        <Modal
          isOpen={true}
          onClose={() => setSelectedSession(null)}
          title="Détail Fournée"
          maxWidth="460px"
        >
            {/* Closed status */}
            {selectedSession.is_closed && (
              <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--color-success))', backgroundColor: 'hsl(var(--color-success) / 0.1)', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '10px' }}>
                <FiCheckCircle />
                Fournée clôturée{selectedSession.closed_at ? ` le ${new Date(selectedSession.closed_at).toLocaleString('fr-FR')}` : ''} — saisie verrouillée.
              </div>
            )}

            {/* Session summary */}
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '10px 14px', marginBottom: '14px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', fontSize: '0.75rem' }}>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Boulangerie</div>
                  <div style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{selectedSession.node_display || selectedSession.node}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Date · Équipe</div>
                  <div style={{ fontWeight: 700 }}>{selectedSession.date} — Éq.{selectedSession.team}</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Pains Produits</div>
                  <div style={{ fontWeight: 800 }}>{selectedSession.total_breads} pains</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Farine Utilisée</div>
                  <div style={{ fontWeight: 700 }}>{selectedSession.flour_sacks_used} sacs</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Valeur Produite</div>
                  <div style={{ fontWeight: 800, color: 'hsl(var(--color-success))' }}>{(selectedSession.total_fc_produced || 0).toLocaleString('fr-FR')} FC</div>
                </div>
                <div>
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Rendement</div>
                  {(() => {
                    const rPct = selectedSession.theoretical_yield > 0 ? ((selectedSession.total_fc_produced || 0) / selectedSession.theoretical_yield) * 100 : 0;
                    const rColor = rPct >= 90 ? 'hsl(var(--color-success))' : rPct >= 75 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                    return <div style={{ fontWeight: 800, color: rColor }}>{rPct.toFixed(1)}%</div>;
                  })()}
                </div>
              </div>
            </div>

            {/* Breakdown by bread category */}
            {selectedSession.lines && selectedSession.lines.length > 0 && (
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '6px' }}>
                  Production par Catégorie
                </div>
                <div style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
                  <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.72rem' }}>
                    <thead>
                      <tr style={{ backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.62rem', textTransform: 'uppercase', color: 'hsl(var(--text-muted))' }}>
                        <th style={{ padding: '5px 10px', textAlign: 'left', fontWeight: 700 }}>Catégorie</th>
                        <th style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700 }}>Qté</th>
                        <th style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700 }}>PU</th>
                        <th style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700 }}>Total FC</th>
                      </tr>
                    </thead>
                    <tbody>
                      {[...selectedSession.lines].sort((a, b) => (a.unit_price || 0) - (b.unit_price || 0)).map((line, i) => (
                        <tr key={i} style={{ borderTop: '1px solid hsl(var(--border-color))' }}>
                          <td style={{ padding: '5px 10px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>
                            {line.bread_price_display || `Pain ${line.unit_price} FC`}
                          </td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 800 }}>{line.quantity}</td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', color: 'hsl(var(--text-muted))' }}>{(line.unit_price || 0).toLocaleString('fr-FR')} FC</td>
                          <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 700, color: 'hsl(var(--color-success))' }}>
                            {(line.line_fc ?? line.quantity * (line.unit_price || 0)).toLocaleString('fr-FR')} FC
                          </td>
                        </tr>
                      ))}
                    </tbody>
                    <tfoot>
                      <tr style={{ borderTop: '2px solid hsl(var(--border-color))', backgroundColor: 'hsl(var(--bg-tertiary))' }}>
                        <td colSpan={2} style={{ padding: '5px 10px', fontWeight: 800, fontSize: '0.68rem' }}>TOTAL</td>
                        <td />
                        <td style={{ padding: '5px 10px', textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>
                          {(selectedSession.total_fc_produced || 0).toLocaleString('fr-FR')} FC
                        </td>
                      </tr>
                    </tfoot>
                  </table>
                </div>
              </div>
            )}

            {/* BUG-108 : recoupement automatique figé à la clôture */}
            {selectedSession.is_closed && selectedSession.closure_summary && (
              <div style={{ marginBottom: '14px', paddingTop: '10px', borderTop: '1px solid hsl(var(--border-color))' }}>
                <ClosureSummaryCard summary={selectedSession.closure_summary} />
              </div>
            )}

            {/* Notes */}
            <div>
              <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>
                Commentaires / Observations
              </label>
              <textarea
                value={sessionNotes}
                onChange={e => setSessionNotes(e.target.value)}
                rows={4}
                disabled={selectedSession.is_closed}
                placeholder="Saisir vos observations sur cette fournée..."
                className="form-input"
                style={{ resize: 'vertical', fontSize: '0.78rem', padding: '8px 10px', lineHeight: 1.5, opacity: selectedSession.is_closed ? 0.6 : 1 }}
              />
            </div>

            <div style={{ display: 'flex', gap: '10px', marginTop: '14px', flexWrap: 'wrap' }}>
              <button onClick={() => setSelectedSession(null)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>
                Fermer
              </button>
              {!selectedSession.is_closed && (
                <button
                  onClick={async () => {
                    setSavingNotes(true);
                    try {
                      await productionApi.sessions.update(selectedSession.id, { notes: sessionNotes });
                      setHistorySessions(prev => prev.map(s => s.id === selectedSession.id ? { ...s, notes: sessionNotes } : s));
                      setSelectedSession(null);
                    } catch (err) {
                      console.error('Failed to save notes', err);
                    }
                    setSavingNotes(false);
                  }}
                  disabled={savingNotes}
                  className="btn btn-primary"
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', opacity: savingNotes ? 0.6 : 1 }}
                >
                  {savingNotes ? 'Enregistrement...' : 'Sauvegarder le commentaire'}
                </button>
              )}
              {!selectedSession.is_closed && (
                <button
                  onClick={() => setCloseSessionModalOpen(true)}
                  className="btn btn-primary"
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', backgroundColor: 'hsl(var(--color-success))', borderColor: 'hsl(var(--color-success))' }}
                >
                  <FiCheckCircle style={{ marginRight: '4px', verticalAlign: '-2px' }} />
                  Clôturer la fournée
                </button>
              )}
            </div>
        </Modal>
      )}

      {/* ═══ MODAL CLÔTURE — Reste du Jour par catégorie (BUG-154) ═══ */}
      <CloseSessionModal
        isOpen={closeSessionModalOpen}
        session={selectedSession}
        onClose={() => setCloseSessionModalOpen(false)}
        onClosed={(updated) => {
          setHistorySessions(prev => prev.map(s => s.id === updated.id ? updated : s));
          setSelectedSession(updated);
          setSessionNotes(updated.notes || '');
        }}
      />

      {/* ═══ MODAL APPROVISIONNEMENT ═══ */}
      <Modal
        isOpen={showApproModal}
        onClose={() => setShowApproModal(false)}
        title="Approvisionnement Consommable"
        maxWidth="420px"
      >
            <form onSubmit={handleAppro} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Consommable *</label>
                <select value={approStock} onChange={e => setApproStock(e.target.value)} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }}>
                  <option value="">— Sélectionner —</option>
                  {stocks.map(s => <option key={s.id} value={s.id}>{STOCK_ICONS[s.consumable_type] || '📦'} {displayStock(s.consumable_type_display || s.consumable_type)} (actuel: {s.quantity} {s.unit})</option>)}
                </select>
              </div>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Quantité Entrante *</label>
                  <input type="number" step="any" min={0} value={approQty} onChange={e => setApproQty(e.target.value)} placeholder="Ex: 10 ou 10.5" className="form-input" style={{ height: '36px', fontSize: '0.8rem', padding: '0 10px' }} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Prix unitaire (FC) *</label>
                  <input type="number" step="any" min={0} value={approPrice} onChange={e => setApproPrice(e.target.value)} placeholder="Ex: 15000" className="form-input" style={{ height: '36px', fontSize: '0.8rem', padding: '0 10px' }} />
                </div>
              </div>
              {approQty && approPrice && parseFloat(approQty) > 0 && parseFloat(approPrice) > 0 && (
                <div style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', backgroundColor: 'hsl(var(--bg-tertiary))', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                  Coût total : <strong style={{ color: 'hsl(var(--accent-color))' }}>{(parseFloat(approQty) * parseFloat(approPrice)).toLocaleString('fr-FR')} FC</strong>
                </div>
              )}
              {/* Fournisseur — visible only when FLOUR stock is selected */}
              {(() => {
                const sel = stocks.find(s => s.id === approStock);
                return sel?.consumable_type === 'FLOUR' ? (
                  <div>
                    <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Fournisseur Farine</label>
                    <select value={approSupplier} onChange={e => setApproSupplier(e.target.value)} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }}>
                      <option value="">— Non précisé —</option>
                      <option value="MIDEMA">MIDEMA</option>
                      <option value="GMK">GMK</option>
                      <option value="DVS">DVS</option>
                      <option value="LOCAL">Achat local</option>
                    </select>
                  </div>
                ) : null;
              })()}
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Description</label>
                <input type="text" value={approDesc} onChange={e => setApproDesc(e.target.value)} placeholder="Lot, observations..." className="form-input" style={{ height: '36px', fontSize: '0.78rem', padding: '0 10px' }} />
              </div>
              {approError && (
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '6px 10px', borderRadius: 'var(--radius-sm)' }}>
                  {isStockInsufficientError(approError) && <FiAlertTriangle style={{ flexShrink: 0 }} />}
                  <span>{approError}</span>
                </div>
              )}
              <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
                <button type="button" onClick={() => setShowApproModal(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>Annuler</button>
                <button type="submit" disabled={approSaving} className="btn btn-primary" style={{ flex: 2, padding: '8px', fontSize: '0.8rem', opacity: approSaving ? 0.6 : 1 }}>{approSaving ? 'Enregistrement...' : "Valider l'Approvisionnement"}</button>
              </div>
            </form>
      </Modal>

    </div>
  );
};
