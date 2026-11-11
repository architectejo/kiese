import React, { useEffect, useState } from 'react';
import { FiAlertTriangle, FiCheckCircle, FiLoader, FiTrash2 } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import { coreApi, ResetDataCounts } from '@/api/services';
import { getErrorDetail } from '@/api/errors';

const CONFIRM_PHRASE = 'SUPPRIMER TOUT';

// BUG-150 : libellés français des catégories renvoyées par
// GET/POST /api/core/reset-data/ (voir contrat BUG-149 côté backend), dans l'ordre
// des plus volumineuses/sensibles aux plus anecdotiques, pour que le superuser
// voie en premier ce qui compte le plus avant de confirmer une suppression
// irréversible. `clients_to_reset` est traité séparément : ce n'est pas une
// suppression mais une remise à zéro de champs dérivés sur des fiches conservées.
const COUNT_LABELS: Array<{ key: keyof Omit<ResetDataCounts, 'clients_to_reset'>; label: string }> = [
  { key: 'invoices', label: 'Factures' },
  { key: 'invoice_lines', label: 'Lignes de facture' },
  { key: 'production_sessions', label: 'Sessions de production' },
  { key: 'production_session_lines', label: 'Lignes de production' },
  { key: 'bread_stocks', label: 'Stocks de pains' },
  { key: 'daily_bread_stock_snapshots', label: 'Instantanés de stock journalier' },
  { key: 'daily_opening_confirmations', label: 'Confirmations d’ouverture' },
  { key: 'daily_opening_confirmation_lines', label: 'Lignes de confirmation d’ouverture' },
  { key: 'bread_transfers', label: 'Transferts de pains' },
  { key: 'bread_transfer_lines', label: 'Lignes de transfert de pains' },
  { key: 'bread_disposals', label: 'Dispositions de pains (soldés/invendus...)' },
  { key: 'consumable_stocks', label: 'Stocks de consommables' },
  { key: 'consumable_movements', label: 'Mouvements de consommables' },
  { key: 'consumable_counts', label: 'Comptages de consommables' },
  { key: 'cashbook_entries', label: 'Écritures du livre de caisse' },
  { key: 'journal_entries', label: 'Écritures de journal' },
  { key: 'cash_closures', label: 'Clôtures de caisse' },
  { key: 'facturier_reports', label: 'Rapports facturier' },
  { key: 'local_expenses', label: 'Dépenses locales' },
  { key: 'direction_cash_counts', label: 'Comptages caisse Direction' },
  { key: 'daily_savings', label: 'Épargnes journalières' },
  { key: 'disbursement_vouchers', label: 'Bordereaux de décaissement' },
  { key: 'commission_periods', label: 'Périodes de commission' },
  { key: 'client_commissions', label: 'Commissions clients' },
  { key: 'financial_years', label: 'Exercices financiers' },
  { key: 'blockchain_snapshots', label: 'Instantanés blockchain' },
  { key: 'tamper_alerts', label: 'Alertes de falsification' },
  { key: 'social_contributions', label: 'Cotisations sociales' },
  { key: 'social_distributions', label: 'Distributions sociales' },
  { key: 'social_distribution_lines', label: 'Lignes de distribution sociale' },
  { key: 'colis_distributions', label: 'Distributions COLIS' },
  { key: 'debt_movements', label: 'Mouvements de dette' },
  { key: 'activity_logs', label: 'Journaux d’activité' },
  { key: 'system_notifications', label: 'Notifications système' },
  { key: 'sync_batch_logs', label: 'Journaux de synchronisation' },
  { key: 'sync_conflict_logs', label: 'Conflits de synchronisation' },
];

type Step = 'loading' | 'preview-error' | 'confirm' | 'submitting' | 'success' | 'submit-error';

interface ResetDataModalProps {
  isOpen: boolean;
  onClose: () => void;
}

/**
 * BUG-150 : boîte de confirmation pour GET/POST /api/core/reset-data/
 * (demande client, remarque.md après l.404 — bouton Superuser « Réinitialiser les
 * données »). Visible uniquement si `user.is_superuser` côté appelant (Settings.tsx).
 *
 * Flux volontairement en plusieurs étapes, aucune fermeture automatique après
 * succès : l'utilisateur doit lire le décompte et fermer lui-même.
 */
