import React, { useEffect, useState } from 'react';
import { FiInfo, FiAlertTriangle } from 'react-icons/fi';
import { coreApi, SystemNotificationItem } from '@/api/services';

// BUG-1119 (remarque.md l.516, BUG-1074) : la clôture automatique des fournées à l'heure de clôture
// est déclenchée côté serveur (shift-end-status) et signalée par une notification
// « Fournée clôturée automatiquement — <code> <date> ». Ce bandeau l'affiche en clair sur l'écran de
// clôture journalière, pour la boulangerie et le jour consultés, tant que la notification n'est pas lue.
// Affichage seul : aucune règle métier ici.

const AUTO_CLOSED_PREFIX = 'Fournée clôturée automatiquement';
const AUTO_CLOSE_SKIPPED_PREFIX = 'Fournée non clôturée automatiquement';

export interface AutoClosedDayBannerProps {
  nodeCode: string;
  /** Jour consulté (AAAA-MM-JJ). */
  date: string;
}

export const AutoClosedDayBanner: React.FC<AutoClosedDayBannerProps> = ({ nodeCode, date }) => {
  const [items, setItems] = useState<SystemNotificationItem[]>([]);

  useEffect(() => {
    if (!nodeCode || !date) { setItems([]); return; }
    let cancelled = false;
    coreApi.notifications.page({ page: '1', page_size: '50' })
      .then(res => {
        if (cancelled) return;
        const suffix = ` — ${nodeCode} ${date}`;
        setItems((res.data.results ?? []).filter(n =>
          (n.title === `${AUTO_CLOSED_PREFIX}${suffix}` || n.title === `${AUTO_CLOSE_SKIPPED_PREFIX}${suffix}`),
        ));
      })
      .catch(() => { if (!cancelled) setItems([]); }); // non bloquant : simple information
    return () => { cancelled = true; };
  }, [nodeCode, date]);

  if (items.length === 0) return null;

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
      {items.map(n => {
        const warn = n.severity === 'WARNING' || n.title.startsWith(AUTO_CLOSE_SKIPPED_PREFIX);
        const color = warn ? 'var(--color-warning)' : 'var(--color-info, var(--accent-color))';
        return (
          <div key={n.id} role="status" style={{
            display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '0.78rem', lineHeight: 1.4,
            overflowWrap: 'anywhere', padding: '10px 12px', borderRadius: 'var(--radius-sm)',
            color: `hsl(${color})`, backgroundColor: `hsl(${color} / 0.1)`, border: `1px solid hsl(${color} / 0.4)`,
          }}>
            {warn ? <FiAlertTriangle style={{ flexShrink: 0, marginTop: '2px' }} /> : <FiInfo style={{ flexShrink: 0, marginTop: '2px' }} />}
            <span><strong>{n.title.split(' — ')[0]}.</strong> {n.message}</span>
          </div>
        );
      })}
    </div>
  );
};
