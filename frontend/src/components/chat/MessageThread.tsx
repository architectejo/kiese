import React, { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { FiArrowLeft, FiSend, FiX } from 'react-icons/fi';
import { chatApi, ChatConversation, ChatMessage } from '@/api/services';
import { CHAT_MAX_LENGTH, CHAT_POLL_MS, chatErrorMessage, conversationTitle, formatChatTime } from './chatUtils';

interface Props {
  conversation: ChatConversation;
  onBack: () => void;
  onClose: () => void;
  onRead: () => void;
}

const PAGE_SIZE = '30';

function mergeMessages(prev: ChatMessage[], incoming: ChatMessage[]): ChatMessage[] {
  const map = new Map<string, ChatMessage>();
  prev.forEach(m => map.set(m.id, m));
  incoming.forEach(m => map.set(m.id, m));
  return Array.from(map.values()).sort((a, b) => a.created_at.localeCompare(b.created_at));
}

/** Fil de discussion : historique paginé (« Voir plus »), envoi, marquage lu, défilement. Rien n'est stocké localement. */
export const MessageThread: React.FC<Props> = ({ conversation, onBack, onClose, onRead }) => {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [hasMore, setHasMore] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  const [text, setText] = useState('');
  const [sending, setSending] = useState(false);
  const [sendError, setSendError] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);
  const lastPageRef = useRef(1);
  const stickBottomRef = useRef(true);
  const prevHeightRef = useRef<number | null>(null);
  const knownIdsRef = useRef<Set<string>>(new Set());

  const markRead = useCallback(async () => {
    try {
      await chatApi.markRead(conversation.id);
      onRead();
    } catch {
      /* non bloquant */
    }
  }, [conversation.id, onRead]);

  const loadFirst = useCallback(async (initial: boolean) => {
    try {
      const { data } = await chatApi.messages(conversation.id, { page: '1', page_size: PAGE_SIZE });
      const el = listRef.current;
      if (el) stickBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
      const fresh = data.results.filter(m => !knownIdsRef.current.has(m.id));
      const newIncoming = fresh.some(m => !m.is_mine);
      data.results.forEach(m => knownIdsRef.current.add(m.id));
      setMessages(prev => mergeMessages(prev, data.results));
      if (initial) { setHasMore(data.next != null); stickBottomRef.current = true; }
      setError(null);
      if (initial || newIncoming) markRead();
    } catch (err) {
      if (initial) setError(chatErrorMessage(err, 'Impossible de charger les messages.'));
    } finally {
      if (initial) setLoading(false);
    }
  }, [conversation.id, markRead]);

  useEffect(() => {
    loadFirst(true);
    const t = window.setInterval(() => { if (!document.hidden) loadFirst(false); }, CHAT_POLL_MS);
    return () => window.clearInterval(t);
  }, [loadFirst]);

  useLayoutEffect(() => {
    const el = listRef.current;
    if (!el) return;
    if (prevHeightRef.current !== null) {
      el.scrollTop = el.scrollHeight - prevHeightRef.current;
      prevHeightRef.current = null;
    } else if (stickBottomRef.current) {
      el.scrollTop = el.scrollHeight;
    }
  }, [messages]);

  const loadMore = async () => {
    if (loadingMore) return;
    setLoadingMore(true);
    try {
      const page = lastPageRef.current + 1;
      const { data } = await chatApi.messages(conversation.id, { page: String(page), page_size: PAGE_SIZE });
      lastPageRef.current = page;
      setHasMore(data.next != null);
      data.results.forEach(m => knownIdsRef.current.add(m.id));
      prevHeightRef.current = listRef.current?.scrollHeight ?? null;
      stickBottomRef.current = false;
      setMessages(prev => mergeMessages(prev, data.results));
    } catch (err) {
      setError(chatErrorMessage(err, "Impossible de charger l'historique."));
    } finally {
      setLoadingMore(false);
    }
  };

  const send = async (e: React.FormEvent) => {
    e.preventDefault();
    const body = text.trim();
    if (!body || sending || body.length > CHAT_MAX_LENGTH) return;
    setSending(true);
    setSendError(null);
    try {
      const { data } = await chatApi.send(conversation.id, body);
      knownIdsRef.current.add(data.id);
      stickBottomRef.current = true;
      setMessages(prev => mergeMessages(prev, [data]));
      setText('');
      onRead();
    } catch (err) {
      setSendError(chatErrorMessage(err, "Le message n'a pas pu être envoyé."));
    } finally {
      setSending(false);
    }
  };

  const remaining = CHAT_MAX_LENGTH - text.length;
  const isGroup = conversation.kind !== 'DIRECT';

  return (
    <>
      <div className="chat-header">
        <button type="button" onClick={onBack} aria-label="Retour aux conversations" className="chat-icon-btn"><FiArrowLeft aria-hidden="true" /></button>
        <h2 style={{ fontSize: '1rem', fontWeight: 800, flex: 1, margin: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {conversationTitle(conversation)}
        </h2>
        <button type="button" onClick={onClose} aria-label="Fermer la messagerie" className="chat-icon-btn"><FiX aria-hidden="true" /></button>
      </div>

      <div ref={listRef} className="chat-body" style={{ padding: '12px' }} role="log" aria-live="polite" aria-label="Messages">
        {error && <div role="alert" className="chat-error">{error}</div>}
        {loading && <div className="chat-empty">Chargement…</div>}
        {!loading && !error && messages.length === 0 && <div className="chat-empty">Aucun message. Écrivez le premier.</div>}
        {hasMore && (
          <button type="button" className="btn btn-secondary" onClick={loadMore} disabled={loadingMore}
            style={{ alignSelf: 'center', minHeight: '40px', fontSize: '0.8rem', marginBottom: '8px' }}>
            {loadingMore ? 'Chargement…' : 'Voir plus'}
          </button>
        )}
        {messages.map(m => (
          <div key={m.id} style={{
            alignSelf: m.is_mine ? 'flex-end' : 'flex-start', maxWidth: '85%', marginBottom: '8px',
            padding: '8px 12px', borderRadius: '12px',
            background: m.is_mine ? 'hsl(var(--accent-color) / 0.18)' : 'hsl(var(--bg-tertiary))',
            border: '1px solid hsl(var(--border-color))',
          }}>
            {!m.is_mine && isGroup && (
              <div style={{ fontSize: '0.7rem', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{m.sender_name}</div>
            )}
            <div style={{ fontSize: '0.9rem', whiteSpace: 'pre-wrap', overflowWrap: 'anywhere' }}>{m.body}</div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))', textAlign: 'right' }}>{formatChatTime(m.created_at)}</div>
          </div>
        ))}
      </div>

      <form onSubmit={send} className="chat-composer">
        {sendError && <div role="alert" className="chat-error" style={{ margin: 0 }}>{sendError}</div>}
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-end' }}>
          <label htmlFor="chat-message-input" style={{ position: 'absolute', left: '-9999px' }}>Votre message</label>
          <textarea
            id="chat-message-input" className="form-input" rows={2} value={text} maxLength={CHAT_MAX_LENGTH + 200}
            placeholder="Votre message…" style={{ flex: 1, resize: 'none' }}
            onChange={e => setText(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); e.currentTarget.form?.requestSubmit(); } }}
          />
          <button type="submit" className="btn btn-primary" aria-label="Envoyer"
            disabled={sending || !text.trim() || remaining < 0} style={{ minHeight: '44px', minWidth: '44px' }}>
            <FiSend aria-hidden="true" />
          </button>
        </div>
        <div style={{ fontSize: '0.7rem', textAlign: 'right', fontWeight: 700,
          color: remaining < 0 ? 'hsl(var(--color-danger))' : 'hsl(var(--text-muted))' }}>
          {text.length.toLocaleString('fr-FR')} / {CHAT_MAX_LENGTH.toLocaleString('fr-FR')}
        </div>
      </form>
    </>
  );
};
