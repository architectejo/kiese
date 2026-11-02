import React from 'react';
import { BackupManager } from '@/components/admin/BackupManager';

/**
 * Écran « Administration » (BUG-074) : pour l'instant centré sur la
 * sauvegarde/restauration locale desktop. La logique est entièrement dans
 * `BackupManager` pour garder cette page légère si d'autres sections
 * d'administration locale s'y ajoutent plus tard.
 */
export const Administration: React.FC = () => {
  return <BackupManager />;
};
