import React from 'react';
import { FiAlertTriangle, FiDollarSign, FiPackage, FiPercent, FiRefreshCw, FiSave } from 'react-icons/fi';
import { SiteConfig } from '@/api/services';

interface ConfigFormProps {
  form: Partial<SiteConfig>;
  set: (key: keyof SiteConfig, value: string | number | boolean) => void;
  isSaving: boolean;
  onSubmit: (e: React.FormEvent<HTMLFormElement>) => void;
}

export const ConfigForm: React.FC<ConfigFormProps> = ({ form, set, isSaving, onSubmit }) => {
  return (
      <form onSubmit={onSubmit}>
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '16px' }}>

          {/* §2 Paramètres des commissions */}
          <div className="glass-card" style={{ padding: '16px' }}>
            <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiPercent style={{ color: 'hsl(var(--accent-color))' }} />
              §2.3 — Algorithme des Commissions (CM)
            </h3>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Taux de Commission par Défaut (%)
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number" step="1" min="0" max="100"
                    value={form.default_commission_rate != null ? Math.round(parseFloat(String(form.default_commission_rate)) * 100) : ''}
                    onChange={e => set('default_commission_rate', (parseFloat(e.target.value) / 100).toFixed(2))}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>%</span>
                </div>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>Défaut : 25 — applicable à tous les clients sans taux personnalisé</div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Taux Cotisation Sociale (%)
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number" step="0.01"
                    value={form.social_deduction_rate ?? ''}
                    onChange={e => set('social_deduction_rate', e.target.value)}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', whiteSpace: 'nowrap' }}>
                    = {((parseFloat(String(form.social_deduction_rate)) || 0) * 100).toFixed(0)}%
                  </span>
                </div>
              </div>

              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Frais d'Imprimés (FC)
                </label>
                <input
                  type="number"
                  value={form.print_fee ?? ''}
                  onChange={e => set('print_fee', e.target.value)}
                  className="form-input"
                  style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                />
              </div>
            </div>
          </div>

          {/* §2.2 + §3.1 Seuils et rendements */}
          <div style={{ display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <div className="glass-card" style={{ padding: '16px' }}>
              <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FiDollarSign style={{ color: 'hsl(var(--accent-color))' }} />
                §2.2 — Seuils de Segmentation Clients
              </h3>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Plafond de Dette — Client à Risque (FC)
                  </label>
                  <input
                    type="number"
                    value={form.debt_ceiling ?? ''}
                    onChange={e => set('debt_ceiling', e.target.value)}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>
                    Au-delà → catégorie RISK + alerte rouge
                  </div>
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                    Seuil "Meilleur Client" (nb pains)
                  </label>
                  <input
                    type="number"
                    value={form.best_client_threshold ?? ''}
                    onChange={e => set('best_client_threshold', Number(e.target.value))}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px' }}>
                    Volume cumulé ≥ seuil → catégorie BEST
                  </div>
                </div>
              </div>
            </div>

            <div className="glass-card" style={{ padding: '16px' }}>
              <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FiPackage style={{ color: 'hsl(var(--accent-color))' }} />
                §3.1 — Valeur Théorique par Sac de Farine
              </h3>
              <div>
                <label style={{ display: 'block', fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Valeur FC théorique / sac de farine
                </label>
                <div style={{ display: 'flex', gap: '8px', alignItems: 'center' }}>
                  <input
                    type="number"
                    value={form.sac_value_fc ?? ''}
                    onChange={e => set('sac_value_fc', Number(e.target.value))}
                    className="form-input"
                    style={{ height: '34px', fontSize: '0.8rem', padding: '0 10px' }}
                  />
                  <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', whiteSpace: 'nowrap' }}>FC</span>
                </div>
                <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '4px', lineHeight: 1.5 }}>
                  Défaut : <strong>200 000 FC</strong> / sac.
                  <br />Équivalences : {(form.sac_value_fc || 200000).toLocaleString('fr-FR')} FC =
                  {' '}<strong>{Math.round((form.sac_value_fc || 200000) / 1000)}</strong> pains 1000 FC
                  {' '}= <strong>{Math.round((form.sac_value_fc || 200000) / 500)}</strong> pains 500 FC
                  {' '}= <strong>{Math.round((form.sac_value_fc || 200000) / 300)}</strong> pains 300 FC
                </div>
              </div>
            </div>

            <div className="glass-card" style={{ padding: '16px' }}>
              <h3 style={{ fontSize: '0.88rem', fontWeight: 800, marginBottom: '14px', display: 'flex', alignItems: 'center', gap: '6px' }}>
                <FiAlertTriangle style={{ color: 'hsl(var(--accent-color))' }} />
                Ventes Passées (saisie rétroactive)
              </h3>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: '0.78rem', fontWeight: 700 }}>
                    Autoriser la saisie de ventes datées (passées)
                  </div>
                  <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '3px', lineHeight: 1.5 }}>
                    Permet aux facturiers de choisir une date antérieure lors de l'enregistrement d'une
                    commande ou d'une livraison. Désactivé par défaut.
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => set('allow_backdated_sales', !form.allow_backdated_sales)}
                  style={{
                    position: 'relative', width: '48px', height: '26px',
                    borderRadius: '13px', border: 'none', cursor: 'pointer',
                    backgroundColor: form.allow_backdated_sales ? 'hsl(var(--color-success))' : 'hsl(var(--text-muted))',
                    transition: 'background-color 0.3s ease',
                    flexShrink: 0,
                  }}
                  title={form.allow_backdated_sales ? 'Cliquer pour désactiver' : 'Cliquer pour activer'}
                >
                  <span style={{
                    position: 'absolute', top: '3px',
                    left: form.allow_backdated_sales ? '25px' : '3px',
                    width: '20px', height: '20px', borderRadius: '50%',
                    backgroundColor: '#fff',
                    transition: 'left 0.3s ease',
                    boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
                  }} />
                </button>
              </div>
              <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '10px' }}>
                N'oubliez pas d'enregistrer la configuration pour appliquer ce changement.
              </div>
            </div>
          </div>
        </div>

        {/* Save button */}
        <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: '16px' }}>
          <button
            type="submit"
            disabled={isSaving}
            className="btn btn-primary"
            style={{ padding: '10px 28px', fontSize: '0.82rem', display: 'flex', alignItems: 'center', gap: '8px', opacity: isSaving ? 0.7 : 1 }}
          >
            {isSaving ? <FiRefreshCw style={{ animation: 'spin 1s linear infinite' }} /> : <FiSave />}
            {isSaving ? 'Enregistrement...' : 'Enregistrer la Configuration'}
          </button>
        </div>
      </form>
  );
};
