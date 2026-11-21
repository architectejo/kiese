import React from 'react';
import type { BakeryNode } from '@/api/services';

interface ClientsBulkBarProps {
  selectedClientIds: Set<string>;
  setSelectedClientIds: (ids: Set<string>) => void;
  nodesList: BakeryNode[];
  bulkMoveTarget: string;
  setBulkMoveTarget: (v: string) => void;
  bulkLoading: boolean;
  bulkMsgBar: string | null;
  handleBulkMove: () => void | Promise<void>;
  handleBulkDelete: () => void | Promise<void>;
}

/** Barre d'actions groupées (déplacer / supprimer) — Direction centrale uniquement. */
export const ClientsBulkBar: React.FC<ClientsBulkBarProps> = ({
  selectedClientIds, setSelectedClientIds, nodesList, bulkMoveTarget, setBulkMoveTarget, bulkLoading,
  bulkMsgBar, handleBulkMove, handleBulkDelete,
}) => {
  return (
        <div className="glass-card animate-fade-in" style={{ padding: '10px 14px', display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
          <span style={{ fontSize: '0.75rem', fontWeight: 700 }}>{selectedClientIds.size} client(s) sélectionné(s)</span>
          <select
            value={bulkMoveTarget}
            onChange={e => setBulkMoveTarget(e.target.value)}
            className="form-input"
            style={{ height: '32px', fontSize: '0.75rem', width: 'auto', minWidth: '200px' }}
          >
            <option value="">— Déplacer vers —</option>
            {nodesList.map(n => (
              <option key={n.id} value={n.id}>{n.code} — {n.name}</option>
            ))}
          </select>
          <button
            className="btn btn-secondary"
            disabled={!bulkMoveTarget || bulkLoading}
            onClick={handleBulkMove}
            style={{ height: '32px', fontSize: '0.75rem', padding: '0 12px' }}
          >
            {bulkLoading ? '…' : 'Déplacer'}
          </button>
          <button
            className="btn btn-secondary"
            disabled={bulkLoading}
            onClick={handleBulkDelete}
            style={{ height: '32px', fontSize: '0.75rem', padding: '0 12px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.3)' }}
          >
            Supprimer
          </button>
          <button
            className="btn btn-secondary"
            onClick={() => setSelectedClientIds(new Set())}
            style={{ height: '32px', fontSize: '0.75rem', padding: '0 12px' }}
          >
            Annuler la sélection
          </button>
          {bulkMsgBar && <span style={{ fontSize: '0.72rem', color: 'hsl(var(--text-secondary))' }}>{bulkMsgBar}</span>}
        </div>
  );
};
