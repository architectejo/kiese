import React, { useCallback, useEffect, useState } from 'react';
import { clientsApi } from '../../api/services';
import type { SocialDistribution, SocialDistributionLine } from '../../api/services';
import { getErrorDetail } from '../../api/errors';

interface Props {
  node: string;
  year: number;
  canRead: boolean;
}

const fmt = (v: string | number) => (typeof v === 'number' ? v : parseFloat(v) || 0).toLocaleString('fr-FR');
const th: React.CSSProperties = { padding: '6px 8px', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.72rem', textTransform: 'uppercase', letterSpacing: '0.04em' };
const btn: React.CSSProperties = { padding: '8px 14px', borderRadius: 6, border: 'none', cursor: 'pointer', fontSize: '0.8rem', fontWeight: 600 };
const input: React.CSSProperties = { padding: '4px 6px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.8rem' };

/**
 * Distribution annuelle de la caisse sociale (BUG-295) :
 * REMISE = INDICE × TARIF ; TOTAL À PAYER = TOTAL SOCIAL + REMISE + MÉRITE.
 * Le TARIF est fixé par année et par boulangerie, modifiable tant que la distribution n'est pas clôturée.
 */
export const SocialDistributionPanel: React.FC<Props> = ({ node, year, canRead }) => {
  const [distributions, setDistributions] = useState<SocialDistribution[]>([]);
  const [openId, setOpenId] = useState<number | null>(null);
  const [loading, setLoading] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tarifInputs, setTarifInputs] = useState<Record<number, string>>({});
  const [meriteInputs, setMeriteInputs] = useState<Record<number, string>>({});

  const replaceDist = (d: SocialDistribution) =>
    setDistributions(prev => prev.map(x => (x.id === d.id ? d : x)));

  const load = useCallback(async () => {
    if (!node || !canRead) return;
    setLoading(true);
    setError(null);
    try {
      const res = await clientsApi.distributions.list({ node, year: String(year) });
      setDistributions(Array.isArray(res.data) ? res.data : []);
    } catch (e: unknown) {
      setError(getErrorDetail(e, 'Impossible de charger les distributions.'));
    } finally { setLoading(false); }
  }, [node, year, canRead]);

  useEffect(() => { load(); }, [load]);

  const run = async (fn: () => Promise<void>, fallback: string) => {
    setMsg(null); setError(null);
    try { await fn(); } catch (e: unknown) { setError(getErrorDetail(e, fallback)); }
  };

  const handleCreate = () => run(async () => {
    const r = await clientsApi.distributions.create({ node, year });
    setDistributions(prev => [r.data, ...prev]);
  }, 'Erreur création.');

  const handleAutoPopulate = (id: number) => run(async () => {
    const r = await clientsApi.distributions.autoPopulate(id);
    setMsg(`${r.data.created} ligne(s) créée(s), ${r.data.skipped} existante(s).`);
    replaceDist(r.data.distribution);
    setOpenId(id);
  }, 'Erreur auto-population.');

  const handleRefresh = (id: number) => run(async () => {
    const r = await clientsApi.distributions.refreshIndices(id);
    setMsg(`${r.data.updated} ligne(s) recalculée(s) (indices, total social, remise).`);
    replaceDist(r.data.distribution);
    setOpenId(id);
  }, 'Erreur lors du recalcul des indices.');

  const handleSaveTarif = (d: SocialDistribution) => run(async () => {
    const value = (tarifInputs[d.id] ?? String(parseFloat(d.tarif))).trim();
    if (value === '' || isNaN(Number(value)) || Number(value) < 0) { setError('Tarif invalide.'); return; }
    const r = await clientsApi.distributions.update(d.id, { tarif: value });
    replaceDist(r.data);
    setTarifInputs(prev => { const n = { ...prev }; delete n[d.id]; return n; });
    setMsg('Tarif enregistré, remises recalculées.');
  }, 'Erreur lors de la modification du tarif.');

  const handleSaveMerite = (d: SocialDistribution, line: SocialDistributionLine) => run(async () => {
    const value = (meriteInputs[line.id] ?? String(parseFloat(line.merite))).trim();
    if (value === '' || isNaN(Number(value)) || Number(value) < 0) { setError('Mérite invalide.'); return; }
    await clientsApi.distributionLines.update(line.id, { merite: value });
    const r = await clientsApi.distributions.list({ node, year: String(year) });
    setDistributions(Array.isArray(r.data) ? r.data : []);
    setMeriteInputs(prev => { const n = { ...prev }; delete n[line.id]; return n; });
    setOpenId(d.id);
  }, 'Erreur lors de la saisie du mérite.');

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
        <button onClick={handleCreate} style={{ ...btn, background: 'hsl(var(--accent-color))', color: '#fff' }}>
          + Nouvelle distribution {year}
        </button>
        {msg && <span style={{ fontSize: '0.8rem', color: 'hsl(var(--color-success))' }}>{msg}</span>}
      </div>
      {error && (
        <div style={{ marginBottom: 10, padding: '7px 10px', borderRadius: 6, fontSize: '0.78rem', color: 'hsl(var(--color-danger))', background: 'hsl(var(--color-danger) / 0.1)' }}>{error}</div>
      )}
      <div style={{ fontSize: '0.72rem', color: 'hsl(var(--text-muted))', marginBottom: 10 }}>
        Remise annuelle = INDICE × TARIF + MÉRITE (INDICE : nombre de mois de cotisation payés dans l'année).
      </div>
      {loading ? (
        <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
      ) : distributions.length === 0 ? (
        <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
          Aucune distribution pour {year}. Créez-en une pour commencer.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
          {distributions.map(dist => {
            const lines = dist.lines || [];
            const isOpen = openId === dist.id;
            return (
              <div key={dist.id} style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 8, padding: 14 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
                    <span style={{ fontWeight: 700, fontSize: '0.9rem' }}>Distribution {dist.year}</span>
                    <label style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', display: 'flex', alignItems: 'center', gap: 6 }}>
                      Tarif (FC/indice)
                      {dist.is_closed ? (
                        <strong>{fmt(dist.tarif)}</strong>
                      ) : (
                        <>
                          <input
                            type="number" min="0" step="1" style={{ ...input, width: 90 }}
                            value={tarifInputs[dist.id] ?? String(parseFloat(dist.tarif))}
                            onChange={e => setTarifInputs(prev => ({ ...prev, [dist.id]: e.target.value }))}
                          />
                          <button type="button" onClick={() => handleSaveTarif(dist)} style={{ ...btn, padding: '4px 10px', background: 'hsl(var(--accent-color))', color: '#fff' }}>OK</button>
                        </>
                      )}
                    </label>
                    {dist.is_closed && <span style={{ padding: '2px 8px', background: 'hsl(var(--color-success))', color: '#fff', borderRadius: 12, fontSize: '0.7rem', fontWeight: 700 }}>CLÔTURÉE</span>}
                  </div>
                  <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    <button onClick={() => setOpenId(isOpen ? null : dist.id)}
                      style={{ ...btn, padding: '6px 12px', border: '1px solid hsl(var(--border-color))', background: 'none', color: 'hsl(var(--text-primary))', fontWeight: 400 }}>
                      {isOpen ? 'Masquer' : 'Voir'} les lignes ({lines.length})
                    </button>
                    {!dist.is_closed && (
                      <>
                        <button onClick={() => handleAutoPopulate(dist.id)} style={{ ...btn, padding: '6px 12px', background: 'hsl(var(--accent-color))', color: '#fff' }}>Auto-peupler</button>
                        <button onClick={() => handleRefresh(dist.id)} style={{ ...btn, padding: '6px 12px', background: 'hsl(var(--color-info))', color: '#fff' }}>Recalculer les indices</button>
                      </>
                    )}
                  </div>
                </div>

                {isOpen && lines.length === 0 && (
                  <div style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', padding: 8 }}>Aucune ligne : utilisez « Auto-peupler ».</div>
                )}
                {isOpen && lines.length > 0 && (
                  <div style={{ overflowX: 'auto', marginTop: 8 }}>
                    <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
                      <thead>
                        <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                          <th style={{ ...th, textAlign: 'left' }}>Client</th>
                          <th style={{ ...th, textAlign: 'left' }}>Indice</th>
                          <th style={{ ...th, textAlign: 'right' }}>Total social</th>
                          <th style={{ ...th, textAlign: 'right' }} title="INDICE × TARIF">Remise (indice × tarif)</th>
                          <th style={{ ...th, textAlign: 'right' }}>Mérite</th>
                          <th style={{ ...th, textAlign: 'right' }}>Total à recevoir</th>
                          <th style={{ ...th, textAlign: 'left' }}>Présence</th>
                          <th style={{ ...th, textAlign: 'left' }}>Forme</th>
                        </tr>
                      </thead>
                      <tbody>
                        {lines.map(line => (
                          <tr key={line.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                            <td style={{ padding: '6px 8px', fontWeight: 600 }}>{line.client_display || line.client}</td>
                            <td style={{ padding: '6px 8px' }}>{line.indice}</td>
                            <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmt(line.total_social)}</td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-info))' }}>{fmt(line.remise)}</td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))' }}>
                              {dist.is_closed ? fmt(line.merite) : (
                                <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center' }}>
                                  <input
                                    type="number" min="0" step="1" style={{ ...input, width: 80, textAlign: 'right' }}
                                    value={meriteInputs[line.id] ?? String(parseFloat(line.merite))}
                                    onChange={e => setMeriteInputs(prev => ({ ...prev, [line.id]: e.target.value }))}
                                  />
                                  {meriteInputs[line.id] !== undefined && (
                                    <button type="button" onClick={() => handleSaveMerite(dist, line)} style={{ ...btn, padding: '3px 8px', background: 'hsl(var(--accent-color))', color: '#fff' }}>OK</button>
                                  )}
                                </span>
                              )}
                            </td>
                            <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>{fmt(line.total_payer)}</td>
                            <td style={{ padding: '6px 8px' }}>
                              <span style={{ padding: '2px 7px', borderRadius: 10, fontSize: '0.7rem', fontWeight: 700, background: line.position === 'present' ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))', color: '#fff' }}>
                                {line.position === 'present' ? 'Présent' : 'Absent'}
                              </span>
                            </td>
                            <td style={{ padding: '6px 8px', color: 'hsl(var(--text-secondary))' }}>{line.form === 'especes' ? 'Espèces' : 'Colis'}</td>
                          </tr>
                        ))}
                      </tbody>
                      <tfoot>
                        <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 700 }}>
                          <td colSpan={2} style={{ padding: '6px 8px' }}>{lines.length} client(s)</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmt(lines.reduce((s, l) => s + parseFloat(l.total_social), 0))}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmt(lines.reduce((s, l) => s + parseFloat(l.remise), 0))}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right' }}>{fmt(lines.reduce((s, l) => s + parseFloat(l.merite), 0))}</td>
                          <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--accent-color))' }}>{fmt(lines.reduce((s, l) => s + parseFloat(l.total_payer), 0))}</td>
                          <td colSpan={2} />
                        </tr>
                      </tfoot>
                    </table>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
};
