import React from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import { fmt } from '@/components/treasury/treasuryShared';
import type { ProductionRecap } from '@/components/treasury/clotureRecap';

interface Props {
  recap: ProductionRecap;
  effectiveSacValueFc: number;
  pendingReports: number;
  reportsReady: boolean;
  reportsCount: number;
  reportsProgress: string;
  confirmingDay: boolean;
  confirmMsg: string | null;
  onConfirmDay: () => void;
}

/** §5.1.1 — Récapitulatif de production du jour + bouton « Confirmer & Clôturer ». */
export const ProductionRecapPanel: React.FC<Props> = ({
  recap, effectiveSacValueFc, pendingReports, reportsReady, reportsCount,
  reportsProgress, confirmingDay, confirmMsg, onConfirmDay,
}) => {
  const { totalSacs, totalTheorFC, prodMap, soldMap, cats, actualSalesFC, ecart } = recap;
  if (!(totalSacs > 0 || cats.length > 0)) return null;
  const balanceOk = Math.abs(ecart) === 0;
  return (
    <div style={{ marginTop: '16px', borderTop: '1px solid hsl(var(--border-color))', paddingTop: '14px' }}>

      {/* ── Header ── */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '12px', flexWrap: 'wrap', gap: '8px' }}>
        <span style={{ fontSize: '0.75rem', fontWeight: 800, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', letterSpacing: '0.04em' }}>
          Rapport Journalier · Clôture du Jour
        </span>
        {pendingReports > 0 && (
          <button
            onClick={onConfirmDay}
            disabled={confirmingDay}
            className="btn btn-primary"
            style={{ padding: '5px 12px', fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: '5px' }}
          >
            <FiCheckCircle size={13} />
            {confirmingDay ? 'Validation...' : `Confirmer & Clôturer (${pendingReports} rapport${pendingReports > 1 ? 's' : ''})`}
          </button>
        )}
        {!reportsReady && (
          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>
            Rapports : {reportsProgress}
          </span>
        )}
        {reportsReady && pendingReports === 0 && reportsCount > 0 && (
          <span style={{ fontSize: '0.65rem', color: 'hsl(var(--color-success))', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '4px' }}>
            <FiCheckCircle size={12} /> Tous les rapports validés
          </span>
        )}
      </div>

      {confirmMsg && (
        <div style={{ fontSize: '0.65rem', padding: '6px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '10px', backgroundColor: 'hsl(var(--color-info) / 0.1)', color: 'hsl(var(--color-info))' }}>
          {confirmMsg}
        </div>
      )}

      {/* ── Section FACTURIER : sacs × valeur ── */}
      <div style={{ backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', padding: '10px 12px', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.6rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '6px', letterSpacing: '0.06em' }}>
          Facturier — Montant Attendu (Sacs)
        </div>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: '6px', fontSize: '0.8rem', fontWeight: 700 }}>
          <span style={{ color: 'hsl(var(--color-info))' }}>{totalSacs.toLocaleString('fr-FR')} sac{totalSacs > 1 ? 's' : ''}</span>
          <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>×</span>
          <span style={{ color: 'hsl(var(--text-secondary))' }}>{fmt(totalSacs > 0 ? totalTheorFC / totalSacs : effectiveSacValueFc)} FC</span>
          <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>=</span>
          <span style={{ color: 'hsl(var(--color-warning))', fontSize: '0.9rem', fontWeight: 800 }}>{fmt(totalTheorFC)} FC</span>
        </div>
      </div>

      {/* ── Section VENTES : qty × prix = total par catégorie ── */}
      <div style={{ backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', padding: '10px 12px', marginBottom: '10px' }}>
        <div style={{ fontSize: '0.6rem', fontWeight: 800, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '8px', letterSpacing: '0.06em' }}>
          Ventes du Jour — Résultat
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {cats.map(cat => {
            const prod = prodMap[cat] ?? 0;
            const s = soldMap[cat] ?? { qty: 0, fc: 0 };
            const restant = prod - s.qty;
            return (
              <div key={cat} style={{ display: 'grid', gridTemplateColumns: '1fr auto', alignItems: 'center', gap: '8px' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: '5px', fontSize: '0.78rem' }}>
                  <span style={{ fontWeight: 800, color: s.qty > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))' }}>
                    {s.qty > 0 ? s.qty.toLocaleString('fr-FR') : '0'}
                  </span>
                  <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}>×</span>
                  <span style={{ fontWeight: 700, color: 'hsl(var(--text-secondary))' }}>{cat.toLocaleString('fr-FR')} FC</span>
                  <span style={{ color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}>=</span>
                  <span style={{ fontWeight: 800, color: 'hsl(var(--color-success))' }}>{fmt(s.fc)} FC</span>
                </div>
                <div style={{ display: 'flex', gap: '6px', fontSize: '0.6rem', justifyContent: 'flex-end' }}>
                  {prod > 0 && (
                    <span style={{ color: 'hsl(var(--color-info))' }}>produit : {prod.toLocaleString('fr-FR')}</span>
                  )}
                  {prod > 0 && (
                    <span style={{
                      color: restant < 0 ? 'hsl(var(--color-danger))' : restant > 0 ? 'hsl(var(--text-muted))' : 'hsl(var(--color-success))',
                      fontWeight: restant !== 0 ? 700 : 400,
                    }}>
                      restant : {restant > 0 ? '+' : ''}{restant.toLocaleString('fr-FR')}
                    </span>
                  )}
                </div>
              </div>
            );
          })}
          {/* Separator + total */}
          <div style={{ borderTop: '2px solid hsl(var(--border-color))', marginTop: '4px', paddingTop: '6px', display: 'flex', alignItems: 'baseline', gap: '6px', fontSize: '0.82rem', fontWeight: 800 }}>
            <span style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.65rem', textTransform: 'uppercase' }}>Total Ventes</span>
            <span style={{ color: 'hsl(var(--color-success))' }}>{fmt(actualSalesFC)} FC</span>
          </div>
        </div>
      </div>

      {/* ── Balance / Résultat ── */}
      <div style={{
        padding: '10px 14px',
        borderRadius: 'var(--radius-sm)',
        border: `1px solid hsl(var(--${balanceOk ? 'color-success' : Math.abs(ecart) < 10000 ? 'color-warning' : 'color-danger'}) / 0.4)`,
        backgroundColor: `hsl(var(--${balanceOk ? 'color-success' : Math.abs(ecart) < 10000 ? 'color-warning' : 'color-danger'}) / 0.06)`,
        display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '8px',
      }}>
        <div>
          <div style={{ fontSize: '0.62rem', fontWeight: 700, textTransform: 'uppercase', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>Résultat</div>
          <div style={{ fontSize: '0.72rem', fontWeight: 700 }}>
            <span style={{ color: 'hsl(var(--color-warning))' }}>{fmt(totalTheorFC)} FC</span>
            <span style={{ color: 'hsl(var(--text-muted))', margin: '0 6px' }}>=</span>
            <span style={{ color: 'hsl(var(--color-success))' }}>{fmt(actualSalesFC)} FC</span>
          </div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginBottom: '2px' }}>
            {balanceOk ? 'Balance Nulle ✓' : Math.abs(ecart) < 10000 ? 'Écart Tolérable' : 'Écart Significatif'}
          </div>
          <div style={{
            fontSize: '0.8rem', fontWeight: 800,
            color: `hsl(var(--${balanceOk ? 'color-success' : Math.abs(ecart) < 10000 ? 'color-warning' : 'color-danger'}))`,
          }}>
            {balanceOk ? 'PCC — ÉQUILIBRÉ' : `${ecart > 0 ? '+' : ''}${fmt(ecart)} FC`}
          </div>
        </div>
      </div>

    </div>
  );
};
