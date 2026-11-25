import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import {
  clientsApi, salesApi, coreApi,
  Client, BakeryNode, BreadPrice, Invoice,
  SocialContribution,
  BassinRow, ClientImportResult,
} from '@/api/services';
import { getErrorDetail, isTeamNotAssignedError, isSalesBlockedError } from '@/api/errors';
import { useClosureStatusStore } from '@/store/closureStatusStore';
import { useAuthStore } from '@/store/authStore';
import { getWorkDate, useWorkDate, workDateMonthYear } from '@/store/workDateStore';
import { TEAM_NOT_ASSIGNED_MESSAGE, useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { ThermalReceipt, ReceiptData } from '@/components/shared/ThermalReceipt';
import { ClientHistoryModal } from '@/components/clients/ClientHistoryModal';
import {
  ClientItem, ClientDetailTab, DeficitRow, NewClientType, StatModalKind,
  CLIENTS_PAGE_SIZE, mapApiClient, effectiveUnitPrice,
} from '@/components/clients/clientItem';
import { ClientsHeader } from '@/components/clients/ClientsHeader';
import { ClientsKpiGrid } from '@/components/clients/ClientsKpiGrid';
import { ClientsFilters } from '@/components/clients/ClientsFilters';
import { ClientsBulkBar } from '@/components/clients/ClientsBulkBar';
import { ClientsTable } from '@/components/clients/ClientsTable';
import { ImportClientsModal } from '@/components/clients/ImportClientsModal';
import { AddClientModal } from '@/components/clients/AddClientModal';
import { SaleModal } from '@/components/clients/SaleModal';
import { ClientDetailModal } from '@/components/clients/ClientDetailModal';
import { RepaymentModal } from '@/components/clients/RepaymentModal';
import { AdjustInvoiceModal } from '@/components/clients/AdjustInvoiceModal';
import { ClientStatModal } from '@/components/clients/ClientStatModal';
import { BassinsSection } from '@/components/clients/BassinsSection';
import { SocialFundSection } from '@/components/clients/SocialFundSection';

export const Clients: React.FC = () => {
  const { user } = useAuthStore();
  // BUG-161 : jour calendaire du serveur (jamais la date UTC du navigateur) ; 403 TEAM_NOT_ASSIGNED.
  const workDate = useWorkDate();
  const requestTeamAssignment = useTeamAssignmentStore(s => s.requestAssignment);
  const requestClosureRefresh = useClosureStatusStore(s => s.requestRefresh);
  const [clients, setClients] = useState<ClientItem[]>([]);
  const [breadPrices, setBreadPrices] = useState<BreadPrice[]>([]);
  const [debtCeiling, setDebtCeiling] = useState<number>(50000);
  // BUG-083 : réglage global — visible seulement si activé par ADMIN/DIRECTION (Settings.tsx)
  const [allowBackdatedSales, setAllowBackdatedSales] = useState(false);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [addError, setAddError] = useState<string | null>(null);
  const [nodesList, setNodesList] = useState<BakeryNode[]>([]);
  const [selectedNode, setSelectedNode] = useState('');

  // Filtre par boulangerie (utile pour ADMIN/DIRECTION/COMPTABLE/FACTURIER/LIVREUR qui voient toutes les boulangeries)
  const [clientNodeFilter, setClientNodeFilter] = useState('');

  // Search & Filter state
  const [searchTerm, setSearchTerm] = useState('');
  // Terme de recherche réellement envoyé au serveur, avec un léger debounce pour éviter
  // une requête HTTP à chaque frappe (BUG-061 : la recherche doit filtrer côté serveur,
  // pas charger tout le fichier clients puis filtrer en mémoire).
  const [debouncedSearchTerm, setDebouncedSearchTerm] = useState('');
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearchTerm(searchTerm.trim()), 350);
    return () => clearTimeout(timer);
  }, [searchTerm]);
  const [selectedType, setSelectedType] = useState<string>('All');
  const [selectedRisk, setSelectedRisk] = useState<string>('All');

  // BUG-103 : un chargement initial non filtré peut encore avoir des pages en vol quand une
  // recherche plus récente (après le debounce) revient déjà. Sans garde, les pages tardives du
  // premier appel écrasaient `setClients` après coup avec la liste non filtrée. On ignore toute
  // réponse qui n'est plus la dernière requête lancée (même mécanisme que `requestIdRef`/compteur
  // de fraîcheur suggéré au ticket — aucun `AbortController` existant ailleurs dans le code à
  // réutiliser, on reste cohérent avec le style du fichier).
  const loadClientsRequestIdRef = useRef(0);

  // BUG-132 : pour un rôle Siège (ADMIN/DIRECTION/COMPTABLE, `can_access_all_nodes`), la liste
  // couvre les 685+ clients des 8 boulangeries. `clientsApi.list` (via `getList`) attendait TOUTES
  // les pages DRF avant de résoudre : premier affichage très lent. On charge maintenant page par
  // page (`clientsApi.listPage`, page/page_size DRF standard) — la 1ère page (rapide) s'affiche
  // immédiatement, puis le reste continue de charger seul en arrière-plan et s'accumule dans
  // `clients`. Le bouton « Voir plus » existant (`clientsVisibleCount`, cf. plus bas) révèle ce
  // qui a déjà été chargé ; comme le chargement arrière-plan tourne sans attendre de clic, un clic
  // qui arrive avant que la page suivante soit prête revient simplement à attendre qu'elle le soit
  // (choix retenu : pas de second bouton « charger plus » séparé, un seul mécanisme plus simple).
  const [clientsTotalCount, setClientsTotalCount] = useState<number | null>(null);
  const [clientsLoadedCount, setClientsLoadedCount] = useState(0);
  const [clientsBackgroundLoading, setClientsBackgroundLoading] = useState(false);

  const loadClients = useCallback(async () => {
    const requestId = ++loadClientsRequestIdRef.current;
    const isCurrent = () => requestId === loadClientsRequestIdRef.current;
    try {
      setIsLoading(true);
      setLoadError(null);
      setClients([]);
      setClientsTotalCount(null);
      setClientsLoadedCount(0);
      setClientsBackgroundLoading(false);
      const baseParams: Record<string, string> = { page_size: String(CLIENTS_PAGE_SIZE) };
      if (clientNodeFilter) baseParams.node = clientNodeFilter;
      if (debouncedSearchTerm) baseParams.search = debouncedSearchTerm;
      const [firstPage, bpRes, configRes] = await Promise.all([
        clientsApi.listPage({ ...baseParams, page: '1' }),
        coreApi.breadPrices.list(),
        coreApi.config.get(),
      ]);
      if (!isCurrent()) return; // réponse obsolète, ignorée
      setBreadPrices(bpRes.data.filter(b => b.is_active));
      setDebtCeiling(parseFloat(configRes.data.debt_ceiling) || 50000);
      setAllowBackdatedSales(!!configRes.data.allow_backdated_sales);
      const firstResults = firstPage.data.results.map(mapApiClient);
      setClients(firstResults);
      setClientsTotalCount(firstPage.data.count);
      setClientsLoadedCount(firstResults.length);
      setIsLoading(false);

      // Chargement progressif des pages suivantes, en arrière-plan, sans bloquer l'affichage.
      let next = firstPage.data.next;
      let page = 2;
      if (next) setClientsBackgroundLoading(true);
      while (next) {
        if (!isCurrent()) return; // filtre/recherche changé(e) entre-temps : on arrête
        const pageRes = await clientsApi.listPage({ ...baseParams, page: String(page) });
        if (!isCurrent()) return;
        const mapped = pageRes.data.results.map(mapApiClient);
        setClients(prev => [...prev, ...mapped]);
        setClientsLoadedCount(prev => prev + mapped.length);
        next = pageRes.data.next;
        page += 1;
      }
      if (isCurrent()) setClientsBackgroundLoading(false);
    } catch (err: unknown) {
      if (!isCurrent()) return; // réponse obsolète, ignorée
      console.error('Failed to load clients', err);
      setLoadError(getErrorDetail(err, 'Erreur lors du chargement des clients.'));
      setClientsBackgroundLoading(false);
    } finally {
      if (isCurrent()) setIsLoading(false);
    }
  }, [clientNodeFilter, debouncedSearchTerm]);

  useEffect(() => { loadClients(); }, [loadClients]);

  // Pagination — table shows the 20 most recent clients, "Voir plus" reveals more
  const [clientsVisibleCount, setClientsVisibleCount] = useState(20);
  useEffect(() => { setClientsVisibleCount(20); }, [searchTerm, selectedType, selectedRisk]);

  // Selected client for detail modal drawer
  const [selectedClient, setSelectedClient] = useState<ClientItem | null>(null);

  // New Client form state
  const [isAddModalOpen, setIsAddModalOpen] = useState(false);
  const [newName, setNewName] = useState('');
  const [newBusiness, setNewBusiness] = useState('');
  const [newType, setNewType] = useState<NewClientType>('Détaillant');
  const [newPhone, setNewPhone] = useState('');
  const [newAddress, setNewAddress] = useState('');
  const [newCreditLimit, setNewCreditLimit] = useState(50000);
  const [newCommissionRate, setNewCommissionRate] = useState(25);
  const [globalRatePct, setGlobalRatePct] = useState<number | null>(null);
  const rateTouchedRef = useRef(false);
  const [newCotisationSociale, setNewCotisationSociale] = useState('');
  const [newPhoto, setNewPhoto] = useState<File | null>(null);
  const [newPhotoPreview, setNewPhotoPreview] = useState<string | null>(null);

  // Header Dropdown Menu state
  const [isActionMenuOpen, setIsActionMenuOpen] = useState(false);

  // Import clients depuis Excel (Direction centrale uniquement)
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [importFile, setImportFile] = useState<File | null>(null);
  const [importPreview, setImportPreview] = useState<ClientImportResult | null>(null);
  const [importResult, setImportResult] = useState<ClientImportResult | null>(null);
  const [importLoading, setImportLoading] = useState(false);
  const [importError, setImportError] = useState<string | null>(null);

  // Sélection multiple + actions groupées (Direction centrale uniquement)
  const [selectedClientIds, setSelectedClientIds] = useState<Set<string>>(new Set());
  const [bulkMoveTarget, setBulkMoveTarget] = useState('');
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkMsgBar, setBulkMsgBar] = useState<string | null>(null);

  // Sale Modal state
  const [isSaleModalOpen, setIsSaleModalOpen] = useState(false);
  const [saleClient, setSaleClient] = useState<ClientItem | null>(null);
  const [saleQtys, setSaleQtys] = useState<Record<number, number>>({});
  const [versementJour, setVersementJour] = useState<string>('');
  // BUG-230 : vente « Client Occasionnel » (client non identifié) = paiement comptant obligatoire,
  // versement égal à la valeur de la commande, pas de crédit (le serveur refuse sinon, en 400).
  const isCasualSale = !!saleClient && (saleClient.name === 'Client Occasionnel' || saleClient.type === 'Occasionnel');
  // BUG-083 : date de commande rétroactive, optionnelle — vide = aujourd'hui (comportement par défaut).
  const [orderDate, setOrderDate] = useState<string>('');
  const [saleError, setSaleError] = useState<string | null>(null);

  // BUG-083 : la date rétroactive ne doit jamais survivre d'une commande à l'autre.
  useEffect(() => { if (!isSaleModalOpen) setOrderDate(''); }, [isSaleModalOpen]);

  // Remboursement BP modal state
  const [isRepaymentModalOpen, setIsRepaymentModalOpen] = useState(false);
  const [repaymentClient, setRepaymentClient] = useState<ClientItem | null>(null);
  const [repaymentAmount, setRepaymentAmount] = useState('');
  const [repaymentLoading, setRepaymentLoading] = useState(false);
  const [repaymentError, setRepaymentError] = useState<string | null>(null);

  // BUG-109 : ajustement d'une facture déjà enregistrée (GERANT+ uniquement, miroir
  // backend de l'endpoit POST /api/sales/invoices/{id}/adjust/, BUG-097).
  const canAdjustInvoice = ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(user?.role || '');
  const [isAdjustModalOpen, setIsAdjustModalOpen] = useState(false);
  const [adjustTarget, setAdjustTarget] = useState<Invoice | null>(null);
  const [adjustSign, setAdjustSign] = useState<1 | -1>(1);
  const [adjustQtys, setAdjustQtys] = useState<Record<number, number>>({});
  const [adjustPaymentAmount, setAdjustPaymentAmount] = useState('');
  const [adjustDate, setAdjustDate] = useState('');
  const [adjustLoading, setAdjustLoading] = useState(false);
  const [adjustError, setAdjustError] = useState<string | null>(null);

  // Printable Receipt Details state
  const [receiptDetails, setReceiptDetails] = useState<ReceiptData | null>(null);

  // Credit limit edit state (in client detail modal)
  const [isEditingLimit, setIsEditingLimit] = useState(false);
  const [limitInput, setLimitInput] = useState('');

  // Stat card detail modal
  const [statModal, setStatModal] = useState<StatModalKind | null>(null);
  const [deficitData, setDeficitData] = useState<DeficitRow[]>([]);
  const [deficitLoading, setDeficitLoading] = useState(false);

  // Sale form: prevent double-submit
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Add Client form: prevent double-submit
  const [isAddingClient, setIsAddingClient] = useState(false);
  // "Sans commission" / "Vente soldée" checkboxes
  const [sansCommission, setSansCommission] = useState(false);
  const [venteSoldee, setVenteSoldee] = useState(false);
  // Client detail: 3-tab modal (info / history / repayments)
  const [clientDetailTab, setClientDetailTab] = useState<ClientDetailTab>('info');
  const [clientInvoices, setClientInvoices] = useState<Invoice[]>([]);
  const [invoicesLoading, setInvoicesLoading] = useState(false);
  // BUG-1134 : mois/année par défaut = ceux de la journée de travail du serveur (midi à midi).
  const [historyYear, setHistoryYear] = useState(() => workDateMonthYear(getWorkDate()).year);
  const [historyMonth, setHistoryMonth] = useState(() => workDateMonthYear(getWorkDate()).month);

  // §6 Caisse Sociale
  const [socialTab, setSocialTab]               = useState<'cotisations' | 'distribution'>('cotisations');
  const [socialNode, setSocialNode]             = useState('');
  const [socialMonth, setSocialMonth]           = useState(() => workDateMonthYear(getWorkDate()).month);
  const [socialYear, setSocialYear]             = useState(() => workDateMonthYear(getWorkDate()).year);
  const [contributions, setContributions]       = useState<SocialContribution[]>([]);
  const [socialLoading, setSocialLoading]       = useState(false);
  const [bulkMsg, setBulkMsg]                   = useState<string | null>(null);

  // BUG-300 : la caisse sociale est réservée au gérant et aux rôles supérieurs (403 sinon).
  // BUG-400 : historique mensuel (même droit que la caisse sociale : gérant et supérieurs).
  const [historyClient, setHistoryClient] = useState<{ id: string; name: string } | null>(null);
  const canReadSocial = !!user && user.role !== 'FACTURIER' && user.role !== 'LIVREUR';

  const loadContributions = useCallback(async () => {
    if (!socialNode || !canReadSocial) return;
    setSocialLoading(true);
    try {
      const res = await clientsApi.contributions.list({ node: socialNode, month: String(socialMonth), year: String(socialYear) });
      setContributions(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setSocialLoading(false); }
  }, [socialNode, socialMonth, socialYear, canReadSocial]);

  useEffect(() => { if (socialTab === 'cotisations') loadContributions(); }, [loadContributions, socialTab]);

  const handleBulkCreate = async () => {
    if (!socialNode) return;
    setBulkMsg(null);
    try {
      const r = await clientsApi.contributions.bulkCreateMonth({ node: socialNode, month: socialMonth, year: socialYear });
      setBulkMsg(`${r.data.created} fiche(s) créée(s), ${r.data.skipped} déjà existante(s).`);
      await loadContributions();
    } catch (e: unknown) { setBulkMsg(getErrorDetail(e, 'Erreur.')); }
  };

  const handleTogglePaid = async (id: number) => {
    try {
      const res = await clientsApi.contributions.togglePaid(id);
      setContributions(prev => prev.map(c => c.id === id ? res.data : c));
    } catch { /* ignore */ }
  };

  // §7 BASSINS
  const [bassinNode, setBassinNode]   = useState('');
  const [bassinMonth, setBassinMonth] = useState(() => workDateMonthYear(getWorkDate()).month);
  const [bassinYear, setBassinYear]   = useState(() => workDateMonthYear(getWorkDate()).year);
  const [bassinRows, setBassinRows]   = useState<BassinRow[]>([]);
  const [bassinThresholds, setBassinThresholds] = useState<Record<string, number>>({});
  const [bassinLoading, setBassinLoading] = useState(false);
  const [bassinMsg, setBassinMsg]     = useState<string | null>(null);

  const loadBassins = async () => {
    if (!bassinNode) return;
    setBassinLoading(true);
    setBassinMsg(null);
    try {
      const res = await clientsApi.bassins({ node: bassinNode, month: String(bassinMonth), year: String(bassinYear) });
      setBassinRows(res.data.rows || []);
      setBassinThresholds(res.data.thresholds || {});
      if ((res.data.rows || []).length === 0) setBassinMsg('Aucune donnée CM pour ce filtre.');
    } catch (e: unknown) { setBassinMsg(getErrorDetail(e, 'Erreur.')); }
    finally { setBassinLoading(false); }
  };

  // Statistics calculations
  const totalOutstanding = clients.reduce((acc, c) => acc + c.outstandingDebt, 0);
  const overdueCount = clients.filter(c => c.outstandingDebt > c.creditLimit).length;
  const activeCount = clients.filter(c => c.active).length;
  // BUG-269 : les KPI calculés côté client ne sont définitifs qu'une fois toutes les pages lues.
  const kpiComplete = !isLoading && !clientsBackgroundLoading
    && clientsTotalCount !== null && clientsLoadedCount === clientsTotalCount;
  const kpiPending = '…';

  const needsNodeSelector = !user?.node;
  // ADMIN/DIRECTION/COMPTABLE (HQ) et FACTURIER/LIVREUR voient les clients de toutes
  // les boulangeries (cf. get_queryset backend) — seuls eux ont besoin du filtre boulangerie.
  const canFilterByNode = !!user?.can_access_all_nodes || user?.role === 'FACTURIER' || user?.role === 'LIVREUR';

  // Load nodes list for DIRECTION/FACTURIER/LIVREUR users (filtre boulangerie + section Social)
  useEffect(() => {
    if (canFilterByNode && nodesList.length === 0) {
      coreApi.nodes.list().then(res => setNodesList(res.data)).catch(() => {});
    }
    // For GERANT users, pre-set socialNode to their own node
    if (user?.node && !socialNode) setSocialNode(user.node);
    if (user?.node && !bassinNode) setBassinNode(user.node);
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user]);

  const openAddModal = async () => {
    setAddError(null);
    setSelectedNode('');
    rateTouchedRef.current = false;
    setIsAddModalOpen(true);
    // BUG-1103 : taux global de repli (la lecture peut être refusée selon le rôle : on ignore).
    coreApi.config.get()
      .then(res => { const r = parseFloat(String(res.data.default_commission_rate)); if (Number.isFinite(r)) setGlobalRatePct(Math.round(r * 100)); })
      .catch(() => {});
    if (nodesList.length === 0) {
      try {
        const res = await coreApi.nodes.list();
        setNodesList(res.data);
      } catch { /* ignore */ }
    }
  };

  // BUG-1103 : pré-remplit le taux avec celui de la boulangerie du client (sinon le taux global),
  // tant que l'utilisateur ne l'a pas modifié lui-même.
  useEffect(() => {
    if (!isAddModalOpen || rateTouchedRef.current) return;
    const nodeId = selectedNode || user?.node || '';
    const node = nodesList.find(n => n.id === nodeId);
    const raw = node?.default_commission_rate;
    const pct = raw != null && raw !== '' ? Math.round(parseFloat(raw) * 100) : globalRatePct;
    if (pct != null && Number.isFinite(pct)) setNewCommissionRate(pct);
  }, [isAddModalOpen, selectedNode, nodesList, globalRatePct, user?.node]);

  const closeAddClientModal = () => {
    setIsAddModalOpen(false);
    setAddError(null);
    setSelectedNode('');
    if (newPhotoPreview) URL.revokeObjectURL(newPhotoPreview);
    setNewPhoto(null);
    setNewPhotoPreview(null);
  };

  const handleAddClient = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newName || isAddingClient) return;
    if (needsNodeSelector && !selectedNode) { setAddError('Sélectionnez la boulangerie du client.'); return; }
    setAddError(null);
    setIsAddingClient(true);
    const [first_name, ...rest] = newName.trim().split(' ');
    try {
      const payload: Partial<Client> = {
        first_name,
        last_name: rest.join(' ') || first_name,
        phone: newPhone || '+243 800 000 000',
        address: newAddress || 'Non spécifiée',
        notes: newBusiness,
        credit_limit: newCreditLimit.toString(),
        commission_rate: (newCommissionRate / 100).toFixed(2),
        // BUG-289 : facultatif ; vide = valeur de la boulangerie (effective_cotisation_sociale).
        ...(newCotisationSociale.trim() !== '' ? { cotisation_sociale: newCotisationSociale.trim() } : {}),
        client_type: newType === 'Grossiste' ? 'GROSSISTE' : newType === 'Revendeur' ? 'REVENDEUR' : 'DETAILLANT',
        ...(selectedNode ? { node: selectedNode } : {}),
      };
      if (newPhoto) {
        const formData = new FormData();
        Object.entries(payload).forEach(([key, value]) => {
          if (value !== undefined && value !== null) formData.append(key, String(value));
        });
        formData.append('photo', newPhoto);
        await clientsApi.create(formData);
      } else {
        await clientsApi.create(payload);
      }
      await loadClients();
      setIsAddModalOpen(false);
      setNewName(''); setNewBusiness(''); setNewPhone(''); setNewAddress('');
      setNewCreditLimit(50000); setNewCommissionRate(25); setNewCotisationSociale('');
      if (newPhotoPreview) URL.revokeObjectURL(newPhotoPreview);
      setNewPhoto(null); setNewPhotoPreview(null);
    } catch (err: unknown) {
      const detail = axios.isAxiosError(err) ? err.response?.data : undefined;
      const msg = typeof detail === 'string' ? detail
        : (detail as { detail?: string; node?: string[]; first_name?: string[] } | undefined)?.detail
          || (detail as { node?: string[] } | undefined)?.node?.[0]
          || (detail as { first_name?: string[] } | undefined)?.first_name?.[0]
          || (detail ? JSON.stringify(detail) : undefined) || 'Erreur lors de la création du client.';
      setAddError(msg);
      console.error('Failed to create client', detail || err);
    } finally {
      setIsAddingClient(false);
    }
  };

  const openImportModal = () => {
    setImportFile(null);
    setImportPreview(null);
    setImportResult(null);
    setImportError(null);
    setIsImportModalOpen(true);
  };

  const handleImportPreview = async () => {
    if (!importFile) return;
    setImportLoading(true);
    setImportError(null);
    try {
      const res = await clientsApi.importExcel(importFile, true);
      setImportPreview(res.data);
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { file?: string; detail?: string } | undefined)
        : undefined;
      setImportError(d?.file || d?.detail || 'Erreur lors de la lecture du fichier.');
    } finally {
      setImportLoading(false);
    }
  };

  const handleImportConfirm = async () => {
    if (!importFile) return;
    setImportLoading(true);
    setImportError(null);
    try {
      const res = await clientsApi.importExcel(importFile, false);
      setImportResult(res.data);
      setImportPreview(null);
      await loadClients();
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { file?: string; detail?: string } | undefined)
        : undefined;
      setImportError(d?.file || d?.detail || "Erreur lors de l'import.");
    } finally {
      setImportLoading(false);
    }
  };

  const toggleSelectClient = (id: string) => {
    setSelectedClientIds(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  };

  const toggleSelectAllVisible = () => {
    const visibleIds = visibleClients.map(c => c._apiId).filter((id): id is string => !!id);
    const allSelected = visibleIds.length > 0 && visibleIds.every(id => selectedClientIds.has(id));
    setSelectedClientIds(prev => {
      const next = new Set(prev);
      if (allSelected) {
        visibleIds.forEach(id => next.delete(id));
      } else {
        visibleIds.forEach(id => next.add(id));
      }
      return next;
    });
  };

  const handleBulkMove = async () => {
    if (selectedClientIds.size === 0 || !bulkMoveTarget || bulkLoading) return;
    setBulkLoading(true);
    setBulkMsgBar(null);
    try {
      const res = await clientsApi.bulkMove(Array.from(selectedClientIds), bulkMoveTarget);
      setBulkMsgBar(`${res.data.moved} client(s) déplacé(s).`);
      setSelectedClientIds(new Set());
      setBulkMoveTarget('');
      await loadClients();
    } catch (err: unknown) {
      setBulkMsgBar(getErrorDetail(err, 'Erreur lors du déplacement.'));
    } finally {
      setBulkLoading(false);
    }
  };

  const handleBulkDelete = async () => {
    if (selectedClientIds.size === 0 || bulkLoading) return;
    if (!window.confirm(`Supprimer ${selectedClientIds.size} client(s) sélectionné(s) ? Cette action est irréversible.`)) return;
    setBulkLoading(true);
    setBulkMsgBar(null);
    try {
      const res = await clientsApi.bulkDelete(Array.from(selectedClientIds));
      let msg = `${res.data.deleted} client(s) supprimé(s).`;
      if (res.data.blocked.length > 0) {
        msg += ` ${res.data.blocked.length} client(s) non supprimé(s) car ils ont des factures/commissions/cotisations liées : ${res.data.blocked.join(', ')}.`;
      }
      setBulkMsgBar(msg);
      setSelectedClientIds(new Set());
      await loadClients();
    } catch (err: unknown) {
      setBulkMsgBar(getErrorDetail(err, 'Erreur lors de la suppression.'));
    } finally {
      setBulkLoading(false);
    }
  };

  // Handle Purchase Sale Submission
  const handleSaleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!saleClient || isSubmitting) return;
    setIsSubmitting(true);
    setSaleError(null);

    const saleLines = breadPrices.filter(bp => (saleQtys[bp.id] || 0) > 0);
    if (saleLines.length === 0) {
      setSaleError('Déclarez au moins une catégorie de pains.');
      setIsSubmitting(false);
      return;
    }

    // BUG-107 : remise de 75% (Vente Soldée) appliquée dès ce calcul — reflète exactement ce
    // que le serveur facturera (`InvoiceLine.save()`), évite un reçu affichant le prix catalogue.
    const valeurCommande = saleLines.reduce((s, bp) => s + saleQtys[bp.id] * effectiveUnitPrice(bp, venteSoldee), 0);
    const clientLimit = saleClient.creditLimit || debtCeiling;
    // Vente soldée : versement réel enregistré, manquant passé en perte (is_soldee flag)
    const effectivePayment = isCasualSale ? valeurCommande : (parseFloat(versementJour) || 0);
    if (saleLines.some(bp => !Number.isInteger(saleQtys[bp.id]) || saleQtys[bp.id] > 100000)) {
      setSaleError('Chaque quantité doit être un nombre entier compris entre 1 et 100 000.');
      setIsSubmitting(false);
      return;
    }
    if (effectivePayment < 0) {
      setSaleError('Le versement ne peut pas être négatif.');
      setIsSubmitting(false);
      return;
    }
    if (!venteSoldee && saleClient.outstandingDebt >= clientLimit && effectivePayment < valeurCommande) {
      setSaleError(`Plafond de crédit atteint (${saleClient.outstandingDebt.toLocaleString('fr-FR')} FC ≥ ${clientLimit.toLocaleString('fr-FR')} FC). Réglez intégralement la commande ou remboursez la dette.`);
      setIsSubmitting(false);
      return;
    }
    const commissionRate = (sansCommission || venteSoldee) ? 0 : saleClient.commissionRate;
    const balanceAnterieure = saleClient.outstandingDebt;
    // Vente soldée : manquant en perte, BP inchangé
    const nouvelleDette = venteSoldee
      ? balanceAnterieure
      : balanceAnterieure + valeurCommande - effectivePayment;

    let receiptId = `F-${Math.floor(100000 + Math.random() * 900000)}`;
    // BUG-099 : facture renvoyée par la confirmation de livraison — porte la date/heure
    // réelles (`delivered_at`/`invoice_date`), y compris rétroactives (BUG-083) — à
    // transmettre au reçu plutôt que l'horloge du navigateur au moment de l'impression.
    let deliveredInvoice: Invoice | null = null;
    // BUG-184 : équipe portée par la facture (équipe de service désignée si rotation active).
    let invoiceTeam = '';

    // BUG-083 : date rétroactive optionnelle (réglage ADMIN/DIRECTION). Vide ou date du jour
    // → comportement inchangé (aucun champ envoyé, le serveur date normalement).
    const todayStr = workDate;
    const retroactiveDate = allowBackdatedSales && orderDate && orderDate !== todayStr ? orderDate : null;

    // Determine client API ID — for occasional sale, find or auto-create one
    let clientApiId = saleClient._apiId;
    if (!clientApiId) {
      const existingOcc = clients.find(c => c._apiId && c.name === 'Client Occasionnel');
      if (existingOcc) {
        clientApiId = existingOcc._apiId;
      } else {
        try {
          const res = await clientsApi.create({
            first_name: 'Client', last_name: 'Occasionnel',
            phone: '+243 000 000 000', address: 'Vente directe au comptoir', notes: 'Occasionnel',
          });
          clientApiId = res.data.id;
        } catch (err) {
          console.error('Failed to create occasionnel client', err);
        }
      }
    }

    if (clientApiId) {
      try {
        const res = await salesApi.create({
          client: clientApiId,
          payment_amount: effectivePayment.toString(),
          payment_type: isCasualSale || effectivePayment >= valeurCommande ? 'CASH' : 'CREDIT',
          // BUG-230 : `commission_rate` n'est plus envoyé (le serveur applique le taux du client).
          ...(venteSoldee ? { is_soldee: true } : {}),
          // BUG-052 : exonération de commission dédiée, indépendante de « Vente Soldée » —
          // forcée côté serveur (comm_rate=0) même si combinée avec is_soldee (§ ci-dessus).
          ...(sansCommission ? { commission_exempt: true } : {}),
          ...(retroactiveDate ? { invoice_date: retroactiveDate } : {}),
          lines: saleLines.map(bp => ({ bread_price: bp.id, quantity: saleQtys[bp.id] })),
        });
        receiptId = res.data.receipt_number || receiptId;
        invoiceTeam = res.data.team || '';
        // Immediately confirm delivery (no PENDING queue for client sales)
        try {
          const deliverRes = await salesApi.deliver(res.data.id, undefined, retroactiveDate || undefined);
          deliveredInvoice = deliverRes.data;
        } catch (deliverErr) {
          console.error('Auto-deliver failed', deliverErr);
        }
        await loadClients();
      } catch (err: unknown) {
        if (isTeamNotAssignedError(err)) {
          // BUG-161 : équipe de service non désignée — aucune facture, aucun reçu ;
          // la boîte de désignation du tableau de bord se rouvre (comme Sales.tsx).
          setSaleError(TEAM_NOT_ASSIGNED_MESSAGE);
          requestTeamAssignment();
          setIsSubmitting(false);
          return;
        }
        // BUG-973 : clôture du jour en attente de validation -> message du serveur + relecture du statut.
        if (isSalesBlockedError(err)) requestClosureRefresh();
        // BUG-230 : `detail` d'abord, puis erreurs par champ (helper commun).
        setSaleError(getErrorDetail(err, 'Erreur lors de la facturation.'));
        setIsSubmitting(false);
        return;
      }
    }

    setReceiptDetails({
      receiptNumber: receiptId,
      boulangerie: user?.node_display || user?.node || 'ETS. KIESE',
      agentName: user ? `${user.first_name || ''} ${user.last_name || ''}`.trim() || 'GÉRANT' : 'GÉRANT',
      // BUG-184 : équipe de la facture ; repli sur l'équipe de l'utilisateur uniquement
      // pour cette facture qu'il vient de créer (anciennes factures sans équipe).
      team: deliveredInvoice?.team || invoiceTeam || user?.team || '—',
      clientName: saleClient.name,
      clientCode: saleClient.id,
      // BUG-107 : prix unitaire réduit (Vente Soldée) affiché ligne par ligne sur le reçu,
      // cohérent avec `orderTotal` ci-dessous (évite un P.U. catalogue incohérent avec le total).
      lines: saleLines.map(bp => ({ label: bp.label, qty: saleQtys[bp.id], unitPrice: effectiveUnitPrice(bp, venteSoldee) })),
      orderTotal: valeurCommande,
      versement: effectivePayment,
      // BUG-230 : taux appliqué par le serveur (facture livrée) ; repli sur l'estimation locale.
      commissionRate: deliveredInvoice?.commission_rate != null ? parseFloat(deliveredInvoice.commission_rate) : commissionRate,
      debtBefore: balanceAnterieure,
      newDebt: nouvelleDette,
      isSoldee: venteSoldee,
      // BUG-092/BUG-096 : perte calculée par le serveur (prix catalogue × 25% × quantité),
      // issue de la facture livrée — absente/0 si la livraison n'a pas pu être confirmée.
      totalLoss: parseFloat(deliveredInvoice?.total_loss || '0') || 0,
      transactionDate: deliveredInvoice?.delivered_at || deliveredInvoice?.invoice_date,
    });
    setSaleQtys({});
    setSansCommission(false);
    setVenteSoldee(false);
    setIsSubmitting(false);
    setIsSaleModalOpen(false);
  };

  const handleRepaymentSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!repaymentClient?._apiId) return;
    const amount = parseFloat(repaymentAmount);
    if (isNaN(amount) || amount <= 0) {
      setRepaymentError('Montant invalide.');
      return;
    }
    setRepaymentLoading(true);
    setRepaymentError(null);
    try {
      const res = await salesApi.createRepayment(repaymentClient._apiId, amount);
      const inv = res.data;
      // BUG-116 : le client demande à pouvoir imprimer le reçu d'un remboursement
      // de dette / dépôt sans commande, exactement comme celui d'une vente — la
      // facture (sans ligne, `is_debt_repayment: true`) est déjà créée par
      // `createRepayment` ci-dessus ; on ne fait qu'afficher son reçu avec les
      // valeurs réellement renvoyées par le serveur (jamais recalculées ici).
      setReceiptDetails({
        receiptNumber: inv.receipt_number,
        boulangerie: user?.node_display || user?.node || 'ETS. KIESE',
        agentName: user ? `${user.first_name || ''} ${user.last_name || ''}`.trim() || 'GÉRANT' : 'GÉRANT',
        // BUG-184 : équipe de la facture (repli : facture tout juste créée par l'utilisateur).
        team: inv.team || user?.team || '—',
        clientName: repaymentClient.name,
        clientCode: repaymentClient.id,
        lines: [],
        orderTotal: parseFloat(inv.order_total) || 0,
        versement: parseFloat(inv.payment_amount) || 0,
        commissionRate: parseFloat(inv.commission_rate) || 0,
        debtBefore: parseFloat(inv.debt_before) || 0,
        newDebt: parseFloat(inv.debt_after) || 0,
        isSoldee: false,
        totalLoss: 0,
        transactionDate: inv.delivered_at || inv.invoice_date,
      });
      await loadClients();
      setIsRepaymentModalOpen(false);
      setRepaymentAmount('');
      setRepaymentClient(null);
    } catch (err: unknown) {
      if (isTeamNotAssignedError(err)) {
        // BUG-161 : aucune facture ni reçu ; on rouvre la désignation d'équipe.
        setRepaymentError(TEAM_NOT_ASSIGNED_MESSAGE);
        requestTeamAssignment();
      } else {
        setRepaymentError(getErrorDetail(err, 'Erreur lors du remboursement.'));
      }
    } finally {
      setRepaymentLoading(false);
    }
  };

  // BUG-109 : ouvre le formulaire d'ajustement pour une facture existante (déjà
  // livrée ou en attente) — réservé GERANT+, cf. `canAdjustInvoice`.
  const openAdjustModal = (invoice: Invoice) => {
    setAdjustTarget(invoice);
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
      const res = await salesApi.adjust(adjustTarget.id, {
        adjustment_sign: adjustSign,
        payment_amount: paymentAmount.toString(),
        lines,
        ...(allowBackdatedSales && adjustDate && adjustDate !== todayStr ? { invoice_date: adjustDate } : {}),
      });
      // Trace additive dans l'historique déjà chargé, sans tout recharger : la
      // nouvelle facture d'ajustement apparaît immédiatement, et le compteur de
      // l'originale est incrémenté localement (évite un aller-retour réseau).
      setClientInvoices(prev => [
        res.data,
        ...prev.map(inv => inv.id === adjustTarget.id
          ? { ...inv, adjustments_count: (inv.adjustments_count || 0) + 1 }
          : inv),
      ]);
      await loadClients();
      setIsAdjustModalOpen(false);
      setAdjustTarget(null);
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { detail?: string; non_field_errors?: string[] } | undefined)
        : undefined;
      setAdjustError(d?.detail || d?.non_field_errors?.[0] || "Erreur lors de l'ajustement.");
    } finally {
      setAdjustLoading(false);
    }
  };

  // Casual Sale trigger
  const triggerCasualSale = () => {
    setIsActionMenuOpen(false);
    const existingOcc = clients.find(c => c.name === 'Client Occasionnel');
    const casualClient: ClientItem = existingOcc || {
      id: 'OCC-999', _apiId: undefined,
      name: 'Client Occasionnel',
      businessName: 'Vente Directe Au Comptant',
      type: 'Occasionnel',
      phone: 'Non applicable',
      address: 'Vente directe au comptoir',
      creditLimit: 0, outstandingDebt: 0, commissionRate: 0, effectiveCotisation: 0, riskScore: 'Low', active: true,
      avatarColor: 'hsl(200, 10%, 40%)',
      lastPaymentDate: workDate,
      createdAt: new Date().toISOString(),
    };
    setSaleClient(casualClient);
    setSaleQtys({});
    setVersementJour('');
    setSaleError(null);
    setSansCommission(false);
    setVenteSoldee(false);
    setIsSaleModalOpen(true);
  };

  const handleSaveCreditLimit = async () => {
    if (!selectedClient?._apiId) return;
    const newLimit = parseFloat(limitInput.replace(',', '.').replace(/\s/g, ''));
    if (isNaN(newLimit) || newLimit <= 0) return;
    try {
      await clientsApi.update(selectedClient._apiId, { credit_limit: newLimit.toString() });
      await loadClients();
      setSelectedClient(prev => prev ? { ...prev, creditLimit: newLimit } : null);
      setIsEditingLimit(false);
    } catch (err: unknown) {
      console.error('Failed to update credit limit', axios.isAxiosError(err) ? err.response?.data : err);
    }
  };

  // Filter clients
  // La recherche par nom/code est déjà appliquée côté serveur (paramètre `search` de
  // `clientsApi.listPage`, voir `loadClients`) : chaque page reçue correspond déjà au terme
  // recherché, même si certaines pages suivantes sont encore en cours de chargement en
  // arrière-plan (BUG-132). Seuls le type et le niveau de risque, non filtrables côté API,
  // restent appliqués ici en mémoire — et peuvent donc être incomplets tant que
  // `clientsBackgroundLoading` est vrai (avertissement affiché plus bas).
  const filteredClients = clients.filter(c => {
    const matchesType = selectedType === 'All' || c.type === selectedType;
    const matchesRisk = selectedRisk === 'All' ||
      (selectedRisk === 'Exceeded' && c.outstandingDebt > c.creditLimit) ||
      (selectedRisk === 'Normal' && c.outstandingDebt <= c.creditLimit);
    return matchesType && matchesRisk;
  });
  // Most recently added first, so "les 20 derniers clients" shows the newest fiches
  const sortedClients = [...filteredClients].sort(
    (a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
  const visibleClients = sortedClients.slice(0, clientsVisibleCount);

  // Ouvre le formulaire de commande pour un client (réinitialise le formulaire).
  const startSale = (client: ClientItem) => {
    setSaleClient(client);
    setSaleQtys({});
    setVersementJour('');
    setSaleError(null);
    setSansCommission(false);
    setVenteSoldee(false);
    setIsSaleModalOpen(true);
  };

  // Ouvre la fiche détaillée d'un client (onglet Informations, historique rechargé à la demande).
  const openClientDetail = (client: ClientItem) => {
    setSelectedClient(client);
    setClientDetailTab('info');
    setClientInvoices([]);
    setHistoryYear(workDateMonthYear(getWorkDate()).year);
    setHistoryMonth(workDateMonthYear(getWorkDate()).month);
  };

  // Ouvre le formulaire de remboursement / dépôt depuis la fiche client (qui se ferme).
  const startRepayment = (client: ClientItem) => {
    setRepaymentClient(client);
    setRepaymentAmount('');
    setRepaymentError(null);
    setSelectedClient(null);
    setIsRepaymentModalOpen(true);
  };
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', fontSize: '0.85rem' }}>

      <ClientsHeader
        canAccessAllNodes={!!user?.can_access_all_nodes}
        openImportModal={openImportModal}
        isActionMenuOpen={isActionMenuOpen}
        setIsActionMenuOpen={setIsActionMenuOpen}
        triggerCasualSale={triggerCasualSale}
        openAddModal={openAddModal}
      />

      <ClientsKpiGrid
        clientsTotalCount={clientsTotalCount}
        kpiComplete={kpiComplete}
        kpiPending={kpiPending}
        activeCount={activeCount}
        overdueCount={overdueCount}
        totalOutstanding={totalOutstanding}
        setStatModal={setStatModal}
        deficitData={deficitData}
        setDeficitData={setDeficitData}
        deficitLoading={deficitLoading}
        setDeficitLoading={setDeficitLoading}
      />

      <ClientsFilters
        searchTerm={searchTerm}
        setSearchTerm={setSearchTerm}
        canFilterByNode={canFilterByNode}
        clientNodeFilter={clientNodeFilter}
        setClientNodeFilter={setClientNodeFilter}
        nodesList={nodesList}
        selectedType={selectedType}
        setSelectedType={setSelectedType}
        selectedRisk={selectedRisk}
        setSelectedRisk={setSelectedRisk}
      />

      {/* Barre d'actions groupées — Direction centrale uniquement */}
      {user?.can_access_all_nodes && selectedClientIds.size > 0 && (
        <ClientsBulkBar
          selectedClientIds={selectedClientIds}
          setSelectedClientIds={setSelectedClientIds}
          nodesList={nodesList}
          bulkMoveTarget={bulkMoveTarget}
          setBulkMoveTarget={setBulkMoveTarget}
          bulkLoading={bulkLoading}
          bulkMsgBar={bulkMsgBar}
          handleBulkMove={handleBulkMove}
          handleBulkDelete={handleBulkDelete}
        />
      )}

      <ClientsTable
        isLoading={isLoading}
        loadError={loadError}
        clientsBackgroundLoading={clientsBackgroundLoading}
        clientsLoadedCount={clientsLoadedCount}
        clientsTotalCount={clientsTotalCount}
        selectedType={selectedType}
        selectedRisk={selectedRisk}
        searchTerm={searchTerm}
        canAccessAllNodes={!!user?.can_access_all_nodes}
        canReadSocial={canReadSocial}
        visibleClients={visibleClients}
        sortedClients={sortedClients}
        clientsVisibleCount={clientsVisibleCount}
        setClientsVisibleCount={setClientsVisibleCount}
        selectedClientIds={selectedClientIds}
        toggleSelectClient={toggleSelectClient}
        toggleSelectAllVisible={toggleSelectAllVisible}
        setHistoryClient={setHistoryClient}
        onStartSale={startSale}
        onOpenDetail={openClientDetail}
      />

      <ImportClientsModal
        isImportModalOpen={isImportModalOpen}
        setIsImportModalOpen={setIsImportModalOpen}
        importFile={importFile}
        setImportFile={setImportFile}
        importPreview={importPreview}
        setImportPreview={setImportPreview}
        importResult={importResult}
        setImportResult={setImportResult}
        importLoading={importLoading}
        importError={importError}
        setImportError={setImportError}
        handleImportPreview={handleImportPreview}
        handleImportConfirm={handleImportConfirm}
      />

      <AddClientModal
        isAddModalOpen={isAddModalOpen}
        closeAddClientModal={closeAddClientModal}
        handleAddClient={handleAddClient}
        needsNodeSelector={needsNodeSelector}
        nodesList={nodesList}
        selectedNode={selectedNode}
        setSelectedNode={setSelectedNode}
        newName={newName}
        setNewName={setNewName}
        newBusiness={newBusiness}
        setNewBusiness={setNewBusiness}
        newType={newType}
        setNewType={setNewType}
        newCreditLimit={newCreditLimit}
        setNewCreditLimit={setNewCreditLimit}
        newCommissionRate={newCommissionRate}
        setNewCommissionRate={(v: number) => { rateTouchedRef.current = true; setNewCommissionRate(v); }}
        newCotisationSociale={newCotisationSociale}
        setNewCotisationSociale={setNewCotisationSociale}
        newPhone={newPhone}
        setNewPhone={setNewPhone}
        newAddress={newAddress}
        setNewAddress={setNewAddress}
        newPhoto={newPhoto}
        setNewPhoto={setNewPhoto}
        newPhotoPreview={newPhotoPreview}
        setNewPhotoPreview={setNewPhotoPreview}
        addError={addError}
        isAddingClient={isAddingClient}
      />

      <SaleModal
        isSaleModalOpen={isSaleModalOpen}
        setIsSaleModalOpen={setIsSaleModalOpen}
        saleClient={saleClient}
        debtCeiling={debtCeiling}
        breadPrices={breadPrices}
        saleQtys={saleQtys}
        setSaleQtys={setSaleQtys}
        venteSoldee={venteSoldee}
        setVenteSoldee={setVenteSoldee}
        sansCommission={sansCommission}
        setSansCommission={setSansCommission}
        versementJour={versementJour}
        setVersementJour={setVersementJour}
        isSubmitting={isSubmitting}
        handleSaleSubmit={handleSaleSubmit}
        isCasualSale={isCasualSale}
        allowBackdatedSales={allowBackdatedSales}
        workDate={workDate}
        orderDate={orderDate}
        setOrderDate={setOrderDate}
        saleError={saleError}
      />
      {/* Thermal Receipt Print Preview Modal — same shared component as Facturier/Tableau de Bord.
          BUG-110 : largeur d'imprimante thermique réellement configurée côté desktop (58/80mm)
          — undefined hors mode desktop, ThermalReceipt retombe alors sur 80mm. */}
      {receiptDetails && (
        <ThermalReceipt receipt={receiptDetails} printId="clients" onClose={() => setReceiptDetails(null)} printerWidthMm={window.kiese?.printerWidthMm ?? 80} />
      )}

      {/* Client Detail Modal — 3 onglets */}
      {selectedClient && (
        <ClientDetailModal
          selectedClient={selectedClient}
          setSelectedClient={setSelectedClient}
          userRole={user?.role}
          isEditingLimit={isEditingLimit}
          setIsEditingLimit={setIsEditingLimit}
          limitInput={limitInput}
          setLimitInput={setLimitInput}
          handleSaveCreditLimit={handleSaveCreditLimit}
          clientDetailTab={clientDetailTab}
          setClientDetailTab={setClientDetailTab}
          clientInvoices={clientInvoices}
          setClientInvoices={setClientInvoices}
          invoicesLoading={invoicesLoading}
          setInvoicesLoading={setInvoicesLoading}
          historyYear={historyYear}
          historyMonth={historyMonth}
          setHistoryYear={setHistoryYear}
          setHistoryMonth={setHistoryMonth}
          canAdjustInvoice={canAdjustInvoice}
          openAdjustModal={openAdjustModal}
          onStartRepayment={startRepayment}
          onStartSale={startSale}
        />
      )}

      {/* ── Modal Remboursement BP ─────────────────────────────────────────── */}
      {isRepaymentModalOpen && repaymentClient && (
        <RepaymentModal
          repaymentClient={repaymentClient}
          setIsRepaymentModalOpen={setIsRepaymentModalOpen}
          handleRepaymentSubmit={handleRepaymentSubmit}
          repaymentAmount={repaymentAmount}
          setRepaymentAmount={setRepaymentAmount}
          repaymentError={repaymentError}
          repaymentLoading={repaymentLoading}
        />
      )}

      {/* ── Modal Ajustement de facture (BUG-109, réservé GERANT+) ───────────── */}
      {isAdjustModalOpen && adjustTarget && (
        <AdjustInvoiceModal
          adjustTarget={adjustTarget}
          setIsAdjustModalOpen={setIsAdjustModalOpen}
          setAdjustTarget={setAdjustTarget}
          adjustSign={adjustSign}
          setAdjustSign={setAdjustSign}
          handleAdjustSubmit={handleAdjustSubmit}
          breadPrices={breadPrices}
          adjustQtys={adjustQtys}
          setAdjustQtys={setAdjustQtys}
          adjustPaymentAmount={adjustPaymentAmount}
          setAdjustPaymentAmount={setAdjustPaymentAmount}
          allowBackdatedSales={allowBackdatedSales}
          adjustDate={adjustDate}
          setAdjustDate={setAdjustDate}
          adjustError={adjustError}
          adjustLoading={adjustLoading}
        />
      )}

      {/* ── Stat Detail Modals ────────────────────────────────────────────── */}
      {statModal && (
        <ClientStatModal
          statModal={statModal}
          setStatModal={setStatModal}
          clients={clients}
          deficitData={deficitData}
          deficitLoading={deficitLoading}
        />
      )}

      {/* ═══ §7 — BASSINS ═══ */}
      {(user?.can_access_all_nodes) && (
        <BassinsSection
          nodesList={nodesList}
          bassinNode={bassinNode}
          setBassinNode={setBassinNode}
          bassinMonth={bassinMonth}
          setBassinMonth={setBassinMonth}
          bassinYear={bassinYear}
          setBassinYear={setBassinYear}
          bassinRows={bassinRows}
          bassinThresholds={bassinThresholds}
          bassinLoading={bassinLoading}
          bassinMsg={bassinMsg}
          loadBassins={loadBassins}
        />
      )}

      {/* ═══ §6 — CAISSE SOCIALE ═══ */}
      <SocialFundSection
        nodesList={nodesList}
        socialNode={socialNode}
        setSocialNode={setSocialNode}
        socialMonth={socialMonth}
        setSocialMonth={setSocialMonth}
        socialYear={socialYear}
        setSocialYear={setSocialYear}
        socialTab={socialTab}
        setSocialTab={setSocialTab}
        handleBulkCreate={handleBulkCreate}
        bulkMsg={bulkMsg}
        socialLoading={socialLoading}
        contributions={contributions}
        handleTogglePaid={handleTogglePaid}
        canReadSocial={canReadSocial}
      />

      <ClientHistoryModal clientId={historyClient?.id ?? null} clientName={historyClient?.name} onClose={() => setHistoryClient(null)} />
    </div>
  );
};