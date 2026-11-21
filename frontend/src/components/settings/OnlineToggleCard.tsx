import React from 'react';
import { FiGlobe, FiLock } from 'react-icons/fi';
import { SiteConfig } from '@/api/services';

interface OnlineToggleCardProps {
  form: Partial<SiteConfig>;
  updatedAt: string | undefined;
  onToggle: () => void;
}

export const OnlineToggleCard: React.FC<OnlineToggleCardProps> = ({ form, updatedAt, onToggle }) => {
  return (
      <div className="glass-card" style={{
        padding: '20px 24px',
        borderLeft: `4px solid hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}))`,
        backgroundColor: `hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}) / 0.04)`,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
            <div style={{
              width: '48px', height: '48px', borderRadius: '50%',
              backgroundColor: `hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}) / 0.15)`,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: `hsl(var(--${form.on_line ? 'color-success' : 'color-danger'}))`,
              fontSize: '1.4rem'
            }}>
              {form.on_line ? <FiGlobe /> : <FiLock />}
            </div>
            <div>
              <h2 style={{ fontSize: '1rem', fontWeight: 800, marginBottom: '4px' }}>
                Mode d'Affichage Public — §6.2
              </h2>
              <p style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', maxWidth: '500px' }}>
                {form.on_line
                  ? 'Site web vitrine VISIBLE au public. Les agents accèdent au dashboard via le bouton "Connexion".'
                  : 'Site vitrine MASQUÉ. Tout visiteur est automatiquement redirigé vers la page de login du dashboard.'}
              </p>
              <p style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', marginTop: '2px' }}>
                Dernière modification : {updatedAt ? new Date(updatedAt).toLocaleString('fr-FR') : '—'}
              </p>
            </div>
          </div>

          {/* Toggle switch */}
          <button
            type="button"
            onClick={onToggle}
            style={{
              position: 'relative', width: '72px', height: '36px',
              borderRadius: '18px', border: 'none', cursor: 'pointer',
              backgroundColor: form.on_line ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))',
              transition: 'background-color 0.3s ease',
              flexShrink: 0,
            }}
            title={form.on_line ? 'Cliquer pour désactiver la vitrine' : 'Cliquer pour activer la vitrine'}
          >
            <span style={{
              position: 'absolute', top: '4px',
              left: form.on_line ? '38px' : '4px',
              width: '28px', height: '28px', borderRadius: '50%',
              backgroundColor: '#fff',
              transition: 'left 0.3s ease',
              boxShadow: '0 2px 6px rgba(0,0,0,0.3)',
            }} />
            <span style={{
              position: 'absolute', top: '50%', transform: 'translateY(-50%)',
              left: form.on_line ? '6px' : 'auto', right: form.on_line ? 'auto' : '6px',
              fontSize: '0.55rem', fontWeight: 800, color: '#fff',
              transition: 'all 0.3s ease',
            }}>
              {form.on_line ? 'ON' : 'OFF'}
            </span>
          </button>
        </div>

        {/* Status badges */}
        <div style={{ display: 'flex', gap: '8px', marginTop: '12px', flexWrap: 'wrap' }}>
          <span className={`badge ${form.on_line ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.6rem' }}>
            {form.on_line ? '🌐 VITRINE EN LIGNE' : '🔒 DASHBOARD UNIQUEMENT'}
          </span>
          <span className="badge badge-info" style={{ fontSize: '0.6rem' }}>
            Route "/" → {form.on_line ? '<Vitrine />' : '<Navigate to="/login" />'}
          </span>
        </div>
      </div>
  );
};
