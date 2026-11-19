import React, { useCallback, useEffect, useState } from 'react';
import { FiMessageSquare } from 'react-icons/fi';
import { chatApi } from '@/api/services';
import { CHAT_POLL_MS } from './chatUtils';
import { ChatPanel } from './ChatPanel';

/** Icône de messagerie de l'en-tête : badge de non-lus (sondage 8 s, en pause si l'onglet est masqué) + panneau. */
export const ChatButton: React.FC = () => {
  const [open, setOpen] = useState(false);
  const [unread, setUnread] = useState(0);

  const refresh = useCallback(async () => {
    try {
      const { data } = await chatApi.unreadCount();
      setUnread(data.unread_count);
    } catch {
      /* silencieux : le badge garde sa dernière valeur */
    }
  }, []);

  useEffect(() => {
    let timer: number | undefined;
    const start = () => {
      if (timer !== undefined) return;
      refresh();
      timer = window.setInterval(refresh, CHAT_POLL_MS);
    };
    const stop = () => {
      if (timer !== undefined) { window.clearInterval(timer); timer = undefined; }
    };
    const onVisibility = () => (document.hidden ? stop() : start());
    if (!document.hidden) start();
    document.addEventListener('visibilitychange', onVisibility);
    return () => { stop(); document.removeEventListener('visibilitychange', onVisibility); };
  }, [refresh]);

  const close = useCallback(() => setOpen(false), []);
  const label = unread > 0 ? `Messagerie, ${unread} message(s) non lu(s)` : 'Messagerie';

  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-label={label}
        aria-haspopup="dialog"
        aria-expanded={open}
        title="Messagerie"
        style={{
          border: '1px solid hsl(var(--border-color))', background: 'hsl(var(--bg-tertiary))',
          color: unread > 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
          padding: '8px', minWidth: '40px', minHeight: '40px', borderRadius: 'var(--radius-md)', cursor: 'pointer',
          display: 'flex', alignItems: 'center', justifyContent: 'center', fontSize: '1.15rem', position: 'relative',
        }}
      >
        <FiMessageSquare aria-hidden="true" />
        {unread > 0 && (
          <span aria-hidden="true" style={{
            position: 'absolute', top: '-6px', right: '-6px', minWidth: '18px', height: '18px', padding: '0 4px',
            backgroundColor: 'hsl(var(--color-danger))', color: '#fff', fontSize: '0.65rem', fontWeight: 900,
            borderRadius: '9px', display: 'flex', alignItems: 'center', justifyContent: 'center',
          }}>
            {unread > 99 ? '99+' : unread}
          </span>
        )}
      </button>
      {open && <ChatPanel onClose={close} onUnreadChanged={refresh} />}
    </>
  );
};
