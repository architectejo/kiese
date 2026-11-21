import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { FiAlertTriangle, FiDownload, FiPrinter, FiSearch } from 'react-icons/fi';
import { productionApi } from '@/api/services';
import type { DailyClosureClientRow, DailyClosureClientsReport } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import {
  SALE_TYPE_LABELS,
  exportClientsListToExcel,
  printClientsList,
} from '@/utils/clotureReportExport';

// BUG-327 (remarque.md l.447) : « liste du jour » des clients servis, ouverte depuis la
// Clôture Journalière. Affichage uniquement : tous les chiffres viennent du backend
// (GET /api/production/daily-closure/clients/), aucun calcul métier ici.

const PAGE_SIZE = 500;

type TeamFilter = '' | 'A' | 'B';
type SortKey = 'client' | 'tours' | 'order_value' | 'paid' | 'commission' | 'bp_before' | 'bp_current';

const fmtFC = (v: string | number | null | undefined): string => {
  if (v === null || v === undefined || v === '') return '—';
  const n = typeof v === 'string' ? parseFloat(v) : v;
  if (Number.isNaN(n)) return '—';
  return Math.round(n).toLocaleString('fr-FR') + ' FC';
};

const num = (v: string | null): number => {
  if (v === null) return Number.NEGATIVE_INFINITY;
  const n = parseFloat(v);
  return Number.isNaN(n) ? Number.NEGATIVE_INFINITY : n;
};

const SORT_VALUE: Record<SortKey, (r: DailyClosureClientRow) => string | number> = {
  client: r => `${r.client_name} ${r.client_code}`.toLowerCase(),
  tours: r => r.tours,
  order_value: r => num(r.order_value),
  paid: r => num(r.paid),
  commission: r => num(r.commission),
  bp_before: r => num(r.bp_before),
  bp_current: r => num(r.bp_current),
};

const COLUMNS: { key: SortKey; label: string; align: 'left' | 'right' }[] = [
  { key: 'client', label: 'Client', align: 'left' },
  { key: 'tours', label: 'Tours', align: 'right' },
  { key: 'order_value', label: 'Valeur commandée', align: 'right' },
  { key: 'paid', label: 'Versé', align: 'right' },
  { key: 'commission', label: 'Commission', align: 'right' },
  { key: 'bp_before', label: 'BP avant', align: 'right' },
  { key: 'bp_current', label: 'BP actuel', align: 'right' },
];

const BpCell: React.FC<{ value: string | null }> = ({ value }) => {
  if (value === null) return <>—</>;
  const n = parseFloat(value);
  // BP négative = crédit en faveur du client (CLAUDE.md §5.2).
  if (n < 0) {
    return (
      <span style={{ color: 'hsl(var(--color-success))', fontWeight: 700 }} title="Crédit en faveur du client">
        {fmtFC(value)} <small>(crédit)</small>
      </span>
    );
  }
  return <>{fmtFC(value)}</>;
};

interface Props {
  isOpen: boolean;
  onClose: () => void;
  nodeCode: string;
  nodeLabel: string;
  date: string;
}

