import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FiPrinter } from 'react-icons/fi';
import { treasuryApi } from '@/api/services';
import type { DailySavings } from '@/api/services';
import { treasuryErrorMessage } from '@/components/treasury/treasuryRules';
import { PAGE_SIZE, progressLabel, fmt } from '@/components/treasury/treasuryShared';
import { printSavingsDay } from '@/components/treasury/treasuryPrint';
import { useAuthStore } from '@/store/authStore';
import { useProgressiveList } from '@/hooks/useProgressiveList';

interface Props {
  today: string;
  nodeFilter: string;
  isHq: boolean;
  canWriteTreasury: boolean;
}

// §5.1.5 — Épargne journalière (liste du mois, totaux serveur, filtre par jour, impression, saisie gérant+).
export const SavingsSection: React.FC<Props> = ({ today, nodeFilter, isHq, canWriteTreasury }) => {
  const { user } = useAuthStore();
  const nodeParam: Record<string, string> = nodeFilter ? { node: nodeFilter } : {};
  const [savingsMonth, setSavingsMonth] = useState(() => new Date().getMonth() + 1);
  const [savingsYear, setSavingsYear]   = useState(() => new Date().getFullYear());
  const [savingsTotal, setSavingsTotal] = useState<{
    total_flour_sacks: string; total_revenue: string; total_savings: string;
  } | null>(null);
  const [sDate, setSDate]         = useState(today);
  const [sFlour, setSFlour]       = useState('');
  const [sRevenue, setSRevenue]   = useState('');
  const [sRate, setSRate]         = useState('0.1580');
  const [sError, setSError]       = useState<string | null>(null);
  const [sSubmitting, setSSubmitting] = useState(false);
  const [savingsDayFilter, setSavingsDayFilter] = useState('');

  const savingsQ = useProgressiveList<DailySavings>({
    fetchPage: p => treasuryApi.savings.page({ month: String(savingsMonth), year: String(savingsYear), ...nodeParam, page: String(p), page_size: PAGE_SIZE }),
    resetKey: `sav|${savingsMonth}|${savingsYear}|${nodeFilter}`,
  });
  const savingsEntries = savingsQ.items;
  const savingsLoading = savingsQ.isLoading;

  // BUG-161 (F3) : à la relève (passage de minuit), le sélecteur de jour suit la nouvelle journée.
  const prevTodayRef = useRef(today);
  useEffect(() => {
    const previous = prevTodayRef.current;
    if (previous === today) return;
    prevTodayRef.current = today;
    setSDate(d => (d === previous ? today : d));
  }, [today]);

  // §5.1.5 — Épargne Journalière load
  const reloadSavingsEntries = savingsQ.reload;
  const loadSavingsTotal = useCallback(async () => {
    const params: Record<string, string> = { month: String(savingsMonth), year: String(savingsYear) };
    if (nodeFilter) params.node = nodeFilter;
    try {
      const totalRes = await treasuryApi.savings.monthlyTotal(params);
      setSavingsTotal(totalRes.data ?? null);
    } catch { /* ignore */ }
  }, [savingsMonth, savingsYear, nodeFilter]);
  const loadSavings = useCallback(async () => {
    reloadSavingsEntries();
    await loadSavingsTotal();
  }, [reloadSavingsEntries, loadSavingsTotal]);

  useEffect(() => { loadSavingsTotal(); }, [loadSavingsTotal]);

  const handleSavingsSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setSError(null);
    if (!canWriteTreasury) { setSError("Enregistrement réservé au gérant et aux rôles supérieurs."); return; }
    const rev = parseFloat(sRevenue) || 0;
    if (rev <= 0) { setSError('Indiquez le revenu du jour.'); return; }
    const flour = parseFloat(sFlour || '0');
    if (!Number.isFinite(flour) || flour < 0) { setSError('Le nombre de sacs ne peut pas être négatif.'); return; }
    const rate = parseFloat(sRate);
    if (!Number.isFinite(rate) || rate < 0 || rate > 1) { setSError("Le taux d'épargne doit être compris entre 0 et 1 (ex. 0,158)."); return; }
    setSSubmitting(true);
    try {
      const payload: Record<string, string> = {
        date: sDate,
        flour_sacks: sFlour || '0',
        daily_revenue: String(rev),
        savings_rate: sRate,
      };
      // BUG-231 / BUG-206 : `node` n'est envoyé que par le siège (le serveur l'ignore sinon).
      if (isHq && nodeFilter) payload.node = nodeFilter;
      await treasuryApi.savings.create(payload);
      setSFlour(''); setSRevenue('');
      await loadSavings();
    } catch (err: unknown) {
      setSError(treasuryErrorMessage(err, "Erreur lors de l'enregistrement."));
    } finally {
      setSSubmitting(false);
    }
  };

  // §5.1.5 — filtre par jour + impression journalière
  // BUG-164 : jours disponibles, totaux filtrés par jour et impression journalière =
  // calculés sur la liste chargée -> disponibles seulement quand elle est complète.
  const savingsReady = savingsQ.isComplete;
  const savingsDaysAvailable = Array.from(new Set(savingsEntries.map(s => s.date.split('-')[2]))).sort();
  const filteredSavingsEntries = savingsDayFilter
    ? savingsEntries.filter(s => s.date.split('-')[2] === savingsDayFilter)
    : savingsEntries;
  const filteredSavingsTotals = savingsDayFilter
    ? {
        total_flour_sacks: String(filteredSavingsEntries.reduce((a, s) => a + parseFloat(s.flour_sacks || '0'), 0)),
        total_revenue:     String(filteredSavingsEntries.reduce((a, s) => a + parseFloat(s.daily_revenue || '0'), 0)),
        total_savings:     String(filteredSavingsEntries.reduce((a, s) => a + parseFloat(s.savings_amount || '0'), 0)),
      }
    : savingsTotal;
  const savingsTotalsReady = savingsDayFilter ? savingsReady : true;

  const handlePrintSavingsDay = (day: string) => {
    if (!savingsReady) return;
    printSavingsDay(savingsEntries, day);
  };

  return (
      <div style={{ background: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))', borderRadius: 12, padding: 24, marginTop: 24 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16, flexWrap: 'wrap', gap: 12 }}>
          <h3 style={{ margin: 0, fontWeight: 700, fontSize: '1rem', color: 'hsl(var(--text-primary))' }}>
            §5.1.5 — Épargne Journalière
          </h3>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <button onClick={() => { const d = new Date(savingsYear, savingsMonth - 2); setSavingsMonth(d.getMonth() + 1); setSavingsYear(d.getFullYear()); setSavingsDayFilter(''); }} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}>◀</button>
            <span style={{ fontWeight: 600, fontSize: '0.9rem', minWidth: 100, textAlign: 'center' }}>
              {new Date(savingsYear, savingsMonth - 1).toLocaleString('fr-FR', { month: 'long', year: 'numeric' })}
            </span>
            <button onClick={() => { const d = new Date(savingsYear, savingsMonth); setSavingsMonth(d.getMonth() + 1); setSavingsYear(d.getFullYear()); setSavingsDayFilter(''); }} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}>▶</button>
            <select
              value={savingsDayFilter}
              onChange={e => setSavingsDayFilter(e.target.value)}
              disabled={!savingsReady}
              title={savingsReady ? undefined : `Filtre par jour disponible une fois la liste chargée (${savingsQ.loaded}/${savingsQ.total ?? '…'})`}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.85rem' }}
            >
              <option value="">Tous les jours</option>
              {savingsDaysAvailable.map(d => <option key={d} value={d}>Jour {d}</option>)}
            </select>
            {savingsDayFilter && savingsReady && (
              <button
                onClick={() => handlePrintSavingsDay(savingsDayFilter)}
                title={`Imprimer le ${savingsDayFilter}`}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))', display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.8rem' }}
              >
                <FiPrinter /> Imprimer
              </button>
            )}
          </div>
        </div>

        {/* Totaux */}
        {filteredSavingsTotals && (
          <div style={{ display: 'flex', gap: 16, marginBottom: 16, flexWrap: 'wrap' }}>
            {[
              { label: 'Total Sacs Farine', value: savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_flour_sacks)} sacs` : progressLabel(savingsQ), color: 'hsl(var(--text-secondary))' },
              { label: 'Total Revenu', value: savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_revenue)} FC` : progressLabel(savingsQ), color: 'hsl(var(--color-success))' },
              { label: 'Total Épargne', value: savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_savings)} FC` : progressLabel(savingsQ), color: 'hsl(var(--accent-color))' },
            ].map(kpi => (
              <div key={kpi.label} style={{ flex: '1 1 160px', background: 'hsl(var(--bg-tertiary))', borderRadius: 8, padding: '10px 14px', border: '1px solid hsl(var(--border-color))' }}>
                <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', marginBottom: 4 }}>{kpi.label}</div>
                <div style={{ fontWeight: 700, color: kpi.color }}>{kpi.value}</div>
              </div>
            ))}
          </div>
        )}

        {/* Formulaire saisie (BUG-231 : gérant et au-dessus) */}
        {canWriteTreasury && (
        <form onSubmit={handleSavingsSubmit} style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 20, alignItems: 'flex-end' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Date</label>
            <input type="date" value={sDate} onChange={e => setSDate(e.target.value)} required
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Sacs farine (PROD)</label>
            <input type="number" step="0.01" min="0" value={sFlour} onChange={e => setSFlour(e.target.value)} placeholder="0"
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem', width: 100 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Revenu du jour (FC) *</label>
            <input type="number" step="1" min="0" value={sRevenue} onChange={e => setSRevenue(e.target.value)} placeholder="0" required
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem', width: 130 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Taux épargne</label>
            <input type="number" step="0.0001" min="0" max="1" value={sRate} onChange={e => setSRate(e.target.value)}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem', width: 90 }} />
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>Épargne calculée</label>
            <div style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))', color: 'hsl(var(--accent-color))', fontSize: '0.875rem', width: 130, fontWeight: 700, minHeight: 32, display: 'flex', alignItems: 'center' }}>
              {sRevenue && sRate ? `${fmt(parseFloat(sRevenue) * parseFloat(sRate))} FC` : '—'}
            </div>
          </div>
          <button type="submit" disabled={sSubmitting}
            style={{ padding: '7px 18px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: sSubmitting ? 'not-allowed' : 'pointer', opacity: sSubmitting ? 0.6 : 1, whiteSpace: 'nowrap' }}>
            {sSubmitting ? 'Enregistrement…' : '+ Enregistrer'}
          </button>
          {sError && <div style={{ color: 'hsl(var(--color-danger))', fontSize: '0.8rem', alignSelf: 'center' }}>{sError}</div>}
        </form>
        )}

        {/* Table mensuelle */}
        {savingsQ.error && (
          <div role="alert" style={{ textAlign: 'center', padding: 8, color: 'hsl(var(--color-danger))', fontSize: '0.8rem' }}>
            {savingsQ.error}{' '}
            <button onClick={reloadSavingsEntries} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.62rem' }}>Réessayer</button>
          </div>
        )}
        {savingsLoading ? (
          <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
        ) : filteredSavingsEntries.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
            {savingsDayFilter ? `Aucune épargne enregistrée pour le jour ${savingsDayFilter}.` : 'Aucune épargne enregistrée pour ce mois.'}
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.85rem' }}>
              <thead>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                  {['Date', user?.can_access_all_nodes ? 'Succursale' : null, 'Sacs PROD', 'Revenu (FC)', 'Taux', 'Épargne (FC)', ''].filter(h => h !== null).map((h, i) => (
                    <th key={h || `col-${i}`} style={{ padding: '8px 10px', textAlign: h === 'Date' || h === 'Succursale' ? 'left' : 'right', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.78rem', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredSavingsEntries.map(s => (
                  <tr key={s.id} style={{ borderBottom: '1px solid hsl(var(--border-color))', transition: 'background 0.15s' }}
                    onMouseEnter={e => (e.currentTarget.style.background = 'hsl(var(--bg-tertiary))')}
                    onMouseLeave={e => (e.currentTarget.style.background = '')}>
                    <td style={{ padding: '8px 10px' }}>{new Date(s.date).toLocaleDateString('fr-FR')}</td>
                    {user?.can_access_all_nodes && <td style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{s.node_display || s.node}</td>}
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>{fmt(s.flour_sacks)}</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>{fmt(s.daily_revenue)}</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{(parseFloat(s.savings_rate) * 100).toFixed(2)}%</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{fmt(s.savings_amount)} FC</td>
                    <td style={{ textAlign: 'right', padding: '8px 10px' }}>
                      <button
                        onClick={() => handlePrintSavingsDay(s.date.split('-')[2])}
                        disabled={!savingsReady}
                        title={`Imprimer le ${s.date.split('-')[2]}`}
                        style={{ padding: '3px 5px', borderRadius: 4, border: '1px solid hsl(var(--border-color))', background: 'none', color: 'hsl(var(--text-secondary))', cursor: 'pointer' }}
                      >
                        <FiPrinter size={11} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 700 }}>
                  <td colSpan={user?.can_access_all_nodes ? 2 : 1} style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>{savingsDayFilter ? filteredSavingsEntries.length : (savingsQ.total ?? filteredSavingsEntries.length)} entrée(s)</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px' }}>{filteredSavingsTotals && savingsTotalsReady ? fmt(filteredSavingsTotals.total_flour_sacks) : '…'}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--color-success))' }}>{filteredSavingsTotals && savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_revenue)} FC` : '…'}</td>
                  <td style={{ textAlign: 'right', padding: '8px 10px' }}></td>
                  <td style={{ textAlign: 'right', padding: '8px 10px', color: 'hsl(var(--accent-color))' }}>{filteredSavingsTotals && savingsTotalsReady ? `${fmt(filteredSavingsTotals.total_savings)} FC` : '…'}</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
  );
};
