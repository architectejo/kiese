import React, { useCallback, useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { FiX, FiPlus, FiUsers, FiShield, FiMessageSquare } from 'react-icons/fi';
import { chatApi, ChatConversation } from '@/api/services';
import {
  CHAT_POLL_MS, chatErrorMessage, conversationTitle, formatChatTime, isForbidden,
} from './chatUtils';
import { MessageThread } from './MessageThread';
import { NewConversation } from './NewConversation';

interface Props {
  onClose: () => void;
  onUnreadChanged: () => void;
}

type View = { type: 'list' } | { type: 'new' } | { type: 'thread'; conversation: ChatConversation };

export const ChatPanel: React.FC<Props> = ({ onClose, onUnreadChanged }) => {
  const [view, setView] = useState<View>({ type: 'list' });
  const [conversations, setConversations] = useState<ChatConversation[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Fils de groupe : masqués si l'API répond 403.
  const [nodeThread, setNodeThread] = useState<ChatConversation | null>(null);
  const [directionThread, setDirectionThread] = useState<ChatConversation | null>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  const load = useCallback(async () => {
    try {
      const { data } = await chatApi.conversations();
      setConversations(data);
      setError(null);
      // Garde les raccourcis (non-lus) synchronisés avec la liste.
      setNodeThread(prev => (prev ? data.find(c => c.id === prev.id) ?? prev : prev));
      setDirectionThread(prev => (prev ? data.find(c => c.id === prev.id) ?? prev : prev));
    } catch (err) {
      setError(chatErrorMessage(err, 'Impossible de charger les conversations.'));
    }
  }, []);

  useEffect(() => {
    load();
    const t = window.setInterval(() => { if (!document.hidden) load(); }, CHAT_POLL_MS);
    return () => window.clearInterval(t);
  }, [load]);

  useEffect(() => {
    let alive = true;
    chatApi.nodeThread()
      .then(r => { if (alive) setNodeThread(r.data); })
      .catch((e: unknown) => { if (!isForbidden(e)) console.error(e); });
    chatApi.directionThread()
      .then(r => { if (alive) setDirectionThread(r.data); })
      .catch((e: unknown) => { if (!isForbidden(e)) console.error(e); });
    return () => { alive = false; };
  }, []);

  useEffect(() => {
    const prev = document.activeElement as HTMLElement | null;
    panelRef.current?.focus();
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('keydown', onKey); prev?.focus?.(); };
  }, [onClose]);

  const openThread = (c: ChatConversation) => setView({ type: 'thread', conversation: c });
  const backToList = () => { setView({ type: 'list' }); load(); onUnreadChanged(); };

  const shortcutStyle: React.CSSProperties = {
    flex: 1, minHeight: '44px', display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
    fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer', padding: '6px 8px',
    background: 'hsl(var(--bg-tertiary))', border: '1px solid hsl(var(--border-color))',
    borderRadius: 'var(--radius-md)', color: 'hsl(var(--text-primary))',
  };

  return createPortal(
    <div
      ref={panelRef}
      role="dialog"
      aria-modal="false"
      aria-label="Messagerie"
      tabIndex={-1}
      className="chat-panel"
    >
      {view.type === 'thread' ? (
        <MessageThread conversation={view.conversation} onBack={backToList} onClose={onClose} onRead={onUnreadChanged} />
      ) : view.type === 'new' ? (
        <NewConversation onBack={() => setView({ type: 'list' })} onClose={onClose} onOpen={openThread} />
      ) : (
        <>
          <div className="chat-header">
            <h2 style={{ fontSize: '1rem', fontWeight: 800, flex: 1, margin: 0 }}>Messagerie</h2>
            <button type="button" className="btn btn-primary" onClick={() => setView({ type: 'new' })}
              style={{ minHeight: '40px', padding: '6px 12px', fontSize: '0.8rem' }}>
              <FiPlus aria-hidden="true" /> Nouvelle
            </button>
            <button type="button" onClick={onClose} aria-label="Fermer la messagerie" className="chat-icon-btn">
              <FiX aria-hidden="true" />
            </button>
          </div>

          {(nodeThread || directionThread) && (
            <div style={{ display: 'flex', gap: '8px', padding: '10px 12px', borderBottom: '1px solid hsl(var(--border-color))' }}>
              {nodeThread && (
                <button type="button" style={shortcutStyle} onClick={() => openThread(nodeThread)}>
                  <FiUsers aria-hidden="true" /> Ma boulangerie
                  {nodeThread.unread_count > 0 && <span className="chat-badge">{nodeThread.unread_count}</span>}
                </button>
              )}
              {directionThread && (
                <button type="button" style={shortcutStyle} onClick={() => openThread(directionThread)}>
                  <FiShield aria-hidden="true" /> Direction
                  {directionThread.unread_count > 0 && <span className="chat-badge">{directionThread.unread_count}</span>}
                </button>
              )}
            </div>
          )}

          <div className="chat-body" aria-live="polite">
            {error && <div role="alert" className="chat-error">{error}</div>}
            {!error && conversations === null && <div className="chat-empty">Chargement…</div>}
            {conversations !== null && conversations.length === 0 && !error && (
              <div className="chat-empty">
                <FiMessageSquare aria-hidden="true" style={{ fontSize: '1.6rem' }} /><br />
                Aucune conversation. Utilisez « Nouvelle » pour écrire à un collègue.
              </div>
            )}
            {conversations?.map(c => (
              <button key={c.id} type="button" className="chat-row" onClick={() => openThread(c)}>
                <span style={{ display: 'flex', justifyContent: 'space-between', gap: '8px' }}>
                  <strong style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{conversationTitle(c)}</strong>
                  <span style={{ fontSize: '0.7rem', color: 'hsl(var(--text-muted))', flexShrink: 0 }}>{formatChatTime(c.last_message_at)}</span>
                </span>
                <span style={{ display: 'flex', justifyContent: 'space-between', gap: '8px', alignItems: 'center' }}>
                  <span style={{ fontSize: '0.8rem', color: 'hsl(var(--text-secondary))', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {c.last_message
                      ? `${c.last_message.is_mine ? 'Vous' : c.last_message.sender_name} : ${c.last_message.body}`
                      : 'Aucun message'}
                  </span>
                  {c.unread_count > 0 && (
                    <span className="chat-badge" aria-label={`${c.unread_count} non lu(s)`}>{c.unread_count}</span>
                  )}
                </span>
              </button>
            ))}
          </div>
        </>
      )}
    </div>,
    document.body,
  );
};
