import React from 'react';
import { Link } from 'react-router-dom';
import { FiCheckCircle, FiDollarSign, FiLock } from 'react-icons/fi';
import type { CashClosure } from '@/api/services';
import { isInvalidBillCount, parseBillCount } from '@/components/treasury/treasuryRules';
import { BILLS, fmt } from '@/components/treasury/treasuryShared';
import type { BillKey } from '@/components/treasury/treasuryShared';

export type BillCounts = Record<BillKey, number>;

interface Props {
  /** Journée sur laquelle porte la clôture (AAAA-MM-JJ) — BUG-1304 : peut être la veille terminée. */
  today: string;
  /** Borne haute du sélecteur de date rétroactive (journée en cours). */
  maxDate: string;
  /** Journée au format JJ/MM/AAAA, pour les libellés. */
  dayLabel: string;
  editingClosure: CashClosure | null;
  todayClosure: CashClosure | undefined;
  selectedNodeLabel: string | null;
  bills: BillCounts;
  onBillsChange: (updater: (prev: BillCounts) => BillCounts) => void;
  closureNotes: string;
  onNotesChange: (v: string) => void;
  closureDate: string;
  onClosureDateChange: (v: string) => void;
  allowBackdatedSales: boolean;
  closureError: string | null;
  closureInfo: string | null;
  closureBlockedByTransferGap: boolean;
  closuresLoading: boolean;
  billTotalShown: number;
  reportsReady: boolean;
  reportsProgress: string;
  reportsCount: number;
  theoreticalCash: number;
  totalExpenses: number;
  expensesReady: boolean;
  expensesProgress: string;
  dayReady: boolean;
  closureRecorded: boolean;
  soldeComptable: number;
  ecartCaisse: number;
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
  onCancelEdit: () => void;
}

