import React, { useEffect, useState } from 'react';
import { apiClient } from '@/api/client';
import { FiList, FiRefreshCw, FiCalendar, FiUser } from 'react-icons/fi';

interface ActivityLogItem {
  id: string;
  user_name: string;
  user_display: string;
  action: string;
  description: string;
  node_origin: string;
  created_at: string;
}

const formatLogDate = (dateStr: string) => {
  if (!dateStr) return '';
  const formattedStr = dateStr.includes(' ') && !dateStr.includes('T') 
    ? dateStr.replace(' ', 'T') 
    : dateStr;
  const d = new Date(formattedStr);
  return isNaN(d.getTime()) ? dateStr : d.toLocaleString('fr-FR');
};

export const Activities: React.FC = () => {
  const [logs, setLogs] = useState<ActivityLogItem[]>([]);
  const [loading, setLoading] = useState(true);

  const fetchLogs = async () => {
    setLoading(true);
    try {
      const response = await apiClient.get('/api/core/activities/');
      const data = Array.isArray(response.data) ? response.data : (response.data.results || []);
      setLogs(data);
    } catch (error) {
      console.error("Failed to fetch activity logs", error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchLogs();
  }, []);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      {/* Welcome Banner / Header */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '32px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
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

        {loading ? (
          <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '48px', fontSize: '1.1rem', fontWeight: 600 }}>
            Chargement des journaux de caisse en cours...
          </div>
        ) : logs.length === 0 ? (
          <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '48px' }}>
            Aucun journal d'activité disponible pour le moment.
          </div>
        ) : (
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
        )}
      </div>
    </div>
  );
};
