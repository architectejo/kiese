import React, { useCallback, useEffect, useState } from 'react';
import { FiHardDrive, FiDownloadCloud, FiRotateCcw, FiAlertOctagon, FiRefreshCw, FiClock } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import type { KieseBackupEntry } from '@/types/kiese';

/**
 * Écran « Administration → Restaurer une sauvegarde » (BUG-074).
 *
 * Consomme le pont Electron déjà exposé par `desktop/src/preload.ts`
 * (`window.kiese.backup.*`, implémenté dans `desktop/src/backup.ts`) :
 * cette page n'implémente aucune logique de fichier elle-même, elle se
 * contente d'appeler l'API IPC déjà en place.
 *
 * Hors du mode desktop (navigateur classique, POS Android), `window.kiese`
 * est absent : l'écran l'indique clairement et désactive les actions au
 * lieu de planter.
 *
 * Limite résiduelle connue (documentée dans docs/qa/REGISTRE_BUGS.md,
 * BUG-074) : le marqueur `.last_pre_migration_backup` écrit par
 * `backend/desktop_server.py` juste avant une migration n'est pas exposé
 * par `window.kiese.backup.list()` (qui ne renvoie que nom/taille/date des
 * fichiers `.sqlite3.gz`). Il n'est donc pas possible ici de mettre en
 * évidence, de façon fiable, LA sauvegarde précédant spécifiquement la
 * dernière migration — seule la sauvegarde la plus récente (triée par
 * date) est mise en avant, ce qui correspond au cas pratique le plus
 * fréquent mais n'est pas garanti identique si une sauvegarde manuelle a
 * été prise après la migration ratée.
 */

const formatSize = (bytes: number): string => {
  if (bytes < 1024) return `${bytes} o`;
  const ko = bytes / 1024;
  if (ko < 1024) return `${ko.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Ko`;
  const mo = ko / 1024;
  return `${mo.toLocaleString('fr-FR', { maximumFractionDigits: 1 })} Mo`;
};

