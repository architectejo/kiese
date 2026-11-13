import React, { useState, useEffect, useCallback } from 'react';
import {
  FiDollarSign, FiPercent, FiCheck,
  FiPocket, FiAward, FiSearch, FiRefreshCw, FiEdit2,
  FiPrinter, FiDownload
} from 'react-icons/fi';
import { commissionsApi, coreApi, ClientCommission, BakeryNode } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useAuthStore } from '@/store/authStore';
import { localIsoDate } from '@/store/workDateStore';
import { Modal } from '@/components/shared/Modal';
import { useProgressiveList } from '@/hooks/useProgressiveList';

const MONTHS_FR = [
  'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
  'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
];

export const Commissions: React.FC = () => {
  const { user } = useAuthStore();
  const [payoutItem, setPayoutItem] = useState<ClientCommission | null>(null);
  const [payoutLoading, setPayoutLoading] = useState(false);
  const [ficheItem, setFicheItem]   = useState<ClientCommission | null>(null);
  const [manuelItem, setManuelItem] = useState<ClientCommission | null>(null);
  const [manuelValue, setManuelValue] = useState('');
  const [manuelNotes, setManuelNotes] = useState('');
  const [manuelLoading, setManuelLoading] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  // BUG-270 : « Payer » et l'ajustement manuel réservés à ADMIN/DIRECTION (403 pour COMPTABLE).
  const canPay = user?.role === 'ADMIN' || user?.role === 'DIRECTION' || !!user?.is_superuser;
  const [searchTerm, setSearchTerm] = useState('');
  const [statusFilter, setStatusFilter] = useState<'All' | 'Paid' | 'Unpaid'>('All');
  const [nodeFilter, setNodeFilter] = useState('');

  // Generate period modal
  const [isGenerateModalOpen, setIsGenerateModalOpen] = useState(false);
  const [nodesList, setNodesList] = useState<BakeryNode[]>([]);
  const today = new Date();
  const [genNode, setGenNode] = useState('');
  const [genMonth, setGenMonth] = useState(today.getMonth() + 1);
  const [genYear, setGenYear] = useState(today.getFullYear());
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [generateResult, setGenerateResult] = useState<string | null>(null);

  // BUG-164 : liste lue page par page (page 1 affichée tout de suite, suite en arrière-plan).
  // KPI, totaux d'impression/export, recherche et filtre de statut (côté client) ne sont
  // fiables qu'une fois la liste COMPLÈTE : voir `isReady` ci-dessous.
  const commissionsQ = useProgressiveList<ClientCommission>({
    fetchPage: p => commissionsApi.commissions.page({
      ...(nodeFilter ? { period__node: nodeFilter } : {}),
      page: String(p), page_size: '100',
    }),
    resetKey: `cm|${nodeFilter}`,
  });
  const commissions = commissionsQ.items;
  const isLoading = commissionsQ.isLoading;
  const isReady = commissionsQ.isComplete;
  const reloadCommissions = commissionsQ.reload;
  const loadData = useCallback(async () => { reloadCommissions(); }, [reloadCommissions]);
  const progress = `${commissionsQ.loaded} / ${commissionsQ.total ?? '…'}`;

  useEffect(() => {
    if (user?.can_access_all_nodes && nodesList.length === 0) {
      coreApi.nodes.list().then(res => setNodesList(res.data)).catch(() => {});
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user?.can_access_all_nodes]);

  const openGenerateModal = async () => {
    setGenerateError(null);
    setGenerateResult(null);
    setIsGenerateModalOpen(true);
    if (!user?.can_access_all_nodes && user?.node) {
      setGenNode(user.node);
    } else if (nodesList.length === 0) {
      try {
        const res = await coreApi.nodes.list();
        setNodesList(res.data);
        if (res.data.length > 0) setGenNode(res.data[0].id);
      } catch { /* ignore */ }
    }
  };

  const handleGenerate = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!genNode) { setGenerateError('Sélectionnez une boulangerie.'); return; }
    setGenerateError(null);
    setGenerateResult(null);
    setIsGenerating(true);
    try {
      const res = await commissionsApi.periods.generate({ node: genNode, month: genMonth, year: genYear });
      setGenerateResult(`${res.data.generated} commission(s) générée(s) pour ${MONTHS_FR[genMonth - 1]} ${genYear}.`);
      await loadData();
    } catch (err: unknown) {
      setGenerateError(getErrorDetail(err, 'Erreur lors de la génération.'));
    } finally {
      setIsGenerating(false);
    }
  };

  const filteredCommissions = commissions.filter(c => {
    const label = (c.client_display || c.client || '').toLowerCase();
    const matchesSearch = label.includes(searchTerm.toLowerCase());
    const matchesStatus = statusFilter === 'All' || (statusFilter === 'Paid' ? c.is_paid : !c.is_paid);
    return matchesSearch && matchesStatus;
  });

  const handleMarkPaid = async (id: string) => {
    if (payoutLoading) return;
    setPayoutLoading(true);
    setActionError(null);
    try {
      await commissionsApi.commissions.markPaid(id);
      await loadData();
      setPayoutItem(null);
    } catch (err) {
      setActionError(getErrorDetail(err, 'Erreur lors du paiement de la commission.'));
      setPayoutItem(null);
    } finally {
      setPayoutLoading(false);
    }
  };

  const openManuel = (c: ClientCommission) => {
    setManuelItem(c);
    setManuelValue(c.manuel_adjustment ?? '');
    setManuelNotes(c.manuel_notes ?? '');
  };

  const handleSetManuel = async (clear = false) => {
    if (!manuelItem) return;
    setManuelLoading(true);
    setActionError(null);
    try {
      await commissionsApi.commissions.setManuel(manuelItem.id, {
        manuel_adjustment: clear ? null : manuelValue,
        manuel_notes: clear ? '' : manuelNotes,
      });
      await loadData();
      setManuelItem(null);
      setFicheItem(null);
    } catch (err) {
      setActionError(getErrorDetail(err, "Erreur lors de l'enregistrement de l'ajustement."));
      setManuelItem(null);
      setFicheItem(null); // la fiche recouvrirait la bannière d'erreur (BUG-280)
    } finally {
      setManuelLoading(false);
    }
  };

  // Les trois KPI ne sont affichés que si la liste est complète (jamais de total partiel).
  const totalCalculated = commissions.reduce((s, c) => s + parseFloat(c.commission_gross || '0'), 0);
  const totalPaid = commissions.filter(c => c.is_paid).reduce((s, c) => s + parseFloat(c.net_payable || '0'), 0);
  const totalRemaining = commissions.filter(c => !c.is_paid).reduce((s, c) => s + parseFloat(c.net_payable || '0'), 0);

  const handlePrint = () => {
    if (!isReady) return;
    const dateStr = new Date().toLocaleDateString('fr-FR', { day: '2-digit', month: 'long', year: 'numeric' });
    const totCmd = filteredCommissions.reduce((s, c) => s + parseFloat(c.order_value || '0'), 0);
    const totCm  = filteredCommissions.reduce((s, c) => s + parseFloat(c.commission_gross || '0'), 0);
    const totNet = filteredCommissions.reduce((s, c) => s + parseFloat(c.net_payable || '0'), 0);
    const rows = filteredCommissions.map(c => {
      const net  = parseFloat(c.net_payable || '0');
      const rate = (parseFloat(c.commission_rate || '0') * 100).toFixed(0);
      return `<tr>
        <td>${c.client_display || c.client}</td>
        <td style="text-align:right">${parseFloat(c.order_value||'0').toLocaleString('fr-FR')}</td>
        <td style="text-align:center">${rate}%</td>
        <td style="text-align:right">${parseFloat(c.commission_gross||'0').toLocaleString('fr-FR')}</td>
        <td style="text-align:right">${parseFloat(c.net_ordi||'0').toLocaleString('fr-FR')}</td>
        <td style="text-align:right;color:#dc2626">−${parseFloat(c.deduction_carte||'0').toLocaleString('fr-FR')}</td>
        <td style="text-align:right">${parseFloat(c.net_carte||'0').toLocaleString('fr-FR')}</td>
        <td style="text-align:right;font-weight:bold;color:${net<0?'#dc2626':'#059669'}">${net<0?`(${Math.abs(net).toLocaleString('fr-FR')})`:net.toLocaleString('fr-FR')}</td>
        <td style="text-align:center"><span style="padding:2px 6px;border-radius:4px;font-size:10px;font-weight:bold;background:${c.is_paid?'#d1fae5':'#fef3c7'};color:${c.is_paid?'#065f46':'#92400e'}">${c.is_paid?'PAYÉ':'EN ATTENTE'}</span></td>
      </tr>`;
    }).join('');
    const html = `<!DOCTYPE html><html lang="fr"><head><meta charset="UTF-8"><title>Situation des Ristournes</title>
      <style>*{box-sizing:border-box}body{font-family:Arial,sans-serif;font-size:10.5px;padding:20px;color:#111}
      h1{font-size:14px;margin:0 0 2px}.sub{font-size:10px;color:#666;margin-bottom:14px}
      table{width:100%;border-collapse:collapse}th{background:#f3f4f6;font-weight:bold;padding:5px 7px;border:1px solid #d1d5db;font-size:9.5px;text-transform:uppercase}
      td{padding:4px 7px;border:1px solid #e5e7eb}tr:nth-child(even){background:#f9fafb}
      tfoot td{font-weight:bold;background:#f3f4f6;border-top:2px solid #9ca3af}
      @media print{body{padding:10px}}</style></head><body>
      <h1>Situation des Ristournes &amp; Rémunérations</h1>
      <div class="sub">Imprimé le ${dateStr} · ${filteredCommissions.length} client(s)</div>
      <table><thead><tr>
        <th>Client</th><th style="text-align:right">Commande (FC)</th><th style="text-align:center">Taux</th>
        <th style="text-align:right">CM Brute</th><th style="text-align:right">NET/ORDI</th>
        <th style="text-align:right">CARTE 1%</th><th style="text-align:right">NET/CARTE</th>
        <th style="text-align:right">NET À PAYER</th><th style="text-align:center">Statut</th>
      </tr></thead><tbody>${rows}</tbody>
      <tfoot><tr>
        <td>TOTAL (${filteredCommissions.length} clients)</td>
        <td style="text-align:right">${totCmd.toLocaleString('fr-FR')}</td>
        <td></td><td style="text-align:right">${totCm.toLocaleString('fr-FR')}</td>
        <td></td><td></td><td></td>
        <td style="text-align:right;color:#059669">${totNet.toLocaleString('fr-FR')}</td>
        <td></td>
      </tr></tfoot></table></body></html>`;
    const win = window.open('', '_blank', 'width=1100,height=750');
    if (!win) return;
    win.document.write(html);
    win.document.close();
    win.focus();
    setTimeout(() => { win.print(); }, 400);
  };

  const handleExportExcel = () => {
    if (!isReady) return;
    const headers = ['Client', 'Commande (FC)', 'Taux CM', 'CM Brute (FC)', 'NET/ORDI (FC)', 'CARTE 1% (FC)', 'NET/CARTE (FC)', 'NET À PAYER (FC)', 'Statut'];
    const rows = filteredCommissions.map(c => [
      c.client_display || c.client,
      parseFloat(c.order_value || '0'),
      (parseFloat(c.commission_rate || '0') * 100).toFixed(0) + '%',
      parseFloat(c.commission_gross || '0'),
      parseFloat(c.net_ordi || '0'),
      parseFloat(c.deduction_carte || '0'),
      parseFloat(c.net_carte || '0'),
      parseFloat(c.net_payable || '0'),
      c.is_paid ? 'PAYÉ' : 'EN ATTENTE',
    ]);
    const csv = [headers, ...rows]
      .map(row => row.map(cell => `"${String(cell).replace(/"/g, '""')}"`).join(';'))
      .join('\r\n');
    const blob = new Blob(['﻿' + csv], { type: 'text/csv;charset=utf-8;' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `ristournes_${localIsoDate()}.csv`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', fontSize: '0.85rem' }}>

      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '16px 20px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '16px', flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '2px' }}>Commissions des Revendeurs (CM)</h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem' }}>
              Calcul automatique des commissions brutes, déductions et net à payer.
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <button onClick={openGenerateModal} className="btn btn-primary" style={{ padding: '8px 16px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiRefreshCw />
              <span>Générer Commissions</span>
            </button>
            <FiAward style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
          </div>
        </div>
      </div>

      {/* KPIs */}
      <div className="kpi-grid" style={{ gap: '14px' }}>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--accent-color) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--accent-color))' }}>
            <FiPercent />
          </div>
          <div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>COMMISSIONS GÉNÉRÉES</div>
            <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{isReady ? `${totalCalculated.toLocaleString('fr-FR')} FC` : `calcul en cours… ${progress}`}</h3>
          </div>
        </div>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--color-success) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--color-success))' }}>
            <FiCheck />
          </div>
          <div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>COMMISSIONS PAYÉES</div>
            <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{isReady ? `${totalPaid.toLocaleString('fr-FR')} FC` : `calcul en cours… ${progress}`}</h3>
          </div>
        </div>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--color-danger) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--color-danger))' }}>
            <FiDollarSign />
          </div>
          <div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>RESTE À VERSER</div>
            <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{isReady ? `${totalRemaining.toLocaleString('fr-FR')} FC` : `calcul en cours… ${progress}`}</h3>
          </div>
        </div>
      </div>

      {commissionsQ.error && (
        <div role="alert" className="glass-card" style={{ padding: '10px 14px', color: 'hsl(var(--color-danger))', fontSize: '0.78rem', display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {commissionsQ.error}
          <button onClick={reloadCommissions} className="btn btn-secondary" style={{ padding: '3px 10px', fontSize: '0.7rem' }}>Réessayer</button>
        </div>
      )}

      {/* Bandeau : aucune commission générée pour le mois courant */}
      {isReady && commissions.length === 0 && (
        <div className="glass-card animate-fade-in" style={{
          padding: '14px 18px',
          borderLeft: '4px solid hsl(var(--color-warning))',
          background: 'hsl(var(--color-warning) / 0.06)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '16px', flexWrap: 'wrap'
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
            <FiRefreshCw style={{ color: 'hsl(var(--color-warning))', fontSize: '1.2rem', flexShrink: 0 }} />
            <div>
              <div style={{ fontWeight: 800, fontSize: '0.82rem', color: 'hsl(var(--color-warning))' }}>
                Aucune commission générée pour cette période
              </div>
              <div style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', marginTop: '2px' }}>
                Cliquez sur "Générer Commissions" pour calculer les commissions du mois courant à partir des factures livrées.
              </div>
            </div>
          </div>
          <button onClick={openGenerateModal} className="btn btn-primary" style={{ padding: '7px 14px', fontSize: '0.76rem', display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
            <FiRefreshCw />
            <span>Générer maintenant</span>
          </button>
        </div>
      )}

      {/* Search & Filter */}
      <div className="glass-card" style={{ padding: '14px' }}>
        <div style={{ display: 'flex', gap: '12px', flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ flex: 2, minWidth: '240px', position: 'relative' }}>
            <FiSearch style={{ position: 'absolute', left: '12px', top: '50%', transform: 'translateY(-50%)', color: 'hsl(var(--text-muted))' }} />
            <input
              type="text"
              placeholder="Rechercher un client..."
              value={searchTerm}
              onChange={(e) => setSearchTerm(e.target.value)}
              className="form-input"
              style={{ paddingLeft: '36px', height: '36px', fontSize: '0.8rem' }}
            />
          </div>
          <div style={{ flex: 1, minWidth: '160px' }}>
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value as 'All' | 'Paid' | 'Unpaid')}
              className="form-input"
              style={{ cursor: 'pointer', height: '36px', fontSize: '0.8rem' }}
            >
              <option value="All">Tous les statuts</option>
              <option value="Unpaid">En attente</option>
              <option value="Paid">Payé</option>
            </select>
          </div>
          {user?.can_access_all_nodes && (
            <div style={{ flex: 1, minWidth: '180px' }}>
              <select
                value={nodeFilter}
                onChange={(e) => setNodeFilter(e.target.value)}
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
        </div>
        {!isLoading && !isReady && !commissionsQ.error && (searchTerm || statusFilter !== 'All') && (
          <div role="status" style={{ marginTop: '8px', fontSize: '0.7rem', color: 'hsl(var(--color-warning))' }}>
            Chargement en cours ({progress}) : la recherche et le filtre portent sur les commissions déjà chargées — le résultat sera complet à la fin du chargement.
          </div>
        )}
      </div>

      {/* Table */}
      <div className="glass-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 800, margin: 0 }}>
            Situation des Ristournes & Rémunérations
          </h2>
          {!isLoading && filteredCommissions.length > 0 && (
            <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
              {!isReady && !commissionsQ.error && (
                <span role="status" style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))' }}>
                  {progress} chargées — impression et export après chargement complet
                </span>
              )}
              <button
                onClick={handlePrint}
                disabled={!isReady}
                className="btn btn-secondary"
                style={{ padding: '5px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '5px' }}
                title={isReady ? 'Imprimer le tableau' : 'Disponible une fois toutes les commissions chargées'}
              >
                <FiPrinter />
                <span>Imprimer</span>
              </button>
              <button
                onClick={handleExportExcel}
                disabled={!isReady}
                className="btn btn-secondary"
                style={{ padding: '5px 12px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '5px' }}
                title={isReady ? 'Exporter en Excel (CSV)' : 'Disponible une fois toutes les commissions chargées'}
              >
                <FiDownload />
                <span>Excel</span>
              </button>
            </div>
          )}
        </div>
        {isLoading ? (
          <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))' }}>Chargement...</div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                  <th style={{ padding: '8px 10px' }}>Client</th>
                  <th style={{ padding: '8px 10px' }}>Cmd (FC)</th>
                  <th style={{ padding: '8px 10px' }}>Tx</th>
                  <th style={{ padding: '8px 10px' }}>CM Brute</th>
                  <th style={{ padding: '8px 10px' }}>NET/ORDI</th>
                  <th style={{ padding: '8px 10px' }}>CARTE 1%</th>
                  <th style={{ padding: '8px 10px' }}>NET/CARTE</th>
                  <th style={{ padding: '8px 10px', fontWeight: 900 }}>NET À PAYER</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center' }}>Statut</th>
                  <th style={{ padding: '8px 10px', textAlign: 'center' }}>Action</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {filteredCommissions.map(c => {
                  const netPayable = parseFloat(c.net_payable || '0');
                  const netOrdi   = parseFloat(c.net_ordi   || '0');
                  const netCarte  = parseFloat(c.net_carte  || '0');
                  const carte     = parseFloat(c.deduction_carte || '0');
                  const rate      = parseFloat(c.commission_rate || '0') * 100;
                  const hasManuel = c.manuel_adjustment != null;
                  const carriedDebtIn = parseFloat(c.carried_debt_in || '0');
                  return (
                    <tr
                      key={c.id}
                      onClick={() => setFicheItem(c)}
                      style={{ cursor: 'pointer' }}
                      onMouseEnter={e => (e.currentTarget.style.backgroundColor = 'hsl(var(--bg-tertiary))')}
                      onMouseLeave={e => (e.currentTarget.style.backgroundColor = '')}
                    >
                      <td style={{ padding: '8px 10px', fontWeight: 800 }}>
                        {c.client_display || c.client}
                        {hasManuel && <span title="Ajustement manuel" style={{ marginLeft: '4px', color: 'hsl(var(--color-warning))', fontSize: '0.6rem' }}>✎</span>}
                        {carriedDebtIn > 0 && (
                          <span
                            title={`Report période précédente (dette de commission non remise à zéro) : −${carriedDebtIn.toLocaleString('fr-FR')} FC`}
                            style={{
                              marginLeft: '4px', fontSize: '0.56rem', fontWeight: 700, padding: '1px 5px', borderRadius: '4px',
                              color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.1)',
                            }}
                          >
                            Report
                          </span>
                        )}
                      </td>
                      <td style={{ padding: '8px 10px' }}>{parseFloat(c.order_value || '0').toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '8px 10px' }}>
                        <span className="badge badge-info" style={{ fontSize: '0.58rem', padding: '2px 5px' }}>{rate}%</span>
                      </td>
                      <td style={{ padding: '8px 10px', fontWeight: 700 }}>{parseFloat(c.commission_gross || '0').toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '8px 10px' }}>{netOrdi.toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '8px 10px', color: 'hsl(var(--color-danger))' }}>−{carte.toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '8px 10px' }}>{netCarte.toLocaleString('fr-FR')}</td>
                      <td style={{ padding: '8px 10px', fontWeight: 800, color: netPayable < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))' }}>
                        {netPayable < 0
                          ? `Client: ${Math.abs(netPayable).toLocaleString('fr-FR')} FC`
                          : `${netPayable.toLocaleString('fr-FR')} FC`}
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        <span className={`badge ${c.is_paid ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.58rem', padding: '2px 5px' }}>
                          {c.is_paid ? 'PAYÉ' : 'EN ATTENTE'}
                        </span>
                      </td>
                      <td style={{ padding: '8px 10px', textAlign: 'center' }}>
                        {c.is_paid ? (
                          <span style={{ color: 'hsl(var(--color-success))', fontWeight: 700, fontSize: '0.65rem' }}>À jour</span>
                        ) : canPay && netPayable < 0 ? (
                          <span title="Net négatif : non payable, solde reporté comme dette" style={{ color: 'hsl(var(--color-danger))', fontWeight: 700, fontSize: '0.6rem' }}>Net négatif</span>
                        ) : canPay ? (
                          <button
                            onClick={e => { e.stopPropagation(); setPayoutItem(c); }}
                            className="btn btn-primary"
                            style={{ padding: '3px 8px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px', margin: '0 auto' }}
                          >
                            <FiPocket />
                            <span>Régler</span>
                          </button>
                        ) : (
                          <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.65rem' }}>—</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
                {filteredCommissions.length === 0 && (
                  <tr><td colSpan={10} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-muted))' }}>
                    {commissions.length === 0 ? 'Aucune commission enregistrée' : isReady ? 'Aucun résultat pour ces filtres' : 'Aucun résultat parmi les commissions déjà chargées…'}
                  </td></tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {actionError && (
        <div role="alert" style={{ margin: '8px 0', padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', color: 'hsl(var(--color-danger))', fontSize: '0.78rem', fontWeight: 700, display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
          <span>{actionError}</span>
          <button onClick={() => setActionError(null)} style={{ background: 'none', border: 'none', color: 'inherit', cursor: 'pointer' }} aria-label="Fermer">×</button>
        </div>
      )}

      {/* Payout Modal */}
      {payoutItem && (
        <Modal isOpen={true} onClose={() => setPayoutItem(null)} title="Confirmer le Paiement" maxWidth="400px">
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', marginBottom: '16px' }}>
              Marquer la commission de <strong>{payoutItem.client_display || payoutItem.client}</strong> comme payée ?<br />
              Net à payer : <strong>{parseFloat(payoutItem.net_payable || '0').toLocaleString('fr-FR')} FC</strong>
            </p>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button onClick={() => setPayoutItem(null)} className="btn btn-secondary" style={{ flex: 1, padding: '6px 12px', fontSize: '0.78rem' }}>
                Annuler
              </button>
              <button onClick={() => handleMarkPaid(payoutItem.id)} disabled={payoutLoading} className="btn btn-primary" style={{ flex: 1, padding: '6px 12px', fontSize: '0.78rem', opacity: payoutLoading ? 0.6 : 1 }}>
                {payoutLoading ? 'Confirmation...' : 'Confirmer'}
              </button>
            </div>
        </Modal>
      )}

      {/* Fiche de Paie Modal */}
      {ficheItem && (() => {
        const f        = ficheItem;
        const gross    = parseFloat(f.commission_gross   || '0');
        const debt     = parseFloat(f.deduction_debt     || '0');
        const netOrdi  = parseFloat(f.net_ordi           || '0');
        const carte    = parseFloat(f.deduction_carte    || '0');
        const netCarte = parseFloat(f.net_carte          || '0');
        const social   = parseFloat(f.deduction_social   || '0');
        const prints   = parseFloat(f.deduction_prints   || '0');
        const other    = parseFloat(f.deduction_other    || '0');
        const remise   = parseFloat(f.deduction_remise   || '0');
        const carriedDebtIn = parseFloat(f.carried_debt_in || '0');
        const net      = parseFloat(f.net_payable        || '0');
        const rate     = parseFloat(f.commission_rate    || '0') * 100;
        const isDir    = canPay;
        const fmt = (n: number) => n.toLocaleString('fr-FR') + ' FC';
        const row = (label: string, value: number, color?: string, prefix = '') => (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0', borderBottom: '1px solid hsl(var(--border-color) / 0.4)', fontSize: '0.76rem' }}>
            <span style={{ color: 'hsl(var(--text-secondary))' }}>{label}</span>
            <span style={{ fontWeight: 700, color: color || 'hsl(var(--text-primary))' }}>{prefix}{fmt(value)}</span>
          </div>
        );
        const subtotalRow = (label: string, value: number) => (
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 0 5px 8px', borderBottom: '1px dashed hsl(var(--border-color) / 0.6)', fontSize: '0.76rem', background: 'hsl(var(--bg-secondary) / 0.6)' }}>
            <span style={{ fontWeight: 700, fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
            <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{fmt(value)}</span>
          </div>
        );
        return (
          <Modal isOpen={true} onClose={() => setFicheItem(null)} maxWidth="420px">
              <div style={{ marginBottom: '14px' }}>
                <div style={{ fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-muted))', textTransform: 'uppercase', marginBottom: '2px' }}>
                  Fiche de Paie CM · {f.period_display || f.period}
                </div>
                <div style={{ fontSize: '1.05rem', fontWeight: 800 }}>{f.client_display || f.client}</div>
                <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>
                  {f.total_breads?.toLocaleString('fr-FR') || '—'} pains livrés · Taux {rate.toFixed(0)}% · {f.node_display || ''}
                </div>
              </div>

              <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', padding: '10px 14px', marginBottom: '10px' }}>
                {row('ORDI (CM brute)', gross, 'hsl(var(--accent-color))')}
                {debt > 0 && row('(−) Retenue BP (dette)', debt, 'hsl(var(--color-danger))', '−')}
                {subtotalRow('= NET / ORDI', netOrdi)}
                {carte > 0 && row('(−) CARTE 1%', carte, 'hsl(var(--color-danger))', '−')}
                {subtotalRow('= NET / CARTE', netCarte)}
                {social > 0 && row('(−) Cotisation sociale',  social, 'hsl(var(--color-danger))', '−')}
                {prints > 0 && row('(−) Frais imprimés',      prints, 'hsl(var(--color-danger))', '−')}
                {other  > 0 && row('(−) Retenues diverses',   other,  'hsl(var(--color-danger))', '−')}
                {remise > 0 && row('(−) Remise 0,1%',         remise, 'hsl(var(--color-danger))', '−')}
                {carriedDebtIn > 0 && (
                  <div style={{ padding: '5px 0', borderBottom: '1px solid hsl(var(--border-color) / 0.4)', fontSize: '0.76rem' }} title="Dette de commission non réglée lors de la période précédente, reportée et jamais remise à zéro">
                    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                      <span style={{ color: 'hsl(var(--color-danger))', fontWeight: 700 }}>(−) Report période précédente</span>
                      <span style={{ fontWeight: 800, color: 'hsl(var(--color-danger))' }}>−{fmt(carriedDebtIn)}</span>
                    </div>
                    {f.manuel_adjustment != null && (
                      <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>
                        ↳ non appliqué au net à payer : un ajustement manuel est en vigueur
                      </div>
                    )}
                  </div>
                )}

                {f.manuel_adjustment != null && (
                  <div style={{ padding: '5px 0', borderBottom: '1px solid hsl(var(--border-color) / 0.4)', fontSize: '0.76rem' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <span style={{ color: 'hsl(var(--color-warning))' }}>✎ Ajustement Manuel</span>
                      <span style={{ fontWeight: 700, color: 'hsl(var(--color-warning))' }}>{fmt(parseFloat(f.manuel_adjustment))}</span>
                    </div>
                    {f.manuel_notes && <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>↳ {f.manuel_notes}</div>}
                  </div>
                )}

                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', paddingTop: '8px', marginTop: '4px', borderTop: '2px solid hsl(var(--border-color))' }}>
                  <span style={{ fontWeight: 800, fontSize: '0.85rem' }}>NET À PAYER</span>
                  <span style={{ fontWeight: 800, fontSize: '1rem', color: net >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>{fmt(net)}</span>
                </div>

                {net < 0 && (
                  <div style={{ marginTop: '6px', padding: '4px 8px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.1)', fontSize: '0.72rem', color: 'hsl(var(--color-danger))', fontWeight: 700, textAlign: 'center' }}>
                    P/RECEPT — Client doit : {Math.abs(net).toLocaleString('fr-FR')} FC
                  </div>
                )}
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px' }}>
                <span className={`badge ${f.is_paid ? 'badge-success' : 'badge-warning'}`} style={{ fontSize: '0.7rem', padding: '3px 8px' }}>
                  {f.is_paid ? `PAYÉ${f.paid_at ? ' le ' + new Date(f.paid_at).toLocaleDateString('fr-FR') : ''}` : 'EN ATTENTE DE PAIEMENT'}
                </span>
                {f.is_paid && f.paid_by && (
                  <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>par {f.paid_by}</span>
                )}
              </div>

              <div style={{ display: 'flex', gap: '8px', flexDirection: 'column' }}>
                {!f.is_paid && isDir && net < 0 && (
                  <div style={{ fontSize: '0.74rem', color: 'hsl(var(--color-danger))', fontWeight: 600 }}>
                    Net à payer négatif : paiement impossible, le solde est reporté comme dette.
                  </div>
                )}
                {!f.is_paid && isDir && net >= 0 && (
                  <button
                    onClick={() => { setFicheItem(null); setPayoutItem(f); }}
                    className="btn btn-primary"
                    style={{ width: '100%', padding: '8px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                  >
                    <FiPocket /> Régler cette commission
                  </button>
                )}
                {isDir && (
                  <button
                    onClick={() => openManuel(f)}
                    className="btn btn-secondary"
                    style={{ width: '100%', padding: '7px', fontSize: '0.76rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                  >
                    <FiEdit2 /> {f.manuel_adjustment != null ? 'Modifier l\'ajustement manuel' : 'Ajustement manuel'}
                  </button>
                )}
              </div>
          </Modal>
        );
      })()}

      {/* Modal Ajustement Manuel */}
      {manuelItem && (
        <Modal
          isOpen={true}
          onClose={() => setManuelItem(null)}
          title="Ajustement Manuel"
          subtitle={<>Saisir le montant net à payer manuellement pour <strong>{manuelItem.client_display || manuelItem.client}</strong>. Laissez vide pour supprimer l'ajustement.</>}
          maxWidth="380px"
        >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Montant Net Manuel (FC)</label>
                <input
                  type="number"
                  value={manuelValue}
                  onChange={e => setManuelValue(e.target.value)}
                  placeholder={`Net calculé : ${parseFloat(manuelItem.net_payable || '0').toLocaleString('fr-FR')} FC`}
                  className="form-input"
                  style={{ height: '36px', fontSize: '0.82rem' }}
                />
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Observation (OBSERV)</label>
                <textarea
                  value={manuelNotes}
                  onChange={e => setManuelNotes(e.target.value)}
                  placeholder="Raison de l'ajustement..."
                  className="form-input"
                  style={{ height: '64px', fontSize: '0.8rem', resize: 'vertical' }}
                />
              </div>
              <div style={{ display: 'flex', gap: '8px' }}>
                <button onClick={() => setManuelItem(null)} className="btn btn-secondary" style={{ flex: 1, padding: '7px', fontSize: '0.78rem' }}>
                  Annuler
                </button>
                {manuelItem.manuel_adjustment != null && (
                  <button onClick={() => handleSetManuel(true)} disabled={manuelLoading} className="btn btn-secondary" style={{ flex: 1, padding: '7px', fontSize: '0.78rem', color: 'hsl(var(--color-danger))' }}>
                    Supprimer
                  </button>
                )}
                <button onClick={() => handleSetManuel(false)} disabled={manuelLoading || !manuelValue} className="btn btn-primary" style={{ flex: 1, padding: '7px', fontSize: '0.78rem' }}>
                  {manuelLoading ? '...' : 'Enregistrer'}
                </button>
              </div>
            </div>
        </Modal>
      )}

      {/* Generate Period Modal */}
      <Modal
        isOpen={isGenerateModalOpen}
        onClose={() => setIsGenerateModalOpen(false)}
        title="Générer une Période de Commissions"
        subtitle="Calcule automatiquement la commission de chaque client à partir des factures livrées du mois choisi."
        maxWidth="420px"
      >
            <form onSubmit={handleGenerate} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              {(user?.can_access_all_nodes) && (
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Boulangerie *</label>
                  <select value={genNode} onChange={e => setGenNode(e.target.value)} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }} required>
                    <option value="">Sélectionner...</option>
                    {nodesList.map(n => (
                      <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
                    ))}
                  </select>
                </div>
              )}
              <div style={{ display: 'grid', gridTemplateColumns: '1.5fr 1fr', gap: '10px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Mois *</label>
                  <select value={genMonth} onChange={e => setGenMonth(Number(e.target.value))} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }}>
                    {MONTHS_FR.map((m, i) => (
                      <option key={m} value={i + 1}>{m}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px' }}>Année *</label>
                  <input type="number" value={genYear} onChange={e => setGenYear(Number(e.target.value))} className="form-input" style={{ height: '36px', fontSize: '0.8rem' }} />
                </div>
              </div>

              {generateError && (
                <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: '0.72rem', color: 'hsl(var(--color-danger))' }}>{generateError}</div>
              )}
              {generateResult && (
                <div style={{ backgroundColor: 'hsl(var(--color-success) / 0.1)', border: '1px solid hsl(var(--color-success) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 10px', fontSize: '0.72rem', color: 'hsl(var(--color-success))' }}>{generateResult}</div>
              )}

              <div style={{ display: 'flex', gap: '10px', marginTop: '4px' }}>
                <button type="button" onClick={() => setIsGenerateModalOpen(false)} className="btn btn-secondary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.8rem' }}>
                  Fermer
                </button>
                <button type="submit" disabled={isGenerating} className="btn btn-primary" style={{ flex: 1, padding: '8px 12px', fontSize: '0.8rem' }}>
                  {isGenerating ? 'Génération...' : 'Générer'}
                </button>
              </div>
            </form>
      </Modal>
    </div>
  );
};
