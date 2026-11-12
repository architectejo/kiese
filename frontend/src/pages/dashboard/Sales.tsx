import React, { useState, useEffect, useCallback, useRef } from 'react';
import {
  FiTruck, FiPlusCircle, FiClock, FiCheckCircle,
  FiAlertCircle, FiSearch, FiX, FiPrinter, FiChevronRight, FiCreditCard
} from 'react-icons/fi';
import { salesApi, clientsApi, coreApi, Invoice, Client, BreadPrice, InvoiceAdjustPayload } from '@/api/services';
import { getErrorDetail, isTeamNotAssignedError } from '@/api/errors';
import { useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { ThermalReceipt, ReceiptData, ReceiptLine } from '@/components/shared/ThermalReceipt';
import { Modal } from '@/components/shared/Modal';

// ── Delivery queue item ───────────────────────────────────────────────────────
interface QueueItem {
  _apiId: string;
  id: string;
  clientName: string;
  clientCode: string;
  clientPhoto?: string;
  nodeDisplay: string;
  facturierDisplay: string;
  livreurDisplay?: string;
  lines: { label: string; qty: number }[];
  totalValue: number;
  versement: number;
  paymentType: 'CASH' | 'CREDIT';
  debtBefore: number;
  debtAfter: number;
  commissionRate: number;
  isSoldee: boolean;
  /** BUG-092/BUG-096 : perte (prix catalogue − prix facturé) × quantité, nulle hors vente soldée. */
  totalLoss: number;
  isRepayment: boolean;
  specialCode: string;
  /** BUG-177 : facture « Non Servi » (NS) — reste PENDING indéfiniment, jamais livrable. */
  isNonServi: boolean;
  status: 'En attente' | 'Livré';
  invoiceDate: string;
  timeAdded: string;
  createdAt: string;
  // BUG-109 : trace d'ajustement (correction/annulation d'une commande déjà
  // enregistrée via une facture liée — jamais de mutation de l'originale).
  isAdjustment: boolean;
  adjustmentSign: 1 | -1 | null;
  adjustsId: string | null;
  adjustmentsCount: number;
}

const mapInvoice = (inv: Invoice, bpMap: Record<number, BreadPrice>): QueueItem => ({
  _apiId: inv.id,
  id: inv.receipt_number,
  clientName: inv.client_display || inv.client,
  clientCode: inv.client_code || '',
  clientPhoto: inv.client_photo || undefined,
  nodeDisplay: inv.node_display || inv.node || '—',
  facturierDisplay: inv.facturier_display || '—',
  livreurDisplay: inv.livreur_display || undefined,
  lines: (inv.lines || []).map(l => ({
    label: bpMap[Number(l.bread_price)]?.label || l.bread_price_display || l.bread_price,
    qty: l.quantity,
  })),
  totalValue: parseFloat(inv.order_total) || 0,
  versement: parseFloat(inv.payment_amount) || 0,
  paymentType: inv.payment_type,
  debtBefore: parseFloat(inv.debt_before) || 0,
  debtAfter: parseFloat(inv.debt_after) || 0,
  commissionRate: parseFloat(inv.commission_rate) || 0,
  isSoldee: inv.is_soldee === true,
  totalLoss: parseFloat(inv.total_loss || '0') || 0,
  isRepayment: inv.is_debt_repayment === true,
  specialCode: inv.special_code || '',
  isNonServi: inv.special_code === 'NS' && inv.is_debt_repayment !== true,
  status: inv.status === 'DELIVERED' || inv.status === 'CANCELLED' ? 'Livré' : 'En attente',
  invoiceDate: inv.invoice_date || inv.created_at?.split('T')[0] || '',
  timeAdded: new Date(inv.created_at).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' }),
  createdAt: inv.created_at,
  isAdjustment: inv.is_adjustment === true,
  adjustmentSign: inv.adjustment_sign ?? null,
  adjustsId: inv.adjusts || null,
  adjustmentsCount: inv.adjustments_count || 0,
});

// ── Main component ─────────────────────────────────────────────────────────────
const TEAM_NOT_ASSIGNED_MESSAGE =
  "Désignez l'équipe de service du jour avant de facturer. La boîte de désignation vient de s'ouvrir.";

export const Sales: React.FC = () => {
  const requestTeamAssignment = useTeamAssignmentStore(s => s.requestAssignment);
  const { user } = useAuthStore();
  // BUG-161 (F3) : jour calendaire fourni par le serveur (repli : date locale, jamais UTC).
  // Un changement de journée (relève) relance le chargement de la file du jour (`loadData`).
  const workDate = useWorkDate();
  const [queue, setQueue] = useState<QueueItem[]>([]);
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
  const [bpMap, setBpMap] = useState<Record<string, BreadPrice>>({});
  const [isLoading, setIsLoading] = useState(true);
  // BUG-164 : la file du jour est lue page par page (page 1 affichée aussitôt, suite en
  // arrière-plan). Compteurs et total de la file ne sont définitifs que lorsque
  // `queueComplete` est vrai : sinon « calcul en cours… X/Y ».
  const [queueComplete, setQueueComplete] = useState(false);
  const [queueProgress, setQueueProgress] = useState<{ loaded: number; total: number | null }>({ loaded: 0, total: null });
  const [queueError, setQueueError] = useState<string | null>(null);
  const queueLoadSeqRef = useRef(0);
  const queueTotalRef = useRef<number | null>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Erreur de livraison (ex. BUG-047 : vacation déjà rapportée) — rattachée à la facture concernée
  const [deliveryError, setDeliveryError] = useState<{ id: string; message: string } | null>(null);
  const [receipt, setReceipt] = useState<ReceiptData | null>(null);
  // cache receipts by invoice API id to allow reprint after delivery
  const [receiptCache, setReceiptCache] = useState<Record<string, ReceiptData>>({});

  // Client search — BUG-065 : recherche serveur débattue (debounce 350ms), même principe que
  // BUG-061 sur Clients.tsx. On n'embarque plus les 690+ fiches clients à chaque chargement de
  // l'écran : seul le terme saisi déclenche une requête `?search=...` filtrée côté serveur.
  const [clientSearch, setClientSearch] = useState('');
  const [debouncedClientSearch, setDebouncedClientSearch] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedClientSearch(clientSearch.trim()), 350);
    return () => clearTimeout(timer);
  }, [clientSearch]);
  const [clientSuggestions, setClientSuggestions] = useState<Client[]>([]);
  const [isSearchingClients, setIsSearchingClients] = useState(false);
  const [clientSearchError, setClientSearchError] = useState<string | null>(null);
  const [selectedClient, setSelectedClient] = useState<Client | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(false);
  const [isOccasional, setIsOccasional] = useState(false);
  const searchRef = useRef<HTMLInputElement>(null);

  // Bread quantities keyed by BreadPrice integer id
  const [quantities, setQuantities] = useState<Record<number, number>>({});

  // Payment
  const [versement, setVersement] = useState(0);
  const [venteSoldee, setVenteSoldee] = useState(false);
  // BUG-052 : exonération de commission (CM=0) sur une facture normale — INDÉPENDANTE de
  // « Vente Soldée » (qui applique en plus la remise de prix à 75% et gèle la BP).
  // Combinable sans incohérence (voir note affichée quand les deux sont cochées).
  const [commissionExempt, setCommissionExempt] = useState(false);
  const [specialCode, setSpecialCode] = useState<'' | 'NV' | 'RG' | 'NS'>('');
  const [showSpecialCode, setShowSpecialCode] = useState(false);
  // BUG-177 : choix du client non servi (CREDIT = garde la dette, CASH = payé comptant).
  const [nsPaymentType, setNsPaymentType] = useState<'CASH' | 'CREDIT'>('CREDIT');

  // "Voir plus" — full delivery queue modal
  const [queueModalOpen, setQueueModalOpen] = useState(false);
  // KPI detail modals
  const [statModal, setStatModal] = useState<'livrees' | 'total' | null>(null);

  // BUG-083 : réglage global — visible seulement si activé par ADMIN/DIRECTION (Settings.tsx)
  const [allowBackdatedSales, setAllowBackdatedSales] = useState(false);
  // Date de commande rétroactive, optionnelle — vide = aujourd'hui (comportement par défaut)
  const [invoiceDate, setInvoiceDate] = useState('');
  // Modale de confirmation de livraison avec date rétroactive optionnelle (BUG-083)
  const [deliverModalItem, setDeliverModalItem] = useState<QueueItem | null>(null);
  const [deliverDate, setDeliverDate] = useState('');

  // BUG-090 : remboursement de dette / dépôt « client épargne » — paiement seul, sans
  // ligne de pain. Même mécanisme que Clients.tsx (salesApi.createRepayment), rattaché
  // ici au client déjà sélectionné pour la facturation en cours.
  const [isRepaymentModalOpen, setIsRepaymentModalOpen] = useState(false);
  const [repaymentAmount, setRepaymentAmount] = useState('');
  const [repaymentDate, setRepaymentDate] = useState('');
  const [repaymentLoading, setRepaymentLoading] = useState(false);
  const [repaymentError, setRepaymentError] = useState<string | null>(null);

  // BUG-109 : ajustement d'une facture déjà enregistrée — réservé GERANT et au-dessus
  // (jamais FACTURIER/LIVREUR, cohérent avec la permission 403 côté serveur).
  const canAdjustInvoice = ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(user?.role || '');
  const [isAdjustModalOpen, setIsAdjustModalOpen] = useState(false);
  const [adjustTarget, setAdjustTarget] = useState<QueueItem | null>(null);
  const [adjustSign, setAdjustSign] = useState<1 | -1>(1);
  const [adjustQtys, setAdjustQtys] = useState<Record<number, number>>({});
  const [adjustPaymentAmount, setAdjustPaymentAmount] = useState('');
  const [adjustDate, setAdjustDate] = useState('');
  const [adjustLoading, setAdjustLoading] = useState(false);
  const [adjustError, setAdjustError] = useState<string | null>(null);

  const loadData = useCallback(async (isRetry = false): Promise<void> => {
    queueLoadSeqRef.current += 1;
    const seq = queueLoadSeqRef.current;
    try {
      setIsLoading(true);
      setQueueComplete(false);
      setQueueError(null);
      setQueueProgress({ loaded: 0, total: null });
      await salesApi.cleanupExpired().catch(() => {});
      // Charge les factures du JOUR (PENDING + DELIVERED), pas seulement PENDING :
      // une commande livrée doit rester comptée dans les stats de la page tant
      // qu'elle n'est pas annulée — seul un statut CANCELLED doit l'en exclure.
      const todayStr = workDate;
      // BUG-283 : les PENDING non expirées du nœud (créées avant minuit) viennent de
      // `pending_deliveries`, indépendamment de la date du jour ; filtrage nœud/rôle côté serveur.
      const [invoicesRes, bpRes, configRes, pendingRes] = await Promise.all([
        salesApi.listPage({ invoice_date: todayStr, page: '1', page_size: '100' }),
        coreApi.breadPrices.list(),
        coreApi.config.get(),
        salesApi.pendingDeliveries().catch(() => ({ data: [] as Invoice[] })),
      ]);
      if (seq !== queueLoadSeqRef.current) return;
      setAllowBackdatedSales(!!configRes.data.allow_backdated_sales);
      const bps = bpRes.data.filter(b => b.is_active);
      const map: Record<string, BreadPrice> = {};
      bps.forEach(b => { map[b.id] = b; });
      setBreadPrices(bps);
      setBpMap(map);
      const TWELVE_H = 12 * 60 * 60 * 1000;
      // BUG-177 : une facture NS reste PENDING indéfiniment (jamais purgée côté serveur).
      const keepInvoice = (inv: Invoice) =>
        inv.status !== 'CANCELLED' &&
        (inv.status !== 'PENDING' || inv.special_code === 'NS' || (Date.now() - new Date(inv.created_at).getTime()) < TWELVE_H);
      const dayIds = new Set(invoicesRes.data.results.map(inv => String(inv.id)));
      const olderPending = pendingRes.data.filter(inv => !dayIds.has(String(inv.id)) && keepInvoice(inv));
      setQueue(invoicesRes.data.results.concat(olderPending).filter(keepInvoice).map(inv => mapInvoice(inv, map)));
      const initQty: Record<number, number> = {};
      bps.forEach(b => { initQty[b.id] = 0; });
      setQuantities(initQty);
      // BUG-172 : ids lus côté serveur, pour contrôler `lus === count` en fin de lecture.
      const serverIds = new Set<string>(invoicesRes.data.results.map(inv => String(inv.id)));
      let loaded = invoicesRes.data.results.length;
      queueTotalRef.current = invoicesRes.data.count;
      setQueueProgress({ loaded, total: invoicesRes.data.count });
      setIsLoading(false);
      // Pages suivantes en arrière-plan (annulées si une nouvelle lecture démarre).
      let next = invoicesRes.data.next;
      let page = 1;
      try {
        while (next) {
          page += 1;
          const more = await salesApi.listPage({ invoice_date: todayStr, page: String(page), page_size: '100' });
          if (seq !== queueLoadSeqRef.current) return;
          loaded += more.data.results.length;
          more.data.results.forEach(inv => serverIds.add(String(inv.id)));
          const fresh = more.data.results.filter(keepInvoice).map(inv => mapInvoice(inv, map));
          setQueue(prev => {
            const known = new Set(prev.map(q => q._apiId));
            return prev.concat(fresh.filter(q => !known.has(q._apiId)));
          });
          queueTotalRef.current = more.data.count;
          setQueueProgress({ loaded, total: more.data.count });
          next = more.data.next;
        }
        // BUG-172 : ligne sautée/doublée (insertion concurrente, tri instable) => un seul
        // rechargement automatique, puis erreur ; la file n'est jamais déclarée complète.
        if (serverIds.size !== queueTotalRef.current) {
          if (!isRetry) { void loadData(true); return; }
          setQueueError('Données incomplètes, réessayez.');
          return;
        }
        setQueueComplete(true);
      } catch (err) {
        if (seq !== queueLoadSeqRef.current) return;
        setQueueError(getErrorDetail(err, 'Impossible de charger la suite des factures du jour.'));
      }
    } catch (err) {
      if (seq !== queueLoadSeqRef.current) return;
      console.error('Failed to load sales data', err);
      setQueueError(getErrorDetail(err, 'Impossible de charger les factures du jour.'));
    } finally {
      if (seq === queueLoadSeqRef.current) setIsLoading(false);
    }
  }, [workDate]);

  useEffect(() => { loadData(); }, [loadData]);

  // Recherche prédictive client — BUG-065 : requête serveur filtrée (`?search=...`), plus
  // de chargement intégral du fichier clients avant la première suggestion.
  useEffect(() => {
    if (debouncedClientSearch.length < 1) {
      setClientSuggestions([]);
      setClientSearchError(null);
      setIsSearchingClients(false);
      return;
    }
    let cancelled = false;
    setIsSearchingClients(true);
    setClientSearchError(null);
    // BUG-069 : `page_size` borné — seules 8 suggestions sont affichées (`.slice(0, 8)`
    // ci-dessous) : inutile de laisser `getList()` paginer jusqu'à épuisement (plusieurs
    // requêtes séquentielles) pour un terme large (ex. préfixe de boulangerie `K1-`).
    clientsApi.list({ search: debouncedClientSearch, page_size: '10' })
      .then(res => {
        if (cancelled) return;
        setClientSuggestions(res.data.filter(c => c.is_active).slice(0, 8));
      })
      .catch((err: unknown) => {
        if (cancelled) return;
        const data = (err as { response?: { data?: { detail?: string } } })?.response?.data;
        setClientSearchError(data?.detail || 'Recherche client indisponible. Réessayez.');
        setClientSuggestions([]);
      })
      .finally(() => { if (!cancelled) setIsSearchingClients(false); });
    return () => { cancelled = true; };
  }, [debouncedClientSearch]);

  const suggestions = clientSuggestions;

  const selectClient = (c: Client) => {
    setSelectedClient(c);
    setClientSearch(`${c.code} — ${c.full_name}`);
    setShowSuggestions(false);
  };

  const clearClient = () => {
    setSelectedClient(null);
    setClientSearch('');
    setShowSuggestions(false);
    searchRef.current?.focus();
  };

  // BUG-107 : l'aperçu local doit refléter exactement le prix que le serveur va facturer en
  // « Vente Soldée » — remise de 75 % appliquée PAR LIGNE puis arrondie au franc le plus proche
  // (ROUND_HALF_UP), jamais sur le total global (même formule que `backend/sales/models.py::
  // InvoiceLine.save()` / `SOLDEE_PRICE_RATIO = Decimal('0.75')`). `Math.round` arrondit déjà au
  // demi supérieur pour un nombre positif, équivalent à ROUND_HALF_UP ici.
  const effectiveUnitPrice = (bp: BreadPrice) => (venteSoldee ? Math.round(bp.unit_price * 0.75) : bp.unit_price);
  const orderTotal = breadPrices.reduce((sum, b) => sum + (quantities[b.id] || 0) * effectiveUnitPrice(b), 0);
  const isNonServiForm = specialCode === 'NS';
  const isRegularisationForm = specialCode === 'RG';
  // BUG-177 : pour NS, le type de paiement exprime le choix du client (garde la dette ou non) ;
  // sinon il est déduit du versement comme avant.
  // BUG-230 : une vente sans client enregistré est obligatoirement payée comptant — le versement
  // est alors égal à la valeur de la commande (le serveur refuse le crédit sans client, en 400).
  const isCashOnlySale = isOccasional && !isNonServiForm && !isRegularisationForm;
  const effectiveVersement = isCashOnlySale ? orderTotal : versement;
  const paymentType: 'CASH' | 'CREDIT' = isNonServiForm
    ? nsPaymentType
    : (isCashOnlySale || (versement >= orderTotal && orderTotal > 0) ? 'CASH' : 'CREDIT');

  const resetForm = () => {
    setSelectedClient(null);
    setClientSearch('');
    setVersement(0);
    setVenteSoldee(false);
    setCommissionExempt(false);
    setIsOccasional(false);
    setSpecialCode('');
    setNsPaymentType('CREDIT');
    setShowSpecialCode(false);
    setInvoiceDate('');
    setQuantities(prev => { const q: Record<number, number> = {}; Object.keys(prev).forEach(k => { q[Number(k)] = 0; }); return q; });
    setFormError(null);
    searchRef.current?.focus();
  };

  // BUG-090 : remboursement de dette ou dépôt « client épargne » — un simple montant
  // qui réduit (ou, au-delà de la dette, rend négative) la balance de paiement du
  // client, sans aucune ligne de pain (CLAUDE.md §5.1 et §5.2). Même endpoint que la
  // facturation normale (`is_debt_repayment: true`), déjà exposé dans Clients.tsx.
  const handleRepaymentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!selectedClient) return;
    const amount = parseFloat(repaymentAmount);
    if (isNaN(amount) || amount <= 0) { setRepaymentError('Montant invalide.'); return; }
    setRepaymentLoading(true);
    setRepaymentError(null);
    try {
      const todayStr = workDate;
      const retroactiveDate = allowBackdatedSales && repaymentDate && repaymentDate !== todayStr ? repaymentDate : undefined;
      const res = await salesApi.createRepayment(selectedClient.id, amount, retroactiveDate);
      const inv = res.data;
      const built: ReceiptData = {
        receiptNumber: inv.receipt_number,
        boulangerie: inv.node_display || inv.node || '—',
        agentName: user?.first_name ? `${user.first_name} ${user.last_name}` : 'Facturier',
        // BUG-184 : équipe portée par la facture (équipe de service si rotation active) ;
        // repli sur l'équipe de l'utilisateur : facture qu'il vient de créer.
        team: inv.team || user?.team || 'A',
        clientCode: inv.client_code || selectedClient.code,
        clientName: inv.client_display || selectedClient.full_name,
        lines: [],
        orderTotal: 0,
        versement: parseFloat(inv.payment_amount) || amount,
        commissionRate: 0,
        debtBefore: parseFloat(inv.debt_before) || 0,
        newDebt: parseFloat(inv.debt_after ?? '0'),
        isSoldee: false,
        // BUG-099 : remboursement/dépôt livré immédiatement côté serveur (delivered_at
        // combine la date — éventuellement rétroactive, BUG-083 — avec l'heure réelle).
        transactionDate: inv.delivered_at || inv.invoice_date,
      };
      setReceipt(built);
      setReceiptCache(prev => ({ ...prev, [inv.id]: built }));
      if (retroactiveDate) {
        setQueue(prev => [mapInvoice(inv, bpMap), ...prev]);
      } else {
        await loadData();
      }
      setIsRepaymentModalOpen(false);
      setRepaymentAmount('');
      setRepaymentDate('');
      clearClient();
    } catch (err: unknown) {
      if (isTeamNotAssignedError(err)) {
        // BUG-161 : équipe de service non désignée — aucun reçu, aucune facture locale ;
        // la boîte de désignation du tableau de bord se rouvre.
        setRepaymentError(TEAM_NOT_ASSIGNED_MESSAGE);
        requestTeamAssignment();
      } else {
        setRepaymentError(getErrorDetail(err, 'Erreur lors de l\'enregistrement.'));
      }
    } finally {
      setRepaymentLoading(false);
    }
  };

  // BUG-109 : ouvre le formulaire d'ajustement pour une facture déjà enregistrée
  // (correction/annulation via une nouvelle facture liée, jamais de mutation de
  // l'originale) — réservé GERANT+, cf. `canAdjustInvoice`.
  const openAdjustModal = (item: QueueItem) => {
    setAdjustTarget(item);
    setAdjustSign(1);
    setAdjustQtys({});
    setAdjustPaymentAmount('');
    setAdjustDate('');
    setAdjustError(null);
    setIsAdjustModalOpen(true);
  };

  const handleAdjustSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!adjustTarget || adjustLoading) return;
    const lines = breadPrices
      .filter(bp => (adjustQtys[bp.id] || 0) > 0)
      .map(bp => ({ bread_price: bp.id, quantity: adjustQtys[bp.id] }));
    if (lines.length === 0) {
      setAdjustError('Déclarez au moins une catégorie de pains (quantité = ampleur du changement).');
      return;
    }
    const paymentAmount = parseFloat(adjustPaymentAmount || '0');
    if (isNaN(paymentAmount) || paymentAmount < 0) {
      setAdjustError('Montant de versement invalide.');
      return;
    }
    setAdjustLoading(true);
    setAdjustError(null);
    try {
      const todayStr = workDate;
      const payload: InvoiceAdjustPayload = {
        adjustment_sign: adjustSign,
        payment_amount: paymentAmount.toString(),
        lines,
        ...(allowBackdatedSales && adjustDate && adjustDate !== todayStr ? { invoice_date: adjustDate } : {}),
      };
      const res = await salesApi.adjust(adjustTarget._apiId, payload);
      setQueue(prev => [
        mapInvoice(res.data, bpMap),
        ...prev.map(q => q._apiId === adjustTarget._apiId
          ? { ...q, adjustmentsCount: q.adjustmentsCount + 1 }
          : q),
      ]);
      setIsAdjustModalOpen(false);
      setAdjustTarget(null);
    } catch (err: unknown) {
      setAdjustError(getErrorDetail(err, "Erreur lors de l'ajustement."));
    } finally {
      setAdjustLoading(false);
    }
  };

  const handleSubmit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setFormError(null);

    // Pre-flight: user must be assigned to a node to create invoices
    if (!user?.node) {
      setFormError('Votre compte n\'est pas assigné à une boulangerie. Seuls les Facturiers et Gérants affectés à un nœud peuvent créer des factures.');
      return;
    }
    if (!isOccasional && !selectedClient) { setFormError('Sélectionnez un client ou cochez "Vente occasionnelle".'); return; }
    const lines = breadPrices.filter(b => (quantities[b.id] || 0) > 0).map(b => ({ bread_price: b.id, quantity: quantities[b.id] }));
    if (lines.length === 0) { setFormError('Entrez au moins une quantité de pain.'); return; }
    // BUG-230 : contrôles de forme minimaux (le serveur reste l'autorité : quantité entière 1 à 100 000).
    if (lines.some(l => !Number.isInteger(l.quantity) || l.quantity < 1 || l.quantity > 100000)) {
      setFormError('Chaque quantité doit être un nombre entier compris entre 1 et 100 000.');
      return;
    }
    if (!isNonServiForm && !isRegularisationForm && (!Number.isFinite(effectiveVersement) || effectiveVersement < 0)) {
      setFormError('Le versement ne peut pas être négatif.');
      return;
    }

    setIsSubmitting(true);
    try {
      // BUG-083 : date de commande rétroactive optionnelle (réglage ADMIN/DIRECTION). Vide ou
      // date du jour → comportement inchangé (aucun champ envoyé, le serveur date normalement).
      const todayStr = workDate;
      const retroactiveDate = allowBackdatedSales && invoiceDate && invoiceDate !== todayStr ? invoiceDate : null;
      const res = await salesApi.create({
        client: isOccasional ? null : selectedClient?.id,
        payment_type: paymentType,
        // BUG-177 : aucun versement pour NS (rien n'est remis) ni RG (aucune dette créée).
        payment_amount: (isNonServiForm || isRegularisationForm ? 0 : effectiveVersement).toString(),
        // BUG-230 : `commission_rate` n'est plus envoyé (le serveur applique le taux du client).
        ...(venteSoldee ? { is_soldee: true } : {}),
        // BUG-052 : exonération de commission dédiée, indépendante de « Vente Soldée » —
        // forcée côté serveur (comm_rate=0) même si combinée avec is_soldee (§ ci-dessus).
        ...(commissionExempt ? { commission_exempt: true } : {}),
        ...(specialCode ? { special_code: specialCode } : {}),
        ...(retroactiveDate ? { invoice_date: retroactiveDate } : {}),
        lines,
      });
      if (retroactiveDate) {
        // La facture est datée d'un jour antérieur : le rechargement habituel (filtré sur
        // aujourd'hui) ne la montrerait pas dans la file. On l'ajoute localement pour que le
        // facturier puisse immédiatement confirmer sa livraison (éventuellement rétroactive).
        setQueue(prev => [mapInvoice(res.data, bpMap), ...prev]);
      } else {
        await loadData();
      }
      resetForm();
    } catch (err: unknown) {
      if (isTeamNotAssignedError(err)) {
        // BUG-161 : aucune facture créée, aucun reçu ; on rouvre la désignation d'équipe.
        setFormError(TEAM_NOT_ASSIGNED_MESSAGE);
        requestTeamAssignment();
        return;
      }
      // BUG-230 : `detail` d'abord, puis les erreurs par champ (helper commun).
      setFormError(getErrorDetail(err, 'Erreur lors de la facturation.'));
    } finally {
      setIsSubmitting(false);
    }
  };

  const cancelInvoice = async (item: QueueItem) => {
    const consequence = item.isNonServi
      ? 'Aucun stock n\'est concerné ; la dette éventuelle du client sera annulée.'
      : 'Le stock de pains sera restitué et la balance client ajustée.';
    if (!window.confirm(`Annuler la commande ${item.id} de ${item.clientName} ?\n${consequence}`)) return;
    try {
      await salesApi.cancel(item._apiId);
      setQueue(prev => prev.filter(q => q._apiId !== item._apiId));
    } catch (err: unknown) {
      alert(getErrorDetail(err, 'Erreur lors de l\'annulation.'));
    }
  };

  const confirmDelivery = async (item: QueueItem, deliveredAt?: string) => {
    setDeliveryError(null);
    try {
      const res = await salesApi.deliver(item._apiId, deliveredAt);
      const inv = res.data as Invoice;
      // Build receipt
      // BUG-111 : utiliser le prix réellement facturé et figé par le serveur (InvoiceLine.unit_price,
      // backend/sales/models.py::InvoiceLine.save()) plutôt que le prix catalogue courant (bpMap),
      // sinon le reçu d'une vente soldée affiche un P.U./sous-total de ligne au prix plein alors que
      // le total général (inv.order_total) reste correct.
      const receiptLines: ReceiptLine[] = (inv.lines || []).map(l => ({
        label: bpMap[l.bread_price]?.label || l.bread_price_display || l.bread_price,
        qty: l.quantity,
        unitPrice: l.unit_price != null ? parseFloat(l.unit_price) : (bpMap[l.bread_price]?.unit_price || parseInt(l.bread_price_display || '0')),
      }));
      const built: ReceiptData = {
        receiptNumber: inv.receipt_number,
        boulangerie: inv.node_display || inv.node || '—',
        agentName: user?.first_name ? `${user.first_name} ${user.last_name}` : 'Facturier',
        // BUG-184 : la livraison peut concerner une facture d'un autre utilisateur ou plus
        // ancienne : jamais de repli sur l'équipe de l'utilisateur connecté.
        team: inv.team || '—',
        clientCode: item.clientCode || '—',
        clientName: inv.client_display || item.clientName,
        lines: receiptLines,
        orderTotal: parseFloat(inv.order_total) || item.totalValue,
        versement: parseFloat(inv.payment_amount) || item.versement,
        commissionRate: inv.commission_rate != null ? parseFloat(inv.commission_rate) : item.commissionRate,
        debtBefore: parseFloat(inv.debt_before) || item.debtBefore,
        newDebt: parseFloat(inv.debt_after ?? '0'),
        isSoldee: inv.is_soldee === true,
        totalLoss: parseFloat(inv.total_loss || '0') || 0,
        // BUG-099 : date/heure réelles de la livraison (éventuellement rétroactive,
        // BUG-083) plutôt que l'horloge du navigateur au moment de l'impression.
        transactionDate: inv.delivered_at || inv.invoice_date,
      };
      setReceipt(built);
      setReceiptCache(prev => ({ ...prev, [item._apiId]: built }));
      // BUG-083 : le rechargement habituel est filtré sur la date du jour (`invoice_date`). Une
      // facture rétroactive livrée disparaîtrait donc de la file au lieu d'afficher "Livré" —
      // on met simplement à jour l'entrée locale dans ce cas, sans toucher au comportement normal.
      const todayStr = workDate;
      if (item.invoiceDate && item.invoiceDate !== todayStr) {
        setQueue(prev => prev.map(q => q._apiId === item._apiId ? mapInvoice(inv, bpMap) : q));
      } else {
        await loadData();
      }
      setDeliverModalItem(null);
      setDeliverDate('');
    } catch (err: unknown) {
      const msg = getErrorDetail(err, 'Erreur lors de la confirmation de livraison.');
      setDeliveryError({ id: item._apiId, message: msg });
      console.error('Delivery failed', err);
    }
  };

  // BUG-083 : clic sur « Imprimer le reçu » — si le réglage est actif, propose une petite
  // confirmation avec date de livraison rétroactive optionnelle ; sinon, comportement inchangé
  // (livraison immédiate, datée d'aujourd'hui).
  const handleDeliverClick = (item: QueueItem) => {
    if (allowBackdatedSales) {
      setDeliverDate('');
      setDeliverModalItem(item);
    } else {
      confirmDelivery(item);
    }
  };

  const queueProgressLabel = `calcul en cours… ${queueProgress.loaded}/${queueProgress.total ?? '…'}`;
  const pendingCount = queue.filter(o => o.status === 'En attente' && !o.isNonServi).length;
  const livrésCount = queue.filter(o => o.status === 'Livré').length;  const totalFacture = queue.reduce((a, o) => a + o.totalValue, 0);

  // ── Renders a single delivery-queue card (reused by main view & "Voir plus" modal) ──
  const renderQueueCard = (item: QueueItem, detailed: boolean = false) => {
    // BUG-177 : une NS n'est jamais « à livrer » ; elle est affichée comme enregistrée.
    const isNonServi = item.isNonServi;
    const isPending = item.status === 'En attente' && !isNonServi;
    const avatarColor = `hsl(${(item.clientName.charCodeAt(0) * 37 + (item.clientCode.charCodeAt(3) || 0) * 13) % 360}, 58%, 38%)`;
    return (
      <div key={item.id} style={{
        borderRadius: 'var(--radius-sm)',
        border: `1px solid hsl(var(--${isPending ? 'color-warning' : 'border-color'}) / ${isPending ? '0.5' : '1'})`,
        backgroundColor: isPending ? 'hsl(var(--color-warning) / 0.04)' : 'hsl(var(--bg-secondary))',
        overflow: 'hidden',
        flexShrink: 0,
      }}>
        {/* Card header — receipt + badge */}
        <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid hsl(var(--border-color) / 0.5)`, backgroundColor: 'hsl(var(--bg-tertiary) / 0.5)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', fontSize: '0.72rem' }}>{item.id}</span>
            {item.isRepayment && (
              <span className="badge badge-info" style={{ fontSize: '0.54rem', background: 'hsl(210,80%,50%)', color: '#fff' }}>REMB</span>
            )}
            {!item.isRepayment && item.isSoldee && (
              <span className="badge badge-warning" style={{ fontSize: '0.54rem' }}>SOLDÉE</span>
            )}
            {!item.isRepayment && !item.isSoldee && (
              <span className={`badge ${item.paymentType === 'CASH' ? 'badge-success' : 'badge-secondary'}`} style={{ fontSize: '0.54rem' }}>
                {item.paymentType === 'CASH' ? 'CASH' : 'CRÉDIT'}
              </span>
            )}
            {item.specialCode && (
              <span className="badge badge-info" style={{ fontSize: '0.52rem', opacity: 0.85 }}>{item.specialCode}</span>
            )}
            {/* BUG-109 : trace d'ajustement — badge + référence vers la facture d'origine */}
            {item.isAdjustment && (
              <span
                className="badge"
                title={`Ajustement de la facture ${queue.find(o => o._apiId === item.adjustsId)?.id || item.adjustsId}`}
                style={{ fontSize: '0.52rem', background: item.adjustmentSign === -1 ? 'hsl(0,70%,45%)' : 'hsl(150,60%,35%)', color: '#fff' }}
              >
                AJUST. {item.adjustmentSign === -1 ? '−' : '+'} · réf {queue.find(o => o._apiId === item.adjustsId)?.id || item.adjustsId}
              </span>
            )}
            {!item.isAdjustment && item.adjustmentsCount > 0 && (
              <span className="badge badge-info" style={{ fontSize: '0.5rem' }}>
                {item.adjustmentsCount} ajustement{item.adjustmentsCount > 1 ? 's' : ''}
              </span>
            )}
            {detailed && (
              <span className="badge badge-info" style={{ fontSize: '0.56rem' }}>{item.nodeDisplay}</span>
            )}
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>
              {detailed ? `${item.invoiceDate ? new Date(item.invoiceDate).toLocaleDateString('fr-FR') : '—'} ${item.timeAdded}` : item.timeAdded}
            </span>
          </div>
          <span className={`badge ${isNonServi ? 'badge-secondary' : isPending ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.58rem' }}>
            {isNonServi ? 'NON SERVIE — ENREGISTRÉE' : item.status.toUpperCase()}
          </span>
        </div>

        {/* Card body */}
        <div style={{ padding: '10px 12px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>

          {/* CLIENT PHOTO — §4.1.2: identification visuelle obligatoire */}
          <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
            <div style={{
              width: '52px', height: '52px', borderRadius: '8px', flexShrink: 0,
              border: `2px solid hsl(var(--${isPending ? 'color-warning' : 'border-color'}) / 0.6)`,
              overflow: 'hidden', backgroundColor: avatarColor,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {item.clientPhoto ? (
                <img
                  src={item.clientPhoto}
                  alt={`Photo ${item.clientName}`}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              ) : (
                <span style={{ color: '#fff', fontWeight: 800, fontSize: '1.1rem', lineHeight: 1 }}>
                  {item.clientName.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
                </span>
              )}
            </div>
            {!item.clientPhoto && (
              <span style={{ fontSize: '0.5rem', color: 'hsl(var(--color-warning))', fontWeight: 700, textAlign: 'center', lineHeight: 1.2 }}>
                PAS DE<br/>PHOTO
              </span>
            )}
          </div>

          {/* Client info + order lines */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: '4px' }}>
              <span style={{ fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--accent-color))', backgroundColor: 'hsl(var(--accent-glow))', padding: '1px 5px', borderRadius: '3px', marginRight: '6px' }}>
                {item.clientCode}
              </span>
              <span style={{ fontWeight: 800, fontSize: '0.85rem', color: 'hsl(var(--text-primary))' }}>
                {item.clientName}
              </span>
            </div>

            {/* Order lines */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '6px' }}>
              {item.lines.map((l, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem' }}>
                  <span style={{ fontWeight: 800, color: 'hsl(var(--text-primary))', minWidth: '28px' }}>{l.qty}×</span>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>{l.label}</span>
                  <span style={{ marginLeft: 'auto', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>
                    {(l.qty * (bpMap[Object.keys(bpMap).find(k => bpMap[k]?.label === l.label) ?? '']?.unit_price || 0)).toLocaleString('fr-FR')} FC
                  </span>
                </div>
              ))}
            </div>

            {/* Financial summary */}
            <div style={{ display: 'flex', gap: '12px', fontSize: '0.65rem', flexWrap: 'wrap' }}>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                Total: <strong style={{ color: 'hsl(var(--accent-color))' }}>{item.totalValue.toLocaleString('fr-FR')} FC</strong>
              </span>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                Versé: <strong style={{ color: 'hsl(var(--color-success))' }}>{item.versement.toLocaleString('fr-FR')} FC</strong>
              </span>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                BP avant: <strong style={{ color: item.debtBefore > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{item.debtBefore.toLocaleString('fr-FR')} FC</strong>
              </span>
              {item.isSoldee && item.totalLoss > 0 && (
                <span style={{ color: 'hsl(var(--text-secondary))' }} title="Perte attendue du mécanisme de vente soldée (-25% sur le prix catalogue)">
                  Perte (soldée): <strong style={{ color: 'hsl(38, 92%, 38%)' }}>-{item.totalLoss.toLocaleString('fr-FR')} FC</strong>
                </span>
              )}
              {detailed && (
                <>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>
                    Mode: <strong>{item.paymentType === 'CASH' ? 'CASH' : 'CRÉDIT'}</strong>
                  </span>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>
                    BP après: <strong style={{ color: item.debtAfter > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{item.debtAfter.toLocaleString('fr-FR')} FC</strong>
                  </span>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>
                    Commission: <strong>{(item.commissionRate * 100).toFixed(0)}%</strong>
                  </span>
                </>
              )}
            </div>

            {detailed && (
              <div style={{ display: 'flex', gap: '12px', fontSize: '0.65rem', flexWrap: 'wrap', marginTop: '4px', color: 'hsl(var(--text-muted))' }}>
                <span>Facturier: <strong style={{ color: 'hsl(var(--text-secondary))' }}>{item.facturierDisplay}</strong></span>
                {item.livreurDisplay && (
                  <span>Livreur: <strong style={{ color: 'hsl(var(--text-secondary))' }}>{item.livreurDisplay}</strong></span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Action footer */}
        {isPending && (() => {
          const msLeft = 12 * 3600 * 1000 - (Date.now() - new Date(item.createdAt).getTime());
          const hLeft = Math.floor(msLeft / 3600000);
          const mLeft = Math.floor((msLeft % 3600000) / 60000);
          const isUrgent = msLeft < 3600000;
          return (
            <div style={{ padding: '8px 12px', borderTop: `1px solid hsl(var(--color-warning) / 0.2)`, backgroundColor: 'hsl(var(--color-warning) / 0.04)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.6rem', color: isUrgent ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))', fontWeight: isUrgent ? 700 : 400 }}>
                <FiClock style={{ fontSize: '0.68rem', flexShrink: 0 }} />
                <span>
                  {msLeft > 0
                    ? `Expire dans ${hLeft}h${String(mLeft).padStart(2, '0')}`
                    : 'Expirée — sera supprimée au prochain rechargement'}
                </span>
              </div>
              {deliveryError && deliveryError.id === item._apiId && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 9px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                  <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                  <span>{deliveryError.message}</span>
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: 'auto 1fr', gap: '6px' }}>
                <button
                  onClick={() => cancelInvoice(item)}
                  className="btn btn-secondary"
                  style={{ padding: '7px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.4)' }}
                  title="Annuler la commande — restitue le stock et la balance client"
                >
                  <FiX />
                  <span>Annuler</span>
                </button>
                <button
                  onClick={() => handleDeliverClick(item)}
                  className="btn btn-primary"
                  style={{ padding: '7px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                  title="Confirmer la livraison et imprimer le reçu"
                >
                  <FiPrinter />
                  <span>Imprimer le reçu</span>
                </button>
              </div>
            </div>
          );
        })()}
        {isNonServi && (
          <div style={{ padding: '6px 12px', borderTop: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--text-secondary))', fontSize: '0.7rem', fontWeight: 700 }}>
              <FiCheckCircle />
              <span>Non servie — enregistrée (aucun pain remis, rien à livrer)</span>
            </div>
            <button
              onClick={() => cancelInvoice(item)}
              className="btn btn-secondary"
              style={{ padding: '3px 10px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.4)' }}
              title="Annuler cet enregistrement de non servi"
            >
              <FiX />
              <span>Annuler</span>
            </button>
          </div>
        )}
        {!isPending && !isNonServi && (
          <div style={{ padding: '6px 12px', borderTop: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--color-success))', fontSize: '0.7rem', fontWeight: 700 }}>
              <FiCheckCircle />
              <span>Distribué</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {/* BUG-109 : correction/annulation réservée GERANT+, jamais sur un remboursement
                  ou une facture d'ajustement elle-même (on remonte toujours à l'originale). */}
              {canAdjustInvoice && !item.isAdjustment && !item.isRepayment && (
                <button
                  onClick={() => openAdjustModal(item)}
                  className="btn btn-secondary"
                  style={{ padding: '3px 10px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                  title="Corriger/annuler cette commande via une facture d'ajustement"
                >
                  Ajuster
                </button>
              )}
              {receiptCache[item._apiId] && (
                <button
                  onClick={() => setReceipt(receiptCache[item._apiId])}
                  className="btn btn-secondary"
                  style={{ padding: '3px 10px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <FiPrinter /> Ré-imprimer
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '16px', fontSize: '0.85rem' }}>

      {/* BUG-110 : largeur d'imprimante thermique réellement configurée côté desktop
          (58/80mm) — undefined hors mode desktop, ThermalReceipt retombe alors sur 80mm. */}
      {receipt && <ThermalReceipt receipt={receipt} onClose={() => setReceipt(null)} printId="sales" printerWidthMm={window.kiese?.printerWidthMm ?? 80} />}

      {/* Header */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))', padding: '14px 20px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '1.3rem', fontWeight: 800, marginBottom: '2px' }}>
              Facturation en Chaîne & Livraison
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem' }}>
              Saisie ultra-rapide par code client · Grille tarifaire officielle ETS. KIESE · Reçu thermique intégré
            </p>
          </div>
          <FiTruck style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
        </div>
      </div>

      {/* Stats */}
      <div className="kpi-grid" style={{ gap: '12px' }}>
        {[
          { key: null as 'livrees' | 'total' | null, label: 'EN ATTENTE DE LIVRAISON', value: queueComplete ? `${pendingCount}` : queueProgressLabel, icon: <FiClock />, color: 'var(--color-warning)' },
          { key: 'livrees' as 'livrees' | 'total' | null, label: 'LIVRÉES AUJOURD\'HUI', value: queueComplete ? `${livrésCount}` : queueProgressLabel, icon: <FiCheckCircle />, color: 'var(--color-success)' },
          { key: 'total' as 'livrees' | 'total' | null, label: 'TOTAL FACTURÉ', value: queueComplete ? `${totalFacture.toLocaleString('fr-FR')} FC` : queueProgressLabel, icon: <FiTruck />, color: 'var(--color-info)' },
        ].map((s, i) => (
          <div
            key={i}
            className="glass-card"
            onClick={s.key ? () => setStatModal(s.key) : undefined}
            style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: s.key ? 'pointer' : 'default' }}
          >
            <div style={{ width: '34px', height: '34px', borderRadius: '50%', backgroundColor: `hsl(${s.color} / 0.1)`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: `hsl(${s.color})` }}>{s.icon}</div>
            <div>
              <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>{s.label}</div>
              <h3 style={{ fontSize: '0.95rem', fontWeight: 800 }}>{s.value}</h3>
            </div>
          </div>
        ))}
      </div>

      {/* Main Grid */}
      <div className="split-grid" style={{ '--split-cols': '1.1fr 1.9fr', gap: '16px', alignItems: 'start' } as React.CSSProperties}>

        {/* ── FACTURIER FORM ─────────────────────────────────── */}
        <div className="glass-card" style={{ padding: '16px' }}>
          <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
            <FiPlusCircle style={{ color: 'hsl(var(--accent-color))' }} />
            Nouvelle Facture POS
          </h2>

          <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>

            {/* Vente occasionnelle toggle */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: isOccasional ? 'hsl(var(--color-info) / 0.08)' : 'hsl(var(--bg-tertiary))', border: `1px solid ${isOccasional ? 'hsl(var(--color-info) / 0.3)' : 'hsl(var(--border-color))'}`, cursor: 'pointer' }}
              onClick={() => { setIsOccasional(v => !v); if (!isOccasional) { setSelectedClient(null); setClientSearch(''); } }}
            >
              <input type="checkbox" checked={isOccasional} onChange={() => {}} style={{ cursor: 'pointer', accentColor: 'hsl(var(--color-info))' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: isOccasional ? 'hsl(var(--color-info))' : 'hsl(var(--text-secondary))' }}>
                Vente occasionnelle (sans client enregistré)
              </span>
            </div>

            {/* BUG-090 : un remboursement/dépôt exige un client enregistré — rappel visible
                dès que la vente occasionnelle est cochée, pour ne pas induire en erreur le
                facturier qui chercherait ce bouton sans l'avoir trouvé. */}
            {isOccasional && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                Un remboursement de dette ou un dépôt épargne nécessite un client enregistré — décochez « Vente occasionnelle » et recherchez le client.
              </div>
            )}

            {/* Vente soldée */}
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: venteSoldee ? 'hsl(var(--color-warning) / 0.08)' : 'hsl(var(--bg-tertiary))', border: `1px solid ${venteSoldee ? 'hsl(var(--color-warning) / 0.4)' : 'hsl(var(--border-color))'}`, cursor: 'pointer' }}
              onClick={() => setVenteSoldee(v => !v)}
            >
              <input type="checkbox" checked={venteSoldee} onChange={() => {}} style={{ cursor: 'pointer', accentColor: 'hsl(var(--color-warning))' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: venteSoldee ? 'hsl(var(--color-warning))' : 'hsl(var(--text-secondary))' }}>
                Vente Soldée / Vente Cash — -25% sur le prix catalogue, 0% commission, manquant non imputé en BP
                {/* BUG-096 : distinct de « Vente occasionnelle » (client non enregistré) — les deux sont combinables. */}
              </span>
            </div>
            {venteSoldee && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                Remise automatique de 25 % appliquée par le serveur sur le prix catalogue de chaque pain ;
                distinct de « Vente occasionnelle » (client non enregistré) — les deux cases sont combinables.
              </div>
            )}

            {/* BUG-052 : Vente sans commission (25%) — distincte et combinable avec « Vente
                Soldée » ci-dessus. Ne change ni le prix ni le traitement de la BP : seule la
                commission (CM) est annulée (remarque.md l.190). */}
            <div
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '7px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: commissionExempt ? 'hsl(var(--color-info) / 0.08)' : 'hsl(var(--bg-tertiary))', border: `1px solid ${commissionExempt ? 'hsl(var(--color-info) / 0.4)' : 'hsl(var(--border-color))'}`, cursor: 'pointer' }}
              onClick={() => setCommissionExempt(v => !v)}
            >
              <input type="checkbox" checked={commissionExempt} onChange={() => {}} style={{ cursor: 'pointer', accentColor: 'hsl(var(--color-info))' }} />
              <span style={{ fontSize: '0.72rem', fontWeight: 700, color: commissionExempt ? 'hsl(var(--color-info))' : 'hsl(var(--text-secondary))' }}>
                Vente sans commission (25%) — geste commercial ponctuel, prix et BP inchangés
              </span>
            </div>
            {commissionExempt && (
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                {venteSoldee
                  ? 'Facture à la fois SOLDÉE (prix à 75%, BP gelée) ET sans commission — les deux cases restent combinables, CM=0 dans tous les cas.'
                  : 'Distinct de « Vente Soldée » (ci-dessus) : ici le prix reste plein et la BP suit la commande normalement, seule la commission (CM) est annulée.'}
              </div>
            )}

            {/* Code spécial optionnel */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
              <button
                type="button"
                onClick={() => { setShowSpecialCode(v => !v); if (showSpecialCode) setSpecialCode(''); }}
                style={{ background: 'none', border: 'none', cursor: 'pointer', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: 0, textDecoration: 'underline' }}
              >
                {showSpecialCode ? '− Code spécial' : '+ Code spécial (NV/RG/NS)'}
              </button>
              {showSpecialCode && (
                <select
                  value={specialCode}
                  onChange={e => setSpecialCode(e.target.value as '' | 'NV' | 'RG' | 'NS')}
                  className="form-input"
                  style={{ height: '28px', fontSize: '0.75rem', flex: 1 }}
                >
                  <option value="">— Aucun</option>
                  <option value="NV">NV — Nouveau client</option>
                  <option value="RG">RG — Régularisation</option>
                  <option value="NS">NS — Non Servi</option>
                </select>
              )}
            </div>

            {/* BUG-083 : date de commande rétroactive — visible seulement si activé en Configuration */}
            {allowBackdatedSales && (
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '2px', textTransform: 'uppercase' }}>
                  Date de la commande (optionnel)
                </label>
                <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                  Laisser vide = aujourd'hui. Jamais une date future.
                </span>
                <input
                  type="date"
                  max={workDate}
                  value={invoiceDate}
                  onChange={e => setInvoiceDate(e.target.value)}
                  className="form-input"
                  style={{ fontSize: '0.78rem', height: '30px', padding: '0 8px' }}
                />
              </div>
            )}

            {/* Predictive client search */}
            {!isOccasional && <div style={{ position: 'relative' }}>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                Client — code ou nom *
              </label>
              <div style={{ position: 'relative' }}>
                <FiSearch style={{ position: 'absolute', left: '9px', top: '50%', transform: 'translateY(-50%)', color: 'hsl(var(--text-muted))', fontSize: '0.85rem', pointerEvents: 'none' }} />
                <input
                  ref={searchRef}
                  type="text"
                  placeholder="Ex: K1-0045 ou KANZA Albert..."
                  value={clientSearch}
                  onChange={e => { setClientSearch(e.target.value); setSelectedClient(null); setShowSuggestions(true); }}
                  onFocus={() => setShowSuggestions(true)}
                  onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
                  className="form-input"
                  style={{ paddingLeft: '28px', paddingRight: selectedClient ? '28px' : '8px', fontSize: '0.78rem', height: '32px', borderColor: selectedClient ? 'hsl(var(--color-success) / 0.5)' : undefined }}
                  autoComplete="off"
                />
                {selectedClient && (
                  <button type="button" onClick={clearClient} style={{ position: 'absolute', right: '6px', top: '50%', transform: 'translateY(-50%)', border: 'none', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-muted))', padding: 0 }}>
                    <FiX style={{ fontSize: '0.8rem' }} />
                  </button>
                )}
              </div>

              {/* État de la recherche serveur — BUG-065 : la saisie reste réactive, l'attente
                  réseau (debounce 350 ms) est visible plutôt que silencieuse */}
              {showSuggestions && !selectedClient && clientSearch.length >= 1 && isSearchingClients && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px',
                  padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--text-muted))'
                }}>
                  Recherche en cours…
                </div>
              )}
              {showSuggestions && !selectedClient && !isSearchingClients && clientSearchError && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--color-danger) / 0.4)',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px',
                  padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))'
                }}>
                  {clientSearchError}
                </div>
              )}
              {showSuggestions && !selectedClient && !isSearchingClients && !clientSearchError
                && clientSearch.length >= 1 && suggestions.length === 0 && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px',
                  padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--text-muted))'
                }}>
                  Aucun client ne correspond à « {clientSearch} ».
                </div>
              )}
              {showSuggestions && suggestions.length > 0 && !selectedClient && !isSearchingClients && (
                <div style={{
                  position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 50,
                  backgroundColor: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))',
                  borderRadius: 'var(--radius-sm)', boxShadow: 'var(--shadow-md)', marginTop: '2px', overflow: 'hidden'
                }}>
                  {suggestions.map(c => (
                    <div
                      key={c.id}
                      onMouseDown={() => selectClient(c)}
                      style={{ padding: '8px 12px', cursor: 'pointer', borderBottom: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}
                      className="theme-picker-btn"
                    >
                      <div>
                        <span style={{ fontWeight: 800, fontSize: '0.72rem', color: 'hsl(var(--accent-color))' }}>{c.code}</span>
                        <span style={{ fontSize: '0.78rem', marginLeft: '8px', fontWeight: 700 }}>{c.full_name}</span>
                        {c.category === 'RISK' && (
                          <span style={{ marginLeft: '6px', fontSize: '0.6rem', fontWeight: 800, padding: '1px 6px', borderRadius: '999px', backgroundColor: 'hsl(var(--color-danger) / 0.15)', color: 'hsl(var(--color-danger))' }}>À risque</span>
                        )}
                      </div>
                      <span style={{ fontSize: '0.65rem', color: parseFloat(c.current_debt) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))', fontWeight: 700 }}>
                        {parseFloat(c.current_debt) > 0 ? `BP: ${parseFloat(c.current_debt).toLocaleString('fr-FR')} FC` : 'Solde OK'}
                      </span>
                    </div>
                  ))}
                </div>
              )}
            </div>}

            {/* Selected client info */}
            {!isOccasional && selectedClient && (
              <div style={{ backgroundColor: 'hsl(var(--color-success) / 0.08)', border: '1px solid hsl(var(--color-success) / 0.25)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.7rem' }}>
                <div>
                  <div style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{selectedClient.code} — {selectedClient.full_name}</div>
                  <div style={{ color: 'hsl(var(--text-secondary))', marginTop: '1px' }}>Taux CM : {(parseFloat(selectedClient.commission_rate) * 100).toFixed(0)}%</div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontWeight: 800, color: parseFloat(selectedClient.current_debt) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>
                    BP : {parseFloat(selectedClient.current_debt).toLocaleString('fr-FR')} FC
                  </div>
                  <div style={{ color: 'hsl(var(--text-muted))' }}>Balance antérieure</div>
                </div>
              </div>
            )}

            {/* BUG-229 : client à risque servi quand même ; le serveur décide du blocage (403). */}
            {!isOccasional && selectedClient && selectedClient.category === 'RISK' && (
              <div role="alert" style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '8px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                Client à risque — BP {parseFloat(selectedClient.current_debt).toLocaleString('fr-FR')} FC
                {parseFloat(selectedClient.credit_limit) > 0 && ` / plafond ${parseFloat(selectedClient.credit_limit).toLocaleString('fr-FR')} FC`}.
                <div style={{ fontWeight: 500, marginTop: '2px' }}>
                  Si la BP atteint le plafond, la facture n'est acceptée que si le versement couvre au moins la valeur de la commande ; sinon le serveur la refuse.
                </div>
              </div>
            )}

            {/* BUG-090 : remboursement de dette / dépôt épargne — paiement seul, sans
                commande de pain. Nécessite un client enregistré (pas une vente occasionnelle). */}
            {!isOccasional && selectedClient && (
              <button
                type="button"
                onClick={() => { setRepaymentAmount(''); setRepaymentDate(''); setRepaymentError(null); setIsRepaymentModalOpen(true); }}
                className="btn btn-secondary"
                style={{ padding: '7px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', color: 'hsl(var(--color-info))', borderColor: 'hsl(var(--color-info) / 0.4)' }}
                title="Enregistrer un versement sans commande de pain : remboursement de dette ou dépôt épargne"
              >
                <FiCreditCard />
                <span>Remboursement / Dépôt sans commande</span>
              </button>
            )}

            {/* Bread quantities — line-by-line with running total */}
            <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>
                Commande (Qté × Catégorie)
              </label>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                {/* Header row */}
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 60px 80px', gap: '4px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase', paddingBottom: '2px' }}>
                  <span>Catégorie</span><span style={{ textAlign: 'right' }}>Qté</span><span style={{ textAlign: 'right' }}>Sous-total</span>
                </div>
                {breadPrices.map(bp => {
                  const qty = quantities[bp.id] || 0;
                  // BUG-107 : sous-total à l'écran avec remise de 75% appliquée (Vente Soldée)
                  const lineTotal = qty * effectiveUnitPrice(bp);
                  return (
                    <div key={bp.id} style={{ display: 'grid', gridTemplateColumns: '1fr 60px 80px', gap: '4px', alignItems: 'center' }}>
                      <span style={{ fontSize: '0.73rem', color: qty > 0 ? 'hsl(var(--text-primary))' : 'hsl(var(--text-secondary))', fontWeight: qty > 0 ? 700 : 400 }}>
                        {bp.label}
                      </span>
                      <input
                        type="number" min={0}
                        value={qty || ''}
                        placeholder="0"
                        onChange={e => setQuantities(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) }))}
                        className="form-input"
                        style={{ fontSize: '0.78rem', height: '28px', padding: '0 6px', textAlign: 'right', fontWeight: 700 }}
                      />
                      <span style={{ fontSize: '0.73rem', textAlign: 'right', fontWeight: lineTotal > 0 ? 800 : 400, color: lineTotal > 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--text-muted))' }}>
                        {lineTotal > 0 ? `${lineTotal.toLocaleString('fr-FR')} FC` : '—'}
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Order total */}
            <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px dashed hsl(var(--border-color))', padding: '8px 10px', borderRadius: 'var(--radius-sm)', display: 'flex', flexDirection: 'column', gap: '2px' }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>Total commande :</span>
                <strong style={{ color: 'hsl(var(--accent-color))', fontSize: '0.88rem' }}>{orderTotal.toLocaleString('fr-FR')} FC</strong>
              </div>
              {/* BUG-107 : rend explicite que le total ci-dessus intègre déjà la remise à 75 %
                  (prix catalogue plein affiché à titre de comparaison, jamais ce qui sera facturé) */}
              {venteSoldee && (
                <div style={{ fontSize: '0.6rem', color: 'hsl(var(--color-warning))', textAlign: 'right' }}>
                  Remise de 25% déjà appliquée (prix catalogue plein : {breadPrices.reduce((s, b) => s + (quantities[b.id] || 0) * b.unit_price, 0).toLocaleString('fr-FR')} FC)
                </div>
              )}
            </div>

            {/* BUG-177 : Non Servi — le type de paiement exprime le choix du client, sans versement */}
            {isNonServiForm && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', textTransform: 'uppercase' }}>
                  Client non servi — dette
                </label>
                <select
                  value={nsPaymentType}
                  onChange={e => setNsPaymentType(e.target.value as 'CASH' | 'CREDIT')}
                  className="form-input"
                  style={{ height: '34px', fontSize: '0.78rem' }}
                  aria-label="Choix du client non servi"
                >
                  <option value="CREDIT">Le client garde la dette</option>
                  <option value="CASH">Payé comptant</option>
                </select>
                <span style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>
                  Aucun pain n'est retiré du stock ; la dette n'est enregistrée que si le client la garde.
                </span>
              </div>
            )}
            {isRegularisationForm && (
              <div style={{ fontSize: '0.64rem', color: 'hsl(var(--text-muted))', padding: '0 2px' }}>
                Régularisation : aucune dette n'est créée (aucun versement à saisir).
              </div>
            )}

            {/* Versement + auto payment type */}
            {!isNonServiForm && !isRegularisationForm && <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-success))', marginBottom: '2px', textTransform: 'uppercase' }}>
                Versement du Jour (FC)
              </label>
              <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>Acompte en espèces versé ce jour</span>
              <div style={{ display: 'grid', gridTemplateColumns: '1fr auto', gap: '6px', alignItems: 'center' }}>
                <input
                  type="number" min={0}
                  value={isCashOnlySale ? orderTotal : (versement || '')}
                  placeholder="0"
                  disabled={isCashOnlySale}
                  onChange={e => setVersement(Math.max(0, Number(e.target.value)))}
                  className="form-input"
                  style={{ fontSize: '0.78rem', height: '30px', padding: '0 8px', borderColor: 'hsl(var(--color-success) / 0.4)', fontWeight: 800 }}
                />
                <span className={`badge ${venteSoldee ? 'badge-warning' : paymentType === 'CASH' ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.6rem', whiteSpace: 'nowrap' }}>
                  {venteSoldee ? 'SOLDÉ ✓' : paymentType === 'CASH' ? 'CASH ✓' : 'CRÉDIT'}
                </span>
              </div>
              {isCashOnlySale && (
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-info))', marginTop: '3px', fontWeight: 700 }}>
                  Vente sans client enregistré : paiement comptant obligatoire, le versement est égal à la valeur de la commande (pas de crédit).
                </div>
              )}
              {selectedClient && orderTotal > 0 && (
                <div style={{ fontSize: '0.62rem', color: venteSoldee ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))', marginTop: '3px', fontWeight: venteSoldee ? 700 : 400 }}>
                  {venteSoldee
                    ? 'Vente soldée — aucune dette ajoutée au BP'
                    : `Nouvelle BP ≈ ${(parseFloat(selectedClient.current_debt) + orderTotal - versement).toLocaleString('fr-FR')} FC`}
                </div>
              )}
            </div>}

            {formError && (
              <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '7px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                <span>{formError}</span>
              </div>
            )}

            <button type="submit" disabled={isSubmitting} className="btn btn-primary" style={{ padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: isSubmitting ? 0.7 : 1 }}>
              <FiCheckCircle />
              <span>{isSubmitting ? 'Enregistrement...' : isNonServiForm ? 'Enregistrer le non servi' : 'Facturer & Mettre en Attente'}</span>
            </button>
          </form>
        </div>

        {/* ── DELIVERY QUEUE ──────────────────────────────────── */}
        <div className="glass-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
            <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiTruck style={{ color: 'hsl(var(--color-info))' }} />
              File des Livraisons — Confirmation & Impression Reçu
            </h2>
            {queue.length > 3 && (
              <button onClick={() => setQueueModalOpen(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', whiteSpace: 'nowrap' }}>
                <span>Voir plus</span>
                <FiChevronRight size={12} />
              </button>
            )}
          </div>

          {isLoading && <div style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Chargement...</div>}
          {queueError && (
            <div role="alert" style={{ textAlign: 'center', padding: '8px', color: 'hsl(var(--color-danger))', fontSize: '0.75rem' }}>
              {queueError}{' '}
              <button onClick={() => { void loadData(); }} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.65rem' }}>Réessayer</button>
            </div>
          )}
          {!isLoading && !queueComplete && !queueError && (
            <div role="status" style={{ textAlign: 'center', padding: '4px', color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}>
              {queueProgress.loaded} / {queueProgress.total ?? '…'} factures chargées…
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {queue.slice(0, 3).map(item => renderQueueCard(item))}

            {!isLoading && queue.length === 0 && (
              <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.78rem' }}>
                <FiTruck style={{ fontSize: '1.8rem', opacity: 0.2, display: 'block', margin: '0 auto 8px' }} />
                Aucune facture en attente de livraison.
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── BUG-083 : confirmation de livraison avec date rétroactive optionnelle ──────────── */}
      <Modal
        isOpen={!!deliverModalItem}
        onClose={() => { setDeliverModalItem(null); setDeliverDate(''); }}
        title="Confirmer la livraison"
        subtitle={deliverModalItem ? `Facture ${deliverModalItem.id} — ${deliverModalItem.clientName}` : undefined}
        maxWidth="420px"
      >
        {deliverModalItem && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '2px', textTransform: 'uppercase' }}>
                Date de livraison (optionnel)
              </label>
              <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                Laisser vide = aujourd'hui. Jamais une date future.
              </span>
              <input
                type="date"
                max={workDate}
                value={deliverDate}
                onChange={e => setDeliverDate(e.target.value)}
                className="form-input"
                style={{ fontSize: '0.78rem', height: '32px', padding: '0 8px' }}
              />
            </div>
            {deliveryError && deliveryError.id === deliverModalItem._apiId && (
              <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 9px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
                {deliveryError.message}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                type="button"
                onClick={() => { setDeliverModalItem(null); setDeliverDate(''); }}
                className="btn btn-secondary"
                style={{ padding: '7px 14px', fontSize: '0.75rem' }}
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => {
                  const todayStr = workDate;
                  const d = deliverDate && deliverDate !== todayStr ? deliverDate : undefined;
                  confirmDelivery(deliverModalItem, d);
                }}
                className="btn btn-primary"
                style={{ padding: '7px 14px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <FiPrinter /> Confirmer & imprimer
              </button>
            </div>
          </div>
        )}
      </Modal>

      {/* ── BUG-090 : remboursement de dette / dépôt épargne (paiement sans commande) ────── */}
      <Modal
        isOpen={isRepaymentModalOpen}
        onClose={() => setIsRepaymentModalOpen(false)}
        title="Remboursement / Dépôt sans commande"
        subtitle={selectedClient ? `${selectedClient.code} — ${selectedClient.full_name}` : undefined}
        maxWidth="380px"
      >
        {selectedClient && (
          <form onSubmit={handleRepaymentSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>
              Un même versement couvre deux cas : réduire une dette existante (<strong>remboursement</strong>),
              ou verser plus que la dette pour un <strong>dépôt épargne</strong> (la BP devient alors négative,
              CLAUDE.md §5.1). Ce versement ne correspond à aucune commande de pain.
            </div>
            <div style={{ display: 'flex', gap: '12px', fontSize: '0.72rem' }}>
              <span>BP actuel : <strong style={{ color: parseFloat(selectedClient.current_debt) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{parseFloat(selectedClient.current_debt).toLocaleString('fr-FR')} FC</strong></span>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                Montant versé (FC) *
              </label>
              <input
                type="number"
                min="1"
                step="1"
                value={repaymentAmount}
                onChange={e => setRepaymentAmount(e.target.value)}
                placeholder="Ex: 10 000"
                className="form-input"
                style={{ height: '34px', fontSize: '0.84rem', fontWeight: 700 }}
                autoFocus
                required
              />
            </div>
            {repaymentAmount && parseFloat(repaymentAmount) > 0 && (
              <div style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.7rem' }}>
                <span style={{ color: 'hsl(var(--text-secondary))' }}>Nouvelle BP après versement : </span>
                <strong style={{ color: (parseFloat(selectedClient.current_debt) - parseFloat(repaymentAmount)) <= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))' }}>
                  {(parseFloat(selectedClient.current_debt) - parseFloat(repaymentAmount)).toLocaleString('fr-FR')} FC
                </strong>
                {(parseFloat(selectedClient.current_debt) - parseFloat(repaymentAmount)) < 0 && (
                  <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>(dépôt épargne — crédit en faveur du client)</span>
                )}
              </div>
            )}
            {allowBackdatedSales && (
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '2px', textTransform: 'uppercase' }}>
                  Date du versement (optionnel)
                </label>
                <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                  Laisser vide = aujourd'hui. Jamais une date future.
                </span>
                <input
                  type="date"
                  max={workDate}
                  value={repaymentDate}
                  onChange={e => setRepaymentDate(e.target.value)}
                  className="form-input"
                  style={{ fontSize: '0.78rem', height: '30px', padding: '0 8px' }}
                />
              </div>
            )}
            {repaymentError && (
              <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '7px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                <span>{repaymentError}</span>
              </div>
            )}
            <div style={{ display: 'flex', gap: '8px' }}>
              <button type="button" onClick={() => setIsRepaymentModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>
                Annuler
              </button>
              <button type="submit" disabled={repaymentLoading || !repaymentAmount} className="btn btn-primary" style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: repaymentLoading ? 0.7 : 1 }}>
                <FiCheckCircle />
                <span>{repaymentLoading ? 'Enregistrement...' : 'Confirmer le versement'}</span>
              </button>
            </div>
          </form>
        )}
      </Modal>

      {/* ── BUG-109 : ajustement d'une facture déjà enregistrée (GERANT+) ─────── */}
      <Modal
        isOpen={isAdjustModalOpen}
        onClose={() => { setIsAdjustModalOpen(false); setAdjustTarget(null); }}
        title="Ajuster une commande"
        subtitle={adjustTarget ? `Facture ${adjustTarget.id} — ${adjustTarget.clientName}` : undefined}
        maxWidth="480px"
      >
        {adjustTarget && (
          <div style={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: '2px' }}>
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '10px' }}>
              Corrige ou annule une commande déjà enregistrée. La facture d'origine n'est jamais
              modifiée : une nouvelle facture d'ajustement, liée, est créée (« grande trace »). Si
              la commission de la période d'origine est déjà clôturée, la Direction/le Comptable en
              sera averti automatiquement — l'ajustement n'est pas bloqué pour autant.
            </div>

            <div style={{ display: 'flex', gap: '8px', marginBottom: '12px' }}>
              <button
                type="button"
                onClick={() => setAdjustSign(1)}
                className={adjustSign === 1 ? 'btn btn-primary' : 'btn btn-secondary'}
                style={{ flex: 1, padding: '8px', fontSize: '0.78rem', fontWeight: 700 }}
              >
                + Augmentation
              </button>
              <button
                type="button"
                onClick={() => setAdjustSign(-1)}
                className={adjustSign === -1 ? 'btn btn-primary' : 'btn btn-secondary'}
                style={{ flex: 1, padding: '8px', fontSize: '0.78rem', fontWeight: 700 }}
              >
                − Diminution
              </button>
            </div>

            <form onSubmit={handleAdjustSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>
                  Ampleur du changement, par catégorie de pain (quantité, toujours positive) *
                </label>
                {breadPrices.length === 0 ? (
                  <p style={{ fontSize: '0.72rem', color: 'hsl(var(--text-muted))' }}>Aucune catégorie de pain active.</p>
                ) : (
                  <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(breadPrices.length, 3)}, 1fr)`, gap: '8px' }}>
                    {breadPrices.map(bp => (
                      <div key={bp.id} style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
                        <label style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>{bp.label}</label>
                        <input
                          type="number"
                          min={0}
                          step={1}
                          value={adjustQtys[bp.id] || ''}
                          onChange={e => setAdjustQtys(prev => ({ ...prev, [bp.id]: parseInt(e.target.value, 10) || 0 }))}
                          className="form-input"
                          style={{ height: '32px', fontSize: '0.78rem', fontWeight: 700 }}
                          placeholder="0"
                        />
                        {(adjustQtys[bp.id] || 0) > 0 && (
                          <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>
                            {(adjustQtys[bp.id] * bp.unit_price).toLocaleString('fr-FR')} FC
                          </span>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                  Versement associé (FC)
                </label>
                <input
                  type="number"
                  min="0"
                  step="1"
                  value={adjustPaymentAmount}
                  onChange={e => setAdjustPaymentAmount(e.target.value)}
                  placeholder="0"
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.84rem', fontWeight: 700 }}
                />
              </div>

              {allowBackdatedSales && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Date de l'ajustement (optionnel)
                  </label>
                  <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                    Laisser vide = aujourd'hui. Jamais une date future.
                  </span>
                  <input
                    type="date"
                    max={workDate}
                    value={adjustDate}
                    onChange={e => setAdjustDate(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.78rem', padding: '0 8px' }}
                  />
                </div>
              )}

              {adjustError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '7px 10px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))', display: 'flex', alignItems: 'flex-start', gap: '6px' }}>
                  <FiAlertCircle style={{ flexShrink: 0, marginTop: '1px' }} />
                  <span>{adjustError}</span>
                </div>
              )}

              <div style={{ display: 'flex', gap: '8px' }}>
                <button
                  type="button"
                  onClick={() => { setIsAdjustModalOpen(false); setAdjustTarget(null); }}
                  className="btn btn-secondary"
                  style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={adjustLoading}
                  className="btn btn-primary"
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: adjustLoading ? 0.7 : 1 }}
                >
                  <FiCheckCircle />
                  <span>{adjustLoading ? 'Enregistrement...' : "Confirmer l'ajustement"}</span>
                </button>
              </div>
            </form>
          </div>
        )}
      </Modal>

      {/* ── "Voir plus" Modal: full delivery queue ────────────────────────── */}
      <Modal
        isOpen={queueModalOpen}
        onClose={() => setQueueModalOpen(false)}
        title="File des Livraisons — Liste Complète"
        subtitle={queueComplete ? `${queue.length} facture(s) du jour.` : `Chargement en cours (${queueProgress.loaded}/${queueProgress.total ?? '…'}) — liste partielle.`}
        maxWidth="620px"
      >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {queue.map(item => renderQueueCard(item, true))}
            </div>
      </Modal>

      {/* ── KPI Detail Modals ──────────────────────────────────────────────── */}
      <Modal
        isOpen={!!statModal}
        onClose={() => setStatModal(null)}
        title={statModal === 'livrees' ? "Factures Livrées Aujourd'hui" : statModal === 'total' ? 'Total Facturé Aujourd\'hui' : undefined}
        subtitle={
          statModal === 'livrees' ? (queueComplete ? `${livrésCount} facture(s) distribuée(s) avec succès.` : `Chargement en cours (${queueProgress.loaded}/${queueProgress.total ?? '…'}) — liste partielle.`)
          : statModal === 'total' ? (queueComplete ? 'Cumul des factures En attente et Livrées de la journée.' : `Chargement en cours (${queueProgress.loaded}/${queueProgress.total ?? '…'}) — liste partielle.`)
          : undefined
        }
        maxWidth="620px"
      >
            {statModal === 'livrees' && (
              <>
                <div style={{ overflowY: 'auto', flex: 1 }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.66rem', textTransform: 'uppercase' }}>
                        <th>N° Reçu</th>
                        <th>Client</th>
                        <th>Heure</th>
                        <th style={{ textAlign: 'right' }}>Montant</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.74rem' }}>
                      {queue.filter(o => o.status === 'Livré').length === 0 ? (
                        <tr><td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune livraison aujourd'hui.</td></tr>
                      ) : queue.filter(o => o.status === 'Livré').map(o => (
                        <tr key={o.id}>
                          <td><span className="badge badge-info" style={{ fontSize: '0.6rem' }}>{o.id}</span></td>
                          <td style={{ fontWeight: 700 }}>{o.clientName}</td>
                          <td style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.68rem' }}>{o.timeAdded}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>{o.totalValue.toLocaleString('fr-FR')} FC</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {statModal === 'total' && (
              <>
                <div style={{ overflowY: 'auto', flex: 1 }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.66rem', textTransform: 'uppercase' }}>
                        <th>N° Reçu</th>
                        <th>Client</th>
                        <th>Statut</th>
                        <th>Mode</th>
                        <th style={{ textAlign: 'right' }}>Montant</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.74rem' }}>
                      {queue.length === 0 ? (
                        <tr><td colSpan={5} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune facture aujourd'hui.</td></tr>
                      ) : queue.map(o => (
                        <tr key={o.id}>
                          <td><span className="badge badge-info" style={{ fontSize: '0.6rem' }}>{o.id}</span></td>
                          <td style={{ fontWeight: 700 }}>{o.clientName}</td>
                          <td>
                            <span className={`badge ${o.status === 'Livré' ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.58rem' }}>{o.status.toUpperCase()}</span>
                          </td>
                          <td style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>{o.paymentType === 'CASH' ? 'CASH' : 'CRÉDIT'}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{o.totalValue.toLocaleString('fr-FR')} FC</td>
                        </tr>
                      ))}
                    </tbody>
                    {queue.length > 0 && (
                      <tfoot>
                        <tr style={{ fontSize: '0.78rem', borderTop: '2px solid hsl(var(--border-color))' }}>
                          <td colSpan={4} style={{ fontWeight: 800, textAlign: 'right', padding: '8px 0' }}>Total :</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-info))', padding: '8px 0' }}>{queueComplete ? `${totalFacture.toLocaleString('fr-FR')} FC` : queueProgressLabel}</td>
                        </tr>
                      </tfoot>
                    )}
                  </table>
                </div>
              </>
            )}
      </Modal>
    </div>
  );
};
