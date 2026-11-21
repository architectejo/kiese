import React from 'react';
import { BackupManager } from '@/components/admin/BackupManager';
import { useAuthStore } from '@/store/authStore';

/**
 * Écran « Administration » (BUG-074) : pour l'instant centré sur la
 * sauvegarde/restauration locale desktop. La logique est entièrement dans
 * `BackupManager` pour garder cette page légère si d'autres sections
 * d'administration locale s'y ajoutent plus tard.
 */
export const Administration: React.FC = () => {
  // BUG-405 : défense en profondeur, la route est déjà limitée ADMIN/DIRECTION
  // dans App.tsx ; la page n'affiche jamais les actions de restauration sinon.
  const { user } = useAuthStore();
  const allowed = !!user && (user.is_superuser || ['ADMIN', 'DIRECTION'].includes(user.role));
  if (!allowed) {
    return (
      <div role="alert" style={{ padding: '24px', fontWeight: 600 }}>
        Accès refusé : la sauvegarde et la restauration sont réservées à l'administration et à la direction.
      </div>
    );
  }
  return <BackupManager />;
};