const formatDate = (iso: string): string => {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('fr-FR', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' });
};

type FeedbackState = { type: 'success' | 'error'; text: string } | null;

export const BackupManager: React.FC = () => {
  const bridge = typeof window !== 'undefined' ? window.kiese : undefined;
  const backupApi = bridge?.backup;
  const isElectron = Boolean(backupApi);

  const [backups, setBackups] = useState<KieseBackupEntry[]>([]);
  const [isLoading, setIsLoading] = useState(isElectron);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [restoringName, setRestoringName] = useState<string | null>(null);
  const [confirmTarget, setConfirmTarget] = useState<KieseBackupEntry | null>(null);
  const [feedback, setFeedback] = useState<FeedbackState>(null);

  const fetchBackups = useCallback(async () => {
    if (!backupApi) return;
    setIsLoading(true);
    setLoadError(null);
    try {
      const list = await backupApi.list();
      setBackups(list);
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Impossible de lire le dossier des sauvegardes.');
    } finally {
      setIsLoading(false);
    }
  }, [backupApi]);

  useEffect(() => {
    fetchBackups();
  }, [fetchBackups]);

  const mostRecent = backups.length > 0 ? backups[0] : null;

  const handleCreateNow = async () => {
    if (!backupApi || isCreating) return;
    setIsCreating(true);
    setFeedback(null);
    try {
      const result = await backupApi.createNow();
      if (result.ok) {
        setFeedback({ type: 'success', text: 'Sauvegarde créée avec succès.' });
        await fetchBackups();
      } else {
        setFeedback({ type: 'error', text: result.error || 'La sauvegarde a échoué.' });
      }
    } catch (err) {
      setFeedback({ type: 'error', text: err instanceof Error ? err.message : 'La sauvegarde a échoué.' });
    } finally {
      setIsCreating(false);
    }
  };

  const handleConfirmRestore = async () => {
    if (!backupApi || !confirmTarget) return;
    const target = confirmTarget;
    setRestoringName(target.name);
    setFeedback(null);
    try {
      const result = await backupApi.restore(target.name);
      if (result.ok) {
        setConfirmTarget(null);
        setFeedback({
          type: 'success',
          text: 'Restauration terminée. Le service redémarre : rechargez la page dans quelques secondes.',
        });
      } else {
        setFeedback({ type: 'error', text: result.error || 'La restauration a échoué.' });
      }
    } catch (err) {
      setFeedback({ type: 'error', text: err instanceof Error ? err.message : 'La restauration a échoué.' });
    } finally {
      setRestoringName(null);
    }
  };

  if (!isElectron) {
    return (
      <div className="glass-card" style={{ padding: '20px', display: 'flex', flexDirection: 'column', gap: '10px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
          <FiHardDrive style={{ fontSize: '1.4rem', color: 'hsl(var(--text-muted))' }} />
          <h2 style={{ fontSize: '1rem', fontWeight: 800 }}>Sauvegarde et restauration</h2>
        </div>
        <p style={{ fontSize: '0.85rem', color: 'hsl(var(--text-secondary))', lineHeight: 1.5 }}>
          Cette fonctionnalité n'est disponible que sur l'application de bureau (Electron) installée
          dans chaque boulangerie, car elle agit directement sur le fichier de base de données local.
          Vous consultez actuellement l'application depuis un navigateur web : aucune sauvegarde locale
          n'est accessible depuis cet écran.
        </p>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', fontSize: '0.85rem' }}>
      <div className="glass-card animate-fade-in" style={{
        background: 'linear-gradient(135deg, hsl(var(--bg-tertiary)) 0%, hsl(var(--bg-secondary)) 100%)',
        borderLeft: '4px solid hsl(var(--accent-color))',
        padding: '16px 20px',
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <div>
            <h1 style={{ fontSize: '1.4rem', fontWeight: 800, marginBottom: '2px' }}>
              Sauvegarde et restauration locale
            </h1>
            <p style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.75rem' }}>
              Base de données de cette boulangerie uniquement. Utilisez cet écran si une mise à jour a
              échoué (voir le message affiché au démarrage) ou avant une opération risquée.
            </p>
          </div>
          <FiHardDrive style={{ fontSize: '2rem', color: 'hsl(var(--accent-color))', opacity: 0.8, flexShrink: 0 }} />
        </div>
      </div>

      {feedback && (
        <div style={{
          padding: '10px 14px', borderRadius: 'var(--radius-md)', fontSize: '0.82rem', fontWeight: 600,
          backgroundColor: feedback.type === 'success' ? 'hsl(var(--color-success) / 0.12)' : 'hsl(var(--color-danger) / 0.12)',
          color: feedback.type === 'success' ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))',
          border: `1px solid ${feedback.type === 'success' ? 'hsl(var(--color-success) / 0.3)' : 'hsl(var(--color-danger) / 0.3)'}`,
        }}>
          {feedback.text}
        </div>
      )}

      <div className="glass-card" style={{ padding: '16px 20px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '16px', gap: '10px', flexWrap: 'wrap' }}>
          <h2 style={{ fontSize: '0.95rem', fontWeight: 800, color: 'hsl(var(--text-primary))' }}>
            Sauvegardes disponibles sur ce poste
          </h2>
          <div style={{ display: 'flex', gap: '10px' }}>
            <button
              onClick={fetchBackups}
              className="btn btn-secondary"
              style={{ padding: '6px 10px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}
              disabled={isLoading}
            >
              <FiRefreshCw className={isLoading ? 'animate-spin' : ''} />
              <span>Actualiser</span>
            </button>
            <button
              onClick={handleCreateNow}
              className="btn btn-primary"
              style={{ padding: '6px 12px', display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.78rem' }}
              disabled={isCreating}
            >
              <FiDownloadCloud />
              <span>{isCreating ? 'Sauvegarde en cours...' : 'Sauvegarder maintenant'}</span>
            </button>
          </div>
        </div>

        {loadError && (
          <div style={{
            marginBottom: '12px', padding: '10px 14px', borderRadius: 'var(--radius-md)', fontSize: '0.8rem',
            backgroundColor: 'hsl(var(--color-danger) / 0.1)', color: 'hsl(var(--color-danger))',
            border: '1px solid hsl(var(--color-danger) / 0.3)',
          }}>
            {loadError}
          </div>
        )}

        <div style={{ overflowX: 'auto' }}>
          <table className="premium-table">
            <thead>
              <tr style={{ fontSize: '0.68rem', textTransform: 'uppercase' }}>
                <th style={{ padding: '8px 10px' }}>Fichier</th>
                <th style={{ padding: '8px 10px' }}>Créée le</th>
                <th style={{ padding: '8px 10px' }}>Taille</th>
                <th style={{ padding: '8px 10px', textAlign: 'right' }}>Action</th>
              </tr>
            </thead>
            <tbody style={{ fontSize: '0.75rem' }}>
              {isLoading ? (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))' }}>
                    Lecture du dossier des sauvegardes...
                  </td>
                </tr>
              ) : backups.length === 0 ? (
                <tr>
                  <td colSpan={4} style={{ textAlign: 'center', padding: '20px', color: 'hsl(var(--text-secondary))' }}>
                    Aucune sauvegarde trouvée sur ce poste. Cliquez sur « Sauvegarder maintenant ».
                  </td>
                </tr>
              ) : (
                backups.map((b) => (
                  <tr key={b.name}>
                    <td style={{ padding: '8px 10px', fontWeight: 700, color: 'hsl(var(--text-primary))', wordBreak: 'break-all' }}>
                      {b.name}
                      {mostRecent?.name === b.name && (
                        <span className="badge badge-info" style={{ marginLeft: '8px', fontSize: '0.6rem' }}>
                          Plus récente
                        </span>
                      )}
                    </td>
                    <td style={{ padding: '8px 10px', color: 'hsl(var(--text-muted))', fontSize: '0.7rem' }}>
                      <div style={{ display: 'flex', alignItems: 'center', gap: '4px' }}>
                        <FiClock />
                        <span>{formatDate(b.createdAt)}</span>
                      </div>
                    </td>
                    <td style={{ padding: '8px 10px', color: 'hsl(var(--text-secondary))' }}>
                      {formatSize(b.sizeBytes)}
                    </td>
                    <td style={{ padding: '8px 10px', textAlign: 'right' }}>
                      <button
                        onClick={() => setConfirmTarget(b)}
                        className="btn btn-secondary"
                        style={{ padding: '6px 10px', fontSize: '0.72rem', display: 'inline-flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--color-danger))' }}
                        disabled={restoringName !== null}
                      >
                        <FiRotateCcw />
                        <span>Restaurer</span>
                      </button>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      <Modal
        isOpen={confirmTarget !== null}
        onClose={() => (restoringName ? undefined : setConfirmTarget(null))}
        title="Confirmer la restauration"
        subtitle="Cette action remplace la base de données actuelle de cette boulangerie."
        maxWidth="480px"
      >
        {confirmTarget && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
            <div style={{
              display: 'flex', gap: '10px', alignItems: 'flex-start', padding: '12px',
              borderRadius: 'var(--radius-md)', backgroundColor: 'hsl(var(--color-danger) / 0.1)',
              border: '1px solid hsl(var(--color-danger) / 0.3)',
            }}>
              <FiAlertOctagon style={{ color: 'hsl(var(--color-danger))', fontSize: '1.2rem', flexShrink: 0, marginTop: '2px' }} />
              <p style={{ fontSize: '0.8rem', color: 'hsl(var(--text-primary))', lineHeight: 1.5, margin: 0 }}>
                Toutes les données enregistrées <strong>après</strong> la création de cette sauvegarde
                (ventes, clôtures, production...) seront définitivement perdues sur ce poste. Le service
                local va s'arrêter puis redémarrer automatiquement.
              </p>
            </div>
            <div style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))' }}>
              Fichier : <strong style={{ color: 'hsl(var(--text-primary))' }}>{confirmTarget.name}</strong><br />
              Créée le {formatDate(confirmTarget.createdAt)} — {formatSize(confirmTarget.sizeBytes)}
            </div>
            <div style={{ display: 'flex', gap: '10px' }}>
              <button
                type="button"
                onClick={() => setConfirmTarget(null)}
                className="btn btn-secondary"
                style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem' }}
                disabled={restoringName !== null}
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={handleConfirmRestore}
                className="btn btn-primary"
                style={{ flex: 1, padding: '8px 12px', fontSize: '0.82rem', backgroundColor: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger))' }}
                disabled={restoringName !== null}
              >
                {restoringName ? 'Restauration en cours...' : 'Confirmer et restaurer'}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
};