export const ClotureClientsModal: React.FC<Props> = ({ isOpen, onClose, nodeCode, nodeLabel, date }) => {
  const [team, setTeam] = useState<TeamFilter>('');
  const [rows, setRows] = useState<DailyClosureClientRow[]>([]);
  const [meta, setMeta] = useState<DailyClosureClientsReport | null>(null);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [sort, setSort] = useState<{ key: SortKey; dir: 'asc' | 'desc' }>({ key: 'client', dir: 'asc' });

  const load = useCallback(async (pageToLoad: number) => {
    if (!nodeCode || !date) return;
    setLoading(true);
    setError(null);
    try {
      const res = await productionApi.dailyClosureClients({
        node: nodeCode, date, team: team || undefined, page: pageToLoad, page_size: PAGE_SIZE,
      });
      setMeta(res.data);
      setPage(pageToLoad);
      setRows(prev => (pageToLoad === 1 ? res.data.results : [...prev, ...res.data.results]));
    } catch (err: unknown) {
      const detail = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
      setError(detail || 'Erreur lors du chargement de la liste du jour.');
      if (pageToLoad === 1) { setRows([]); setMeta(null); }
    } finally {
      setLoading(false);
    }
  }, [nodeCode, date, team]);

  useEffect(() => {
    if (isOpen) load(1);
  }, [isOpen, load]);

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? rows.filter(r => r.client_name.toLowerCase().includes(q) || r.client_code.toLowerCase().includes(q))
      : rows;
    const get = SORT_VALUE[sort.key];
    return [...filtered].sort((a, b) => {
      const va = get(a); const vb = get(b);
      const cmp = va < vb ? -1 : va > vb ? 1 : 0;
      return sort.dir === 'asc' ? cmp : -cmp;
    });
  }, [rows, search, sort]);

  const toggleSort = (key: SortKey) =>
    setSort(s => (s.key === key ? { key, dir: s.dir === 'asc' ? 'desc' : 'asc' } : { key, dir: key === 'client' ? 'asc' : 'desc' }));

  const teamLabel = team ? `Équipe ${team}` : 'Toutes les équipes';
  const hasMore = meta !== null && rows.length < meta.count;
  const dateFr = new Date(date).toLocaleDateString('fr-FR', { day: '2-digit', month: '2-digit', year: 'numeric' });

  const btnStyle: React.CSSProperties = {
    padding: '5px 10px', fontSize: '0.72rem', display: 'flex', alignItems: 'center', gap: '5px', height: '32px',
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="Liste du jour — clients servis"
      subtitle={`${nodeLabel} — ${dateFr}`}
      maxWidth="1100px"
      contentPadding="12px 16px 16px"
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', fontSize: '0.8rem' }}>
        <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap', alignItems: 'center' }}>
          <select
            value={team}
            onChange={e => setTeam(e.target.value as TeamFilter)}
            className="form-input"
            aria-label="Filtrer par équipe"
            style={{ height: '32px', fontSize: '0.75rem', width: 'auto', minWidth: '130px' }}
          >
            <option value="">Toutes les équipes</option>
            <option value="A">Équipe A</option>
            <option value="B">Équipe B</option>
          </select>
          <div style={{ position: 'relative', flex: '1 1 180px', minWidth: '160px' }}>
            <FiSearch style={{ position: 'absolute', left: '9px', top: '50%', transform: 'translateY(-50%)', color: 'hsl(var(--text-muted))' }} />
            <input
              type="search"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder="Rechercher par nom ou code…"
              className="form-input"
              style={{ height: '32px', fontSize: '0.75rem', paddingLeft: '28px', width: '100%' }}
            />
          </div>
          <button
            type="button"
            className="btn btn-secondary"
            style={btnStyle}
            disabled={!meta}
            onClick={() => meta && exportClientsListToExcel({ ...meta, results: rows }, nodeLabel, teamLabel)}
            title="Exporter la liste affichée en Excel"
          >
            <FiDownload /><span>Excel</span>
          </button>
          <button
            type="button"
            className="btn btn-secondary"
            style={btnStyle}
            disabled={!meta}
            onClick={() => meta && printClientsList({ ...meta, results: rows }, nodeLabel, teamLabel)}
            title="Imprimer la liste"
          >
            <FiPrinter /><span>Imprimer</span>
          </button>
        </div>

        {error && (
          <div role="alert" style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '10px 14px', borderRadius: 'var(--radius-md)', border: '1px solid hsl(var(--color-danger) / 0.25)' }}>
            <FiAlertTriangle /> {error}
          </div>
        )}

        {loading && rows.length === 0 && (
          <div style={{ padding: '24px', textAlign: 'center', color: 'hsl(var(--text-muted))' }}>Chargement de la liste du jour…</div>
        )}

        {meta && (
          <>
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table" style={{ minWidth: '900px' }}>
                <thead>
                  <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                    {COLUMNS.map(c => (
                      <th
                        key={c.key}
                        onClick={() => toggleSort(c.key)}
                        style={{ textAlign: c.align, cursor: 'pointer', whiteSpace: 'nowrap', userSelect: 'none' }}
                        aria-sort={sort.key === c.key ? (sort.dir === 'asc' ? 'ascending' : 'descending') : 'none'}
                      >
                        {c.label}{sort.key === c.key ? (sort.dir === 'asc' ? ' ▲' : ' ▼') : ''}
                      </th>
                    ))}
                    <th>Types de vente</th>
                  </tr>
                </thead>
                <tbody style={{ fontSize: '0.74rem' }}>
                  {visible.length === 0 ? (
                    <tr>
                      <td colSpan={8} style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '16px' }}>
                        {rows.length === 0 ? 'Aucun client servi pour ce jour.' : 'Aucun client ne correspond à la recherche.'}
                      </td>
                    </tr>
                  ) : visible.map((r, i) => (
                    <tr key={`${r.client ?? 'passage'}-${i}`}>
                      <td style={{ fontWeight: 700 }}>
                        {r.client_code && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginRight: '6px' }}>{r.client_code}</span>}
                        {r.client_name}
                      </td>
                      <td style={{ textAlign: 'right' }}>{r.tours}</td>
                      <td style={{ textAlign: 'right' }}>{fmtFC(r.order_value)}</td>
                      <td style={{ textAlign: 'right' }}>{fmtFC(r.paid)}</td>
                      <td style={{ textAlign: 'right' }}>{fmtFC(r.commission)}</td>
                      <td style={{ textAlign: 'right' }}><BpCell value={r.bp_before} /></td>
                      <td style={{ textAlign: 'right', fontWeight: 700 }}><BpCell value={r.bp_current} /></td>
                      <td>
                        <div style={{ display: 'flex', gap: '4px', flexWrap: 'wrap' }}>
                          {r.sale_types.map(t => (
                            <span key={t} className="badge badge-warning" style={{ fontSize: '0.6rem' }}>{SALE_TYPE_LABELS[t] ?? t}</span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
                <tfoot style={{ fontSize: '0.76rem', fontWeight: 800 }}>
                  <tr>
                    <td>Totaux — {meta.totals.clients} client(s)</td>
                    <td style={{ textAlign: 'right' }}>{meta.totals.tours}</td>
                    <td style={{ textAlign: 'right' }}>{fmtFC(meta.totals.order_value)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtFC(meta.totals.paid)}</td>
                    <td style={{ textAlign: 'right' }}>{fmtFC(meta.totals.commission)}</td>
                    <td /><td /><td />
                  </tr>
                </tfoot>
              </table>
            </div>

            {hasMore && (
              <div style={{ textAlign: 'center' }}>
                <button type="button" className="btn btn-secondary" style={{ ...btnStyle, margin: '0 auto' }} disabled={loading} onClick={() => load(page + 1)}>
                  {loading ? 'Chargement…' : `Voir plus (${rows.length} / ${meta.count})`}
                </button>
              </div>
            )}

            <div>
              <h3 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '6px' }}>
                Non servis <span className="badge badge-danger" style={{ fontSize: '0.62rem', marginLeft: '6px' }}>{meta.non_servis.count}</span>
              </h3>
              {meta.non_servis.results.length === 0 ? (
                <p style={{ color: 'hsl(var(--text-muted))', fontSize: '0.74rem' }}>Aucun non servi pour ce jour.</p>
              ) : (
                <div style={{ overflowX: 'auto' }}>
                  <table className="premium-table" style={{ minWidth: '320px' }}>
                    <thead>
                      <tr style={{ fontSize: '0.62rem', textTransform: 'uppercase' }}>
                        <th>Client</th>
                        <th style={{ textAlign: 'right' }}>Nombre</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.74rem' }}>
                      {meta.non_servis.results.map((r, i) => (
                        <tr key={`${r.client ?? 'passage'}-${i}`}>
                          <td style={{ fontWeight: 700 }}>
                            {r.client_code && <span className="badge badge-info" style={{ fontSize: '0.6rem', marginRight: '6px' }}>{r.client_code}</span>}
                            {r.client_name}
                          </td>
                          <td style={{ textAlign: 'right' }}>{r.count}</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          </>
        )}
      </div>
    </Modal>
  );
};
