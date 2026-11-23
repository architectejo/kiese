import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FiTruck, FiClock, FiCheckCircle } from 'react-icons/fi';
import { salesApi, clientsApi, coreApi, Invoice, Client, BreadPrice, InvoiceAdjustPayload, ServedLinePayload } from '@/api/services';
import { getErrorDetail, isTeamNotAssignedError, isSalesBlockedError } from '@/api/errors';
import { useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { useClosureStatusStore } from '@/store/closureStatusStore';
import { ClosureBlockBanner } from '@/components/sales/ClosureBlockBanner';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { ThermalReceipt, ReceiptData, ReceiptLine } from '@/components/shared/ThermalReceipt';
import { type InvoiceMotif } from '@/components/sales/MotifSelect';
import { QueueItem, mapInvoice, TEAM_NOT_ASSIGNED_MESSAGE, axiosStatus } from '@/components/sales/salesTypes';
import { InvoiceForm } from '@/components/sales/InvoiceForm';
import { DeliveryQueueCard } from '@/components/sales/DeliveryQueueCard';
import { DeliverModal } from '@/components/sales/DeliverModal';
import { RepaymentModal } from '@/components/sales/RepaymentModal';
import { AdjustModal } from '@/components/sales/AdjustModal';
import { QueueListModal } from '@/components/sales/QueueListModal';
import { StatModal } from '@/components/sales/StatModal';

export const Sales: React.FC = () => {
  const requestTeamAssignment = useTeamAssignmentStore(s => s.requestAssignment);
  const requestClosureRefresh = useClosureStatusStore(s => s.requestRefresh);
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
  // Texte saisi (entier signé) : un champ type="number" empêche le « − » sur certains claviers Android.
  const [versementText, setVersementText] = useState('');
  const [motif, setMotif] = useState<InvoiceMotif>('');
  const [repaymentMotif, setRepaymentMotif] = useState<InvoiceMotif>('');
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
  // BUG-318 : quantités servies saisies sur la carte, transmises via la modale de date rétroactive.
  const [deliverLines, setDeliverLines] = useState<ServedLinePayload[] | undefined>(undefined);

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
      // BUG-318 : l'expiration (12 h -> « Non servi ») est appliquée par le serveur à la lecture ;
      // plus aucun nettoyage côté interface, une facture n'est jamais supprimée.
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
    setVersementText('');
    setMotif('');
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
    if (isNaN(amount) || !Number.isInteger(amount) || amount === 0) { setRepaymentError('Montant invalide : entier non nul (négatif = sortie de caisse).'); return; }
    setRepaymentLoading(true);
    setRepaymentError(null);
    try {
      const todayStr = workDate;
      const retroactiveDate = allowBackdatedSales && repaymentDate && repaymentDate !== todayStr ? repaymentDate : undefined;
      const res = await salesApi.createRepayment(selectedClient.id, amount, retroactiveDate, repaymentMotif);
      const inv = res.data;
      const built: ReceiptData = {
        receiptNumber: inv.receipt_number,
        boulangerie: inv.node_display || inv.node || '—',
        boulangerieCode: inv.node_code ?? null,
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
      setRepaymentMotif('');
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
    if (!isNonServiForm && !isRegularisationForm && (!Number.isInteger(effectiveVersement) || versementText === '-')) {
      setFormError('Le versement doit être un nombre entier (le signe « - » est accepté).');
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
        ...(motif ? { motif } : {}),
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
      // BUG-973 : clôture du jour en attente de validation -> message du serveur + relecture du statut.
      if (isSalesBlockedError(err)) requestClosureRefresh();
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

  const confirmDelivery = async (item: QueueItem, deliveredAt?: string, servedLines?: ServedLinePayload[]) => {
    setDeliveryError(null);
    try {
      const res = await salesApi.deliver(item._apiId, servedLines, deliveredAt);
      const inv = res.data;
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
        boulangerieCode: inv.node_code ?? null,
        agentName: user?.first_name ? `${user.first_name} ${user.last_name}` : 'Facturier',
        // BUG-184 : la livraison peut concerner une facture d'un autre utilisateur ou plus
        // ancienne : jamais de repli sur l'équipe de l'utilisateur connecté.
        team: inv.team || '—',
        clientCode: item.clientCode || '—',
        clientName: inv.client_display || item.clientName,
        lines: receiptLines,
        orderTotal: parseFloat(inv.order_total) || 0,
        // BUG-318 : « commandé initial » si la livraison a été partielle.
        initialOrderTotal: inv.initial_order_total != null ? parseFloat(inv.initial_order_total) || 0 : undefined,
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
      setDeliverLines(undefined);
    } catch (err: unknown) {
      const msg = getErrorDetail(err, 'Erreur lors de la confirmation de livraison.');
      setDeliveryError({ id: item._apiId, message: msg });
      // 409 : la facture a changé de statut entre-temps (déjà non servie / expirée) -> file à jour.
      if (axiosStatus(err) === 409) { setDeliverModalItem(null); await loadData(); }
    }
  };

  // BUG-318 : « Non servi » (motif optionnel). 409 = déjà traitée -> message + rechargement.
  const markNotServed = async (item: QueueItem, reason: string) => {
    setDeliveryError(null);
    try {
      await salesApi.markNotServed(item._apiId, reason || undefined);
      await loadData();
    } catch (err: unknown) {
      setDeliveryError({ id: item._apiId, message: getErrorDetail(err, 'Erreur lors de la déclaration « Non servi ».') });
      if (axiosStatus(err) === 409) await loadData();
    }
  };

  // BUG-083 : clic sur « Imprimer le reçu » — si le réglage est actif, propose une petite
  // confirmation avec date de livraison rétroactive optionnelle ; sinon, comportement inchangé
  // (livraison immédiate, datée d'aujourd'hui).
  const handleDeliverClick = (item: QueueItem, lines?: ServedLinePayload[]) => {
    if (allowBackdatedSales) {
      setDeliverDate('');
      setDeliverLines(lines);
      setDeliverModalItem(item);
    } else {
      confirmDelivery(item, undefined, lines);
    }
  };

  const queueProgressLabel = `calcul en cours… ${queueProgress.loaded}/${queueProgress.total ?? '…'}`;
  const pendingCount = queue.filter(o => o.status === 'En attente' && !o.isNonServi).length;
  const livrésCount = queue.filter(o => o.status === 'Livré').length;  const totalFacture = queue.reduce((a, o) => a + (o.isNotServed ? 0 : o.totalValue), 0);

  // ── Renders a single delivery-queue card (reused by main view & "Voir plus" modal) ──

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

      {/* BUG-973 : blocage des ventes après l'heure de clôture */}
      <ClosureBlockBanner />

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
      <InvoiceForm breadPrices={breadPrices} formError={formError} isSubmitting={isSubmitting} clientSearch={clientSearch} setClientSearch={setClientSearch} isSearchingClients={isSearchingClients} clientSearchError={clientSearchError} selectedClient={selectedClient} setSelectedClient={setSelectedClient} showSuggestions={showSuggestions} setShowSuggestions={setShowSuggestions} isOccasional={isOccasional} setIsOccasional={setIsOccasional} quantities={quantities} setQuantities={setQuantities} versement={versement} setVersement={setVersement} versementText={versementText} setVersementText={setVersementText} motif={motif} setMotif={setMotif} setRepaymentMotif={setRepaymentMotif} venteSoldee={venteSoldee} setVenteSoldee={setVenteSoldee} commissionExempt={commissionExempt} setCommissionExempt={setCommissionExempt} specialCode={specialCode} setSpecialCode={setSpecialCode} showSpecialCode={showSpecialCode} setShowSpecialCode={setShowSpecialCode} nsPaymentType={nsPaymentType} setNsPaymentType={setNsPaymentType} allowBackdatedSales={allowBackdatedSales} invoiceDate={invoiceDate} setInvoiceDate={setInvoiceDate} setIsRepaymentModalOpen={setIsRepaymentModalOpen} setRepaymentAmount={setRepaymentAmount} setRepaymentDate={setRepaymentDate} setRepaymentError={setRepaymentError} workDate={workDate} searchRef={searchRef} suggestions={suggestions} selectClient={selectClient} clearClient={clearClient} effectiveUnitPrice={effectiveUnitPrice} orderTotal={orderTotal} isNonServiForm={isNonServiForm} isRegularisationForm={isRegularisationForm} isCashOnlySale={isCashOnlySale} paymentType={paymentType} handleSubmit={handleSubmit} />

        {/* ── DELIVERY QUEUE ──────────────────────────────────── */}
      <DeliveryQueueCard queue={queue} isLoading={isLoading} queueComplete={queueComplete} queueProgress={queueProgress} queueError={queueError} deliveryError={deliveryError} setReceipt={setReceipt} receiptCache={receiptCache} setQueueModalOpen={setQueueModalOpen} canAdjustInvoice={canAdjustInvoice} loadData={loadData} openAdjustModal={openAdjustModal} cancelInvoice={cancelInvoice} markNotServed={markNotServed} handleDeliverClick={handleDeliverClick} />
      </div>

      {/* ── BUG-083 : confirmation de livraison avec date rétroactive optionnelle ──────────── */}
      <DeliverModal deliveryError={deliveryError} deliverModalItem={deliverModalItem} setDeliverModalItem={setDeliverModalItem} deliverDate={deliverDate} setDeliverDate={setDeliverDate} deliverLines={deliverLines} setDeliverLines={setDeliverLines} workDate={workDate} confirmDelivery={confirmDelivery} />

      {/* ── BUG-090 : remboursement de dette / dépôt épargne (paiement sans commande) ────── */}
      <RepaymentModal selectedClient={selectedClient} repaymentMotif={repaymentMotif} setRepaymentMotif={setRepaymentMotif} allowBackdatedSales={allowBackdatedSales} isRepaymentModalOpen={isRepaymentModalOpen} setIsRepaymentModalOpen={setIsRepaymentModalOpen} repaymentAmount={repaymentAmount} setRepaymentAmount={setRepaymentAmount} repaymentDate={repaymentDate} setRepaymentDate={setRepaymentDate} repaymentLoading={repaymentLoading} repaymentError={repaymentError} workDate={workDate} handleRepaymentSubmit={handleRepaymentSubmit} />

      {/* ── BUG-109 : ajustement d'une facture déjà enregistrée (GERANT+) ─────── */}
      <AdjustModal breadPrices={breadPrices} allowBackdatedSales={allowBackdatedSales} isAdjustModalOpen={isAdjustModalOpen} setIsAdjustModalOpen={setIsAdjustModalOpen} adjustTarget={adjustTarget} setAdjustTarget={setAdjustTarget} adjustSign={adjustSign} setAdjustSign={setAdjustSign} adjustQtys={adjustQtys} setAdjustQtys={setAdjustQtys} adjustPaymentAmount={adjustPaymentAmount} setAdjustPaymentAmount={setAdjustPaymentAmount} adjustDate={adjustDate} setAdjustDate={setAdjustDate} adjustLoading={adjustLoading} adjustError={adjustError} workDate={workDate} handleAdjustSubmit={handleAdjustSubmit} />

      {/* ── "Voir plus" Modal: full delivery queue ────────────────────────── */}
      <QueueListModal queue={queue} queueComplete={queueComplete} queueProgress={queueProgress} deliveryError={deliveryError} setReceipt={setReceipt} receiptCache={receiptCache} queueModalOpen={queueModalOpen} setQueueModalOpen={setQueueModalOpen} canAdjustInvoice={canAdjustInvoice} openAdjustModal={openAdjustModal} cancelInvoice={cancelInvoice} markNotServed={markNotServed} handleDeliverClick={handleDeliverClick} />

      {/* ── KPI Detail Modals ──────────────────────────────────────────────── */}
      <StatModal livrésCount={livrésCount} queue={queue} queueComplete={queueComplete} queueProgress={queueProgress} statModal={statModal} setStatModal={setStatModal} queueProgressLabel={queueProgressLabel} totalFacture={totalFacture} />
    </div>
  );
};
