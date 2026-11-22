import React from 'react';
import type { ServedLinePayload } from '@/api/services';
import { FiTruck, FiChevronRight } from 'react-icons/fi';
import type { ReceiptData } from '@/components/shared/ThermalReceipt';
import type { QueueItem } from './salesTypes';
import { QueueCard } from './QueueCard';

export interface DeliveryQueueCardProps {
  queue: QueueItem[];
  isLoading: boolean;
  queueComplete: boolean;
  queueProgress: { loaded: number; total: number | null };
  queueError: string | null;
  deliveryError: { id: string; message: string } | null;
  setReceipt: React.Dispatch<React.SetStateAction<ReceiptData | null>>;
  receiptCache: Record<string, ReceiptData>;
  setQueueModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  canAdjustInvoice: boolean;
  loadData: (isRetry?: boolean) => Promise<void>;
  openAdjustModal: (item: QueueItem) => void;
  cancelInvoice: (item: QueueItem) => Promise<void>;
  markNotServed: (item: QueueItem, reason: string) => Promise<void>;
  handleDeliverClick: (item: QueueItem, lines?: ServedLinePayload[]) => void;
}

export const DeliveryQueueCard: React.FC<DeliveryQueueCardProps> = ({ queue, isLoading, queueComplete, queueProgress, queueError, deliveryError, setReceipt, receiptCache, setQueueModalOpen, canAdjustInvoice, loadData, openAdjustModal, cancelInvoice, markNotServed, handleDeliverClick }) => {
  return (
        <div className="glass-card" style={{ padding: '16px' }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '14px' }}>
            <h2 style={{ fontSize: '0.9rem', fontWeight: 800, display: 'flex', alignItems: 'center', gap: '6px' }}>
              <FiTruck style={{ color: 'hsl(var(--color-info))' }} />
              File des Livraisons — Confirmation & Impression Reçu
            </h2>
            {queue.length > 3 && (
              <button onClick={() => setQueueModalOpen(true)} className="btn btn-secondary" style={{ padding: '5px 10px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', whiteSpace: 'nowrap' }}>
                <span>Voir plus</span>
                <FiChevronRight size={12} />
              </button>
            )}
          </div>

          {isLoading && <div style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-secondary))', fontSize: '0.8rem' }}>Chargement...</div>}
          {queueError && (
            <div role="alert" style={{ textAlign: 'center', padding: '8px', color: 'hsl(var(--color-danger))', fontSize: '0.75rem' }}>
              {queueError}{' '}
              <button onClick={() => { void loadData(); }} className="btn btn-secondary" style={{ padding: '2px 8px', fontSize: '0.65rem' }}>Réessayer</button>
            </div>
          )}
          {!isLoading && !queueComplete && !queueError && (
            <div role="status" style={{ textAlign: 'center', padding: '4px', color: 'hsl(var(--text-muted))', fontSize: '0.68rem' }}>
              {queueProgress.loaded} / {queueProgress.total ?? '…'} factures chargées…
            </div>
          )}

          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            {queue.slice(0, 3).map(item => <QueueCard key={item.id} item={item} queue={queue} deliveryError={deliveryError} setReceipt={setReceipt} receiptCache={receiptCache} canAdjustInvoice={canAdjustInvoice} openAdjustModal={openAdjustModal} cancelInvoice={cancelInvoice} markNotServed={markNotServed} handleDeliverClick={handleDeliverClick} />)}

            {!isLoading && queue.length === 0 && (
              <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.78rem' }}>
                <FiTruck style={{ fontSize: '1.8rem', opacity: 0.2, display: 'block', margin: '0 auto 8px' }} />
                Aucune facture en attente de livraison.
              </div>
            )}
          </div>
        </div>
  );
};
