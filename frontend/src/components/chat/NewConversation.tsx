import React, { useEffect, useState } from 'react';
import { FiArrowLeft, FiX } from 'react-icons/fi';
import { chatApi, ChatConversation, ChatUser } from '@/api/services';
import { chatErrorMessage, userSubtitle } from './chatUtils';

interface Props {
  onBack: () => void;
  onClose: () => void;
  onOpen: (c: ChatConversation) => void;
}

/** Annuaire des utilisateurs avec recherche ; un choix ouvre (ou crée) la conversation 1-à-1. */
export const NewConversation: React.FC<Props> = ({ onBack, onClose, onOpen }) => {
  const [search, setSearch] = useState('');
  const [users, setUsers] = useState<ChatUser[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let alive = true;
    const t = window.setTimeout(async () => {
      try {
        const { data } = await chatApi.users(search.trim() || undefined);
        if (!alive) return;
        setUsers(Array.isArray(data) ? data : data.results);
        setError(null);
      } catch (err) {
        if (alive) setError(chatErrorMessage(err, "Impossible de charger l'annuaire."));
      }
    }, 250);
    return () => { alive = false; window.clearTimeout(t); };
  }, [search]);

  const pick = async (u: ChatUser) => {
    if (busy) return;
    setBusy(true);
    try {
      const { data } = await chatApi.direct(u.id);
      onOpen(data);
    } catch (err) {
      setError(chatErrorMessage(err, 'Impossible de créer la conversation.'));
      setBusy(false);
    }
  };

  return (
    <>
      <div className="chat-header">
        <button type="button" onClick={onBack} aria-label="Retour aux conversations" className="chat-icon-btn"><FiArrowLeft aria-hidden="true" /></button>
        <h2 style={{ fontSize: '1rem', fontWeight: 800, flex: 1, margin: 0 }}>Nouvelle conversation</h2>
        <button type="button" onClick={onClose} aria-label="Fermer la messagerie" className="chat-icon-btn"><FiX aria-hidden="true" /></button>
      </div>
      <div style={{ padding: '10px 12px', borderBottom: '1px solid hsl(var(--border-color))' }}>
        <label htmlFor="chat-user-search" style={{ position: 'absolute', left: '-9999px' }}>Rechercher un utilisateur</label>
        <input
          id="chat-user-search" type="search" className="form-input" style={{ width: '100%' }} autoFocus
          placeholder="Rechercher un nom…" value={search} onChange={e => setSearch(e.target.value)}
        />
      </div>
      <div className="chat-body" aria-live="polite">
        {error && <div role="alert" className="chat-error">{error}</div>}
        {!error && users === null && <div className="chat-empty">Chargement…</div>}
        {users !== null && users.length === 0 && !error && <div className="chat-empty">Aucun utilisateur trouvé.</div>}
        {users?.map(u => (
          <button key={u.id} type="button" className="chat-row" disabled={busy} onClick={() => pick(u)}>
            <strong>{u.name}</strong>
            <span style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))' }}>{userSubtitle(u)}</span>
          </button>
        ))}
      </div>
    </>
  );
};
