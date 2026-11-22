import React, { useState } from 'react';
import { treasuryApi, LocalExpense } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { PAGE_SIZE, progressLabel, fmt } from '@/components/treasury/treasuryShared';

interface Props {
  isOpen: boolean;
  onClose: () => void;
  /** Identifiant de boulangerie filtrée ('' = toutes, selon les droits du compte). */
  nodeFilter: string;
  subtitle?: string;
  /** Affiche le nom de la boulangerie à côté de chaque dépense (siège). */
  showNode: boolean;
}

/** §5.1.2 — Historique mensuel des Dépenses Locales, jour par jour (modale). */
export const ExpenseHistoryModal: React.FC<Props> = ({ isOpen, onClose, nodeFilter, subtitle, showNode }) => {
  const [expenseHistoryMonth, setExpenseHistoryMonth] = useState(() => new Date().getMonth() + 1);
  const [expenseHistoryYear, setExpenseHistoryYear] = useState(() => new Date().getFullYear());
  const expenseHistoryQ = useProgressiveList<LocalExpense>({
    fetchPage: p => treasuryApi.expenses.page({
      month: String(expenseHistoryMonth), year: String(expenseHistoryYear),
      ...(nodeFilter ? { node: nodeFilter } : {}), page: String(p), page_size: PAGE_SIZE,
    }),
    resetKey: `exph|${expenseHistoryMonth}|${expenseHistoryYear}|${nodeFilter}`,
    enabled: isOpen,
  });
  const expenseHistoryEntries = expenseHistoryQ.items;
  const expenseHistoryLoading = expenseHistoryQ.isLoading;

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Historique des Dépenses Locales"
      subtitle={subtitle}
      maxWidth="620px"
    >
      <div style={{ display: 'flex', justifyContent: 'center', alignItems: 'center', gap: '10px', marginBottom: '14px' }}>
        <button
          onClick={() => { const d = new Date(expenseHistoryYear, expenseHistoryMonth - 2); setExpenseHistoryMonth(d.getMonth() + 1); setExpenseHistoryYear(d.getFullYear()); }}
          style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}
        >◀</button>
        <span style={{ fontWeight: 700, fontSize: '0.85rem', minWidth: '120px', textAlign: 'center' }}>
          {new Date(expenseHistoryYear, expenseHistoryMonth - 1).toLocaleString('fr-FR', { month: 'long', year: 'numeric' })}
        </span>
        <button
          onClick={() => { const d = new Date(expenseHistoryYear, expenseHistoryMonth); setExpenseHistoryMonth(d.getMonth() + 1); setExpenseHistoryYear(d.getFullYear()); }}
          style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'none', cursor: 'pointer', color: 'hsl(var(--text-primary))' }}
        >▶</button>
      </div>

      {expenseHistoryQ.error && (
        <div role="alert" style={{ textAlign: 'center', padding: '8px', color: 'hsl(var(--color-danger))', fontSize: '0.78rem' }}>{expenseHistoryQ.error}</div>
      )}
      {expenseHistoryLoading ? (
        <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-secondary))', fontSize: '0.82rem' }}>Chargement...</div>
      ) : expenseHistoryEntries.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.82rem' }}>Aucune dépense pour ce mois.</div>
      ) : (() => {
        const byDay: Record<string, LocalExpense[]> = {};
        expenseHistoryEntries.forEach(e => {
          byDay[e.date] = byDay[e.date] || [];
          byDay[e.date].push(e);
        });
        const days = Object.keys(byDay).sort((a, b) => b.localeCompare(a));
        const monthTotal = expenseHistoryEntries.reduce((s, e) => s + parseFloat(e.amount || '0'), 0);
        return (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.78rem', fontWeight: 800, padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)' }}>
              <span>Total du mois ({expenseHistoryQ.total ?? expenseHistoryEntries.length} dépense{(expenseHistoryQ.total ?? expenseHistoryEntries.length) > 1 ? 's' : ''})</span>
              <span style={{ color: expenseHistoryQ.isComplete ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))', fontWeight: expenseHistoryQ.isComplete ? 800 : 600 }}>
                {expenseHistoryQ.isComplete ? `−${monthTotal.toLocaleString('fr-FR')} FC` : progressLabel(expenseHistoryQ)}
              </span>
            </div>
            {days.map(day => {
              const dayEntries = byDay[day];
              const dayTotal = dayEntries.reduce((s, e) => s + parseFloat(e.amount || '0'), 0);
              return (
                <div key={day}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', fontSize: '0.72rem', fontWeight: 800, color: 'hsl(var(--accent-color))', marginBottom: '6px', borderBottom: '1px solid hsl(var(--border-color))', paddingBottom: '4px' }}>
                    <span>{new Date(day).toLocaleDateString('fr-FR', { weekday: 'long', day: '2-digit', month: 'long' })}</span>
                    <span>{expenseHistoryQ.isComplete ? `−${dayTotal.toLocaleString('fr-FR')} FC` : '…'}</span>
                  </div>
                  <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                    {dayEntries.map(e => (
                      <div key={e.id} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', padding: '5px 8px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px' }}>
                        <span style={{ color: 'hsl(var(--text-secondary))' }}>
                          {e.description} <em>({e.category_display || e.category})</em>
                          {showNode && e.node_display && (
                            <span style={{ color: 'hsl(var(--text-muted))' }}> · {e.node_display}</span>
                          )}
                        </span>
                        <strong style={{ color: 'hsl(var(--color-danger))', whiteSpace: 'nowrap', marginLeft: '8px' }}>-{fmt(e.amount)} FC</strong>
                      </div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
        );
      })()}
    </Modal>
  );
};
