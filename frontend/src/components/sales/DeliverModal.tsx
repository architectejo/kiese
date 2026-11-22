import React from 'react';
import type { ServedLinePayload } from '@/api/services';
import { FiPrinter } from 'react-icons/fi';
import type { QueueItem } from './salesTypes';
import { Modal } from '@/components/shared/Modal';

export interface DeliverModalProps {
  deliveryError: { id: string; message: string } | null;
  deliverModalItem: QueueItem | null;
  setDeliverModalItem: React.Dispatch<React.SetStateAction<QueueItem | null>>;
  deliverDate: string;
  setDeliverDate: React.Dispatch<React.SetStateAction<string>>;
  deliverLines: ServedLinePayload[] | undefined;
  setDeliverLines: React.Dispatch<React.SetStateAction<ServedLinePayload[] | undefined>>;
  workDate: string;
  confirmDelivery: (item: QueueItem, deliveredAt?: string, servedLines?: ServedLinePayload[]) => Promise<void>;
}

export const DeliverModal: React.FC<DeliverModalProps> = ({ deliveryError, deliverModalItem, setDeliverModalItem, deliverDate, setDeliverDate, deliverLines, setDeliverLines, workDate, confirmDelivery }) => {
  return (
      <Modal
        isOpen={!!deliverModalItem}
        onClose={() => { setDeliverModalItem(null); setDeliverDate(''); setDeliverLines(undefined); }}
        title="Confirmer la livraison"
        subtitle={deliverModalItem ? `Facture ${deliverModalItem.id} — ${deliverModalItem.clientName}` : undefined}
        maxWidth="420px"
      >
        {deliverModalItem && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '12px' }}>
            <div>
              <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '2px', textTransform: 'uppercase' }}>
                Date de livraison (optionnel)
              </label>
              <span style={{ display: 'block', fontSize: '0.6rem', color: 'hsl(var(--text-muted))', marginBottom: '4px' }}>
                Laisser vide = aujourd'hui. Jamais une date future.
              </span>
              <input
                type="date"
                max={workDate}
                value={deliverDate}
                onChange={e => setDeliverDate(e.target.value)}
                className="form-input"
                style={{ fontSize: '0.78rem', height: '32px', padding: '0 8px' }}
              />
            </div>
            {deliveryError && deliveryError.id === deliverModalItem._apiId && (
              <div style={{ backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '6px 9px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
                {deliveryError.message}
              </div>
            )}
            <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '8px' }}>
              <button
                type="button"
                onClick={() => { setDeliverModalItem(null); setDeliverDate(''); setDeliverLines(undefined); }}
                className="btn btn-secondary"
                style={{ padding: '7px 14px', fontSize: '0.75rem' }}
              >
                Annuler
              </button>
              <button
                type="button"
                onClick={() => {
                  const todayStr = workDate;
                  const d = deliverDate && deliverDate !== todayStr ? deliverDate : undefined;
                  confirmDelivery(deliverModalItem, d, deliverLines);
                }}
                className="btn btn-primary"
                style={{ padding: '7px 14px', fontSize: '0.75rem', display: 'flex', alignItems: 'center', gap: '6px' }}
              >
                <FiPrinter /> Confirmer & imprimer
              </button>
            </div>
          </div>
        )}
      </Modal>
  );
};
