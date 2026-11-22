import React from 'react';
import type { ServedLinePayload } from '@/api/services';
import type { ReceiptData } from '@/components/shared/ThermalReceipt';
import type { QueueItem } from './salesTypes';
import { Modal } from '@/components/shared/Modal';
import { QueueCard } from './QueueCard';

export interface QueueListModalProps {
  queue: QueueItem[];
  queueComplete: boolean;
  queueProgress: { loaded: number; total: number | null };
  deliveryError: { id: string; message: string } | null;
  setReceipt: React.Dispatch<React.SetStateAction<ReceiptData | null>>;
  receiptCache: Record<string, ReceiptData>;
  queueModalOpen: boolean;
  setQueueModalOpen: React.Dispatch<React.SetStateAction<boolean>>;
  canAdjustInvoice: boolean;
  openAdjustModal: (item: QueueItem) => void;
  cancelInvoice: (item: QueueItem) => Promise<void>;
  markNotServed: (item: QueueItem, reason: string) => Promise<void>;
  handleDeliverClick: (item: QueueItem, lines?: ServedLinePayload[]) => void;
}

export const QueueListModal: React.FC<QueueListModalProps> = ({ queue, queueComplete, queueProgress, deliveryError, setReceipt, receiptCache, queueModalOpen, setQueueModalOpen, canAdjustInvoice, openAdjustModal, cancelInvoice, markNotServed, handleDeliverClick }) => {
  return (
      <Modal
        isOpen={queueModalOpen}
        onClose={() => setQueueModalOpen(false)}
        title="File des Livraisons — Liste Complète"
        subtitle={queueComplete ? `${queue.length} facture(s) du jour.` : `Chargement en cours (${queueProgress.loaded}/${queueProgress.total ?? '…'}) — liste partielle.`}
        maxWidth="620px"
      >
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              {queue.map(item => <QueueCard key={item.id} item={item} detailed queue={queue} deliveryError={deliveryError} setReceipt={setReceipt} receiptCache={receiptCache} canAdjustInvoice={canAdjustInvoice} openAdjustModal={openAdjustModal} cancelInvoice={cancelInvoice} markNotServed={markNotServed} handleDeliverClick={handleDeliverClick} />)}
            </div>
      </Modal>
  );
};