/** §5.2 — Billetage physique (« Versement ») : saisie du gérant uniquement. */
export const BilletageForm: React.FC<Props> = ({
  today, maxDate, dayLabel, editingClosure, todayClosure, selectedNodeLabel, bills, onBillsChange,
  closureNotes, onNotesChange, closureDate, onClosureDateChange, allowBackdatedSales,
  closureError, closureInfo, closureBlockedByTransferGap, closuresLoading, billTotalShown,
  reportsReady, reportsProgress, reportsCount, theoreticalCash, totalExpenses, expensesReady,
  expensesProgress, dayReady, closureRecorded, soldeComptable, ecartCaisse, onSubmit, onCancelEdit,
}) => (
  <div className="glass-card" style={{ padding: '16px', order: 2 }}>
    <h2 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '6px' }}>
      <FiDollarSign style={{ color: editingClosure ? 'hsl(var(--color-warning))' : 'hsl(var(--accent-color))' }} />
      {editingClosure ? 'Corriger la Clôture Infirmée' : 'Versement'}
    </h2>
    {editingClosure && (
      <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-warning))', fontWeight: 700, marginBottom: '6px', padding: '5px 8px', backgroundColor: 'hsl(var(--color-warning) / 0.08)', borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--color-warning) / 0.3)' }}>
        Motif du rejet : {editingClosure.rejection_reason || 'Non précisé'} &nbsp;
        <button type="button" onClick={onCancelEdit} style={{ marginLeft: '8px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', background: 'none', border: 'none', cursor: 'pointer', textDecoration: 'underline' }}>Annuler</button>
      </div>
    )}
    {!editingClosure && selectedNodeLabel && (
      <div style={{ fontSize: '0.62rem', color: 'hsl(var(--accent-color))', fontWeight: 700, marginBottom: '4px', display: 'flex', alignItems: 'center', gap: '4px' }}>
        <FiLock size={10} />
        {selectedNodeLabel}
      </div>
    )}
    <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
      Saisir le nombre de coupures physiques — le système calcule et compare au solde théorique.
    </p>
    <form noValidate onSubmit={onSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
      {/* Header row */}
      <div style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 1fr', gap: '8px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase', marginBottom: '2px', paddingBottom: '4px', borderBottom: '1px solid hsl(var(--border-color))' }}>
        <span>Valeur Faciale</span><span style={{ textAlign: 'right' }}>Quantité</span><span style={{ textAlign: 'right' }}>Sous-Total FC</span>
      </div>
      {BILLS.map(b => {
        const subtotal = bills[b.key] * b.face;
        return (
          <div key={b.key} style={{ display: 'grid', gridTemplateColumns: '1.4fr 0.8fr 1fr', gap: '8px', alignItems: 'center' }}>
            <span style={{ fontSize: '0.75rem', fontWeight: 700 }}>{b.label}</span>
            <input
              type="number" inputMode="numeric"
              value={bills[b.key] || ''}
              placeholder="0"
              aria-invalid={isInvalidBillCount(bills[b.key])}
              onChange={e => onBillsChange(prev => ({ ...prev, [b.key]: parseBillCount(e.target.value) }))}
              className="form-input"
              disabled={!!editingClosure?.is_validated}
              style={{ fontSize: '0.78rem', height: '26px', padding: '0 6px', textAlign: 'right', fontWeight: 700 }}
            />
            <span style={{ textAlign: 'right', fontSize: '0.73rem', fontWeight: subtotal > 0 ? 800 : 400, color: subtotal > 0 ? 'hsl(var(--text-primary))' : 'hsl(var(--text-muted))' }}>
              {subtotal > 0 ? subtotal.toLocaleString('fr-FR') : '—'}
            </span>
          </div>
        );
      })}

      {/* Totals comparison */}
      <div style={{ borderTop: '2px solid hsl(var(--border-color))', marginTop: '4px', paddingTop: '8px', display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800 }}>
          <span>TOTAL GÉNÉRAL ESPÈCES :</span>
          <span style={{ color: 'hsl(var(--color-success))', fontSize: '0.9rem' }}>{billTotalShown.toLocaleString('fr-FR')} FC</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
          <span>
            Recette / Paiement :
            <span style={{ fontSize: '0.58rem', color: 'hsl(var(--text-muted))', marginLeft: '4px' }}>
              {!reportsReady ? `(${reportsProgress})` : reportsCount > 0 ? `(§5.1.1 · ${reportsCount} rapport(s))` : '(aucun rapport §5.1.1)'}
            </span>
          </span>
          <span style={{ fontWeight: 700, color: reportsCount > 0 ? 'inherit' : 'hsl(var(--color-warning))' }}>{reportsReady ? `${fmt(theoreticalCash)} FC` : '…'}</span>
        </div>
        {(totalExpenses > 0 || !expensesReady) && (
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
            <span>— Dépenses Locales :</span>
            <span style={{ fontWeight: 700, color: 'hsl(var(--color-danger))' }}>{expensesReady ? `−${fmt(totalExpenses)} FC` : expensesProgress}</span>
          </div>
        )}
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>
          <span>Solde comptable caisse :</span>
          <span style={{ fontWeight: 800, color: 'hsl(var(--color-warning))' }}>{dayReady || closureRecorded ? `${fmt(soldeComptable)} FC` : '…'}</span>
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.75rem', fontWeight: 800, padding: '5px 8px', borderRadius: 'var(--radius-sm)', backgroundColor: !dayReady ? 'hsl(var(--bg-tertiary))' : ecartCaisse === 0 ? 'hsl(var(--color-success) / 0.08)' : 'hsl(var(--color-danger) / 0.08)', border: `1px solid hsl(var(--${!dayReady ? 'border-color' : ecartCaisse === 0 ? 'color-success' : 'color-danger'}) / 0.3)` }}>
          <span>ÉCART DE CAISSE :</span>
          {dayReady ? (
            <span style={{ color: ecartCaisse === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
              {ecartCaisse >= 0 ? '+' : ''}{ecartCaisse.toLocaleString('fr-FR')} FC
              {ecartCaisse > 0 ? ' (Excédent)' : ecartCaisse < 0 ? ' (Manque)' : ' ✓ Équilibré'}
            </span>
          ) : (
            <span style={{ color: 'hsl(var(--text-muted))', fontWeight: 600 }}>calcul en cours…</span>
          )}
        </div>
      </div>

      {/* BUG-086 : date de clôture rétroactive optionnelle (nouvelle clôture uniquement) —
          visible seulement si activée en Configuration. */}
      {allowBackdatedSales && !editingClosure && (
        <div>
          <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '3px', textTransform: 'uppercase' }}>
            Date de la clôture (optionnel)
          </label>
          <span style={{ display: 'block', fontSize: '0.58rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
            Laisser vide = journée du {dayLabel}. Jamais une date future.
          </span>
          <input
            type="date"
            max={maxDate}
            value={closureDate}
            onChange={e => onClosureDateChange(e.target.value)}
            className="form-input"
            style={{ fontSize: '0.72rem', height: '28px', padding: '0 8px' }}
          />
        </div>
      )}

      <div>
        <label style={{ display: 'block', fontSize: '0.62rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', textTransform: 'uppercase' }}>Notes (optionnel)</label>
        <input type="text" value={closureNotes} onChange={e => onNotesChange(e.target.value)} placeholder="Observations, écart justifié..." className="form-input" disabled={!!editingClosure?.is_validated} style={{ fontSize: '0.72rem', height: '28px', padding: '0 8px' }} />
      </div>

      {closureError && (
        <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)', display: 'flex', flexDirection: 'column', gap: '6px' }}>
          <span>{closureError}</span>
          {closureBlockedByTransferGap && (
            <Link
              to="/production"
              style={{ alignSelf: 'flex-start', fontWeight: 700, color: 'hsl(var(--accent-color))', textDecoration: 'underline' }}
            >
              Voir les transferts inter-boulangeries (§3.3) →
            </Link>
          )}
        </div>
      )}
      {closureInfo && (
        <div style={{ fontSize: '0.65rem', color: 'hsl(var(--color-info))', backgroundColor: 'hsl(var(--color-info) / 0.08)', padding: '5px 8px', borderRadius: 'var(--radius-sm)' }}>
          {closureInfo}
        </div>
      )}

      {/* BUG-046 : une clôture déjà confirmée par le comptable est figée — pas de bouton de soumission dans ce cas. */}
      {!closuresLoading && (!todayClosure || editingClosure) && !editingClosure?.is_validated && (
        <button type="submit" className="btn btn-primary" style={{ padding: '7px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '5px', ...(editingClosure ? { backgroundColor: 'hsl(var(--color-warning))', borderColor: 'hsl(var(--color-warning))' } : {}) }}>
          <FiLock /> {editingClosure
            ? 'Corriger et Re-soumettre'
            : (allowBackdatedSales && closureDate && closureDate !== today)
              ? `Valider la Clôture du ${new Date(closureDate).toLocaleDateString('fr-FR')}`
              : `Valider la clôture de la journée du ${dayLabel}`}
        </button>
      )}
      {todayClosure && !editingClosure && (
        <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-success))', fontWeight: 700, textAlign: 'center', padding: '6px' }}>
          <FiCheckCircle style={{ marginRight: '4px' }} />Clôture créée — Physical total: {fmt(todayClosure.physical_cash_total)} FC · Écart: {fmt(todayClosure.cash_gap)} FC
        </div>
      )}
    </form>
  </div>
);