export const ResetDataModal: React.FC<ResetDataModalProps> = ({ isOpen, onClose }) => {
  const [step, setStep] = useState<Step>('loading');
  const [preview, setPreview] = useState<ResetDataCounts | null>(null);
  const [result, setResult] = useState<ResetDataCounts | null>(null);
  const [previewError, setPreviewError] = useState('');
  const [submitError, setSubmitError] = useState('');
  const [confirmText, setConfirmText] = useState('');
  const [password, setPassword] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    setStep('loading');
    setPreview(null);
    setResult(null);
    setPreviewError('');
    setSubmitError('');
    setConfirmText('');
    setPassword('');
    coreApi.resetData.preview()
      .then(res => { setPreview(res.data); setStep('confirm'); })
      .catch(err => { setPreviewError(getErrorDetail(err, 'Impossible de charger l’aperçu.')); setStep('preview-error'); });
  }, [isOpen]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (confirmText !== CONFIRM_PHRASE || !password) return;
    setStep('submitting');
    setSubmitError('');
    try {
      const res = await coreApi.resetData.execute({ confirm_phrase: confirmText, password });
      setResult(res.data);
      setStep('success');
    } catch (err) {
      setSubmitError(getErrorDetail(err, 'Phrase ou mot de passe incorrect — rien n’a été supprimé.'));
      setStep('submit-error');
    }
  };

  const renderCounts = (counts: ResetDataCounts) => {
    const rows = COUNT_LABELS.filter(({ key }) => counts[key] > 0);
    const total = rows.reduce((sum, { key }) => sum + counts[key], 0);
    if (rows.length === 0) {
      return (
        <p style={{ fontSize: '0.8rem', color: 'hsl(var(--text-muted))' }}>
          Aucune donnée transactionnelle à supprimer actuellement.
        </p>
      );
    }
    return (
      <div style={{ maxHeight: '260px', overflowY: 'auto', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.78rem' }}>
          <tbody>
            {rows.map(({ key, label }) => (
              <tr key={key} style={{ borderBottom: '1px solid hsl(var(--border-color))' }}>
                <td style={{ padding: '6px 10px' }}>{label}</td>
                <td style={{ padding: '6px 10px', textAlign: 'right', fontWeight: 700 }}>
                  {counts[key].toLocaleString('fr-FR')}
                </td>
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr style={{ background: 'hsl(var(--bg-tertiary))', fontWeight: 800 }}>
              <td style={{ padding: '6px 10px' }}>TOTAL</td>
              <td style={{ padding: '6px 10px', textAlign: 'right' }}>{total.toLocaleString('fr-FR')}</td>
            </tr>
          </tfoot>
        </table>
      </div>
    );
  };

  const confirmMatches = confirmText === CONFIRM_PHRASE;

  return (
    <Modal
      isOpen={isOpen}
      onClose={step === 'submitting' ? () => {} : onClose}
      title="Réinitialiser les données"
      subtitle="Action réservée au Superuser — irréversible"
      maxWidth="620px"
      closeOnBackdropClick={step !== 'submitting'}
      showCloseButton={step !== 'submitting'}
    >
      <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', padding: '18px' }}>
        {step === 'loading' && (
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'hsl(var(--text-secondary))', fontSize: '0.82rem' }}>
            <FiLoader style={{ animation: 'spin 1s linear infinite' }} /> Chargement de l’aperçu…
          </div>
        )}

        {step === 'preview-error' && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '8px', color: 'hsl(var(--color-danger))', fontSize: '0.82rem', fontWeight: 700 }}>
              <FiAlertTriangle /> {previewError}
            </div>
            <button type="button" onClick={onClose} className="btn btn-secondary" style={{ alignSelf: 'flex-start', padding: '6px 14px', fontSize: '0.78rem' }}>
              Fermer
            </button>
          </div>
        )}

        {(step === 'confirm' || step === 'submitting' || step === 'submit-error') && preview && (
          <>
            <div style={{
              padding: '10px 14px', borderRadius: 'var(--radius-sm)', fontSize: '0.78rem',
              backgroundColor: 'hsl(var(--color-danger) / 0.08)', border: '1px solid hsl(var(--color-danger) / 0.3)',
              color: 'hsl(var(--color-danger))', display: 'flex', gap: '8px', alignItems: 'flex-start',
            }}>
              <FiAlertTriangle style={{ flexShrink: 0, marginTop: '2px' }} />
              <span>
                Cette action supprime <strong>définitivement</strong> toutes les données ci-dessous.
                Les <strong>boulangeries</strong>, les <strong>utilisateurs</strong>, la <strong>configuration</strong>
                {' '}et la <strong>liste des clients</strong> sont conservés
                {preview.clients_to_reset > 0 && (
                  <> ({preview.clients_to_reset.toLocaleString('fr-FR')} fiche(s) client auront leur dette et leur
                    catégorie remises à zéro, sans être supprimées)</>
                )}.
              </span>
            </div>

            {renderCounts(preview)}

            <form onSubmit={handleSubmit} style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Tapez exactement « {CONFIRM_PHRASE} » pour confirmer
                </label>
                <input
                  type="text"
                  value={confirmText}
                  onChange={e => setConfirmText(e.target.value)}
                  className="form-input"
                  placeholder={CONFIRM_PHRASE}
                  disabled={step === 'submitting'}
                  name="reset-confirm-phrase"
                  autoComplete="off"
                  data-lpignore="true"
                  data-1p-ignore="true"
                  style={{ height: '36px', fontSize: '0.85rem', padding: '0 10px' }}
                />
                {confirmText.length > 0 && !confirmMatches && (
                  <div style={{ fontSize: '0.68rem', color: 'hsl(var(--color-danger))', marginTop: '4px', fontWeight: 700 }}>
                    La phrase ne correspond pas : tapez exactement « {CONFIRM_PHRASE} ».
                  </div>
                )}
              </div>
              <div>
                <label style={{ display: 'block', fontSize: '0.7rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
                  Votre mot de passe actuel
                </label>
                <input
                  type="password"
                  value={password}
                  onChange={e => setPassword(e.target.value)}
                  className="form-input"
                  disabled={step === 'submitting'}
                  name="reset-current-password"
                  autoComplete="new-password"
                  style={{ height: '36px', fontSize: '0.85rem', padding: '0 10px' }}
                />
              </div>

              {step === 'submit-error' && (
                <div style={{ fontSize: '0.75rem', color: 'hsl(var(--color-danger))', fontWeight: 700, display: 'flex', alignItems: 'center', gap: '6px' }}>
                  <FiAlertTriangle /> {submitError}
                </div>
              )}

              <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
                <button
                  type="button"
                  onClick={onClose}
                  disabled={step === 'submitting'}
                  className="btn btn-secondary"
                  style={{ padding: '8px 16px', fontSize: '0.8rem' }}
                >
                  Annuler
                </button>
                <button
                  type="submit"
                  disabled={!confirmMatches || !password || step === 'submitting'}
                  className="btn"
                  style={{
                    padding: '8px 16px', fontSize: '0.8rem', fontWeight: 800,
                    display: 'flex', alignItems: 'center', gap: '6px',
                    backgroundColor: 'hsl(var(--color-danger))', color: '#fff', border: 'none',
                    opacity: (!confirmMatches || !password || step === 'submitting') ? 0.5 : 1,
                    cursor: (!confirmMatches || !password || step === 'submitting') ? 'not-allowed' : 'pointer',
                  }}
                >
                  {step === 'submitting' ? <FiLoader style={{ animation: 'spin 1s linear infinite' }} /> : <FiTrash2 />}
                  {step === 'submitting' ? 'Suppression en cours…' : 'Supprimer définitivement'}
                </button>
              </div>
            </form>
          </>
        )}

        {step === 'success' && result && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div style={{
              display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem', fontWeight: 700,
              color: 'hsl(var(--color-success))',
            }}>
              <FiCheckCircle /> Réinitialisation effectuée avec succès.
            </div>
            <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))' }}>
              Décompte de ce qui a été effectivement supprimé / remis à zéro :
            </p>
            {renderCounts(result)}
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
              <button type="button" onClick={onClose} className="btn btn-primary" style={{ padding: '8px 18px', fontSize: '0.8rem' }}>
                Fermer
              </button>
            </div>
          </div>
        )}
      </div>
    </Modal>
  );
};
