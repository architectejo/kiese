import React, { useCallback, useEffect, useState } from 'react';
import { coreApi, productionApi } from '@/api/services';
import type { BakeryNode, IntrantStatRow, IntrantStats, IntrantStatType } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

// BUG-1061 : lot I-2, statistiques journalières des intrants (farine, levure, huile, sel).
const TYPES: Array<{ code: IntrantStatType; label: string }> = [
  { code: 'FLOUR', label: 'Farine' },
  { code: 'YEAST', label: 'Levure' },
  { code: 'OIL', label: 'Huile' },
  { code: 'SALT', label: 'Sel' },
];

const UNIT_LABELS: Record<string, string> = { sacks: 'sacs', sac: 'sacs', kg: 'kg', l: 'litres', liters: 'litres', litres: 'litres', g: 'g', packs: 'paquets', paquets: 'paquets' };

type SaltUnit = 'g' | 'bags' | 'units';
const SALT_G_PER_BAG = 20000; // 1 sac = 20 kg = 204 boîtes (à confirmer avec le client)
const SALT_UNITS_PER_BAG = 204;
const NUM_FIELDS = ['initial', 'entry', 'exit', 'total_before_production', 'consumption', 'balance', 'declared_remaining', 'gap'] as const;
type NumField = typeof NUM_FIELDS[number];

/** Valeur dans l'unité de sel choisie : champ serveur `_bags`/`_units` s'il est présent, sinon conversion locale ; null reste null. */
const saltValue = (r: IntrantStatRow, f: NumField, u: Exclude<SaltUnit, 'g'>): string | null => {
  const key: `${string}_bags` | `${string}_units` = u === 'bags' ? `${f}_bags` : `${f}_units`;
  const server = r[key];
  if (server !== undefined && server !== null) return server;
  const base = r[f];
  if (base === null) return null;
  const n = Number(base);
  if (!Number.isFinite(n)) return null;
  const bags = n / SALT_G_PER_BAG;
  return String(u === 'bags' ? bags : bags * SALT_UNITS_PER_BAG);
};

