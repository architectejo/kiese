import React, { useState, useEffect, useCallback } from 'react';
import { FiPackage, FiPlus, FiTrash2 } from 'react-icons/fi';
import { coreApi, ColisDistribution, BakeryNode } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

interface ColisSectionProps {
  nodes: BakeryNode[];
  defaultNode: string;
}

export const ColisSection: React.FC<ColisSectionProps> = ({ nodes: colisNodes, defaultNode }) => {
  const [colisNode, setColisNode]     = useState(defaultNode);
  const [colisYear, setColisYear]     = useState(() => new Date().getFullYear());
  const [colisList, setColisList]     = useState<ColisDistribution[]>([]);
  const [colisLoading, setColisLoading] = useState(false);
  const [colisLabel, setColisLabel]   = useState('');
  const [colisRiceSacks, setColisRiceSacks] = useState('');
  const [colisRiceValue, setColisRiceValue] = useState('');
  const [colisMeatKg, setColisMeatKg] = useState('');
  const [colisMeatValue, setColisMeatValue] = useState('');
  const [colisCash, setColisCash]     = useState('');
  const [colisNotes, setColisNotes]   = useState('');
  const [colisError, setColisError]   = useState<string | null>(null);
  const [colisSubmitting, setColisSubmitting] = useState(false);
  const [showColisForm, setShowColisForm] = useState(false);

  const loadColis = useCallback(async () => {
    if (!colisNode) return;
    setColisLoading(true);
    try {
      const res = await coreApi.colis.list({ node: colisNode, year: String(colisYear) });
      setColisList(Array.isArray(res.data) ? res.data : []);
    } catch { setColisList([]); }
    finally { setColisLoading(false); }
  }, [colisNode, colisYear]);

  useEffect(() => { loadColis(); }, [loadColis]);

  const handleColisSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!colisLabel) { setColisError('Indiquez le bénéficiaire.'); return; }
    setColisSubmitting(true); setColisError(null);
    try {
      await coreApi.colis.create({
        node: colisNode, year: colisYear, beneficiary_label: colisLabel,
        rice_sacks: colisRiceSacks || '0', rice_value: colisRiceValue || '0',
        meat_kg: colisMeatKg || '0', meat_value: colisMeatValue || '0',
        cash_amount: colisCash || '0', notes: colisNotes,
      });
      setColisLabel(''); setColisRiceSacks(''); setColisRiceValue('');
      setColisMeatKg(''); setColisMeatValue(''); setColisCash(''); setColisNotes('');
      setShowColisForm(false);
      await loadColis();
    } catch (err: unknown) { setColisError(getErrorDetail(err, 'Erreur.')); }
    finally { setColisSubmitting(false); }
  };

  const handleColisDelete = async (id: number) => {
    if (!window.confirm('Supprimer cette ligne COLIS ?')) return;
    try { await coreApi.colis.delete(id); await loadColis(); } catch { /* ignore */ }
  };

  return (
      <div className="glass-card" style={{ padding: '16px' }}>
        <h3 style={{ fontSize: '0.85rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
          <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
          §6.4 — Distribution COLIS Personnel
        </h3>

        {/* Filters */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 14, alignItems: 'flex-end' }}>
          {colisNodes.length > 0 && (
            <div>
              <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Succursale</label>
              <select value={colisNode} onChange={e => setColisNode(e.target.value)}
                className="form-input" style={{ fontSize: '0.8rem', height: 32, padding: '0 8px' }}>
                {colisNodes.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Année</label>
            <select value={colisYear} onChange={e => setColisYear(Number(e.target.value))}
              className="form-input" style={{ fontSize: '0.8rem', height: 32, padding: '0 8px' }}>
              {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
          <button onClick={() => setShowColisForm(v => !v)}
            className="btn btn-primary" style={{ padding: '5px 12px', fontSize: '0.78rem', height: 32, display: 'flex', alignItems: 'center', gap: 5 }}>
            <FiPlus />{showColisForm ? 'Annuler' : 'Ajouter'}
          </button>
        </div>

        {/* Add form */}
        {showColisForm && (
          <form onSubmit={handleColisSubmit} style={{ background: 'hsl(var(--bg-tertiary))', borderRadius: 8, padding: 14, marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 10 }}>
            <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap' }}>
              <div style={{ flex: '2 1 200px' }}>
                <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Bénéficiaire *</label>
                <input value={colisLabel} onChange={e => setColisLabel(e.target.value)} placeholder="ex: Boulanger 1" required
                  className="form-input" style={{ fontSize: '0.82rem', height: 32, width: '100%', padding: '0 8px' }} />
              </div>
              {[
                { label: 'Sacs riz', val: colisRiceSacks, set: setColisRiceSacks },
                { label: 'Valeur riz (FC)', val: colisRiceValue, set: setColisRiceValue },
                { label: 'Viande (kg)', val: colisMeatKg, set: setColisMeatKg },
                { label: 'Valeur viande (FC)', val: colisMeatValue, set: setColisMeatValue },
                { label: 'Espèces (FC)', val: colisCash, set: setColisCash },
              ].map(f => (
                <div key={f.label} style={{ flex: '1 1 110px' }}>
                  <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>{f.label}</label>
                  <input type="number" step="0.01" min="0" value={f.val} onChange={e => f.set(e.target.value)} placeholder="0"
                    className="form-input" style={{ fontSize: '0.82rem', height: 32, width: '100%', padding: '0 8px' }} />
                </div>
              ))}
            </div>
            <div>
              <label style={{ fontSize: '0.7rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 3 }}>Notes</label>
              <input value={colisNotes} onChange={e => setColisNotes(e.target.value)} placeholder="optionnel"
                className="form-input" style={{ fontSize: '0.82rem', height: 32, width: '100%', padding: '0 8px' }} />
            </div>
            {colisError && <div style={{ color: 'hsl(var(--color-danger))', fontSize: '0.78rem' }}>{colisError}</div>}
            <div style={{ display: 'flex', gap: 8 }}>
              <button type="submit" disabled={colisSubmitting} className="btn btn-primary" style={{ padding: '5px 16px', fontSize: '0.8rem' }}>
                {colisSubmitting ? 'Enregistrement…' : 'Enregistrer'}
              </button>
              <button type="button" onClick={() => setShowColisForm(false)} className="btn btn-secondary" style={{ padding: '5px 12px', fontSize: '0.8rem' }}>
                Annuler
              </button>
            </div>
          </form>
        )}

        {/* Table */}
        {colisLoading ? (
          <div style={{ textAlign: 'center', padding: 16, color: 'hsl(var(--text-secondary))', fontSize: '0.82rem' }}>Chargement…</div>
        ) : colisList.length === 0 ? (
          <div style={{ textAlign: 'center', padding: 16, color: 'hsl(var(--text-muted))', fontSize: '0.82rem' }}>
            Aucune distribution COLIS pour {colisYear}.
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
              <thead>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                  {['Bénéficiaire', 'Riz (sacs)', 'Valeur riz', 'Viande (kg)', 'Valeur viande', 'Espèces', 'TOTAL', ''].map(h => (
                    <th key={h} style={{ padding: '6px 8px', textAlign: h === 'Bénéficiaire' || h === '' ? 'left' : 'right', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.68rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {colisList.map(row => (
                  <tr key={row.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                    <td style={{ padding: '6px 8px', fontWeight: 600 }}>{row.beneficiary_label}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.rice_sacks).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.rice_value).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.meat_kg).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.meat_value).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right' }}>{parseFloat(row.cash_amount).toLocaleString('fr-FR')}</td>
                    <td style={{ padding: '6px 8px', textAlign: 'right', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{parseFloat(row.total_value).toLocaleString('fr-FR')} FC</td>
                    <td style={{ padding: '6px 8px' }}>
                      <button onClick={() => handleColisDelete(row.id)} style={{ padding: '2px 6px', borderRadius: 4, border: '1px solid hsl(var(--color-danger)/0.3)', background: 'hsl(var(--color-danger)/0.06)', color: 'hsl(var(--color-danger))', cursor: 'pointer', fontSize: '0.7rem' }}>
                        <FiTrash2 />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 800 }}>
                  <td style={{ padding: '6px 8px' }}>{colisList.length} bénéficiaire(s)</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.rice_sacks), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.rice_value), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.meat_kg), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.meat_value), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right' }}>{colisList.reduce((s, r) => s + parseFloat(r.cash_amount), 0).toLocaleString('fr-FR')}</td>
                  <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--accent-color))' }}>{colisList.reduce((s, r) => s + parseFloat(r.total_value), 0).toLocaleString('fr-FR')} FC</td>
                  <td />
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>
  );
};
