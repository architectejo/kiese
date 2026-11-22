import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FiBook, FiRefreshCw } from 'react-icons/fi';
import { treasuryApi, coreApi } from '@/api/services';
import type { CashbookEntry, BakeryNode, DisbursementVoucher } from '@/api/services';
import { isGerantOrAbove } from '@/components/treasury/treasuryRules';
import { PAGE_SIZE } from '@/components/treasury/treasuryShared';
import { useAuthStore } from '@/store/authStore';
import { useWorkDate } from '@/store/workDateStore';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { CashbookEntryModal } from '@/components/treasury/CashbookEntryModal';
import { VouchersSection } from '@/components/treasury/VouchersSection';
import { CashbookSection } from '@/components/treasury/CashbookSection';
import { JournalSection } from '@/components/treasury/JournalSection';
import { SavingsSection } from '@/components/treasury/SavingsSection';

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

  const cashbook = cashbookQ.items;
  const reloadCashbook = cashbookQ.reload;
  const reloadVouchers = vouchersQ.reload;
  // Rechargement après une action (bordereau, filtre de dates).
  const loadData = useCallback(async () => {
    reloadCashbook(); reloadVouchers();
  }, [reloadCashbook, reloadVouchers]);
  const isLoading = cashbookQ.isLoading;

  // BUG-161 (F3) : à la relève (passage de minuit), le sélecteur de fin de période suit la nouvelle journée.
  const prevTodayRef = useRef(today);
  useEffect(() => {
    const previous = prevTodayRef.current;
    if (previous === today) return;
    prevTodayRef.current = today;
    setDateTo(d => (d === previous ? today : d));
  }, [today]);

  // Load nodes list (HQ needs it for the bakery filter; every role needs it
  // to resolve their own node's "Valeur Théorique par Sac de Farine (FC)" —
  // NodeViewSet.list() is open to any authenticated user).
  useEffect(() => {
    coreApi.nodes.list().then(res => setAllNodes(res.data)).catch(() => {});
  }, []);

  // Active node label for visual indicators
  const selectedNode = allNodes.find(n => n.id === nodeFilter);
  const selectedNodeLabel = selectedNode
    ? `${selectedNode.code} — ${selectedNode.name}`
    : (!user?.can_access_all_nodes && user?.node_display)
      ? user.node_display
      : null;

  // Current consolidated balance — cashbook is ordered newest-first, so [0] is the latest entry
  // BUG-164 : `consolidatedBalance` = `running_balance` de la 1re écriture. Le serveur trie
  // (-date, -created_at) AVANT de paginer : la page 1 contient donc exactement la même
  // écriture [0] que la liste complète, et `running_balance` est une valeur stockée dans
  // l'écriture (aucune somme côté client) -> fiable dès la page 1, sans attendre la
  // complétude. Elle dépend en revanche du tri serveur : ne jamais re-trier ici.
  const consolidatedBalance = cashbook.length > 0 ? parseFloat(cashbook[0].running_balance) : 0;
  const consolidatedBalanceReady = !cashbookQ.isLoading && cashbookQ.error === null;

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
      {isHq && (
        <VouchersSection
          today={today} dateFrom={dateFrom} dateTo={dateTo} vouchersQ={vouchersQ}
          consolidatedBalance={consolidatedBalance} consolidatedBalanceReady={consolidatedBalanceReady}
          balanceError={cashbookQ.error} onCreated={loadData}
        />
      )}

      {/* ═══ §5.1.3 — NIVEAU 3 : LIVRE DE CAISSE DIRECTION ═══ */}
      {/* BUG-044 : réservé au siège (IsHeadquarters côté API depuis BUG-026) — masqué pour GERANT/FACTURIER/LIVREUR plutôt que de laisser les appels échouer en 403. */}
      {isHq && (
        <CashbookSection
          today={today} dateFrom={dateFrom} dateTo={dateTo}
          onDateFromChange={setDateFrom} onDateToChange={setDateTo}
          cashbookQ={cashbookQ} onFilter={loadData} onSelectEntry={setDetailEntry}
        />
      )}

      {/* ═══ §5.1.4 — JOURNAL DE CAISSE PAR BOULANGERIE ═══ */}
      <JournalSection today={today} nodeFilter={nodeFilter} isHq={isHq} canWriteTreasury={canWriteTreasury} />

      {/* ═══ §5.1.5 — ÉPARGNE JOURNALIÈRE ═══ */}
      <SavingsSection today={today} nodeFilter={nodeFilter} isHq={isHq} canWriteTreasury={canWriteTreasury} />

      {detailEntry && <CashbookEntryModal entry={detailEntry} onClose={() => setDetailEntry(null)} />}
    </div>
  );
};
