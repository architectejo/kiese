import React, { useState, useEffect } from 'react';
import {
  FiShield, FiCheckCircle, FiCpu, FiLock, FiAlertTriangle
} from 'react-icons/fi';
import { blockchainApi, treasuryApi, TamperAlert, BlockchainSnapshot, CashbookEntry } from '@/api/services';
import { useProgressiveList } from '@/hooks/useProgressiveList';

export const Blockchain: React.FC = () => {
  const [verifying, setVerifying] = useState(false);
  const [globalStatus, setGlobalStatus] = useState<{
    open_alerts: number;
    nodes_checked: number;
    all_intact: boolean;
    node_snapshots: BlockchainSnapshot[];
  } | null>(null);
  const [alerts, setAlerts] = useState<TamperAlert[]>([]);
  // BUG-164 : l'aperçu n'affiche que les 10 écritures les plus récentes. Le serveur trie
  // (-date, -created_at) avant de paginer : on ne demande donc QUE cette page de 10 lignes
  // (mode `manual`, aucun chargement de suite) au lieu de lire tout le livre de caisse puis
  // de tronquer. La vérification d'intégrité (`runCheck`, `globalStatus`) est entièrement
  // calculée par le serveur sur la chaîne complète : elle ne dépend d'aucune liste client.
  const cashbookQ = useProgressiveList<CashbookEntry>({
    fetchPage: p => treasuryApi.cashbook.page({ page: String(p), page_size: '10' }),
    resetKey: 'blockchain-preview',
    mode: 'manual',
  });
  const cashbookEntries = cashbookQ.items.slice(0, 10);

  const loadStatus = async () => {
    try {
      const [statusRes, alertsRes] = await Promise.all([
        blockchainApi.snapshots.globalStatus(),
        blockchainApi.alerts.list({ resolved: 'false' }),
      ]);
      setGlobalStatus(statusRes.data);
      setAlerts(alertsRes.data);
    } catch (err) {
      console.error('Failed to load blockchain status', err);
    }
  };

  useEffect(() => {
    loadStatus();
  }, []);

  const runVerification = async () => {
    setVerifying(true);
    try {
      await blockchainApi.snapshots.runCheck();
      await loadStatus();
      cashbookQ.reload();
    } catch (err) {
      console.error('Integrity check failed', err);
    } finally {
      setVerifying(false);
    }
  };

  const allIntact = globalStatus?.all_intact ?? true;
  const openAlerts = globalStatus?.open_alerts ?? 0;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', fontSize: '0.85rem' }}>

      {/* Header */}
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '16px 20px'
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '2px' }}>
              Registre d'Audit Blockchain SHA-256
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem' }}>
              Journal de sécurité immuable. Chaque écriture du Livre de Caisse génère un bloc chaîné.
            </p>
          </div>
          <FiShield style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8 }} />
        </div>
      </div>

      {/* KPI Stats */}
      <div className="kpi-grid" style={{ gap: '14px' }}>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: `hsl(var(--${allIntact ? 'color-success' : 'color-danger'}) / 0.1)`, display: 'flex', alignItems: 'center', justifyContent: 'center', color: `hsl(var(--${allIntact ? 'color-success' : 'color-danger'}))` }}>
            <FiShield />
          </div>
          <div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>ÉTAT DE LA CHAÎNE</div>
            <h3 style={{ fontSize: '1rem', fontWeight: 800, color: allIntact ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
              {allIntact ? 'INTÈGRE' : 'COMPROMIS'}
            </h3>
          </div>
        </div>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--color-danger) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--color-danger))' }}>
            <FiAlertTriangle />
          </div>
          <div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>ALERTES OUVERTES</div>
            <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{openAlerts}</h3>
          </div>
        </div>
        <div className="glass-card" style={{ display: 'flex', alignItems: 'center', gap: '10px', padding: '10px 12px' }}>
          <div style={{ width: '36px', height: '36px', borderRadius: '50%', backgroundColor: 'hsl(var(--color-info) / 0.1)', display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'hsl(var(--color-info))' }}>
            <FiCpu />
          </div>
          <div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-secondary))', fontWeight: 700 }}>NŒUDS VÉRIFIÉS</div>
            <h3 style={{ fontSize: '1rem', fontWeight: 800 }}>{globalStatus?.nodes_checked ?? '—'}</h3>
          </div>
        </div>
      </div>

      {/* Verification Control */}
      <div className="glass-card" style={{
        display: 'flex', justifyContent: 'space-between', alignItems: 'center',
        padding: '16px', flexWrap: 'wrap', gap: '12px',
        borderLeft: `4px solid hsl(var(--${allIntact ? 'color-success' : 'color-danger'}))`,
        transition: 'all 0.3s ease'
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <FiCpu style={{ fontSize: '1.8rem', color: 'hsl(var(--accent-color))' }} />
          <div>
            <strong style={{ fontSize: '0.8rem', color: 'hsl(var(--text-primary))', display: 'block' }}>
              {verifying ? 'Validation cryptographique en cours...' :
                allIntact ? '✓ Registre Intègre — Aucune Altération Détectée' :
                  '⚠ Altérations Détectées — Vérifiez les Alertes'}
            </strong>
            <span style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>
              {verifying ? 'Calcul des hash SHA-256 de tous les nœuds...' :
                'Chaîne de hash du Livre de Caisse Direction.'}
            </span>
          </div>
        </div>
        <button
          onClick={runVerification}
          disabled={verifying}
          className="btn btn-primary"
          style={{ padding: '8px 16px', fontSize: '0.78rem', display: 'flex', alignItems: 'center', gap: '6px' }}
        >
          <FiCheckCircle />
          <span>{verifying ? 'Calcul...' : "Vérifier l'Intégrité"}</span>
        </button>
      </div>

      {/* Open Tamper Alerts */}
      {alerts.length > 0 && (
        <div className="glass-card" style={{ padding: '16px', borderLeft: '4px solid hsl(var(--color-danger))' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 800, color: 'hsl(var(--color-danger))', marginBottom: '12px' }}>
            <FiAlertTriangle style={{ marginRight: '6px' }} />
            Alertes de Falsification Actives ({alerts.length})
          </h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
            {alerts.map(alert => (
              <div key={alert.id} style={{ backgroundColor: 'hsl(var(--color-danger) / 0.05)', border: '1px solid hsl(var(--color-danger) / 0.2)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
                  <strong style={{ fontSize: '0.78rem', color: 'hsl(var(--text-primary))' }}>{alert.node_name} — {alert.affected_model}</strong>
                  <span className="badge badge-danger" style={{ fontSize: '0.58rem' }}>{alert.severity}</span>
                </div>
                <p style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))', margin: 0 }}>{alert.description}</p>
                <p style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', marginTop: '4px', marginBottom: 0 }}>
                  {new Date(alert.detected_at).toLocaleString('fr-FR')}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Node Snapshots */}
      {globalStatus?.node_snapshots && globalStatus.node_snapshots.length > 0 && (
        <div className="glass-card" style={{ padding: '16px' }}>
          <h3 style={{ fontSize: '0.9rem', fontWeight: 800, marginBottom: '12px' }}>État par Nœud</h3>
          <div style={{ overflowX: 'auto' }}>
            <table className="premium-table">
              <thead>
                <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                  <th>Nœud</th>
                  <th style={{ textAlign: 'center' }}>Date Vérif.</th>
                  <th style={{ textAlign: 'right' }}>Entrées</th>
                  <th style={{ textAlign: 'right' }}>Falsifiées</th>
                  <th style={{ textAlign: 'center' }}>Statut</th>
                </tr>
              </thead>
              <tbody style={{ fontSize: '0.72rem' }}>
                {globalStatus.node_snapshots.map(s => (
                  <tr key={s.id}>
                    <td style={{ fontWeight: 700 }}>{s.node_name}</td>
                    <td style={{ textAlign: 'center', color: 'hsl(var(--text-secondary))' }}>{s.snapshot_date}</td>
                    <td style={{ textAlign: 'right' }}>{s.total_entries}</td>
                    <td style={{ textAlign: 'right', color: s.tampered_entries > 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))' }}>
                      {s.tampered_entries}
                    </td>
                    <td style={{ textAlign: 'center' }}>
                      <span className={`badge ${s.is_intact ? 'badge-success' : 'badge-danger'}`} style={{ fontSize: '0.58rem' }}>
                        {s.is_intact ? 'INTÈGRE' : 'COMPROMIS'}
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Cashbook Chain Preview */}
      {cashbookEntries.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '12px', position: 'relative' }}>
          <div style={{ position: 'absolute', top: '30px', bottom: '30px', left: '24px', width: '2px', backgroundColor: 'hsl(var(--border-color))', zIndex: 1 }} />
          {cashbookEntries.map((entry, idx) => (
            <div key={entry.id} className="glass-card" style={{
              marginLeft: '50px', padding: '14px', position: 'relative', zIndex: 2,
              border: `1px solid hsl(var(--${entry.is_tampered ? 'color-danger' : 'border-color'}))`
            }}>
              <div style={{ position: 'absolute', left: '-40px', top: '14px', width: '22px', height: '22px', borderRadius: '50%', backgroundColor: entry.is_tampered ? 'hsl(var(--color-danger))' : 'hsl(var(--bg-tertiary))', border: '2px solid hsl(var(--border-color))', display: 'flex', alignItems: 'center', justifyContent: 'center', color: entry.is_tampered ? '#fff' : 'hsl(var(--text-secondary))', fontSize: '0.62rem', fontWeight: 800, zIndex: 3 }}>
                #{cashbookEntries.length - idx}
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <FiLock style={{ color: entry.is_tampered ? 'hsl(var(--color-danger))' : 'hsl(var(--accent-color))' }} />
                  <strong style={{ fontSize: '0.78rem' }}>{entry.piece_number} — {entry.label}</strong>
                </div>
                <span style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))' }}>{entry.date}</span>
              </div>
              <div style={{ backgroundColor: 'hsl(var(--bg-tertiary))', padding: '8px', borderRadius: 'var(--radius-sm)', fontSize: '0.72rem', fontFamily: 'monospace', marginBottom: '8px' }}>
                E: {parseFloat(entry.entry_amount).toLocaleString('fr-FR')} FC | S: {parseFloat(entry.exit_amount).toLocaleString('fr-FR')} FC | Solde: {parseFloat(entry.running_balance).toLocaleString('fr-FR')} FC
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                <div><strong style={{ color: 'hsl(var(--text-secondary))' }}>HASH: </strong>{entry.block_hash}</div>
              </div>
            </div>
          ))}
        </div>
      )}

      {cashbookQ.isLoading && (
        <div className="glass-card" style={{ padding: '24px', textAlign: 'center', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>
          Chargement des dernières écritures…
        </div>
      )}
      {cashbookQ.error && (
        <div role="alert" className="glass-card" style={{ padding: '14px', color: 'hsl(var(--color-danger))', fontSize: '0.78rem', display: 'flex', gap: '10px', alignItems: 'center', flexWrap: 'wrap' }}>
          {cashbookQ.error}
          <button onClick={cashbookQ.reload} className="btn btn-secondary" style={{ padding: '3px 10px', fontSize: '0.7rem' }}>Réessayer</button>
        </div>
      )}
      {cashbookEntries.length === 0 && !verifying && !cashbookQ.isLoading && !cashbookQ.error && (
        <div className="glass-card" style={{ padding: '32px', textAlign: 'center', color: 'hsl(var(--text-secondary))' }}>
          <FiLock style={{ fontSize: '2rem', marginBottom: '8px', opacity: 0.4 }} />
          <p style={{ fontSize: '0.8rem' }}>Aucune écriture dans le Livre de Caisse. Poussez une clôture de caisse pour créer la première entrée.</p>
        </div>
      )}
    </div>
  );
};
