import React, { useState, useEffect, useCallback, useRef } from 'react';
import { FiDollarSign, FiPlus } from 'react-icons/fi';
import { treasuryApi } from '@/api/services';
import type { DirectionCashCount } from '@/api/services';
import { isInvalidBillCount, parseBillCount, validateBillCounts, treasuryErrorMessage } from '@/components/treasury/treasuryRules';
import { BILLS, fmt } from '@/components/treasury/treasuryShared';
import type { BillKey } from '@/components/treasury/treasuryShared';
import { useAuthStore } from '@/store/authStore';

// §5.1.3c — BUG-119 : Comptage physique de caisse Direction (contrôle annexe, séparé du chaînage SHA-256).
export const DirectionCashCountSection: React.FC<{ today: string; dateFrom: string; dateTo: string }> = ({ today, dateFrom, dateTo }) => {
  const { user } = useAuthStore();
  const [directionCashCounts, setDirectionCashCounts] = useState<DirectionCashCount[]>([]);
  const [dccLoading, setDccLoading] = useState(false);
  const [showDccForm, setShowDccForm] = useState(false);
  const [dccDate, setDccDate] = useState(today);
  const [dccBills, setDccBills] = useState<Record<BillKey, number>>({
    bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0,
    bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0,
  });
  const [dccNotes, setDccNotes] = useState('');
  const [dccError, setDccError] = useState<string | null>(null);
  const [dccSubmitting, setDccSubmitting] = useState(false);

  // BUG-161 (F3) : à la relève (passage de minuit), le sélecteur de jour suit la nouvelle journée.
  const prevTodayRef = useRef(today);
  useEffect(() => {
    const previous = prevTodayRef.current;
    if (previous === today) return;
    prevTodayRef.current = today;
    setDccDate(d => (d === previous ? today : d));
  }, [today]);

  const loadDirectionCashCounts = useCallback(async () => {
    if (!user?.can_access_all_nodes) return;
    setDccLoading(true);
    try {
      const res = await treasuryApi.directionCashCounts.list({ date_from: dateFrom, date_to: dateTo });
      setDirectionCashCounts(Array.isArray(res.data) ? res.data : []);
    } catch { /* ignore */ }
    finally { setDccLoading(false); }
  }, [user?.can_access_all_nodes, dateFrom, dateTo]);

  useEffect(() => { loadDirectionCashCounts(); }, [loadDirectionCashCounts]);

  const dccBillTotal = BILLS.reduce((sum, b) => sum + dccBills[b.key] * b.face, 0);

  const handleCreateDirectionCashCount = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setDccError(null);
    const dccProblem = validateBillCounts(dccBills);
    if (dccProblem) { setDccError(dccProblem); return; }
    if (dccBillTotal <= 0) { setDccError('Effectuez le billetage (entrez les coupures).'); return; }
    setDccSubmitting(true);
    try {
      await treasuryApi.directionCashCounts.create({
        date: dccDate, notes: dccNotes,
        ...dccBills,
      });
      setDccBills({ bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0, bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0 });
      setDccNotes('');
      setDccDate(today);
      setShowDccForm(false);
      await loadDirectionCashCounts();
    } catch (err: unknown) {
      setDccError(treasuryErrorMessage(err, "Erreur lors de l'enregistrement du comptage."));
    } finally {
      setDccSubmitting(false);
    }
  };

  return (
        <div style={{ marginTop: '18px', paddingTop: '16px', borderTop: '1px solid hsl(var(--border-color))' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '10px' }}>
            <h3 style={{ fontSize: '0.8rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
              Comptage Physique de Caisse — Direction
            </h3>
            <button
              type="button"
              onClick={() => setShowDccForm(v => !v)}
              className="btn btn-primary"
              style={{ padding: '5px 12px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px' }}
            >
              <FiPlus /> {showDccForm ? 'Annuler' : 'Nouveau comptage'}
            </button>
          </div>

          {showDccForm && (
            <form noValidate onSubmit={handleCreateDirectionCashCount} style={{ display: 'flex', flexDirection: 'column', gap: '10px', marginBottom: '14px', padding: '12px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Date du comptage *</label>
                <input
                  type="date" value={dccDate} onChange={e => setDccDate(e.target.value)}
                  className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', maxWidth: '200px' }} required
                />
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '5px' }}>Billetage (comptage physique)</label>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: '6px' }}>
                  {BILLS.map(b => (
                    <div key={b.key}>
                      <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>{b.label}</div>
                      <input
                        type="number" inputMode="numeric" value={dccBills[b.key]} aria-invalid={isInvalidBillCount(dccBills[b.key])}
                        onChange={e => setDccBills(prev => ({ ...prev, [b.key]: parseBillCount(e.target.value) }))}
                        className="form-input" style={{ height: '28px', fontSize: '0.72rem', padding: '0 6px', width: '100%' }}
                      />
                    </div>
                  ))}
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px' }}>Observations</label>
                <input
                  type="text" value={dccNotes} onChange={e => setDccNotes(e.target.value)}
                  placeholder="optionnel" className="form-input" style={{ height: '30px', fontSize: '0.75rem', padding: '0 8px', width: '100%' }}
                />
              </div>

              <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', padding: '6px 8px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)' }}>
                <span>Total compté</span>
                <strong style={{ color: 'hsl(var(--accent-color))' }}>{fmt(dccBillTotal)} FC</strong>
              </div>
              <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>
                Le solde théorique du Livre de Caisse Direction à cette date et l'écart sont calculés automatiquement par le serveur à l'enregistrement.
              </div>

              {dccError && <div style={{ fontSize: '0.7rem', color: 'hsl(var(--color-danger))' }}>{dccError}</div>}
              <button type="submit" disabled={dccSubmitting} className="btn btn-primary" style={{ padding: '7px', fontSize: '0.75rem' }}>
                {dccSubmitting ? 'Enregistrement...' : 'Enregistrer le comptage'}
              </button>
            </form>
          )}

          {/* Historique des comptages — écart coloré comme §5.2 (Clôture Gérant) */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {dccLoading ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Chargement...</div>
            ) : directionCashCounts.length === 0 ? (
              <div style={{ textAlign: 'center', fontSize: '0.72rem', color: 'hsl(var(--text-muted))', padding: '10px' }}>Aucun comptage physique Direction sur la période.</div>
            ) : (
              directionCashCounts.map(c => {
                const gap = parseFloat(c.cash_gap || '0');
                return (
                  <div key={c.id} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '8px 10px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--bg-secondary))', flexWrap: 'wrap', gap: '8px' }}>
                    <div>
                      <div style={{ fontSize: '0.75rem', fontWeight: 700 }}>
                        {new Date(c.date).toLocaleDateString('fr-FR')}
                      </div>
                      <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>
                        Compté : {fmt(c.physical_cash_total)} FC · Théorique : {fmt(c.theoretical_balance)} FC · {c.counted_by_display || '—'}
                        {c.notes && ` · ${c.notes}`}
                      </div>
                    </div>
                    <strong style={{ fontSize: '0.78rem', color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                      {gap >= 0 ? '+' : ''}{fmt(c.cash_gap)} FC{gap === 0 ? ' (sans écart)' : gap > 0 ? ' (excédent)' : ' (manquant)'}
                    </strong>
                  </div>
                );
              })
            )}
          </div>
        </div>
  );
};