const todayIso = (): string => {
  const d = new Date();
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

/** Chaîne décimale -> « 1 250,5 » (espace, virgule) ; null ou non numérique -> « — ». */
const fmt = (v: string | null | undefined, maxDecimals = 3): string => {
  if (v === null || v === undefined || v === '') return '—';
  const n = Number(v);
  if (!Number.isFinite(n)) return '—';
  return n.toLocaleString('fr-FR', { maximumFractionDigits: maxDecimals }).replace(/[  ]/g, ' ');
};

const th: React.CSSProperties = { textAlign: 'right', whiteSpace: 'nowrap', fontSize: '0.6rem', textTransform: 'uppercase' };
const td: React.CSSProperties = { textAlign: 'right', whiteSpace: 'nowrap' };
const stickyCol: React.CSSProperties = { position: 'sticky', left: 0, zIndex: 1, background: 'hsl(var(--bg-card, var(--bg-primary)))', textAlign: 'left', whiteSpace: 'nowrap' };

interface Props {
  /** Siège (ADMIN, DIRECTION, COMPTABLE) : filtre boulangerie disponible. */
  canFilterNode: boolean;
}

export const IntrantsStatsTab: React.FC<Props> = ({ canFilterNode }) => {
  const [type, setType] = useState<IntrantStatType>('FLOUR');
  const [date, setDate] = useState(todayIso());
  const [node, setNode] = useState('');
  const [saltUnit, setSaltUnit] = useState<SaltUnit>('g');
  const [nodes, setNodes] = useState<BakeryNode[]>([]);
  const [data, setData] = useState<IntrantStats | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const today = todayIso();

  useEffect(() => {
    if (!canFilterNode) return;
    coreApi.nodes.list().then(r => setNodes(r.data)).catch(() => setNodes([]));
  }, [canFilterNode]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await productionApi.intrantsStats({ type, date: date || undefined, node: node || undefined });
      setData(r.data);
    } catch (err) {
      setData(null);
      setError(getErrorDetail(err, 'Impossible de charger les statistiques des intrants.'));
    } finally {
      setLoading(false);
    }
  }, [type, date, node]);

  useEffect(() => { void load(); }, [load]);

  const isSalt = type === 'SALT';
  const convertSalt = isSalt && saltUnit !== 'g';
  const unit = data
    ? (convertSalt ? (saltUnit === 'bags' ? 'sacs' : 'boîtes') : (UNIT_LABELS[data.unit.toLowerCase()] ?? data.unit))
    : '';

  const convert = (r: IntrantStatRow): IntrantStatRow => {
    if (!isSalt || saltUnit === 'g') return r;
    const out: IntrantStatRow = { ...r };
    for (const f of NUM_FIELDS) out[f] = saltValue(r, f, saltUnit) as string;
    return out;
  };

  const renderRow = (raw: IntrantStatRow, total = false) => {
    const r = convert(raw);
    const gap = r.gap !== null && r.gap !== undefined ? Number(r.gap) : null;
    const gapColor = gap === null || gap === 0 ? undefined : gap < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--color-success))';
    const label = total ? 'TOTAUX' : r.is_direction ? 'D1 — Direction' : `${r.code} — ${r.name}`;
    return (
      <tr key={total ? 'TOTAUX' : r.code} style={{ fontWeight: total ? 800 : undefined, borderTop: total ? '2px solid hsl(var(--border-color))' : undefined }}>
        <td style={{ ...stickyCol, fontWeight: 700 }}>{label}</td>
        <td style={td}>{fmt(r.initial)}</td>
        <td style={td}>{fmt(r.entry)}</td>
        <td style={td}>{fmt(r.exit)}</td>
        <td style={td}>{fmt(r.total_before_production)}</td>
        <td style={td}>{fmt(r.consumption)}</td>
        <td style={td}>{fmt(r.balance)}</td>
        <td style={td}>{fmt(r.production_reference)}</td>
        <td style={td}>{fmt(r.consumption_index, 4)}</td>
        <td style={td}>{fmt(r.declared_remaining)}</td>
        <td style={{ ...td, fontWeight: 800, color: gapColor }}>
          {gap === null ? '—' : `${gap > 0 ? '+' : ''}${fmt(r.gap)}`}
          {gap !== null && gap < 0 && <span style={{ fontSize: '0.55rem', marginLeft: 4 }}>manquant</span>}
          {gap !== null && gap > 0 && <span style={{ fontSize: '0.55rem', marginLeft: 4 }}>excédent</span>}
        </td>
      </tr>
    );
  };

  return (
    <div className="glass-card" style={{ padding: '14px', minWidth: 0 }}>
      <h2 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '10px' }}>Statistiques des intrants</h2>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: '8px', alignItems: 'center', marginBottom: '10px' }}>
        <div role="tablist" aria-label="Intrant" style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
          {TYPES.map(t => (
            <button key={t.code} role="tab" aria-selected={type === t.code} onClick={() => setType(t.code)}
              className={`btn ${type === t.code ? 'btn-primary' : 'btn-secondary'}`}
              style={{ padding: '6px 12px', fontSize: '0.72rem', minHeight: 36 }}>{t.label}</button>
          ))}
        </div>
        <label style={{ fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: 4 }}>
          Date
          <input type="date" className="form-input" value={date} max={today}
            onChange={e => setDate(e.target.value > today ? today : e.target.value)}
            style={{ height: 32, fontSize: '0.72rem' }} />
        </label>
        {isSalt && (
          <label style={{ fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: 4 }}>
            Unité du sel
            <select className="form-input" value={saltUnit} onChange={e => setSaltUnit(e.target.value as SaltUnit)} style={{ height: 32, fontSize: '0.72rem' }}>
              <option value="g">Grammes</option>
              <option value="bags">Sacs (20 kg)</option>
              <option value="units">Boîtes (204 par sac)</option>
            </select>
          </label>
        )}
        {canFilterNode && (
          <label style={{ fontSize: '0.68rem', display: 'flex', alignItems: 'center', gap: 4 }}>
            Boulangerie
            <select className="form-input" value={node} onChange={e => setNode(e.target.value)} style={{ height: 32, fontSize: '0.72rem' }}>
              <option value="">Toutes</option>
              {nodes.map(n => <option key={n.id} value={n.code}>{n.code} — {n.name}</option>)}
            </select>
          </label>
        )}
      </div>

      {loading && <div role="status" style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Chargement...</div>}

      {!loading && error && (
        <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontSize: '0.75rem', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span>{error}</span>
          <button className="btn btn-secondary" style={{ padding: '4px 10px', fontSize: '0.7rem' }} onClick={() => void load()}>Réessayer</button>
        </div>
      )}

      {!loading && !error && data && (
        <>
          <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginBottom: 6 }}>
            {convertSalt ? 'Sel' : data.label} — unité : <strong>{unit}</strong> — situation du {data.date.split('-').reverse().join('/')}
          </div>
          {data.rows.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '12px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>Aucune donnée pour cette date.</div>
          ) : (
            <div style={{ overflowX: 'auto', maxWidth: '100%' }}>
              <table className="premium-table" style={{ minWidth: 900 }}>
                <thead>
                  <tr>
                    <th style={{ ...th, ...stickyCol }}>Boulangerie</th>
                    <th style={th}>Stock initial ({unit})</th>
                    <th style={th}>Entrée</th>
                    <th style={th}>Sortie</th>
                    <th style={th}>Total avant production</th>
                    <th style={th}>Consommation</th>
                    <th style={th}>Solde comptable</th>
                    <th style={th}>Réf. production (sacs)</th>
                    <th style={th}>Indice de consommation</th>
                    <th style={th}>Reste déclaré</th>
                    <th style={th}>Écart</th>
                  </tr>
                </thead>
                <tbody style={{ fontSize: '0.72rem' }}>
                  {data.rows.map(r => renderRow(r))}
                  {renderRow(data.totals, true)}
                </tbody>
              </table>
            </div>
          )}
          {data.hypotheses.length > 0 && (
            <details style={{ marginTop: 10, fontSize: '0.7rem' }}>
              <summary style={{ cursor: 'pointer', fontWeight: 700 }}>Hypothèses de calcul (à confirmer avec le client)</summary>
              <ul style={{ margin: '6px 0 0 18px', color: 'hsl(var(--text-secondary))' }}>
                {data.hypotheses.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            </details>
          )}
        </>
      )}
    </div>
  );
};
