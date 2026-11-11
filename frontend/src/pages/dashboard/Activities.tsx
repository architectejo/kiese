import React from 'react';
import { coreApi } from '@/api/services';
import { useProgressiveList } from '@/hooks/useProgressiveList';
import { FiList, FiRefreshCw, FiCalendar, FiUser, FiChevronDown } from 'react-icons/fi';

// BUG-163 (remarque.md l.422) : le journal croît sans fin. Page 1 affichée dès
// réception, puis « Voir plus » = page suivante du serveur à chaque clic (pas de
// chargement complet automatique).
const ACTIVITIES_PAGE_SIZE = '50';

const formatLogDate = (dateStr: string) => {
  if (!dateStr) return '';
  const formattedStr = dateStr.includes(' ') && !dateStr.includes('T') 
    ? dateStr.replace(' ', 'T') 
    : dateStr;
  const d = new Date(formattedStr);
  return isNaN(d.getTime()) ? dateStr : d.toLocaleString('fr-FR');
};

export const Activities: React.FC = () => {
  const {
    items: logs, isLoading: loading, isLoadingMore, loaded, total, hasMore, error, loadMore, reload,
  } = useProgressiveList({
    resetKey: 'activities',
    mode: 'manual',
    fetchPage: (page) => coreApi.activities.page({ page: String(page), page_size: ACTIVITIES_PAGE_SIZE }),
  });
  const fetchLogs = reload;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      {/* Welcome Banner / Header */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '32px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: '12px' }}>
          <div>
            <h1 style={{ fontSize: '2.2rem', fontWeight: 800, marginBottom: '8px', letterSpacing: '-0.02em' }}>
              Console Consolidée d'Administration
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '1rem', maxWidth: '800px' }}>
              Registre unifié des journaux d'activités et des transactions consolidées pour l'ensemble des boulangeries du groupe ETS. KIESE.
            </p>
          </div>
          <button 
            onClick={fetchLogs} 
            className="btn btn-secondary"
            style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '10px 16px' }}
          >
            <FiRefreshCw className={loading ? 'animate-spin' : ''} />
            <span>Actualiser</span>
          </button>
        </div>
      </div>

      {/* Main Glass Logs Table */}
      <div className="glass-card animate-fade-in" style={{ padding: '24px' }}>
        <h2 style={{ fontSize: '1.25rem', fontWeight: 800, marginBottom: '20px', display: 'flex', alignItems: 'center', gap: '10px' }}>
          <FiList style={{ color: 'hsl(var(--accent-color))' }} />
          Historique Complet des Événements
        </h2>

        {error && (
          <div role="alert" style={{ color: 'hsl(var(--color-danger))', fontWeight: 700, fontSize: '0.85rem', marginBottom: '12px' }}>
            {error}
          </div>
        )}

        {loading ? (
          <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '48px', fontSize: '1.1rem', fontWeight: 600 }}>
            Chargement des journaux de caisse en cours...
          </div>
        ) : logs.length === 0 && !error ? (
          <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '48px' }}>
            Aucun journal d'activité disponible pour le moment.
          </div>
        ) : (
          <>
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table">
              <thead>
                <tr>
                  <th style={{ width: '100px' }}>Nœud Origin</th>
                  <th style={{ width: '150px' }}>Date & Heure</th>
                  <th style={{ width: '180px' }}>Action</th>
                  <th style={{ width: '180px' }}>Utilisateur / Agent</th>
                  <th>Description de l'Événement</th>
                </tr>
              </thead>
              <tbody>
                {logs.map((log) => (
                  <tr key={log.id} style={{ transition: 'background-color 0.2s ease' }}>
                    <td>
                      <span className="badge badge-info" style={{ fontWeight: 800 }}>
                        {log.node_origin}
                      </span>
                    </td>
                    <td style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.85rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                        <FiCalendar style={{ color: 'hsl(var(--accent-color))' }} />
                        <span>{formatLogDate(log.created_at)}</span>
                      </div>
                    </td>
                    <td>
                      <span className="badge badge-success" style={{ fontWeight: 700, textTransform: 'uppercase', fontSize: '0.7rem' }}>
                        {log.action}
                      </span>
                    </td>
                    <td style={{ fontWeight: 700, color: 'hsl(var(--text-primary))' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                        <FiUser style={{ color: 'hsl(var(--text-muted))' }} />
                        <span>{log.user_display || 'Système'}</span>
                      </div>
                    </td>
                    <td style={{ color: 'hsl(var(--text-secondary))', lineHeight: 1.4, fontSize: '0.9rem' }}>
                      {log.description}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '10px', marginTop: '20px' }}>
            <span role="status" style={{ fontSize: '0.85rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>
              {loaded.toLocaleString('fr-FR')} affichée(s) / {(total ?? loaded).toLocaleString('fr-FR')} au total
            </span>
            {hasMore && (
              <button
                onClick={loadMore}
                disabled={isLoadingMore}
                className="btn btn-secondary"
                style={{ display: 'flex', alignItems: 'center', gap: '8px', padding: '12px 24px', minHeight: '44px', fontWeight: 700 }}
              >
                <FiChevronDown />
                <span>{isLoadingMore ? 'Chargement…' : 'Voir plus'}</span>
              </button>
            )}
          </div>
          </>
        )}
      </div>
    </div>
  );
};
