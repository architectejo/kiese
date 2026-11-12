import React, { useState, useEffect, useCallback, useRef } from 'react';
import axios from 'axios';
import {
  FiUsers, FiPlus, FiSearch, FiDollarSign,
  FiAlertTriangle, FiEye, FiPhone, FiChevronDown,
  FiMapPin, FiArrowRight, FiShield, FiX, FiGrid, FiUserCheck,
  FiShoppingBag, FiCreditCard, FiCheckCircle, FiEdit2, FiSave, FiPrinter, FiDownload
} from 'react-icons/fi';
import {
  clientsApi, salesApi, coreApi,
  Client, Client as ApiClient, BakeryNode, BreadPrice, Invoice,
  SocialContribution, SocialDistribution, SocialDistributionLine,
  BassinRow, ClientImportResult,
} from '@/api/services';
import { getErrorDetail, isTeamNotAssignedError } from '@/api/errors';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { TEAM_NOT_ASSIGNED_MESSAGE, useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { ThermalReceipt, ReceiptData } from '@/components/shared/ThermalReceipt';
import { Modal } from '@/components/shared/Modal';

interface ClientItem {
  id: string;
  _apiId?: string;
  name: string;
  businessName: string;
  type: 'Grossiste' | 'Détaillant' | 'Revendeur' | 'Occasionnel';
  phone: string;
  address: string;
  creditLimit: number;
  outstandingDebt: number;
  commissionRate: number;
  riskScore: 'Low' | 'Medium' | 'High';
  active: boolean;
  avatarColor: string;
  lastPaymentDate: string;
  createdAt: string;
}


const mapApiClient = (c: ApiClient): ClientItem => ({
  id: c.code,
  _apiId: c.id,
  name: c.full_name,
  businessName: c.notes || c.full_name,
  type: c.client_type === 'GROSSISTE' ? 'Grossiste' : c.client_type === 'REVENDEUR' ? 'Revendeur' : 'Détaillant',
  phone: c.phone,
  address: c.address,
  creditLimit: parseFloat(c.credit_limit) || 50000,
  outstandingDebt: parseFloat(c.current_debt) || 0,
  commissionRate: parseFloat(c.commission_rate) || 0.25,
  riskScore: c.category === 'RISK' ? 'High' : c.category === 'BEST' ? 'Low' : 'Medium',
  active: c.is_active,
  avatarColor: `hsl(${(c.code.charCodeAt(0) * 37 + c.code.charCodeAt(2) * 13) % 360}, 65%, 42%)`,
  lastPaymentDate: c.created_at.split('T')[0],
  createdAt: c.created_at,
});

export const Clients: React.FC = () => {
  const { user } = useAuthStore();
  // BUG-161 : jour calendaire du serveur (jamais la date UTC du navigateur) ; 403 TEAM_NOT_ASSIGNED.
  const workDate = useWorkDate();
  const requestTeamAssignment = useTeamAssignmentStore(s => s.requestAssignment);
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
  const CLIENTS_PAGE_SIZE = 50;
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
  const [newType, setNewType] = useState<'Grossiste' | 'Détaillant' | 'Revendeur'>('Détaillant');
  const [newPhone, setNewPhone] = useState('');
  const [newAddress, setNewAddress] = useState('');
  const [newCreditLimit, setNewCreditLimit] = useState(50000);
  const [newCommissionRate, setNewCommissionRate] = useState(25);
  const [newCotisationSociale, setNewCotisationSociale] = useState(3000);
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
  const [statModal, setStatModal] = useState<'plafonds' | 'encours' | 'solvabilite' | 'deficit' | null>(null);
  const [deficitData, setDeficitData] = useState<Array<{
    client_code: string; client_name: string; order_value: string;
    commission_gross: string; current_debt: string; deficit: string; period: string;
  }>>([]);
  const [deficitLoading, setDeficitLoading] = useState(false);

  // Sale form: prevent double-submit
  const [isSubmitting, setIsSubmitting] = useState(false);
  // Add Client form: prevent double-submit
  const [isAddingClient, setIsAddingClient] = useState(false);
  // "Sans commission" / "Vente soldée" checkboxes
  const [sansCommission, setSansCommission] = useState(false);
  const [venteSoldee, setVenteSoldee] = useState(false);
  // BUG-107 : prix effectif affiché (aperçu ET reçu si la livraison serveur n'a pas pu être
  // confirmée) — remise de 75 % appliquée PAR LIGNE puis arrondie au franc le plus proche
  // (ROUND_HALF_UP), même formule que `backend/sales/models.py::InvoiceLine.save()` /
  // `SOLDEE_PRICE_RATIO = Decimal('0.75')`. `Math.round` arrondit déjà au demi supérieur pour
  // un nombre positif, équivalent à ROUND_HALF_UP ici.
  const effectiveUnitPrice = (bp: BreadPrice, soldee: boolean) => (soldee ? Math.round(bp.unit_price * 0.75) : bp.unit_price);
  // Client detail: 3-tab modal (info / history / repayments)
  const [clientDetailTab, setClientDetailTab] = useState<'info' | 'history' | 'repayments'>('info');
  const [clientInvoices, setClientInvoices] = useState<Invoice[]>([]);
  const [invoicesLoading, setInvoicesLoading] = useState(false);
  const [historyYear, setHistoryYear] = useState(() => new Date().getFullYear());
  const [historyMonth, setHistoryMonth] = useState(() => new Date().getMonth() + 1);

  // §6 Caisse Sociale
  const [socialTab, setSocialTab]               = useState<'cotisations' | 'distribution'>('cotisations');
  const [socialNode, setSocialNode]             = useState('');
  const [socialMonth, setSocialMonth]           = useState(() => new Date().getMonth() + 1);
  const [socialYear, setSocialYear]             = useState(() => new Date().getFullYear());
  const [contributions, setContributions]       = useState<SocialContribution[]>([]);
  const [socialLoading, setSocialLoading]       = useState(false);
  const [distributions, setDistributions]       = useState<SocialDistribution[]>([]);
  const [selectedDist, setSelectedDist]         = useState<SocialDistribution | null>(null);
  const [distLines, setDistLines]               = useState<SocialDistributionLine[]>([]);
  const [distLoading, setDistLoading]           = useState(false);
  const [bulkMsg, setBulkMsg]                   = useState<string | null>(null);

  const loadContributions = useCallback(async () => {
    if (!socialNode) return;
    setSocialLoading(true);
    try {
      const res = await clientsApi.contributions.list({ node: socialNode, month: String(socialMonth), year: String(socialYear) });
      setContributions(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setSocialLoading(false); }
  }, [socialNode, socialMonth, socialYear]);

  useEffect(() => { if (socialTab === 'cotisations') loadContributions(); }, [loadContributions, socialTab]);

  const loadDistributions = useCallback(async () => {
    if (!socialNode) return;
    setDistLoading(true);
    try {
      const res = await clientsApi.distributions.list({ node: socialNode, year: String(socialYear) });
      setDistributions(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setDistLoading(false); }
  }, [socialNode, socialYear]);

  useEffect(() => { if (socialTab === 'distribution') loadDistributions(); }, [loadDistributions, socialTab]);

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

  const handleCreateDistribution = async () => {
    if (!socialNode) return;
    try {
      const r = await clientsApi.distributions.create({ node: socialNode, year: socialYear });
      setDistributions(prev => [r.data, ...prev]);
    } catch (e: unknown) { alert(getErrorDetail(e, 'Erreur création.')); }
  };

  const handleAutoPopulate = async (id: number) => {
    try {
      const r = await clientsApi.distributions.autoPopulate(id);
      setBulkMsg(`${r.data.created} ligne(s) créée(s), ${r.data.skipped} existante(s).`);
      setSelectedDist(r.data.distribution);
      setDistLines(r.data.distribution.lines || []);
    } catch (e: unknown) { alert(getErrorDetail(e, 'Erreur auto-population.')); }
  };

  // §7 BASSINS
  const [bassinNode, setBassinNode]   = useState('');
  const [bassinMonth, setBassinMonth] = useState(() => new Date().getMonth() + 1);
  const [bassinYear, setBassinYear]   = useState(() => new Date().getFullYear());
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

  const handleBassinPrint = () => {
    const nodeName = nodesList.find(n => n.id === bassinNode)?.code || '';
    const monthLabel = new Date(2000, bassinMonth - 1).toLocaleString('fr-FR', { month: 'long' });
    const dateStr = new Date().toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
    const CATS = ['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT'];
    const CAT_COLORS = ['#b45309','#1d4ed8','#059669','#7c3aed','#6b7280'];
    const totCmd = bassinRows.reduce((s, r) => s + parseFloat(r.order_value), 0);
    const totBp  = bassinRows.reduce((s, r) => s + parseFloat(r.bp), 0);
    const totCm  = bassinRows.reduce((s, r) => s + parseFloat(r.cm), 0);
    const totNet = bassinRows.reduce((s, r) => s + parseFloat(r.net_payable), 0);
    const catSections = CATS.map((cat, ci) => {
      const rows = bassinRows.filter(r => r.category === cat);
      if (!rows.length) return '';
      const trs = rows.map(r => `<tr>
        <td style="text-align:center;font-weight:bold;color:${CAT_COLORS[ci]}">${r.rank}</td>
        <td style="font-weight:bold;color:#1e40af">${r.client_code}</td>
        <td>${r.client_name}</td>
        <td style="text-align:right">${parseFloat(r.order_value).toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:${parseFloat(r.bp)>0?'#d97706':'#059669'}">${parseFloat(r.bp).toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:#2563eb">${parseFloat(r.cm).toLocaleString('fr-FR')}</td>
        <td style="text-align:right;font-weight:bold;color:${parseFloat(r.net_payable)<0?'#dc2626':'#111'}">${parseFloat(r.net_payable).toLocaleString('fr-FR')}</td>
      </tr>`).join('');
      return `<tr><td colspan="7" style="padding:5px 8px;background:${CAT_COLORS[ci]}18;border-top:2px solid ${CAT_COLORS[ci]}88;font-weight:800;font-size:11px;color:${CAT_COLORS[ci]};letter-spacing:0.05em">${cat} — ${rows.length} client(s)</td></tr>${trs}`;
    }).join('');
    const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Classement BASSINS — ${nodeName}</title>
      <style>*{box-sizing:border-box}body{font-family:Arial,sans-serif;font-size:10.5px;padding:20px;color:#111}
      h1{font-size:14px;margin:0 0 2px}.sub{font-size:10px;color:#666;margin-bottom:14px}
      table{width:100%;border-collapse:collapse}th{background:#f3f4f6;font-weight:bold;padding:5px 7px;border:1px solid #d1d5db;font-size:9.5px;text-transform:uppercase}
      td{padding:4px 7px;border:1px solid #e5e7eb}tr:nth-child(even) td{background:#fafafa}
      tfoot td{font-weight:bold;background:#f3f4f6;border-top:2px solid #9ca3af}
      @media print{body{padding:10px}}</style></head><body>
      <h1>§7 — Classement BASSINS — ${nodeName}</h1>
      <div class="sub">Période : ${monthLabel} ${bassinYear} · Imprimé le ${dateStr} · ${bassinRows.length} client(s)</div>
      <table><thead><tr>
        <th style="text-align:center">Rang</th><th>Code</th><th>Client</th>
        <th style="text-align:right">Commande (FC)</th><th style="text-align:right">BP (FC)</th>
        <th style="text-align:right">CM (FC)</th><th style="text-align:right">Net à Payer (FC)</th>
      </tr></thead><tbody>${catSections}</tbody>
      <tfoot><tr>
        <td colspan="3">${bassinRows.length} client(s)</td>
        <td style="text-align:right">${totCmd.toLocaleString('fr-FR')}</td>
        <td style="text-align:right">${totBp.toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:#2563eb">${totCm.toLocaleString('fr-FR')}</td>
        <td style="text-align:right">${totNet.toLocaleString('fr-FR')}</td>
      </tr></tfoot></table></body></html>`;
    const win = window.open('', '_blank', 'width=1050,height=750');
    if (!win) return;
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => { win.print(); }, 400);
  };

  const handleBassinExport = () => {
    const nodeName = nodesList.find(n => n.id === bassinNode)?.code || '';
    const monthLabel = new Date(2000, bassinMonth - 1).toLocaleString('fr-FR', { month: 'long' });
    const headers = ['Catégorie', 'Rang', 'Code', 'Client', 'Commande (FC)', 'BP (FC)', 'CM (FC)', 'Net à Payer (FC)'];
    const rows = bassinRows.map(r => [
      r.category, r.rank, r.client_code, r.client_name,
      parseFloat(r.order_value), parseFloat(r.bp), parseFloat(r.cm), parseFloat(r.net_payable),
    ]);
    const csv = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(';'))
      .join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `bassins_${nodeName}_${monthLabel}_${bassinYear}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
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
    setIsAddModalOpen(true);
    if (needsNodeSelector && nodesList.length === 0) {
      try {
        const res = await coreApi.nodes.list();
        setNodesList(res.data);
      } catch { /* ignore */ }
    }
  };

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
        cotisation_sociale: newCotisationSociale.toString(),
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
      setNewCreditLimit(50000); setNewCommissionRate(25); setNewCotisationSociale(3000);
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
          const deliverRes = await salesApi.deliver(res.data.id, retroactiveDate || undefined);
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
      creditLimit: 0, outstandingDebt: 0, commissionRate: 0, riskScore: 'Low', active: true,
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

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', fontSize: '0.85rem' }}>

      {/* Page Header */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '20px 24px',
        overflow: 'visible'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div>
            <h1 style={{ fontSize: '1.6rem', fontWeight: 800, marginBottom: '4px', letterSpacing: '-0.02em' }}>
              Gestion Clientèle
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.8rem', maxWidth: '800px' }}>
              Fichier centralisé des revendeurs, calcul automatique du score de risque crédit et alertes de dépassement de plafond.
            </p>
          </div>

          {/* Nouvelle Vente interactive Action Button with Horizontal rollout Drawer */}
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', zIndex: 100 }}>
            {user?.can_access_all_nodes && (
              <button
                onClick={openImportModal}
                className="btn btn-secondary"
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px', fontSize: '0.8rem', height: '38px' }}
              >
                <FiDownload style={{ transform: 'rotate(180deg)' }} />
                <span>Importer (Excel)</span>
              </button>
            )}
            {isActionMenuOpen && (
              <div
                className="animate-fade-in"
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '8px',
                  backgroundColor: 'hsl(var(--bg-tertiary))',
                  border: '1px solid hsl(var(--border-color))',
                  padding: '4px 8px',
                  borderRadius: 'var(--radius-sm)',
                  boxShadow: 'var(--shadow-sm)'
                }}
              >
                <button
                  onClick={triggerCasualSale}
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    fontSize: '0.78rem',
                    whiteSpace: 'nowrap',
                    height: '34px',
                    borderColor: 'hsl(var(--color-info) / 0.3)',
                    backgroundColor: 'hsl(var(--color-info) / 0.05)',
                    color: 'hsl(var(--text-primary))'
                  }}
                >
                  <FiCreditCard style={{ color: 'hsl(var(--color-info))' }} />
                  <span>Vente occasionnelle</span>
                </button>
                <button
                  onClick={() => { setIsActionMenuOpen(false); openAddModal(); }}
                  className="btn btn-secondary"
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '6px',
                    padding: '6px 12px',
                    fontSize: '0.78rem',
                    whiteSpace: 'nowrap',
                    height: '34px',
                    borderColor: 'hsl(var(--accent-color) / 0.3)',
                    backgroundColor: 'hsl(var(--accent-glow))',
                    color: 'hsl(var(--accent-color))'
                  }}
                >
                  <FiPlus />
                  <span>Nouveau client</span>
                </button>
              </div>
            )}

            <button
              onClick={() => setIsActionMenuOpen(!isActionMenuOpen)}
              className="btn btn-primary"
              style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 20px', fontSize: '0.85rem', height: '38px' }}
            >
              <FiShoppingBag />
              <span>Nouvelle vente</span>
              <FiChevronDown style={{ transform: isActionMenuOpen ? 'rotate(180deg)' : 'rotate(0deg)', transition: 'transform 0.2s ease' }} />
            </button>
          </div>
        </div>
      </div>

      {/* KPI Stats Grid */}
      <div className="kpi-grid" style={{ gap: '14px' }}>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--accent-color))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiUsers />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Total Clients</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--text-primary))' }}>{clientsTotalCount !== null ? clientsTotalCount : kpiPending} fiches</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--color-success))', fontWeight: 700 }}>Actifs : {kpiComplete ? activeCount : kpiPending}</span>
          </div>
        </div>

        <div className="glass-card" onClick={() => setStatModal('plafonds')} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-danger))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiAlertTriangle />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Plafonds Dépassés</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--color-danger))' }}>{kpiComplete ? overdueCount : kpiPending} alertes</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>BP à recouvrer</span>
          </div>
        </div>

        <div className="glass-card" onClick={() => setStatModal('encours')} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-info))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiDollarSign />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Encours Global</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--text-primary))' }}>{kpiComplete ? `${totalOutstanding.toLocaleString('fr-FR')} FC` : kpiPending}</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>BP active consolidée</span>
          </div>
        </div>

        <div className="glass-card" onClick={() => setStatModal('solvabilite')} style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}>
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-success))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiUserCheck />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Solvabilité</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--color-success))' }}>A+ Stable</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>Risque moyen pondéré</span>
          </div>
        </div>

        <div
          className="glass-card"
          onClick={async () => {
            setStatModal('deficit');
            if (deficitData.length === 0 && !deficitLoading) {
              setDeficitLoading(true);
              try { const r = await clientsApi.deficitReport(); setDeficitData(r.data); }
              catch { /* ignore */ }
              finally { setDeficitLoading(false); }
            }
          }}
          style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px', cursor: 'pointer' }}
        >
          <div style={{ width: '38px', height: '38px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', color: 'hsl(var(--color-danger))', fontSize: '1.1rem', flexShrink: 0, justifyContent: 'center' }}>
            <FiAlertTriangle />
          </div>
          <div style={{ minWidth: 0 }}>
            <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, marginBottom: '1px', textTransform: 'uppercase', letterSpacing: '0.02em' }}>Déficitaires</p>
            <h3 style={{ fontSize: '1.05rem', fontWeight: 800, marginBottom: '0px', color: 'hsl(var(--color-danger))' }}>{deficitData.length > 0 ? `${deficitData.length} client(s)` : '—'}</h3>
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>BP &gt; CM période</span>
          </div>
        </div>
      </div>

      {/* Filters and Controls */}
      <div className="glass-card" style={{ padding: '14px' }}>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
          {/* Search bar */}
          <div style={{ flex: 2, minWidth: '240px', position: 'relative' }}>
            <FiSearch style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'hsl(var(--text-muted))' }} />
            <input
              type="text"
              placeholder="Rechercher par nom, commerce ou ID..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="form-input"
              style={{ paddingLeft: '36px', height: '36px', fontSize: '0.8rem' }}
            />
          </div>

          {/* Boulangerie filter */}
          {canFilterByNode && (
            <div style={{ flex: 1, minWidth: '170px' }}>
              <select
                value={clientNodeFilter}
                onChange={(e) => setClientNodeFilter(e.target.value)}
                className="form-input"
                style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
              >
                <option value="">Toutes les boulangeries</option>
                {nodesList.map(n => (
                  <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Type filter */}
          <div style={{ flex: 1, minWidth: '150px' }}>
            <select
              value={selectedType}
              onChange={(e) => setSelectedType(e.target.value)}
              className="form-input"
              style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
            >
              <option value="All">Tous les types</option>
              <option value="Grossiste">Grossistes</option>
              <option value="Détaillant">Détaillants</option>
              <option value="Revendeur">Revendeurs</option>
            </select>
          </div>

          {/* Plafond limit status filter */}
          <div style={{ flex: 1, minWidth: '150px' }}>
            <select
              value={selectedRisk}
              onChange={(e) => setSelectedRisk(e.target.value)}
              className="form-input"
              style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
            >
              <option value="All">Tous les statuts de limite</option>
              <option value="Exceeded">Limite dépassée ⚠️</option>
              <option value="Normal">En règle ✅</option>
            </select>
          </div>
        </div>
      </div>

      {/* Barre d'actions groupées — Direction centrale uniquement */}
      {user?.can_access_all_nodes && selectedClientIds.size > 0 && (
        <div className="glass-card animate-fade-in" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 700 }}>{selectedClientIds.size} client(s) sélectionné(s)</span>
          <select
            value={bulkMoveTarget}
            onChange={e => setBulkMoveTarget(e.target.value)}
            className="form-input"
            style={{ height: '32px', fontSize: '0.75rem', width: 'auto', minWidth: '200px' }}
          >
            <option value="">— Déplacer vers —</option>
            {nodesList.map(n => (
              <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
            ))}
          </select>
          <button
            className="btn btn-secondary"
            disabled={!bulkMoveTarget || bulkLoading}
            onClick={handleBulkMove}
            style={{ height: '32px', fontSize: '0.75rem', padding: '0 12px' }}
          >
            {bulkLoading ? '…' : 'Déplacer'}
          </button>
          <button
            className="btn btn-secondary"
            disabled={bulkLoading}
            onClick={handleBulkDelete}
            style={{ height: '32px', fontSize: '0.75rem', padding: '0 12px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.3)' }}
          >
            Supprimer
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setSelectedClientIds(new Set())}
            style={{ height: '32px', fontSize: '0.75rem', padding: '0 12px' }}
          >
            Annuler la sélection
          </button>
          {bulkMsgBar && <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>{bulkMsgBar}</span>}
        </div>
      )}

      {/* Main Glass Clientele Table */}
      <div className="glass-card" style={{ padding: '12px 16px' }}>
        {isLoading && (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))' }}>
            Chargement des clients...
          </div>
        )}
        {!isLoading && loadError && (
          <div style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--color-danger))', fontSize: '0.78rem' }}>
            {loadError}
          </div>
        )}
        {/* BUG-132 : indicateur discret pendant le chargement arrière-plan des pages suivantes
            (le tableau ci-dessous affiche déjà ce qui est arrivé, sans attendre). */}
        {!isLoading && clientsBackgroundLoading && (
          <div style={{
            display: 'flex', alignItems: 'center', gap: '8px', padding: '6px 10px', marginBottom: '8px',
            fontSize: '0.72rem', color: 'hsl(var(--text-secondary))',
            background: 'hsl(var(--accent-color) / 0.08)', borderRadius: '6px',
          }}>
            <span className="spinner" style={{
              width: '12px', height: '12px', border: '2px solid hsl(var(--accent-color) / 0.3)',
              borderTopColor: 'hsl(var(--accent-color))', borderRadius: '50%',
              animation: 'spin 0.8s linear infinite', flexShrink: 0,
            }} />
            Chargement du reste de la liste… {clientsLoadedCount}
            {clientsTotalCount !== null ? ` / ${clientsTotalCount}` : ''} clients chargés.
            {(selectedType !== 'All' || selectedRisk !== 'All') && (
              <span> Les filtres Type/Risque peuvent être incomplets tant que ce chargement n'est pas terminé.</span>
            )}
          </div>
        )}
        {!isLoading && !clientsBackgroundLoading && clientsTotalCount !== null && clientsLoadedCount === clientsTotalCount && clientsTotalCount > CLIENTS_PAGE_SIZE && (
          <div style={{ padding: '4px 10px', marginBottom: '8px', fontSize: '0.7rem', color: 'hsl(var(--color-success))' }}>
            Liste complète chargée ({clientsTotalCount} client(s)).
          </div>
        )}
        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.03em' }}>
                {user?.can_access_all_nodes && (
                  <th style={{ padding: '8px 10px', width: '32px' }}>
                    <input
                      type="checkbox"
                      checked={visibleClients.length > 0 && visibleClients.every(c => c._apiId && selectedClientIds.has(c._apiId))}
                      onChange={toggleSelectAllVisible}
                    />
                  </th>
                )}
                <th style={{ padding: '8px 10px' }}>ID</th>
                <th style={{ padding: '8px 10px' }}>Client</th>
                <th style={{ padding: '8px 10px' }}>BP</th>
                <th style={{ padding: '8px 10px' }}>Risque</th>
                <th style={{ padding: '8px 10px' }}>Statut</th>
                <th style={{ textAlign: 'center', padding: '8px 10px', width: '100px' }}>Actions</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.72rem' }}>
              {visibleClients.map((client) => {
                const isOverLimit = client.outstandingDebt > client.creditLimit;
                return (
                  <tr key={client.id} style={{ transition: 'background-color 0.2s ease' }}>
                    {user?.can_access_all_nodes && (
                      <td style={{ padding: '8px 10px' }}>
                        <input
                          type="checkbox"
                          checked={!!client._apiId && selectedClientIds.has(client._apiId)}
                          onChange={() => client._apiId && toggleSelectClient(client._apiId)}
                        />
                      </td>
                    )}
                    <td style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', padding: '8px 10px' }}>{client.id}</td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <div style={{
                          width: '26px',
                          height: '26px',
                          borderRadius: '50%',
                          backgroundColor: client.avatarColor,
                          color: '#fff',
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'center',
                          fontWeight: 800,
                          fontSize: '0.7rem',
                          flexShrink: 0
                        }}>
                          {client.name.substring(0, 2).toUpperCase()}
                        </div>
                        <div>
                          <div style={{ fontWeight: 800, fontSize: '0.76rem' }}>{client.name}</div>
                          <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>{client.businessName}</div>
                        </div>
                      </div>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', flexDirection: 'column' }}>
                        {client.outstandingDebt < 0 ? (
                          <>
                            <span style={{ fontWeight: 800, color: 'hsl(var(--color-success))', fontSize: '0.78rem' }}>
                              CRÉDIT : {Math.abs(client.outstandingDebt).toLocaleString('fr-FR')} FC
                            </span>
                            <span style={{ fontSize: '0.55rem', color: 'hsl(var(--color-success))', fontWeight: 700 }}>Trop-payé</span>
                          </>
                        ) : (
                          <>
                            <span style={{
                              fontWeight: 800,
                              color: isOverLimit ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))',
                              fontSize: '0.78rem'
                            }}>
                              {client.outstandingDebt.toLocaleString('fr-FR')} FC
                            </span>
                            {isOverLimit && (
                              <span style={{ fontSize: '0.55rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                                +{(client.outstandingDebt - client.creditLimit).toLocaleString('fr-FR')} FC
                              </span>
                            )}
                          </>
                        )}
                      </div>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <span className={`badge ${client.riskScore === 'High' ? 'badge-danger' :
                          client.riskScore === 'Medium' ? 'badge-warning' : 'badge-success'
                        }`} style={{ fontSize: '0.55rem', padding: '1px 3px' }}>
                        {client.riskScore === 'High' ? 'CRITIQUE' : client.riskScore === 'Medium' ? 'MOYEN' : 'MINIME'}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <span className={`badge ${client.active ? 'badge-success' : 'badge-danger'}`} style={{ padding: '1px 4px', fontSize: '0.55rem' }}>
                        {client.active ? 'ACTIF' : 'SUSPENDU'}
                      </span>
                    </td>
                    <td style={{ padding: '8px 10px' }}>
                      <div style={{ display: 'flex', justifyContent: 'center', gap: '4px' }}>
                        {/* Nouvelle action : Enregistrer un achat pour cet ancien client */}
                        <button
                          onClick={() => {
                            setSaleClient(client);
                            setSaleQtys({});
                            setVersementJour('');
                            setSaleError(null);
                            setSansCommission(false);
                            setVenteSoldee(false);
                            setIsSaleModalOpen(true);
                          }}
                          className="theme-picker-btn"
                          style={{
                            padding: '4px 5px',
                            color: 'hsl(var(--color-success))',
                            backgroundColor: 'hsl(var(--color-success) / 0.1)',
                            border: '1px solid hsl(var(--color-success) / 0.2)'
                          }}
                          title="Enregistrer un Achat / Vente"
                        >
                          <FiShoppingBag style={{ fontSize: '0.78rem' }} />
                        </button>

                        {/* Fiche détaillée */}
                        <button
                          onClick={() => {
                            setSelectedClient(client);
                            setClientDetailTab('info');
                            setClientInvoices([]);
                            setHistoryYear(new Date().getFullYear());
                            setHistoryMonth(new Date().getMonth() + 1);
                          }}
                          className="theme-picker-btn"
                          style={{ padding: '4px 5px' }}
                          title="Voir la fiche détaillée"
                        >
                          <FiEye style={{ fontSize: '0.78rem' }} />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {!isLoading && sortedClients.length === 0 && (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>
            {searchTerm || selectedType !== 'All' || selectedRisk !== 'All'
              ? 'Aucun client ne correspond à cette recherche/ces filtres.'
              : 'Aucun client enregistré pour le moment.'}
            {/* BUG-132 : filtres Type/Risque appliqués en mémoire sur les pages déjà reçues —
                tant que le reste de la liste charge encore, « aucun résultat » peut juste
                signifier « pas encore trouvé » plutôt qu'une absence réelle. */}
            {clientsBackgroundLoading && (selectedType !== 'All' || selectedRisk !== 'All') && (
              <div style={{ marginTop: '6px', fontWeight: 700 }}>
                Chargement du reste de la liste toujours en cours — ce résultat peut être incomplet.
              </div>
            )}
          </div>
        )}
        {!isLoading && sortedClients.length > 0 && (() => {
          // BUG-132 : le bouton reste visible tant qu'il reste des clients déjà chargés à
          // révéler OU que le chargement arrière-plan n'est pas terminé (dans ce dernier cas, un
          // clic ne révèle encore rien de neuf mais fait avancer `clientsVisibleCount` : la ligne
          // suivante apparaîtra seule, sans second clic, dès que la page suivante arrivera).
          const hasMoreLoaded = sortedClients.length > clientsVisibleCount;
          const showButton = hasMoreLoaded || clientsBackgroundLoading;
          const isWaiting = clientsBackgroundLoading && !hasMoreLoaded;
          return (
            <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', padding: '14px 0 4px' }}>
              <span style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))' }}>
                {visibleClients.length} sur {sortedClients.length} client(s) affiché(s)
                {clientsTotalCount !== null && clientsTotalCount > clientsLoadedCount
                  ? ` (${clientsTotalCount} au total, chargement en cours)`
                  : ''}
              </span>
              {showButton && (
                <button
                  onClick={() => setClientsVisibleCount(c => c + 20)}
                  className="btn btn-secondary"
                  disabled={isWaiting}
                  style={{ padding: '6px 16px', fontSize: '0.75rem', opacity: isWaiting ? 0.7 : 1 }}
                >
                  {isWaiting ? 'En attente de la page suivante…' : 'Voir plus'}
                </button>
              )}
            </div>
          );
        })()}
      </div>

      {/* Import Clients (Excel) Modal — Direction centrale */}
      <Modal
        isOpen={isImportModalOpen}
        onClose={() => { if (!importLoading) setIsImportModalOpen(false); }}
        title="Importer les Clients depuis Excel"
        maxWidth="560px"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>
            Sélectionnez le classeur "Liste des Clients par Boulangeries" (une feuille par boulangerie).
            Les codes clients sont générés automatiquement par l'application selon la boulangerie.
            Les clients déjà présents (même nom, même boulangerie) sont ignorés — l'import peut être relancé sans créer de doublons.
          </p>

          <input
            type="file"
            accept=".xlsx"
            disabled={importLoading}
            onChange={(e) => {
              setImportFile(e.target.files?.[0] || null);
              setImportPreview(null);
              setImportResult(null);
              setImportError(null);
            }}
            className="form-input"
            style={{ height: 'auto', padding: '8px 12px', fontSize: '0.78rem' }}
          />

          {importError && (
            <div style={{ fontSize: '0.75rem', color: 'hsl(var(--color-danger))', fontWeight: 600 }}>{importError}</div>
          )}

          {importPreview && (
            <div style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
              <table className="premium-table" style={{ fontSize: '0.72rem' }}>
                <thead>
                  <tr>
                    <th style={{ padding: '6px 8px' }}>Boulangerie</th>
                    <th style={{ padding: '6px 8px', textAlign: 'right' }}>Dans le fichier</th>
                    <th style={{ padding: '6px 8px', textAlign: 'right' }}>À importer</th>
                    <th style={{ padding: '6px 8px', textAlign: 'right' }}>Déjà existants</th>
                  </tr>
                </thead>
                <tbody>
                  {importPreview.report.map(r => (
                    <tr key={r.node}>
                      <td style={{ padding: '6px 8px', fontWeight: 700 }}>{r.node} — {r.node_name}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right' }}>{r.total_in_file}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))', fontWeight: 700 }}>{r.to_import}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>{r.already_existing}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {importPreview.unknown_nodes.length > 0 && (
                <div style={{ padding: '8px', fontSize: '0.7rem', color: 'hsl(var(--color-warning))' }}>
                  Boulangeries non reconnues dans le fichier (ignorées) : {importPreview.unknown_nodes.join(', ')}
                </div>
              )}
              {importPreview.skipped_sheets.length > 0 && (
                <div style={{ padding: '0 8px 8px', fontSize: '0.7rem', color: 'hsl(var(--text-muted))' }}>
                  Feuilles ignorées (hors périmètre) : {importPreview.skipped_sheets.join(', ')}
                </div>
              )}
            </div>
          )}

          {importResult && (
            <div style={{ padding: '10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-success) / 0.1)', color: 'hsl(var(--color-success))', fontWeight: 700, fontSize: '0.78rem' }}>
              {importResult.created} client(s) importé(s) avec succès.
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button className="btn btn-secondary" disabled={importLoading} onClick={() => setIsImportModalOpen(false)}>Fermer</button>
            {!importResult && (
              <>
                <button
                  className="btn btn-secondary"
                  disabled={!importFile || importLoading}
                  onClick={handleImportPreview}
                >
                  {importLoading && !importPreview ? 'Lecture…' : 'Aperçu'}
                </button>
                {importPreview && (
                  <button
                    className="btn btn-primary"
                    disabled={importLoading}
                    onClick={handleImportConfirm}
                  >
                    {importLoading ? 'Import en cours…' : `Confirmer l'import (${importPreview.report.reduce((s, r) => s + r.to_import, 0)})`}
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </Modal>

      {/* Add Client Modal */}
      <Modal
        isOpen={isAddModalOpen}
        onClose={closeAddClientModal}
        title="Créer une Fiche Client"
        maxWidth="500px"
      >
            <form onSubmit={handleAddClient} style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
              {needsNodeSelector && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase' }}>Boulangerie de Rattachement *</label>
                  <select
                    value={selectedNode}
                    onChange={e => setSelectedNode(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem' }}
                  >
                    <option value="">— Sélectionner une boulangerie —</option>
                    {nodesList.map(n => (
                      <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Nom Complet de l'Abonné *</label>
                <input
                  type="text"
                  required
                  placeholder="Ex: Dieudonné Kabeya"
                  value={newName}
                  onChange={(e) => setNewName(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Nom du Commerce / Maison</label>
                <input
                  type="text"
                  placeholder="Ex: Boulangerie Kabeya"
                  value={newBusiness}
                  onChange={(e) => setNewBusiness(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Type de Client</label>
                  <select
                    value={newType}
                    onChange={(e: React.ChangeEvent<HTMLSelectElement>) => setNewType(e.target.value as 'Grossiste' | 'Détaillant' | 'Revendeur')}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem' }}
                  >
                    <option value="Détaillant">Détaillant</option>
                    <option value="Grossiste">Grossiste</option>
                    <option value="Revendeur">Revendeur</option>
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Plafond Crédit (FC)</label>
                  <input
                    type="number"
                    value={newCreditLimit}
                    onChange={(e) => setNewCreditLimit(Number(e.target.value))}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                  />
                </div>
              </div>

              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase' }}>Taux de Commission (%)</label>
                  <input
                    type="number"
                    min="0"
                    max="100"
                    step="1"
                    value={newCommissionRate}
                    onChange={(e) => setNewCommissionRate(Number(e.target.value))}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                  />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase' }}>Cotisation Sociale (FC)</label>
                  <input
                    type="number"
                    min="0"
                    value={newCotisationSociale}
                    onChange={(e) => setNewCotisationSociale(Number(e.target.value))}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                  />
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Téléphone</label>
                <input
                  type="text"
                  placeholder="Ex: +243 899 876 543"
                  value={newPhone}
                  onChange={(e) => setNewPhone(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Adresse Commerciale</label>
                <input
                  type="text"
                  placeholder="Ex: Route de Matadi 145, Kasa-Vubu"
                  value={newAddress}
                  onChange={(e) => setNewAddress(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.8rem', padding: '0 12px' }}
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>Photo d'identité</label>
                <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                  {newPhotoPreview && (
                    <img
                      src={newPhotoPreview}
                      alt="Aperçu photo client"
                      style={{ width: '48px', height: '48px', borderRadius: '50%', objectFit: 'cover', border: '1px solid hsl(var(--border-color))' }}
                    />
                  )}
                  <input
                    type="file"
                    accept="image/*"
                    onChange={(e) => {
                      const file = e.target.files?.[0] || null;
                      if (newPhotoPreview) URL.revokeObjectURL(newPhotoPreview);
                      setNewPhoto(file);
                      setNewPhotoPreview(file ? URL.createObjectURL(file) : null);
                    }}
                    className="form-input"
                    style={{ flex: 1, height: '36px', fontSize: '0.75rem', padding: '6px 8px' }}
                  />
                  {newPhoto && (
                    <button
                      type="button"
                      onClick={() => {
                        if (newPhotoPreview) URL.revokeObjectURL(newPhotoPreview);
                        setNewPhoto(null); setNewPhotoPreview(null);
                      }}
                      className="btn btn-secondary"
                      style={{ padding: '6px 10px', fontSize: '0.7rem' }}
                    >
                      Retirer
                    </button>
                  )}
                </div>
              </div>

              {addError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '8px 12px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>
                  {addError}
                </div>
              )}
              <div style={{ display: 'flex', gap: '12px', marginTop: '8px' }}>
                <button type="button" onClick={closeAddClientModal} className="btn btn-secondary" style={{ flex: 1, padding: '8px 16px', fontSize: '0.8rem' }}>
                  Annuler
                </button>
                <button type="submit" disabled={isAddingClient} className="btn btn-primary" style={{ flex: 2, padding: '8px 16px', fontSize: '0.8rem', opacity: isAddingClient ? 0.6 : 1 }}>
                  {isAddingClient ? 'Enregistrement...' : "Enregistrer l'Abonné"}
                </button>
              </div>
            </form>
      </Modal>

      {/* Sale Modal / Enregistrer un Achat */}
      <Modal
        isOpen={isSaleModalOpen && !!saleClient}
        onClose={() => setIsSaleModalOpen(false)}
        title="Enregistrer commande"
        maxWidth="520px"
        footer={saleClient && (() => {
          const cl = saleClient.creditLimit || debtCeiling;
          // BUG-107 : aperçu avec remise de 75% (Vente Soldée) prise en compte
          const cmdTotal = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0);
          const isBlocked = !venteSoldee && saleClient.outstandingDebt >= cl && (parseFloat(versementJour) || 0) < cmdTotal;
          return (
            <>
              <button type="button" onClick={() => setIsSaleModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px 16px', fontSize: '0.8rem' }}>
                Annuler
              </button>
              <button
                type="submit"
                form="sale-form"
                disabled={isBlocked || isSubmitting}
                className="btn btn-primary"
                style={{ flex: 2, padding: '8px 16px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', opacity: (isBlocked || isSubmitting) ? 0.55 : 1 }}
              >
                <FiCheckCircle />
                <span>{isSubmitting ? 'Enregistrement...' : isBlocked ? 'Plafond atteint — Versement insuffisant' : 'Confirmer la transaction'}</span>
              </button>
            </>
          );
        })()}
      >
          {saleClient && (
            <form id="sale-form" onSubmit={handleSaleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>

              {/* Situation actuelle du client — BP affiché en premier */}
              {(() => {
                const debt = saleClient.outstandingDebt;
                const limit = saleClient.creditLimit || debtCeiling;
                // BUG-107 : aperçu avec remise de 75% (Vente Soldée) prise en compte
                const cmdTotal = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0);
                const isOver = debt >= limit;
                const isBlocked = isOver && (parseFloat(versementJour) || 0) < cmdTotal;
                return (
                  <div style={{ backgroundColor: isBlocked ? 'hsl(var(--color-danger) / 0.07)' : isOver ? 'hsl(var(--color-warning) / 0.07)' : 'hsl(var(--color-success) / 0.06)', border: `1px solid hsl(${isBlocked ? 'var(--color-danger)' : isOver ? 'var(--color-warning)' : 'var(--color-success)'} / 0.3)`, borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                    <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '6px' }}>Situation Actuelle du Client</div>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '6px', fontSize: '0.72rem' }}>
                      <div>
                        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>BALANCE ANTÉRIEURE (BP)</div>
                        <div style={{ fontWeight: 800, fontSize: '0.88rem', color: isBlocked ? 'hsl(var(--color-danger))' : isOver ? 'hsl(var(--color-warning))' : 'hsl(var(--text-primary))' }}>
                          {debt.toLocaleString('fr-FR')} FC
                        </div>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>PLAFOND CRÉDIT</div>
                        <div style={{ fontWeight: 700 }}>{limit.toLocaleString('fr-FR')} FC</div>
                      </div>
                      <div>
                        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>STATUT</div>
                        <span className={`badge ${isBlocked ? 'badge-danger' : isOver ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.55rem' }}>
                          {isBlocked ? 'BLOQUÉ' : isOver ? 'DÉPASSÉ' : 'EN RÈGLE'}
                        </span>
                        {isOver && (
                          <div style={{ fontSize: '0.55rem', color: isBlocked ? 'hsl(var(--color-danger))' : 'hsl(var(--color-warning))', fontWeight: 700, marginTop: '2px' }}>
                            +{(debt - limit).toLocaleString('fr-FR')} FC
                          </div>
                        )}
                        {isOver && !isBlocked && cmdTotal > 0 && (
                          <div style={{ fontSize: '0.5rem', color: 'hsl(var(--color-success))', marginTop: '2px' }}>Paiement intégral ✓</div>
                        )}
                      </div>
                    </div>
                  </div>
                );
              })()}

              {/* Dynamic bread quantity grid */}
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '6px', textTransform: 'uppercase' }}>
                  Pains vendus par catégorie
                </label>
                <div style={{ display: 'grid', gridTemplateColumns: `repeat(${Math.min(breadPrices.length, 4)}, 1fr)`, gap: '8px' }}>
                  {breadPrices.map(bp => (
                    <div key={bp.id}>
                      <div style={{ fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textAlign: 'center' }}>{bp.label}</div>
                      <input
                        type="number" min={0}
                        value={saleQtys[bp.id] || ''}
                        placeholder="0"
                        onChange={e => setSaleQtys(prev => ({ ...prev, [bp.id]: Math.max(0, Number(e.target.value)) }))}
                        className="form-input"
                        style={{ fontSize: '0.85rem', height: '34px', padding: '0 6px', textAlign: 'center', fontWeight: 700 }}
                      />
                      {(saleQtys[bp.id] || 0) > 0 && (
                        <div style={{ fontSize: '0.55rem', textAlign: 'center', color: 'hsl(var(--color-info))', marginTop: '2px' }}>
                          {/* BUG-107 : sous-total avec remise de 75% (Vente Soldée) prise en compte */}
                          {(saleQtys[bp.id] * effectiveUnitPrice(bp, venteSoldee)).toLocaleString('fr-FR')} FC
                        </div>
                      )}
                    </div>
                  ))}
                </div>
              </div>

              {/* Versement du jour Cash paid */}
              <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '12px', alignItems: 'center', borderTop: '1px dashed hsl(var(--border-color))', paddingTop: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--color-success))' }}>Versement du Jour (FC)</label>
                  <span style={{ fontSize: '0.65rem', color: isCasualSale ? 'hsl(var(--color-info))' : 'hsl(var(--text-muted))' }}>
                    {isCasualSale ? 'Vente sans client identifié : paiement comptant obligatoire, versement = valeur de la commande.' : 'Acompte en espèces versé ce jour'}
                  </span>
                </div>
                <input
                  type="number"
                  min={0}
                  placeholder="0"
                  value={isCasualSale ? String(breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0)) : versementJour}
                  disabled={isCasualSale}
                  onChange={(e) => setVersementJour(e.target.value)}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.85rem', padding: '0 12px', fontWeight: 800, color: 'hsl(var(--color-success))', borderColor: 'hsl(var(--color-success) / 0.4)' }}
                />
              </div>

              {/* BUG-083 : date de commande rétroactive — visible seulement si activé en Configuration */}
              {allowBackdatedSales && (
                <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 0.8fr', gap: '12px', alignItems: 'center' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--color-warning))' }}>Date de la commande (optionnel)</label>
                    <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>Laisser vide = aujourd'hui. Jamais une date future.</span>
                  </div>
                  <input
                    type="date"
                    max={workDate}
                    value={orderDate}
                    onChange={(e) => setOrderDate(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                </div>
              )}

              {/* Dynamic Billing Engine Display */}
              {(() => {
                // BUG-107 : remise de 75% (Vente Soldée) appliquée dès l'aperçu, cohérente
                // avec le total réellement facturé par le serveur.
                const totalFc    = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * effectiveUnitPrice(bp, venteSoldee), 0);
                const catalogFc  = breadPrices.reduce((s, bp) => s + (saleQtys[bp.id] || 0) * bp.unit_price, 0);
                const commRate   = (sansCommission || venteSoldee) ? 0 : saleClient.commissionRate;
                const effectivePay = isCasualSale ? totalFc : (parseFloat(versementJour) || 0);
                // Vente soldée : manquant passé en perte, pas de dette supplémentaire
                const nouvelEncours = venteSoldee
                  ? saleClient.outstandingDebt
                  : saleClient.outstandingDebt + totalFc - effectivePay;
                return (
                  <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '12px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>Balance Antérieure (BP) :</span>
                      <span style={{ fontWeight: 700 }}>{saleClient.outstandingDebt.toLocaleString('fr-FR')} FC</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>+ Valeur Commande :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--text-primary))' }}>
                        + {totalFc.toLocaleString('fr-FR')} FC
                        {venteSoldee && catalogFc !== totalFc && (
                          <span style={{ fontSize: '0.6rem', color: 'hsl(var(--color-warning))', fontWeight: 400, marginLeft: '4px' }}>
                            (catalogue plein : {catalogFc.toLocaleString('fr-FR')} FC)
                          </span>
                        )}
                      </span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>Commission CM ({commRate * 100}%) :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>- {(totalFc * commRate).toLocaleString('fr-FR')} FC</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>- Versement du Jour :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-info))' }}>
                        - {effectivePay.toLocaleString('fr-FR')} FC
                        {venteSoldee && totalFc > effectivePay && (
                          <span style={{ fontSize: '0.62rem', color: 'hsl(var(--color-warning))', marginLeft: '4px' }}>
                            (+{(totalFc - effectivePay).toLocaleString('fr-FR')} soldé)
                          </span>
                        )}
                      </span>
                    </div>
                    <div style={{ height: '1px', backgroundColor: 'hsl(var(--border-color))', margin: '4px 0' }} />
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.82rem', color: 'hsl(var(--text-primary))', fontWeight: 800 }}>
                      <span>= Nouvelle Dette (BP) :</span>
                      {(() => {
                        const cl = saleClient.creditLimit || debtCeiling;
                        return (
                          <span style={{ color: nouvelEncours > cl ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                            {nouvelEncours.toLocaleString('fr-FR')} FC
                          </span>
                        );
                      })()}
                    </div>
                    {(() => {
                      const cl = saleClient.creditLimit || debtCeiling;
                      return nouvelEncours > cl ? (
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--color-danger))', fontWeight: 700, textAlign: 'right' }}>
                          ⚠ Plafond dépassé de {(nouvelEncours - cl).toLocaleString('fr-FR')} FC
                        </div>
                      ) : null;
                    })()}
                  </div>
                );
              })()}

              {/* Checkboxes: vente sans commission / vente soldée — BUG-052 : les deux cases
                  sont désormais COMBINABLES (remarque.md l.190 ne les décrit jamais comme
                  exclusives ; l'exclusion mutuelle précédente empêchait, par ex., une vente
                  soldée explicitement exonérée en plus de sa remise de prix). */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', borderTop: '1px dashed hsl(var(--border-color))', paddingTop: '12px' }}>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 600, color: 'hsl(var(--text-primary))' }}>
                  <input
                    type="checkbox"
                    checked={sansCommission}
                    onChange={e => setSansCommission(e.target.checked)}
                    style={{ width: '15px', height: '15px', cursor: 'pointer' }}
                  />
                  Vente sans commission (25%) <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', fontWeight: 400 }}>(geste commercial ponctuel, prix et BP inchangés)</span>
                </label>
                <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer', fontSize: '0.78rem', fontWeight: 600, color: 'hsl(var(--text-primary))' }}>
                  <input
                    type="checkbox"
                    checked={venteSoldee}
                    onChange={e => setVenteSoldee(e.target.checked)}
                    style={{ width: '15px', height: '15px', cursor: 'pointer' }}
                  />
                  Vente Soldée / Vente Cash <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', fontWeight: 400 }}>(-25% sur le prix catalogue, 0% commission, manquant non imputé en BP)</span>
                </label>
                {sansCommission && venteSoldee && (
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', paddingLeft: '23px' }}>
                    Facture à la fois SOLDÉE (prix à 75%, BP gelée) ET sans commission — les deux cases restent combinables, CM=0 dans tous les cas.
                  </div>
                )}
                {venteSoldee && (
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', paddingLeft: '23px' }}>
                    Remise automatique de 25 % appliquée par le serveur sur le prix catalogue de chaque pain ;
                    distinct de « Client Occasionnel » (client non identifié) — les deux restent combinables.
                  </div>
                )}
              </div>

              {saleError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>{saleError}</div>
              )}
            </form>
          )}
      </Modal>

      {/* Thermal Receipt Print Preview Modal — same shared component as Facturier/Tableau de Bord.
          BUG-110 : largeur d'imprimante thermique réellement configurée côté desktop (58/80mm)
          — undefined hors mode desktop, ThermalReceipt retombe alors sur 80mm. */}
      {receiptDetails && (
        <ThermalReceipt receipt={receiptDetails} printId="clients" onClose={() => setReceiptDetails(null)} printerWidthMm={window.kiese?.printerWidthMm ?? 80} />
      )}

      {/* Client Detail Modal — 2 onglets */}
      {selectedClient && (
        <Modal
          isOpen={true}
          onClose={() => { setSelectedClient(null); setIsEditingLimit(false); }}
          maxWidth="580px"
          contentPadding="0"
          showCloseButton={false}
        >
            {/* Header */}
            <div style={{ padding: '20px 24px 0', borderBottom: '1px solid hsl(var(--border-color))' }}>
              <button
                onClick={() => { setSelectedClient(null); setIsEditingLimit(false); }}
                style={{ position: 'absolute', top: '14px', right: '14px', border: 'none', background: 'none', cursor: 'pointer', fontSize: '1.1rem', color: 'hsl(var(--text-secondary))' }}
              >
                <FiX />
              </button>

              {/* Profile summary */}
              <div style={{ display: 'flex', gap: '14px', alignItems: 'center', marginBottom: '16px' }}>
                <div style={{ width: '48px', height: '48px', borderRadius: '50%', backgroundColor: selectedClient.avatarColor, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '1.3rem', boxShadow: '0 4px 12px rgba(0,0,0,0.15)', flexShrink: 0 }}>
                  {selectedClient.name.substring(0, 2).toUpperCase()}
                </div>
                <div>
                  <span className="badge badge-info" style={{ marginBottom: '3px', fontSize: '0.6rem', padding: '1px 6px' }}>{selectedClient.id} • {selectedClient.type}</span>
                  <h2 style={{ fontSize: '1.1rem', fontWeight: 800, marginBottom: '1px', color: 'hsl(var(--text-primary))' }}>{selectedClient.name}</h2>
                  <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', fontWeight: 600 }}>{selectedClient.businessName}</p>
                </div>
              </div>

              {/* Tab bar */}
              <div style={{ display: 'flex', gap: 0 }}>
                {(['info', 'history', 'repayments'] as const).map(tab => (
                  <button
                    key={tab}
                    onClick={async () => {
                      setClientDetailTab(tab);
                      if ((tab === 'history' || tab === 'repayments') && clientInvoices.length === 0 && selectedClient._apiId) {
                        setInvoicesLoading(true);
                        try {
                          const res = await salesApi.list({ client: selectedClient._apiId });
                          setClientInvoices(res.data);
                        } catch { /* ignore */ }
                        setInvoicesLoading(false);
                      }
                    }}
                    style={{
                      padding: '8px 14px', fontSize: '0.75rem', fontWeight: 700, cursor: 'pointer',
                      border: 'none', borderBottom: clientDetailTab === tab ? '2px solid hsl(var(--accent-color))' : '2px solid transparent',
                      background: 'none', color: clientDetailTab === tab ? 'hsl(var(--accent-color))' : 'hsl(var(--text-muted))',
                      transition: 'color 0.15s, border-color 0.15s'
                    }}
                  >
                    {tab === 'info' ? 'Informations' : tab === 'history' ? 'Historique' : 'Remboursements'}
                  </button>
                ))}
              </div>
            </div>

            {/* Tab content */}
            <div style={{ padding: '20px 24px', maxHeight: '55vh', overflowY: 'auto' }}>

              {/* ── Onglet Info ── */}
              {clientDetailTab === 'info' && (
                <>
                  <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '14px', marginBottom: '16px' }}>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiPhone /> Contact
                      </h4>
                      <p style={{ fontSize: '0.82rem', fontWeight: 700, color: 'hsl(var(--text-primary))' }}>{selectedClient.phone}</p>
                    </div>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiMapPin /> Adresse
                      </h4>
                      <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', lineHeight: 1.3 }}>{selectedClient.address}</p>
                    </div>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiShield /> Limite Crédit
                        {['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(user?.role || '') && !isEditingLimit && (
                          <button onClick={() => { setLimitInput(selectedClient.creditLimit.toString()); setIsEditingLimit(true); }} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--accent-color))', padding: '0 2px', display: 'flex', alignItems: 'center' }} title="Modifier">
                            <FiEdit2 size={10} />
                          </button>
                        )}
                      </h4>
                      {isEditingLimit ? (
                        <div style={{ display: 'flex', alignItems: 'center', gap: '5px' }}>
                          <input type="number" min={0} value={limitInput} onChange={e => setLimitInput(e.target.value)} className="form-input" style={{ height: '28px', fontSize: '0.78rem', padding: '0 6px', fontWeight: 700, width: '100px' }} autoFocus />
                          <span style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))' }}>FC</span>
                          <button onClick={handleSaveCreditLimit} className="btn btn-primary" style={{ padding: '3px 6px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}><FiSave size={10} /> OK</button>
                          <button onClick={() => setIsEditingLimit(false)} className="btn btn-secondary" style={{ padding: '3px 6px', fontSize: '0.65rem' }}><FiX size={10} /></button>
                        </div>
                      ) : (
                        <p style={{ fontSize: '0.9rem', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{selectedClient.creditLimit.toLocaleString('fr-FR')} FC</p>
                      )}
                    </div>
                    <div>
                      <h4 style={{ display: 'flex', alignItems: 'center', gap: '5px', fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '5px' }}>
                        <FiAlertTriangle /> Encours Actuel
                      </h4>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: '4px' }}>
                        {selectedClient.outstandingDebt < 0 ? (
                          <span style={{ fontSize: '0.9rem', fontWeight: 800, color: 'hsl(var(--color-success))' }}>
                            CRÉDIT : {Math.abs(selectedClient.outstandingDebt).toLocaleString('fr-FR')} FC
                          </span>
                        ) : (
                          <>
                            <span style={{ fontSize: '0.9rem', fontWeight: 800, color: selectedClient.outstandingDebt > selectedClient.creditLimit ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>
                              {selectedClient.outstandingDebt.toLocaleString('fr-FR')} FC
                            </span>
                            {selectedClient.outstandingDebt > selectedClient.creditLimit && (
                              <span style={{ fontSize: '0.58rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>(DÉPASSÉ)</span>
                            )}
                          </>
                        )}
                      </div>
                    </div>
                  </div>

                  <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                    <h4 style={{ fontSize: '0.7rem', fontWeight: 800, color: 'hsl(var(--text-primary))', marginBottom: '7px', display: 'flex', alignItems: 'center', gap: '4px' }}>
                      <FiGrid style={{ color: 'hsl(var(--accent-color))' }} /> Évaluation de Risque
                    </h4>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                      <span>Dernier enregistrement :</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-success))' }}>{selectedClient.lastPaymentDate}</span>
                    </div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
                      <span>Score automatique :</span>
                      <span style={{ fontWeight: 700, color: selectedClient.riskScore === 'High' ? 'hsl(var(--color-danger))' : selectedClient.riskScore === 'Medium' ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>
                        {selectedClient.riskScore === 'High' ? 'Rouge — CRITIQUE' : selectedClient.riskScore === 'Medium' ? 'Orange — MOYEN' : 'Vert — FIABLE'}
                      </span>
                    </div>
                  </div>
                </>
              )}

              {/* ── Onglet Historique ── */}
              {clientDetailTab === 'history' && (() => {
                const MOIS_FR = ['Janvier','Février','Mars','Avril','Mai','Juin','Juillet','Août','Septembre','Octobre','Novembre','Décembre'];
                const now = new Date();
                const isCurrentMonth = historyYear === now.getFullYear() && historyMonth === now.getMonth() + 1;
                const goToPrev = () => {
                  if (historyMonth === 1) { setHistoryMonth(12); setHistoryYear(y => y - 1); }
                  else setHistoryMonth(m => m - 1);
                };
                const goToNext = () => {
                  if (isCurrentMonth) return;
                  if (historyMonth === 12) { setHistoryMonth(1); setHistoryYear(y => y + 1); }
                  else setHistoryMonth(m => m + 1);
                };
                const filtered = clientInvoices.filter(inv => {
                  if (!inv.invoice_date) return false;
                  const d = new Date(inv.invoice_date);
                  return d.getFullYear() === historyYear && d.getMonth() + 1 === historyMonth;
                });
                const monthTotal = filtered.reduce((s, inv) => s + parseFloat(inv.order_total || '0'), 0);
                const monthPaid = filtered.reduce((s, inv) => s + parseFloat(inv.payment_amount || '0'), 0);
                // Pour les ventes soldées, le manquant est passé en perte — ne pas l'inclure dans "Reste dû"
                const monthDebt = filtered.reduce((s, inv) => inv.is_soldee ? s : s + Math.max(0, parseFloat(inv.order_total || '0') - parseFloat(inv.payment_amount || '0')), 0);
                // BUG-092/BUG-096 : perte totale du mois sur les ventes soldées (prix catalogue − prix facturé).
                const monthLoss = filtered.reduce((s, inv) => s + (parseFloat(inv.total_loss || '0') || 0), 0);

                return (
                  <div>
                    {/* Navigation mensuelle */}
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '12px', padding: '8px 12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
                      <button
                        onClick={goToPrev}
                        style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--accent-color))', padding: '4px 8px', borderRadius: '4px', fontSize: '1rem', fontWeight: 700, lineHeight: 1 }}
                        title="Mois précédent"
                      >
                        ‹
                      </button>
                      <span style={{ fontWeight: 800, fontSize: '0.82rem', color: 'hsl(var(--text-primary))' }}>
                        {MOIS_FR[historyMonth - 1]} {historyYear}
                      </span>
                      <button
                        onClick={goToNext}
                        disabled={isCurrentMonth}
                        style={{ background: 'none', border: 'none', cursor: isCurrentMonth ? 'default' : 'pointer', color: isCurrentMonth ? 'hsl(var(--text-muted))' : 'hsl(var(--accent-color))', padding: '4px 8px', borderRadius: '4px', fontSize: '1rem', fontWeight: 700, lineHeight: 1 }}
                        title="Mois suivant"
                      >
                        ›
                      </button>
                    </div>

                    {invoicesLoading ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>Chargement de l'historique...</p>
                    ) : filtered.length === 0 ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-muted))', fontSize: '0.78rem' }}>
                        Aucune commande pour {MOIS_FR[historyMonth - 1]} {historyYear}.
                      </p>
                    ) : (
                      <>
                        <div style={{ overflowX: 'auto' }}>
                          <table className="premium-table" style={{ fontSize: '0.72rem' }}>
                            <thead>
                              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                                <th style={{ padding: '6px 8px' }}>N° Facture</th>
                                <th style={{ padding: '6px 8px' }}>Date</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Total (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Versé (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Perte (FC)</th>
                                <th style={{ padding: '6px 8px' }}>Statut</th>
                                {canAdjustInvoice && <th style={{ padding: '6px 8px' }}></th>}
                              </tr>
                            </thead>
                            <tbody>
                              {filtered.map(inv => {
                                // BUG-109 : référence vers la facture d'origine (si c'est un
                                // ajustement) — recherche dans l'historique déjà chargé ; si la
                                // facture d'origine est hors de ce mois, on retombe sur son id.
                                const originalInvoice = inv.is_adjustment && inv.adjusts
                                  ? clientInvoices.find(o => o.id === inv.adjusts)
                                  : undefined;
                                return (
                                <tr key={inv.id}>
                                  <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{inv.receipt_number}</td>
                                  <td style={{ padding: '6px 8px', color: 'hsl(var(--text-secondary))' }}>
                                    {inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('fr-FR') : '—'}
                                  </td>
                                  <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700 }}>{parseFloat(inv.order_total || '0').toLocaleString('fr-FR')}</td>
                                  <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{parseFloat(inv.payment_amount || '0').toLocaleString('fr-FR')}</td>
                                  <td style={{ padding: '6px 8px', textAlign: 'right', color: parseFloat(inv.total_loss || '0') > 0 ? 'hsl(38, 92%, 38%)' : 'hsl(var(--text-muted))', fontWeight: parseFloat(inv.total_loss || '0') > 0 ? 700 : 400 }}>
                                    {parseFloat(inv.total_loss || '0') > 0 ? `-${parseFloat(inv.total_loss || '0').toLocaleString('fr-FR')}` : '—'}
                                  </td>
                                  <td style={{ padding: '6px 8px', display: 'flex', gap: '4px', flexWrap: 'wrap', alignItems: 'center' }}>
                                    <span className={`badge ${inv.status === 'DELIVERED' ? 'badge-success' : inv.status === 'CANCELLED' ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.55rem' }}>
                                      {inv.status === 'DELIVERED' ? 'LIVRÉ' : inv.status === 'CANCELLED' ? 'ANNULÉ' : 'EN ATTENTE'}
                                    </span>
                                    {inv.is_debt_repayment && (
                                      <span className="badge" style={{ fontSize: '0.5rem', background: 'hsl(210,80%,50%)', color: '#fff' }}>REMB</span>
                                    )}
                                    {!inv.is_debt_repayment && inv.is_soldee && (
                                      <span className="badge badge-warning" style={{ fontSize: '0.5rem' }}>SOLDÉE</span>
                                    )}
                                    {!inv.is_debt_repayment && !inv.is_soldee && (
                                      <span className={`badge ${inv.payment_type === 'CASH' ? 'badge-success' : 'badge-secondary'}`} style={{ fontSize: '0.5rem' }}>
                                        {inv.payment_type === 'CASH' ? 'CASH' : 'CRÉDIT'}
                                      </span>
                                    )}
                                    {inv.special_code && (
                                      <span className="badge badge-info" style={{ fontSize: '0.48rem' }}>{inv.special_code === 'NS' ? 'NS — Non servie' : inv.special_code}</span>
                                    )}
                                    {/* BUG-109 : trace d'ajustement — badge + référence vers l'originale */}
                                    {inv.is_adjustment && (
                                      <span
                                        className="badge"
                                        title={`Ajustement de la facture ${originalInvoice?.receipt_number || inv.adjusts}`}
                                        style={{ fontSize: '0.5rem', background: inv.adjustment_sign === -1 ? 'hsl(0,70%,45%)' : 'hsl(150,60%,35%)', color: '#fff' }}
                                      >
                                        AJUST. {inv.adjustment_sign === -1 ? '−' : '+'} · réf {originalInvoice?.receipt_number || inv.adjusts}
                                      </span>
                                    )}
                                    {!inv.is_adjustment && (inv.adjustments_count || 0) > 0 && (
                                      <span className="badge badge-info" style={{ fontSize: '0.48rem' }}>
                                        {inv.adjustments_count} ajustement{(inv.adjustments_count || 0) > 1 ? 's' : ''}
                                      </span>
                                    )}
                                  </td>
                                  {canAdjustInvoice && (
                                    <td style={{ padding: '6px 8px' }}>
                                      {!inv.is_adjustment && !inv.is_debt_repayment && inv.status !== 'CANCELLED' && (
                                        <button
                                          onClick={() => openAdjustModal(inv)}
                                          className="btn btn-secondary"
                                          style={{ padding: '3px 8px', fontSize: '0.62rem', whiteSpace: 'nowrap' }}
                                          title="Corriger/annuler cette commande via une facture d'ajustement"
                                        >
                                          Ajuster
                                        </button>
                                      )}
                                    </td>
                                  )}
                                </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        {/* Récapitulatif mensuel */}
                        <div style={{ display: 'flex', gap: '12px', marginTop: '10px', padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>{filtered.length} commande(s)</span>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))' }}>Total : <strong>{monthTotal.toLocaleString('fr-FR')} FC</strong></span>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-success))' }}>Versé : <strong>{monthPaid.toLocaleString('fr-FR')} FC</strong></span>
                          {monthDebt > 0 && (
                            <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))' }}>Reste dû : <strong>{monthDebt.toLocaleString('fr-FR')} FC</strong></span>
                          )}
                          {monthLoss > 0 && (
                            <span style={{ fontSize: '0.65rem', color: 'hsl(38, 92%, 38%)' }} title="Perte attendue du mécanisme de vente soldée (-25% sur le prix catalogue)">
                              Perte (ventes soldées) : <strong>-{monthLoss.toLocaleString('fr-FR')} FC</strong>
                            </span>
                          )}
                        </div>
                      </>
                    )}
                  </div>
                );
              })()}

              {/* ── Onglet Remboursements ── */}
              {clientDetailTab === 'repayments' && (() => {
                const repayments = clientInvoices.filter(inv => inv.is_debt_repayment);
                const totalRemboursé = repayments.reduce((s, inv) => s + parseFloat(inv.payment_amount || '0'), 0);
                return (
                  <div>
                    {invoicesLoading ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>Chargement...</p>
                    ) : repayments.length === 0 ? (
                      <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-muted))', fontSize: '0.78rem' }}>
                        Aucun remboursement BP enregistré pour ce client.
                      </p>
                    ) : (
                      <>
                        <div style={{ overflowX: 'auto' }}>
                          <table className="premium-table" style={{ fontSize: '0.72rem' }}>
                            <thead>
                              <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                                <th style={{ padding: '6px 8px' }}>Date</th>
                                <th style={{ padding: '6px 8px' }}>N° Reçu</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>BP Initial (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Montant (FC)</th>
                                <th style={{ padding: '6px 8px', textAlign: 'right' }}>Nouveau BP (FC)</th>
                              </tr>
                            </thead>
                            <tbody>
                              {repayments.map(inv => {
                                const bpAfter = parseFloat(inv.debt_after || '0');
                                return (
                                  <tr key={inv.id}>
                                    <td style={{ padding: '6px 8px', color: 'hsl(var(--text-secondary))' }}>
                                      {inv.invoice_date ? new Date(inv.invoice_date).toLocaleDateString('fr-FR') : '—'}
                                    </td>
                                    <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(210,80%,50%)' }}>{inv.receipt_number}</td>
                                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(inv.debt_before || '0').toLocaleString('fr-FR')}</td>
                                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: 'hsl(var(--color-success))' }}>
                                      {parseFloat(inv.payment_amount || '0').toLocaleString('fr-FR')}
                                    </td>
                                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: bpAfter <= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-primary))' }}>
                                      {bpAfter <= 0 ? `CRÉDIT : ${Math.abs(bpAfter).toLocaleString('fr-FR')}` : bpAfter.toLocaleString('fr-FR')}
                                    </td>
                                  </tr>
                                );
                              })}
                            </tbody>
                          </table>
                        </div>
                        <div style={{ display: 'flex', gap: '12px', marginTop: '10px', padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--border-color))' }}>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>{repayments.length} remboursement(s)</span>
                          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-success))' }}>Total versé : <strong>{totalRemboursé.toLocaleString('fr-FR')} FC</strong></span>
                        </div>
                      </>
                    )}
                  </div>
                );
              })()}

            </div>

            {/* Footer buttons */}
            <div style={{ padding: '14px 24px', borderTop: '1px solid hsl(var(--border-color))', display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
              <button
                onClick={() => { setSelectedClient(null); setIsEditingLimit(false); }}
                className="btn btn-secondary"
                style={{ flex: 1, minWidth: '80px', padding: '8px 16px', fontSize: '0.8rem' }}
              >
                Fermer
              </button>
              {selectedClient && (
                <button
                  onClick={() => {
                    setRepaymentClient(selectedClient);
                    setRepaymentAmount('');
                    setRepaymentError(null);
                    setSelectedClient(null);
                    setIsRepaymentModalOpen(true);
                  }}
                  className="btn btn-secondary"
                  style={{ flex: 1, minWidth: '120px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px 12px', fontSize: '0.78rem', color: 'hsl(var(--color-warning))', borderColor: 'hsl(var(--color-warning) / 0.4)' }}
                >
                  <FiCreditCard />
                  <span>Remboursement / Dépôt sans commande</span>
                </button>
              )}
              <button
                onClick={() => {
                  setSelectedClient(null);
                  setSaleClient(selectedClient);
                  setSaleQtys({});
                  setVersementJour('');
                  setSaleError(null);
                  setSansCommission(false);
                  setVenteSoldee(false);
                  setIsSaleModalOpen(true);
                }}
                className="btn btn-primary"
                style={{ flex: 2, minWidth: '140px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px', padding: '8px 16px', fontSize: '0.8rem' }}
              >
                <span>Facturer une commande</span>
                <FiArrowRight />
              </button>
            </div>
        </Modal>
      )}

      {/* ── Modal Remboursement BP ─────────────────────────────────────────── */}
      {isRepaymentModalOpen && repaymentClient && (
        <Modal
          isOpen={true}
          onClose={() => setIsRepaymentModalOpen(false)}
          title="Remboursement / Dépôt sans commande"
          subtitle={repaymentClient.name}
          maxWidth="380px"
        >
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '10px' }}>
              Un même versement couvre deux cas : réduire une dette existante (<strong>remboursement</strong>),
              ou verser pour un <strong>dépôt épargne</strong> même sans dette préalable (la BP devient alors
              négative, CLAUDE.md §5.1). Ce versement ne correspond à aucune commande de pain.
            </div>
            <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', marginBottom: '14px' }}>
              <div style={{ marginTop: '4px', display: 'flex', gap: '12px' }}>
                <span>BP actuel : <strong style={{ color: repaymentClient.outstandingDebt > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{repaymentClient.outstandingDebt.toLocaleString('fr-FR')} FC</strong></span>
              </div>
            </div>
            <form onSubmit={handleRepaymentSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                  Montant versé (FC) *
                </label>
                <input
                  type="number"
                  min="1"
                  step="1"
                  value={repaymentAmount}
                  onChange={e => setRepaymentAmount(e.target.value)}
                  placeholder="Ex : 10 000"
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.84rem', fontWeight: 700 }}
                  autoFocus
                  required
                />
              </div>
              {repaymentAmount && parseFloat(repaymentAmount) > 0 && (
                <div style={{ padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', fontSize: '0.72rem' }}>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Nouveau BP après versement : </span>
                  <strong style={{ color: (repaymentClient.outstandingDebt - parseFloat(repaymentAmount)) <= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))' }}>
                    {(repaymentClient.outstandingDebt - parseFloat(repaymentAmount)).toLocaleString('fr-FR')} FC
                  </strong>
                  {(repaymentClient.outstandingDebt - parseFloat(repaymentAmount)) < 0 && (
                    <span style={{ marginLeft: '6px', color: 'hsl(var(--text-muted))' }}>(dépôt épargne — crédit en faveur du client)</span>
                  )}
                </div>
              )}
              {repaymentError && (
                <div style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>
                  {repaymentError}
                </div>
              )}
              <div style={{ display: 'flex', gap: '8px' }}>
                <button type="button" onClick={() => setIsRepaymentModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px', fontSize: '0.8rem' }}>
                  Annuler
                </button>
                <button type="submit" disabled={repaymentLoading || !repaymentAmount} className="btn btn-primary" style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}>
                  <FiCheckCircle />
                  {repaymentLoading ? 'Enregistrement...' : 'Confirmer le versement'}
                </button>
              </div>
            </form>
        </Modal>
      )}

      {/* ── Modal Ajustement de facture (BUG-109, réservé GERANT+) ───────────── */}
      {isAdjustModalOpen && adjustTarget && (
        <Modal
          isOpen={true}
          onClose={() => { setIsAdjustModalOpen(false); setAdjustTarget(null); }}
          title="Ajuster une commande"
          subtitle={`Facture ${adjustTarget.receipt_number}`}
          maxWidth="480px"
        >
          <div style={{ maxHeight: '70vh', overflowY: 'auto', paddingRight: '2px' }}>
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '10px' }}>
              Corrige ou annule une commande déjà enregistrée. La facture d'origine n'est
              jamais modifiée : une nouvelle facture d'ajustement, liée, est créée (« grande
              trace »). Si la commission de la période d'origine est déjà clôturée, la
              Direction/le Comptable en sera averti automatiquement — l'ajustement n'est pas
              bloqué pour autant.
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
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>
                    Date de l'ajustement (optionnel — vide = aujourd'hui)
                  </label>
                  <input
                    type="date"
                    value={adjustDate}
                    onChange={e => setAdjustDate(e.target.value)}
                    className="form-input"
                    style={{ height: '36px', fontSize: '0.78rem' }}
                  />
                </div>
              )}

              {adjustError && (
                <div style={{ padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>
                  {adjustError}
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
                  style={{ flex: 2, padding: '8px', fontSize: '0.8rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                >
                  <FiCheckCircle />
                  {adjustLoading ? 'Enregistrement...' : "Confirmer l'ajustement"}
                </button>
              </div>
            </form>
          </div>
        </Modal>
      )}

      {/* ── Stat Detail Modals ────────────────────────────────────────────── */}
      {statModal && (
        <Modal
          isOpen={true}
          onClose={() => setStatModal(null)}
          maxWidth="620px"
          contentPadding="0"
          showCloseButton={false}
        >

            {/* Modal header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '14px 18px', borderBottom: '1px solid hsl(var(--border-color))' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {statModal === 'plafonds' && <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
                {statModal === 'encours'  && <FiDollarSign   style={{ color: 'hsl(var(--color-info))' }} />}
                {statModal === 'solvabilite' && <FiUserCheck style={{ color: 'hsl(var(--color-success))' }} />}
                {statModal === 'deficit' && <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} />}
                <span style={{ fontWeight: 800, fontSize: '0.9rem' }}>
                  {statModal === 'plafonds'    && 'Plafonds Dépassés — Détail'}
                  {statModal === 'encours'     && 'Encours Global — Détail'}
                  {statModal === 'solvabilite' && 'Solvabilité — Analyse du Risque'}
                  {statModal === 'deficit'     && 'Clients Déficitaires — BP > CM Période'}
                </span>
              </div>
              <button onClick={() => setStatModal(null)} style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--text-muted))', fontSize: '1.1rem', lineHeight: 1 }}>
                <FiX />
              </button>
            </div>

            {/* Modal body */}
            <div style={{ overflowY: 'auto', padding: '14px 18px', flex: 1 }}>

              {/* ── PLAFONDS DÉPASSÉS ── */}
              {statModal === 'plafonds' && (() => {
                const exceeded = clients.filter(c => c.outstandingDebt > c.creditLimit).sort((a, b) => (b.outstandingDebt - b.creditLimit) - (a.outstandingDebt - a.creditLimit));
                if (exceeded.length === 0) return (
                  <p style={{ textAlign: 'center', color: 'hsl(var(--color-success))', fontWeight: 700, padding: '24px 0' }}>Aucun client n'a dépassé son plafond. ✓</p>
                );
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>{exceeded.length} client(s) ont dépassé leur plafond de crédit, triés par excédent décroissant.</p>
                    {exceeded.map(c => {
                      const excess = c.outstandingDebt - c.creditLimit;
                      return (
                        <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.06)', border: '1px solid hsl(var(--color-danger) / 0.2)' }}>
                          <div>
                            <div style={{ fontWeight: 800, fontSize: '0.8rem' }}>{c.name}</div>
                            <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))' }}>{c.id} — Plafond : {c.creditLimit.toLocaleString('fr-FR')} FC</div>
                          </div>
                          <div style={{ textAlign: 'right' }}>
                            <div style={{ fontWeight: 800, fontSize: '0.82rem', color: 'hsl(var(--color-danger))' }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</div>
                            <div style={{ fontSize: '0.6rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>+{excess.toLocaleString('fr-FR')} FC</div>
                          </div>
                        </div>
                      );
                    })}
                    <div style={{ marginTop: '8px', padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800 }}>
                      <span>Total excédent à recouvrer :</span>
                      <span style={{ color: 'hsl(var(--color-danger))' }}>
                        {exceeded.reduce((s, c) => s + (c.outstandingDebt - c.creditLimit), 0).toLocaleString('fr-FR')} FC
                      </span>
                    </div>
                  </div>
                );
              })()}

              {/* ── ENCOURS GLOBAL ── */}
              {statModal === 'encours' && (() => {
                const withDebt  = clients.filter(c => c.outstandingDebt > 0).sort((a, b) => b.outstandingDebt - a.outstandingDebt);
                const inCredit  = clients.filter(c => c.outstandingDebt < 0).sort((a, b) => a.outstandingDebt - b.outstandingDebt);
                const noDebt    = clients.filter(c => c.outstandingDebt === 0);
                const allClear  = withDebt.length === 0 && inCredit.length === 0;
                const netBalance = withDebt.reduce((s, c) => s + c.outstandingDebt, 0);
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
                    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr 1fr', gap: '8px', marginBottom: '8px' }}>
                      {[
                        { label: 'Encours Net', value: `${netBalance.toLocaleString('fr-FR')} FC`, color: netBalance > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' },
                        { label: 'Endettés', value: `${withDebt.length}`, color: 'hsl(var(--color-warning))' },
                        { label: 'En Crédit', value: `${inCredit.length}`, color: 'hsl(var(--color-info))' },
                        { label: 'Sans BP', value: `${noDebt.length}`, color: 'hsl(var(--color-success))' },
                      ].map(s => (
                        <div key={s.label} style={{ padding: '8px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', textAlign: 'center' }}>
                          <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))', fontWeight: 700, textTransform: 'uppercase' }}>{s.label}</div>
                          <div style={{ fontWeight: 800, fontSize: '0.88rem', color: s.color }}>{s.value}</div>
                        </div>
                      ))}
                    </div>

                    {allClear ? (
                      <p style={{ textAlign: 'center', color: 'hsl(var(--color-success))', fontWeight: 700, padding: '12px 0' }}>Aucun encours. Tous les clients sont à jour. ✓</p>
                    ) : (
                      <>
                        {/* Clients endettés */}
                        {withDebt.length > 0 && (
                          <div style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', textTransform: 'uppercase', marginTop: '4px', marginBottom: '2px' }}>
                            Clients endettés ({withDebt.length})
                          </div>
                        )}
                        {withDebt.map(c => {
                          const pct = c.creditLimit > 0 ? Math.min(100, Math.round(c.outstandingDebt / c.creditLimit * 100)) : 0;
                          const isOver = c.outstandingDebt > c.creditLimit;
                          return (
                            <div key={c.id} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: isOver ? 'hsl(var(--color-danger) / 0.05)' : 'hsl(var(--bg-tertiary))', border: `1px solid hsl(${isOver ? 'var(--color-danger)' : 'var(--border-color)'} / ${isOver ? '0.25' : '1'})` }}>
                              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                                <div>
                                  <span style={{ fontWeight: 800, fontSize: '0.78rem' }}>{c.name}</span>
                                  <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', marginLeft: '6px' }}>{c.id}</span>
                                </div>
                                <div style={{ textAlign: 'right' }}>
                                  <span style={{ fontWeight: 800, fontSize: '0.78rem', color: isOver ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</span>
                                  <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', marginLeft: '4px' }}>/ {c.creditLimit.toLocaleString('fr-FR')} FC</span>
                                </div>
                              </div>
                                  <div style={{ height: '4px', borderRadius: '2px', backgroundColor: 'hsl(var(--border-color))' }}>
                                <div style={{ height: '100%', borderRadius: '2px', width: `${pct}%`, backgroundColor: isOver ? 'hsl(var(--color-danger))' : pct >= 80 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }} />
                              </div>
                              <div style={{ fontSize: '0.55rem', color: 'hsl(var(--text-muted))', marginTop: '2px', textAlign: 'right' }}>{pct}% du plafond</div>
                            </div>
                          );
                        })}

                        {/* Clients en crédit (trop-payé) */}
                        {inCredit.length > 0 && (
                          <div style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-info))', textTransform: 'uppercase', marginTop: '8px', marginBottom: '2px' }}>
                            En Crédit — Trop-payé ({inCredit.length})
                          </div>
                        )}
                        {inCredit.map(c => (
                          <div key={c.id} style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-info) / 0.05)', border: '1px solid hsl(var(--color-info) / 0.2)' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                              <div>
                                <span style={{ fontWeight: 800, fontSize: '0.78rem' }}>{c.name}</span>
                                <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-secondary))', marginLeft: '6px' }}>{c.id}</span>
                              </div>
                              <span style={{ fontWeight: 800, fontSize: '0.78rem', color: 'hsl(var(--color-info))' }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</span>
                            </div>
                            <div style={{ fontSize: '0.55rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>Trop-payé — se régularise à la prochaine commande</div>
                          </div>
                        ))}
                      </>
                    )}
                  </div>
                );
              })()}

              {/* ── SOLVABILITÉ ── */}
              {statModal === 'solvabilite' && (() => {
                const high   = clients.filter(c => c.riskScore === 'High');
                const medium = clients.filter(c => c.riskScore === 'Medium');
                const low    = clients.filter(c => c.riskScore === 'Low');
                const globalScore = high.length === 0 ? 'A+' : high.length <= 2 ? 'B' : high.length <= 5 ? 'C' : 'D';
                const scoreColor  = globalScore === 'A+' ? 'hsl(var(--color-success))' : globalScore === 'B' ? 'hsl(var(--color-warning))' : 'hsl(var(--color-danger))';
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '16px', padding: '12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))' }}>
                      <div style={{ textAlign: 'center' }}>
                        <div style={{ fontSize: '2rem', fontWeight: 900, color: scoreColor }}>{globalScore}</div>
                        <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>Score Global</div>
                      </div>
                      <div style={{ width: '1px', height: '40px', backgroundColor: 'hsl(var(--border-color))' }} />
                      <div style={{ display: 'flex', gap: '12px' }}>
                        {[
                          { label: 'CRITIQUE', count: high.length,   color: 'hsl(var(--color-danger))' },
                          { label: 'MOYEN',    count: medium.length, color: 'hsl(var(--color-warning))' },
                          { label: 'MINIME',   count: low.length,    color: 'hsl(var(--color-success))' },
                        ].map(s => (
                          <div key={s.label} style={{ textAlign: 'center' }}>
                            <div style={{ fontWeight: 800, fontSize: '1.1rem', color: s.color }}>{s.count}</div>
                            <div style={{ fontSize: '0.55rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>{s.label}</div>
                          </div>
                        ))}
                      </div>
                    </div>
                    {[
                      { label: 'Clients à Risque CRITIQUE', list: high,   badgeClass: 'badge-danger',  desc: 'BP ≥ plafond — recouvrement urgent' },
                      { label: 'Clients à Risque MOYEN',    list: medium, badgeClass: 'badge-warning', desc: 'BP élevée — surveillance recommandée' },
                      { label: 'Clients Fiables',           list: low,    badgeClass: 'badge-success', desc: 'BP faible — aucune alerte' },
                    ].filter(g => g.list.length > 0).map(group => (
                      <div key={group.label}>
                        <div style={{ fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '6px' }}>
                          {group.label} ({group.list.length}) — <span style={{ fontWeight: 400 }}>{group.desc}</span>
                        </div>
                        <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                          {group.list.map(c => (
                            <div key={c.id} style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', padding: '6px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))' }}>
                              <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                <div style={{ width: '20px', height: '20px', borderRadius: '50%', backgroundColor: c.avatarColor, color: '#fff', display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 800, fontSize: '0.55rem', flexShrink: 0 }}>
                                  {c.name.substring(0, 2).toUpperCase()}
                                </div>
                                <div>
                                  <div style={{ fontWeight: 700, fontSize: '0.75rem' }}>{c.name}</div>
                                  <div style={{ fontSize: '0.58rem', color: 'hsl(var(--text-secondary))' }}>{c.id}</div>
                                </div>
                              </div>
                              <div style={{ textAlign: 'right' }}>
                                <div style={{ fontSize: '0.75rem', fontWeight: 800 }}>{c.outstandingDebt.toLocaleString('fr-FR')} FC</div>
                                <span className={`badge ${group.badgeClass}`} style={{ fontSize: '0.5rem' }}>{c.riskScore === 'High' ? 'CRITIQUE' : c.riskScore === 'Medium' ? 'MOYEN' : 'MINIME'}</span>
                              </div>
                            </div>
                          ))}
                        </div>
                      </div>
                    ))}
                  </div>
                );
              })()}


              {/* ── DÉFICITAIRES ── */}
              {statModal === 'deficit' && (
                deficitLoading ? (
                  <p style={{ textAlign: 'center', padding: '24px 0', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>Chargement du rapport...</p>
                ) : deficitData.length === 0 ? (
                  <p style={{ textAlign: 'center', color: 'hsl(var(--color-success))', fontWeight: 700, padding: '24px 0' }}>Aucun client déficitaire pour la dernière période. ✓</p>
                ) : (
                  <div>
                    <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '8px' }}>
                      {deficitData.length} client(s) dont la dette actuelle (BP) dépasse la commission de la dernière période — {deficitData[0]?.period}.
                    </p>
                    <div style={{ overflowX: 'auto' }}>
                      <table className="premium-table" style={{ fontSize: '0.7rem' }}>
                        <thead>
                          <tr style={{ fontSize: '0.6rem', textTransform: 'uppercase' }}>
                            <th style={{ padding: '6px 8px' }}>Code</th>
                            <th style={{ padding: '6px 8px' }}>Nom</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>Commande (FC)</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>CM (FC)</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>BP (FC)</th>
                            <th style={{ padding: '6px 8px', textAlign: 'right' }}>Déficit (FC)</th>
                          </tr>
                        </thead>
                        <tbody>
                          {deficitData.map(row => (
                            <tr key={row.client_code}>
                              <td style={{ padding: '6px 8px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{row.client_code}</td>
                              <td style={{ padding: '6px 8px', fontWeight: 600 }}>{row.client_name}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.order_value).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{parseFloat(row.commission_gross).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-warning))' }}>{parseFloat(row.current_debt).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-danger))' }}>{parseFloat(row.deficit).toLocaleString('fr-FR')}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    <div style={{ marginTop: '8px', padding: '8px 10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))', display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800 }}>
                      <span>Déficit total :</span>
                      <span style={{ color: 'hsl(var(--color-danger))' }}>
                        {deficitData.reduce((s, r) => s + parseFloat(r.deficit), 0).toLocaleString('fr-FR')} FC
                      </span>
                    </div>
                  </div>
                )
              )}

            </div>

            <div style={{ padding: '10px 18px', borderTop: '1px solid hsl(var(--border-color))' }}>
              <button onClick={() => setStatModal(null)} className="btn btn-secondary" style={{ width: '100%', fontSize: '0.8rem', padding: '7px' }}>Fermer</button>
            </div>
        </Modal>
      )}

      {/* ═══ §7 — BASSINS ═══ */}
      {(user?.can_access_all_nodes) && (
        <div style={{ background: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))', borderRadius: 12, padding: 24 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16, flexWrap: 'wrap', gap: 8 }}>
            <h3 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: 'hsl(var(--text-primary))' }}>
              §7 — Classement BASSINS
            </h3>
            {bassinRows.length > 0 && (
              <div style={{ display: 'flex', gap: 8 }}>
                <button
                  onClick={handleBassinPrint}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600 }}
                  title="Imprimer le tableau"
                >
                  <FiPrinter size={13} />
                  <span>Imprimer</span>
                </button>
                <button
                  onClick={handleBassinExport}
                  style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '5px 12px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', cursor: 'pointer', fontSize: '0.75rem', fontWeight: 600 }}
                  title="Exporter en Excel (CSV)"
                >
                  <FiDownload size={13} />
                  <span>Excel</span>
                </button>
              </div>
            )}
          </div>

          {/* Filters */}
          <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
            {nodesList.length > 0 && (
              <div>
                <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Succursale</label>
                <select value={bassinNode} onChange={e => setBassinNode(e.target.value)}
                  style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                  <option value="">— Choisir —</option>
                  {nodesList.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
                </select>
              </div>
            )}
            <div>
              <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Mois</label>
              <select value={bassinMonth} onChange={e => setBassinMonth(Number(e.target.value))}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                  <option key={m} value={m}>{new Date(2000, m - 1).toLocaleString('fr-FR', { month: 'long' })}</option>
                ))}
              </select>
            </div>
            <div>
              <label style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Année</label>
              <select value={bassinYear} onChange={e => setBassinYear(Number(e.target.value))}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
              </select>
            </div>
            <button onClick={loadBassins} disabled={!bassinNode || bassinLoading}
              style={{ padding: '7px 18px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.875rem', opacity: !bassinNode ? 0.5 : 1 }}>
              {bassinLoading ? 'Chargement…' : 'Charger'}
            </button>
            {bassinMsg && <span style={{ fontSize: '0.8rem', color: 'hsl(var(--color-warning))' }}>{bassinMsg}</span>}
          </div>

          {/* Thresholds legend */}
          {Object.keys(bassinThresholds).length > 0 && (
            <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 14 }}>
              {['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT'].map((cat, i) => {
                const colors = ['hsl(45,90%,40%)','hsl(200,80%,40%)','hsl(160,60%,40%)','hsl(280,50%,45%)','hsl(0,0%,50%)'];
                const thresh = bassinThresholds[cat];
                return (
                  <div key={cat} style={{ padding: '4px 10px', borderRadius: 10, background: colors[i] + '22', border: `1px solid ${colors[i]}55`, fontSize: '0.72rem', fontWeight: 700, color: colors[i] }}>
                    {cat}{thresh ? ` ≥ ${thresh.toLocaleString('fr-FR')} FC` : ' < seuil'}
                  </div>
                );
              })}
            </div>
          )}

          {/* Table grouped by category */}
          {bassinRows.length > 0 && (() => {
            const CATS = ['GRAND FORMAT', 'INTER G&M', 'INTER M&PT', 'MOYEN', 'PETIT'];
            const COLORS = ['hsl(45,90%,40%)','hsl(200,80%,40%)','hsl(160,60%,40%)','hsl(280,50%,45%)','hsl(0,0%,50%)'];
            return (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                      {['Rang', 'Code', 'Client', 'Commande (FC)', 'BP (FC)', 'CM (FC)', 'Net à Payer (FC)'].map(h => (
                        <th key={h} style={{ padding: '7px 10px', textAlign: ['Rang'].includes(h) ? 'center' : ['Commande (FC)','BP (FC)','CM (FC)','Net à Payer (FC)'].includes(h) ? 'right' : 'left', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {CATS.map((cat, ci) => {
                      const catRows = bassinRows.filter(r => r.category === cat);
                      if (catRows.length === 0) return null;
                      return [
                        <tr key={`cat-${cat}`}>
                          <td colSpan={7} style={{ padding: '6px 10px', background: COLORS[ci] + '18', borderTop: '2px solid ' + COLORS[ci] + '66', borderBottom: '1px solid ' + COLORS[ci] + '44', fontWeight: 800, fontSize: '0.78rem', color: COLORS[ci], letterSpacing: '0.05em' }}>
                            {cat} — {catRows.length} client(s)
                          </td>
                        </tr>,
                        ...catRows.map(r => (
                          <tr key={r.client_code} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                            <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 800, color: COLORS[ci] }}>{r.rank}</td>
                            <td style={{ padding: '6px 10px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{r.client_code}</td>
                            <td style={{ padding: '6px 10px' }}>{r.client_name}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 600 }}>{parseFloat(r.order_value).toLocaleString('fr-FR')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', color: parseFloat(r.bp) > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--color-success))' }}>{parseFloat(r.bp).toLocaleString('fr-FR')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{parseFloat(r.cm).toLocaleString('fr-FR')}</td>
                            <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 700, color: parseFloat(r.net_payable) < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-primary))' }}>{parseFloat(r.net_payable).toLocaleString('fr-FR')}</td>
                          </tr>
                        )),
                      ];
                    })}
                  </tbody>
                  <tfoot>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 800 }}>
                      <td colSpan={3} style={{ padding: '7px 10px' }}>{bassinRows.length} client(s)</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.order_value), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.bp), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.cm), 0).toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>{bassinRows.reduce((s, r) => s + parseFloat(r.net_payable), 0).toLocaleString('fr-FR')}</td>
                    </tr>
                  </tfoot>
                </table>
              </div>
            );
          })()}
        </div>
      )}

      {/* ═══ §6 — CAISSE SOCIALE ═══ */}
      <div style={{ background: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))', borderRadius: 12, padding: 24 }}>
        <h3 style={{ margin: '0 0 16px 0', fontWeight: 700, fontSize: '1rem', color: 'hsl(var(--text-primary))' }}>
          §6 — Caisse Sociale
        </h3>

        {/* Boulangerie + mois/année */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16, alignItems: 'flex-end' }}>
          {nodesList.length > 0 && (
            <div>
              <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 4 }}>Succursale</label>
              <select value={socialNode} onChange={e => setSocialNode(e.target.value)}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                <option value="">— Choisir —</option>
                {nodesList.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 4 }}>Mois</label>
            <select value={socialMonth} onChange={e => setSocialMonth(Number(e.target.value))}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                <option key={m} value={m}>{new Date(2000, m - 1).toLocaleString('fr-FR', { month: 'long' })}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 4 }}>Année</label>
            <select value={socialYear} onChange={e => setSocialYear(Number(e.target.value))}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
              {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '2px solid hsl(var(--border-color))' }}>
          {(['cotisations', 'distribution'] as const).map(tab => (
            <button key={tab} onClick={() => setSocialTab(tab)}
              style={{ padding: '8px 18px', border: 'none', background: 'none', cursor: 'pointer', fontWeight: socialTab === tab ? 700 : 400, color: socialTab === tab ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))', borderBottom: socialTab === tab ? '2px solid hsl(var(--accent-color))' : '2px solid transparent', marginBottom: -2, fontSize: '0.875rem', textTransform: 'capitalize' }}>
              {tab === 'cotisations' ? 'Cotisations Mensuelles' : 'Distribution Annuelle'}
            </button>
          ))}
        </div>

        {!socialNode ? (
          <div style={{ textAlign: 'center', padding: 32, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
            Sélectionnez une succursale pour afficher la Caisse Sociale.
          </div>
        ) : socialTab === 'cotisations' ? (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              <button onClick={handleBulkCreate}
                style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.8rem' }}>
                Générer fiches du mois
              </button>
              {bulkMsg && <span style={{ fontSize: '0.8rem', color: 'hsl(var(--color-success))' }}>{bulkMsg}</span>}
            </div>
            {socialLoading ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
            ) : contributions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
                Aucune cotisation pour ce mois. Cliquez "Générer fiches du mois" pour créer les fiches.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                      {['Client', 'Cotisation (FC)', 'Payé', 'Date paiement'].map(h => (
                        <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Cotisation (FC)' ? 'right' : 'left', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {contributions.map(c => (
                      <tr key={c.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                        <td style={{ padding: '7px 10px', fontWeight: 600 }}>{c.client_display || c.client}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right' }}>{parseFloat(c.amount).toLocaleString('fr-FR')}</td>
                        <td style={{ padding: '7px 10px' }}>
                          <button onClick={() => handleTogglePaid(c.id)}
                            style={{ padding: '3px 10px', borderRadius: 12, border: 'none', cursor: 'pointer', background: c.is_paid ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))', color: '#fff', fontWeight: 700, fontSize: '0.75rem' }}>
                            {c.is_paid ? '✓ Payé' : 'Non payé'}
                          </button>
                        </td>
                        <td style={{ padding: '7px 10px', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>
                          {c.paid_at ? new Date(c.paid_at).toLocaleDateString('fr-FR') : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 700 }}>
                      <td style={{ padding: '7px 10px' }}>{contributions.length} client(s)</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>
                        {contributions.reduce((s, c) => s + parseFloat(c.amount), 0).toLocaleString('fr-FR')} FC
                      </td>
                      <td style={{ padding: '7px 10px' }}>
                        {contributions.filter(c => c.is_paid).length} / {contributions.length} payé(s)
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        ) : (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              <button onClick={handleCreateDistribution}
                style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.8rem' }}>
                + Nouvelle distribution {socialYear}
              </button>
              {bulkMsg && <span style={{ fontSize: '0.8rem', color: 'hsl(var(--color-success))' }}>{bulkMsg}</span>}
            </div>
            {distLoading ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
            ) : distributions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
                Aucune distribution pour {socialYear}. Créez-en une pour commencer.
              </div>
            ) : (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {distributions.map(dist => (
                  <div key={dist.id} style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 8, padding: 14 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
                      <div>
                        <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>Distribution {dist.year}</span>
                        <span style={{ marginLeft: 12, fontSize: '0.8rem', color: 'hsl(var(--text-secondary))' }}>Tarif : {parseFloat(dist.tarif).toLocaleString('fr-FR')} FC/indice</span>
                        {dist.is_closed && <span style={{ marginLeft: 10, padding: '2px 8px', background: 'hsl(var(--color-success))', color: '#fff', borderRadius: 12, fontSize: '0.7rem', fontWeight: 700 }}>CLÔTURÉE</span>}
                      </div>
                      <div style={{ display: 'flex', gap: 8 }}>
                        <button onClick={() => { setSelectedDist(dist); setDistLines(dist.lines || []); setBulkMsg(null); }}
                          style={{ padding: '4px 12px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', fontSize: '0.8rem', color: 'hsl(var(--text-primary))' }}>
                          Voir lignes ({(dist.lines || []).length})
                        </button>
                        {!dist.is_closed && (
                          <button onClick={() => handleAutoPopulate(dist.id)}
                            style={{ padding: '4px 12px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 }}>
                            Auto-peupler
                          </button>
                        )}
                      </div>
                    </div>

                    {/* Lignes de distribution */}
                    {selectedDist?.id === dist.id && distLines.length > 0 && (
                      <div style={{ overflowX: 'auto', marginTop: 8 }}>
                        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                          <thead>
                            <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                              {['Client', 'Indice', 'Total Cot.', 'Remise', 'Mérite', 'Total à recevoir', 'Présence', 'Forme'].map(h => (
                                <th key={h} style={{ padding: '6px 8px', textAlign: ['Total Cot.', 'Remise', 'Mérite', 'Total à recevoir'].includes(h) ? 'right' : 'left', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                              ))}
                            </tr>
                          </thead>
                          <tbody>
                            {distLines.map(line => (
                              <tr key={line.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                                <td style={{ padding: '6px 8px', fontWeight: 600 }}>{line.client_display || line.client}</td>
                                <td style={{ padding: '6px 8px' }}>{line.indice}</td>
                                <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(line.total_social).toLocaleString('fr-FR')}</td>
                                <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{parseFloat(line.remise).toLocaleString('fr-FR')}</td>
                                <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{parseFloat(line.merite).toLocaleString('fr-FR')}</td>
                                <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{parseFloat(line.total_payer).toLocaleString('fr-FR')}</td>
                                <td style={{ padding: '6px 8px' }}>
                                  <span style={{ padding: '2px 7px', borderRadius: 10, fontSize: '0.7rem', fontWeight: 700, background: line.position === 'present' ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))', color: '#fff' }}>
                                    {line.position === 'present' ? 'Présent' : 'Absent'}
                                  </span>
                                </td>
                                <td style={{ padding: '6px 8px', fontSize: '0.78rem', color: 'hsl(var(--text-secondary))' }}>
                                  {line.form === 'especes' ? 'Espèces' : 'Colis'}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                          <tfoot>
                            <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 700 }}>
                              <td colSpan={2} style={{ padding: '6px 8px' }}>{distLines.length} client(s)</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right' }}>{distLines.reduce((s, l) => s + parseFloat(l.total_social), 0).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{distLines.reduce((s, l) => s + parseFloat(l.remise), 0).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>{distLines.reduce((s, l) => s + parseFloat(l.merite), 0).toLocaleString('fr-FR')}</td>
                              <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--accent-color))' }}>{distLines.reduce((s, l) => s + parseFloat(l.total_payer), 0).toLocaleString('fr-FR')}</td>
                              <td colSpan={2} />
                            </tr>
                          </tfoot>
                        </table>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

    </div>
  );
};
