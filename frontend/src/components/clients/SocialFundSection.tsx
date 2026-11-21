import React from 'react';
import type { BakeryNode, SocialContribution } from '@/api/services';
import { SocialDistributionPanel } from './SocialDistributionPanel';

interface SocialFundSectionProps {
  nodesList: BakeryNode[];
  socialNode: string;
  setSocialNode: (v: string) => void;
  socialMonth: number;
  setSocialMonth: (v: number) => void;
  socialYear: number;
  setSocialYear: (v: number) => void;
  socialTab: 'cotisations' | 'distribution';
  setSocialTab: (t: 'cotisations' | 'distribution') => void;
  handleBulkCreate: () => void | Promise<void>;
  bulkMsg: string | null;
  socialLoading: boolean;
  contributions: SocialContribution[];
  handleTogglePaid: (id: number) => void | Promise<void>;
  canReadSocial: boolean;
}

/** §6 — Caisse sociale : cotisations mensuelles et distribution annuelle. */
export const SocialFundSection: React.FC<SocialFundSectionProps> = ({
  nodesList, socialNode, setSocialNode, socialMonth, setSocialMonth, socialYear, setSocialYear,
  socialTab, setSocialTab, handleBulkCreate, bulkMsg, socialLoading, contributions, handleTogglePaid, canReadSocial,
}) => {
  return (
      <div style={{ background: 'hsl(var(--bg-secondary))', border: '1px solid hsl(var(--border-color))', borderRadius: 12, padding: 24 }}>
        <h3 style={{ margin: '0 0 16px 0', fontWeight: 700, fontSize: '1rem', color: 'hsl(var(--text-primary))' }}>
          §6 — Caisse Sociale
        </h3>

        {/* Boulangerie + mois/année */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 16, alignItems: 'flex-end' }}>
          {nodesList.length > 0 && (
            <div>
              <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 4 }}>Succursale</label>
              <select value={socialNode} onChange={e => setSocialNode(e.target.value)}
                style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
                <option value="">— Choisir —</option>
                {nodesList.map(n => <option key={n.id} value={n.id}>{n.code} — {n.name}</option>)}
              </select>
            </div>
          )}
          <div>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 4 }}>Mois</label>
            <select value={socialMonth} onChange={e => setSocialMonth(Number(e.target.value))}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
              {Array.from({ length: 12 }, (_, i) => i + 1).map(m => (
                <option key={m} value={m}>{new Date(2000, m - 1).toLocaleString('fr-FR', { month: 'long' })}</option>
              ))}
            </select>
          </div>
          <div>
            <label style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', display: 'block', marginBottom: 4 }}>Année</label>
            <select value={socialYear} onChange={e => setSocialYear(Number(e.target.value))}
              style={{ padding: '6px 10px', borderRadius: 6, border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-primary))', color: 'hsl(var(--text-primary))', fontSize: '0.875rem' }}>
              {[2024, 2025, 2026, 2027].map(y => <option key={y} value={y}>{y}</option>)}
            </select>
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '2px solid hsl(var(--border-color))' }}>
          {(['cotisations', 'distribution'] as const).map(tab => (
            <button key={tab} onClick={() => setSocialTab(tab)}
              style={{ padding: '8px 18px', border: 'none', background: 'none', cursor: 'pointer', fontWeight: socialTab === tab ? 700 : 400, color: socialTab === tab ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))', borderBottom: socialTab === tab ? '2px solid hsl(var(--accent-color))' : '2px solid transparent', marginBottom: -2, fontSize: '0.875rem', textTransform: 'capitalize' }}>
              {tab === 'cotisations' ? 'Cotisations Mensuelles' : 'Distribution Annuelle'}
            </button>
          ))}
        </div>

        {!socialNode ? (
          <div style={{ textAlign: 'center', padding: 32, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
            Sélectionnez une succursale pour afficher la Caisse Sociale.
          </div>
        ) : socialTab === 'cotisations' ? (
          <div>
            <div style={{ display: 'flex', gap: 8, marginBottom: 14, flexWrap: 'wrap', alignItems: 'center' }}>
              <button onClick={handleBulkCreate}
                style={{ padding: '7px 14px', borderRadius: 6, border: 'none', background: 'hsl(var(--accent-color))', color: '#fff', fontWeight: 600, cursor: 'pointer', fontSize: '0.8rem' }}>
                Générer fiches du mois
              </button>
              {bulkMsg && <span style={{ fontSize: '0.8rem', color: 'hsl(var(--color-success))' }}>{bulkMsg}</span>}
            </div>
            {socialLoading ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))' }}>Chargement…</div>
            ) : contributions.length === 0 ? (
              <div style={{ textAlign: 'center', padding: 24, color: 'hsl(var(--text-secondary))', fontSize: '0.875rem' }}>
                Aucune cotisation pour ce mois. Cliquez "Générer fiches du mois" pour créer les fiches.
              </div>
            ) : (
              <div style={{ overflowX: 'auto' }}>
                <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.82rem' }}>
                  <thead>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderBottom: '2px solid hsl(var(--border-color))' }}>
                      {['Client', 'Cotisation (FC)', 'Payé', 'Date paiement'].map(h => (
                        <th key={h} style={{ padding: '7px 10px', textAlign: h === 'Cotisation (FC)' ? 'right' : 'left', fontWeight: 600, color: 'hsl(var(--text-secondary))', fontSize: '0.75rem', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{h}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {contributions.map(c => (
                      <tr key={c.id} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                        <td style={{ padding: '7px 10px', fontWeight: 600 }}>{c.client_display || c.client}</td>
                        <td style={{ padding: '7px 10px', textAlign: 'right' }}>{parseFloat(c.amount).toLocaleString('fr-FR')}</td>
                        <td style={{ padding: '7px 10px' }}>
                          <button onClick={() => handleTogglePaid(c.id)}
                            style={{ padding: '3px 10px', borderRadius: 12, border: 'none', cursor: 'pointer', background: c.is_paid ? 'hsl(var(--color-success))' : 'hsl(var(--color-warning))', color: '#fff', fontWeight: 700, fontSize: '0.75rem' }}>
                            {c.is_paid ? '✓ Payé' : 'Non payé'}
                          </button>
                        </td>
                        <td style={{ padding: '7px 10px', color: 'hsl(var(--text-secondary))', fontSize: '0.78rem' }}>
                          {c.paid_at ? new Date(c.paid_at).toLocaleDateString('fr-FR') : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                  <tfoot>
                    <tr style={{ background: 'hsl(var(--bg-tertiary))', borderTop: '2px solid hsl(var(--border-color))', fontWeight: 700 }}>
                      <td style={{ padding: '7px 10px' }}>{contributions.length} client(s)</td>
                      <td style={{ padding: '7px 10px', textAlign: 'right' }}>
                        {contributions.reduce((s, c) => s + parseFloat(c.amount), 0).toLocaleString('fr-FR')} FC
                      </td>
                      <td style={{ padding: '7px 10px' }}>
                        {contributions.filter(c => c.is_paid).length} / {contributions.length} payé(s)
                      </td>
                      <td />
                    </tr>
                  </tfoot>
                </table>
              </div>
            )}
          </div>
        ) : (
          <SocialDistributionPanel node={socialNode} year={socialYear} canRead={canReadSocial} />
        )}
      </div>
  );
};
