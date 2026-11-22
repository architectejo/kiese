import type { FacturierReport } from '@/api/services';
import type { ProgressiveList } from '@/hooks/useProgressiveList';

// ── Bill denominations — §5.2 ────────────────────────────────────────────────
export const BILLS = [
  { key: 'bills_20000', face: 20000, label: '20 000 FC' },
  { key: 'bills_10000', face: 10000, label: '10 000 FC' },
  { key: 'bills_5000',  face: 5000,  label: '5 000 FC'  },
  { key: 'bills_1000',  face: 1000,  label: '1 000 FC'  },
  { key: 'bills_500',   face: 500,   label: '500 FC'    },
  { key: 'bills_200',   face: 200,   label: '200 FC'    },
  { key: 'bills_100',   face: 100,   label: '100 FC'    },
  { key: 'bills_50',    face: 50,    label: '50 FC'     },
] as const;

export type BillKey = typeof BILLS[number]['key'];

export const EMPTY_BILLS: Record<BillKey, number> = {
  bills_20000: 0, bills_10000: 0, bills_5000: 0, bills_1000: 0,
  bills_500: 0, bills_200: 0, bills_100: 0, bills_50: 0,
};

// BUG-164 : taille de page demandée au serveur pour le chargement progressif (max 500).
export const PAGE_SIZE = '100';

// BUG-164 : libellé affiché à la place d'un total tant que la liste n'est pas complète.
export const progressLabel = (q: ProgressiveList<{ id: string | number }>): string =>
  q.error ? 'indisponible' : `calcul en cours… ${q.loaded}/${q.total ?? '…'}`;

export const fmt = (v: string | number | undefined) =>
  parseFloat(String(v || '0')).toLocaleString('fr-FR');

// BUG-045 — quantités décimales (sacs de farine) affichées proprement (ex. 2,25 sacs), sans arrondi agressif.
export const fmtDecimal = (v: string | number | undefined, maxDecimals = 2) =>
  parseFloat(String(v ?? '0')).toLocaleString('fr-FR', { minimumFractionDigits: 0, maximumFractionDigits: maxDecimals });

// BUG-045 — détail par catégorie de pain (§5.1.1) ajouté par la correction backend BUG-033.
export const renderReportCategoryDetail = (r: FacturierReport) => {
  const produced = r.breads_produced_by_category || {};
  const sold = r.breads_sold_by_category || {};
  const categories = Array.from(new Set([...Object.keys(produced), ...Object.keys(sold)]));
  const hasSacks = r.sacks_consumed !== undefined && r.sacks_consumed !== null;
  const hasGap = r.sacks_value_gap !== undefined && r.sacks_value_gap !== null;
  if (categories.length === 0 && !hasSacks && !hasGap) return null;
  const gap = parseFloat(r.sacks_value_gap || '0');
  return (
    <tr key={`detail-${r.id}`} style={{ backgroundColor: 'hsl(var(--bg-tertiary))' }}>
      <td colSpan={7} style={{ padding: '6px 10px 10px 16px' }}>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: '14px', fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', alignItems: 'flex-start' }}>
          {hasSacks && (
            <div><strong>Sacs consommés :</strong> {fmtDecimal(r.sacks_consumed)}</div>
          )}
          {categories.length > 0 && (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
              <strong>Pains par catégorie — produits / vendus :</strong>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: '6px' }}>
                {categories.map(cat => (
                  <span key={cat} style={{ padding: '2px 6px', backgroundColor: 'hsl(var(--bg-secondary))', borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap' }}>
                    {cat} : {produced[cat] ?? 0} / {sold[cat] ?? 0}
                  </span>
                ))}
              </div>
            </div>
          )}
          {hasGap && (
            <div>
              <strong>Écart valeur sacs / ventes :</strong>{' '}
              <span style={{ fontWeight: 700, color: gap === 0 ? 'hsl(var(--text-secondary))' : gap > 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
                {gap >= 0 ? '+' : ''}{fmt(r.sacks_value_gap)} FC{gap === 0 ? '' : gap > 0 ? ' (excédent)' : ' (manquant)'}
              </span>
            </div>
          )}
        </div>
      </td>
    </tr>
  );
};
