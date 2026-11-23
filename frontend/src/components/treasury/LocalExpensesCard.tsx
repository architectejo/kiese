import React, { useEffect, useState } from 'react';
import { FiCalendar, FiPlus, FiX } from 'react-icons/fi';
import { treasuryApi, coreApi } from '@/api/services';
import type { ExpenseCategory, LocalExpense } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { fmt } from '@/components/treasury/treasuryShared';

interface Props {
  today: string;
  /** Boulangerie filtrée (siège) ; ignorée si l'utilisateur est rattaché à une boulangerie. */
  nodeFilter: string;
  userHasNode: boolean;
  selectedNodeLabel: string | null;
  expenses: LocalExpense[];
  isLoading: boolean;
  error: string | null;
  dayReady: boolean;
  netCaisse: number;
  onOpenHistory: () => void;
  /** Rechargement complet après l'enregistrement d'une dépense. */
  onAdded: () => Promise<void>;
}

/** §5.1.2 — Dépenses locales du jour (formulaire d'ajout, liste, caisse nette). */
export const LocalExpensesCard: React.FC<Props> = ({
  today, nodeFilter, userHasNode, selectedNodeLabel, expenses, isLoading, error,
  dayReady, netCaisse, onOpenHistory, onAdded,
}) => {
  const [showExpenseForm, setShowExpenseForm] = useState(false);
  const [expDesc, setExpDesc]       = useState('');
  const [expCategory, setExpCategory] = useState('');
  const [expAmount, setExpAmount]   = useState('');
  const [expError, setExpError]     = useState<string | null>(null);
  const [expenseCategories, setExpenseCategories] = useState<ExpenseCategory[]>([]);

  // Load expense categories once (§5.1.2 — managed from Configuration)
  useEffect(() => {
    coreApi.expenseCategories.list().then(res => {
      const active = (res.data || []).filter(ec => ec.is_active);
      setExpenseCategories(active);
      if (active.length > 0) setExpCategory(prev => prev || String(active[0].id));
    }).catch(() => {});
  }, []);

  const handleAddExpense = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    setExpError(null);
    if (!expDesc || !expAmount || !expCategory) { setExpError('Remplissez tous les champs.'); return; }
    if (!(parseFloat(expAmount) > 0)) { setExpError('Le montant de la dépense doit être supérieur à 0.'); return; }
    try {
      await treasuryApi.expenses.create({
        description: expDesc, category: Number(expCategory),
        amount: expAmount, date: today,
        ...(nodeFilter && !userHasNode ? { node: nodeFilter } : {}),
      });
      setExpDesc(''); setExpAmount('');
      setShowExpenseForm(false);
      await onAdded();
    } catch (err: unknown) {
      setExpError(getErrorDetail(err, "Erreur lors de l'enregistrement de la dépense."));
    }
  };

  return (
    <div className="glass-card" style={{ padding: '14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <h2 style={{ fontSize: '0.85rem', fontWeight: 800 }}>
          §5.1.2 — Dépenses Locales
          {selectedNodeLabel && (
            <span style={{ fontSize: '0.58rem', color: 'hsl(var(--accent-color))', fontWeight: 700, marginLeft: '6px' }}>
              · {selectedNodeLabel}
            </span>
          )}
        </h2>
        <div style={{ display: 'flex', gap: '6px' }}>
          <button onClick={onOpenHistory} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
            <FiCalendar /> Historique
          </button>
          <button onClick={() => setShowExpenseForm(!showExpenseForm)} className="btn btn-secondary" style={{ padding: '4px 8px', fontSize: '0.65rem', display: 'flex', alignItems: 'center', gap: '3px' }}>
            {showExpenseForm ? <FiX /> : <FiPlus />}
            {showExpenseForm ? 'Annuler' : 'Ajouter'}
          </button>
        </div>
      </div>

      {showExpenseForm && (
        <form noValidate onSubmit={handleAddExpense} style={{ display: 'flex', flexDirection: 'column', gap: '6px', marginBottom: '10px', padding: '10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '6px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>Catégorie</label>
              <select value={expCategory} onChange={e => setExpCategory(e.target.value)} className="form-input" style={{ fontSize: '0.7rem', height: '28px' }}>
                {expenseCategories.length === 0 && <option value="">Aucune catégorie — voir Configuration</option>}
                {expenseCategories.map(ec => <option key={ec.id} value={ec.id}>{ec.label}</option>)}
              </select>
            </div>
            <div>
              <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>Montant (FC)</label>
              <input type="number" min={1} value={expAmount} onChange={e => setExpAmount(e.target.value)} placeholder="0" className="form-input" style={{ fontSize: '0.75rem', height: '28px', padding: '0 6px' }} />
            </div>
          </div>
          <div>
            <label style={{ display: 'block', fontSize: '0.6rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '2px' }}>Description</label>
            <input type="text" value={expDesc} onChange={e => setExpDesc(e.target.value)} placeholder="Nature de la dépense..." className="form-input" style={{ fontSize: '0.7rem', height: '28px', padding: '0 6px' }} />
          </div>
          {expError && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--color-danger))' }}>{expError}</div>}
          <button type="submit" className="btn btn-primary" style={{ padding: '5px', fontSize: '0.72rem' }}>Enregistrer la Dépense</button>
        </form>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px', maxHeight: '150px', overflowY: 'auto' }}>
        {expenses.map(e => (
          <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.68rem', padding: '4px 6px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px' }}>
            <span style={{ color: 'hsl(var(--text-secondary))' }}>{e.description} <em>({e.category_display || e.category})</em></span>
            <strong style={{ color: 'hsl(var(--color-danger))' }}>-{fmt(e.amount)} FC</strong>
          </div>
        ))}
        {isLoading && <div style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '8px' }}>Chargement des dépenses…</div>}
        {error && <div role="alert" style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--color-danger))', padding: '8px' }}>{error}</div>}
        {!isLoading && !error && expenses.length === 0 && <div style={{ textAlign: 'center', fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '8px' }}>Aucune dépense locale</div>}
      </div>

      {/* Net caisse */}
      <div style={{ marginTop: '8px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '6px', display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', fontWeight: 800 }}>
        <span>Caisse Nette Boulangerie :</span>
        {dayReady ? (
          <span style={{ color: netCaisse >= 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
            {fmt(netCaisse)} FC
          </span>
        ) : (
          <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>calcul en cours…</span>
        )}
      </div>
    </div>
  );
};
