import React from 'react';
import { FiLock } from 'react-icons/fi';
import { useClosureStatusStore } from '@/store/closureStatusStore';

// BUG-973 : bannière affichée sur les pages de vente quand la clôture du jour attend la
// validation de la direction. Les boutons de création sont désactivés par la page (`useSalesBlocked`) ;
// la règle reste appliquée côté serveur (403).
export const ClosureBlockBanner: React.FC = () => {
  const blocked = useClosureStatusStore((s) => !!s.status?.blocked);
  const reason = useClosureStatusStore((s) => s.status?.reason ?? '');
  const hour = useClosureStatusStore((s) => s.status?.closure_hour ?? null);
  if (!blocked) return null;
  return (
    <div role="alert" style={{
      display: 'flex', alignItems: 'flex-start', gap: '10px', padding: '12px 14px', marginBottom: '12px',
      borderRadius: 'var(--radius-sm)', border: '1px solid hsl(var(--color-danger) / 0.5)',
      backgroundColor: 'hsl(var(--color-danger) / 0.1)', color: 'hsl(var(--color-danger))', lineHeight: 1.4,
    }}>
      <FiLock style={{ flexShrink: 0, marginTop: '2px' }} />
      <div style={{ fontSize: '0.85rem' }}>
        <strong>Ventes bloquées{hour ? ` depuis ${hour.replace(':', 'h')}` : ''}</strong>
        <div>{reason || 'Clôture du jour en attente de validation par la direction.'}</div>
      </div>
    </div>
  );
};
