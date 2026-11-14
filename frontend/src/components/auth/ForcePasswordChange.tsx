import React, { useState } from 'react';
import { coreApi } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useAuthStore } from '@/store/authStore';

/**
 * BUG-284 : écran BLOQUANT de changement du mot de passe initial.
 * Affiché tant que `user.must_change_password` est vrai ou qu'une réponse API
 * a porté le code `password_change_required`. Aucun mot de passe n'est
 * conservé hors de l'état local du formulaire ni journalisé.
 */
export const ForcePasswordChange: React.FC = () => {
  const { user, passwordChangeRequired, fetchCurrentUser, logout } = useAuthStore();
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [confirm, setConfirm] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  if (!user?.must_change_password && !passwordChangeRequired) return null;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    if (!oldPassword || !newPassword) {
      setError('Renseignez l’ancien et le nouveau mot de passe.');
      return;
    }
    if (newPassword !== confirm) {
      setError('La confirmation ne correspond pas au nouveau mot de passe.');
      return;
    }
    setLoading(true);
    try {
      await coreApi.me.changePassword({ old_password: oldPassword, new_password: newPassword });
      setOldPassword(''); setNewPassword(''); setConfirm('');
      useAuthStore.setState({ passwordChangeRequired: false });
      await fetchCurrentUser();
    } catch (err: unknown) {
      setError(getErrorDetail(err, 'Impossible de changer le mot de passe.'));
    } finally {
      setLoading(false);
    }
  };

  const field: React.CSSProperties = { width: '100%', boxSizing: 'border-box' };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-labelledby="force-pwd-title"
      style={{
        position: 'fixed', inset: 0, zIndex: 10000, display: 'flex',
        alignItems: 'center', justifyContent: 'center', padding: 12,
        backgroundColor: 'rgba(0,0,0,0.75)', overflowY: 'auto',
      }}
    >
      <form
        onSubmit={submit}
        className="glass-panel"
        style={{
          width: '100%', maxWidth: 420, maxHeight: '100%', overflowY: 'auto',
          padding: 20, display: 'flex', flexDirection: 'column', gap: 12,
          backgroundColor: 'hsl(var(--bg-card, var(--bg-primary)))',
          borderRadius: 'var(--radius-md)',
        }}
      >
        <h2 id="force-pwd-title" style={{ margin: 0, fontSize: '1.15rem' }}>Changement du mot de passe obligatoire</h2>
        <p style={{ margin: 0, fontSize: '0.85rem', color: 'hsl(var(--text-secondary))' }}>
          Pour votre sécurité, vous devez remplacer le mot de passe initial avant de continuer.
        </p>
        <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>
          Ancien mot de passe
          <input type="password" autoComplete="current-password" className="input-field" style={field}
            value={oldPassword} onChange={(e) => setOldPassword(e.target.value)} disabled={loading} />
        </label>
        <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>
          Nouveau mot de passe
          <input type="password" autoComplete="new-password" className="input-field" style={field}
            value={newPassword} onChange={(e) => setNewPassword(e.target.value)} disabled={loading} />
        </label>
        <label style={{ fontSize: '0.8rem', fontWeight: 600 }}>
          Confirmation du nouveau mot de passe
          <input type="password" autoComplete="new-password" className="input-field" style={field}
            value={confirm} onChange={(e) => setConfirm(e.target.value)} disabled={loading} />
        </label>
        {error && (
          <div role="alert" style={{
            backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)',
            borderRadius: 'var(--radius-sm)', padding: '8px 10px', fontSize: '0.8rem',
            color: 'hsl(var(--color-danger))', fontWeight: 600,
          }}>{error}</div>
        )}
        <button type="submit" className="btn btn-primary" disabled={loading} style={{ padding: '12px', minHeight: 44 }}>
          {loading ? 'Enregistrement…' : 'Changer le mot de passe'}
        </button>
        <button type="button" className="btn btn-secondary" disabled={loading}
          onClick={() => { void logout(); }} style={{ padding: '10px', minHeight: 44 }}>
          Se déconnecter
        </button>
      </form>
    </div>
  );
};
