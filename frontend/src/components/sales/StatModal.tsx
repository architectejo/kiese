import React from 'react';
import type { QueueItem } from './salesTypes';
import { Modal } from '@/components/shared/Modal';

export interface StatModalProps {
  queue: QueueItem[];
  queueComplete: boolean;
  queueProgress: { loaded: number; total: number | null };
  statModal: 'livrees' | 'total' | null;
  setStatModal: React.Dispatch<React.SetStateAction<'livrees' | 'total' | null>>;
  queueProgressLabel: string;
  livrésCount: number;
  totalFacture: number;
}

export const StatModal: React.FC<StatModalProps> = ({ queue, queueComplete, queueProgress, statModal, setStatModal, queueProgressLabel, livrésCount, totalFacture }) => {
  return (
      <Modal
        isOpen={!!statModal}
        onClose={() => setStatModal(null)}
        title={statModal === 'livrees' ? "Factures Livrées Aujourd'hui" : statModal === 'total' ? 'Total Facturé Aujourd\'hui' : undefined}
        subtitle={
          statModal === 'livrees' ? (queueComplete ? `${livrésCount} facture(s) distribuée(s) avec succès.` : `Chargement en cours (${queueProgress.loaded}/${queueProgress.total ?? '…'}) — liste partielle.`)
          : statModal === 'total' ? (queueComplete ? 'Cumul des factures En attente et Livrées de la journée.' : `Chargement en cours (${queueProgress.loaded}/${queueProgress.total ?? '…'}) — liste partielle.`)
          : undefined
        }
        maxWidth="620px"
      >
            {statModal === 'livrees' && (
              <>
                <div style={{ overflowY: 'auto', flex: 1 }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.66rem', textTransform: 'uppercase' }}>
                        <th>N° Reçu</th>
                        <th>Client</th>
                        <th>Heure</th>
                        <th style={{ textAlign: 'right' }}>Montant</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.74rem' }}>
                      {queue.filter(o => o.status === 'Livré').length === 0 ? (
                        <tr><td colSpan={4} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune livraison aujourd'hui.</td></tr>
                      ) : queue.filter(o => o.status === 'Livré').map(o => (
                        <tr key={o.id}>
                          <td><span className="badge badge-info" style={{ fontSize: '0.6rem' }}>{o.id}</span></td>
                          <td style={{ fontWeight: 700 }}>{o.clientName}</td>
                          <td style={{ color: 'hsl(var(--text-secondary))', fontSize: '0.68rem' }}>{o.timeAdded}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-success))' }}>{o.totalValue.toLocaleString('fr-FR')} FC</td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              </>
            )}

            {statModal === 'total' && (
              <>
                <div style={{ overflowY: 'auto', flex: 1 }}>
                  <table className="premium-table">
                    <thead>
                      <tr style={{ fontSize: '0.66rem', textTransform: 'uppercase' }}>
                        <th>N° Reçu</th>
                        <th>Client</th>
                        <th>Statut</th>
                        <th>Mode</th>
                        <th style={{ textAlign: 'right' }}>Montant</th>
                      </tr>
                    </thead>
                    <tbody style={{ fontSize: '0.74rem' }}>
                      {queue.length === 0 ? (
                        <tr><td colSpan={5} style={{ textAlign: 'center', padding: '16px', color: 'hsl(var(--text-muted))' }}>Aucune facture aujourd'hui.</td></tr>
                      ) : queue.map(o => (
                        <tr key={o.id}>
                          <td><span className="badge badge-info" style={{ fontSize: '0.6rem' }}>{o.id}</span></td>
                          <td style={{ fontWeight: 700 }}>{o.clientName}</td>
                          <td>
                            <span className={`badge ${o.status === 'Livré' ? 'badge-success' : o.status === 'Non servi' ? 'badge-secondary' : 'badge-warning'}`} style={{ fontSize: '0.58rem' }}>{o.status.toUpperCase()}</span>
                          </td>
                          <td style={{ fontSize: '0.68rem', color: 'hsl(var(--text-secondary))' }}>{o.paymentType === 'CASH' ? 'CASH' : 'CRÉDIT'}</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--accent-color))' }}>{o.isNotServed ? '—' : `${o.totalValue.toLocaleString('fr-FR')} FC`}</td>
                        </tr>
                      ))}
                    </tbody>
                    {queue.length > 0 && (
                      <tfoot>
                        <tr style={{ fontSize: '0.78rem', borderTop: '2px solid hsl(var(--border-color))' }}>
                          <td colSpan={4} style={{ fontWeight: 800, textAlign: 'right', padding: '8px 0' }}>Total :</td>
                          <td style={{ textAlign: 'right', fontWeight: 800, color: 'hsl(var(--color-info))', padding: '8px 0' }}>{queueComplete ? `${totalFacture.toLocaleString('fr-FR')} FC` : queueProgressLabel}</td>
                        </tr>
                      </tfoot>
                    )}
                  </table>
                </div>
              </>
            )}
      </Modal>
  );
};
