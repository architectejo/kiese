import React from 'react';
import type { ServedLinePayload } from '@/api/services';
import { FiCheckCircle, FiX, FiPrinter } from 'react-icons/fi';
import type { ReceiptData } from '@/components/shared/ThermalReceipt';
import type { QueueItem } from './salesTypes';
import { PendingDeliveryActions } from './PendingDeliveryActions';

export interface QueueCardProps {
  item: QueueItem;
  detailed?: boolean;
  queue: QueueItem[];
  deliveryError: { id: string; message: string } | null;
  setReceipt: React.Dispatch<React.SetStateAction<ReceiptData | null>>;
  receiptCache: Record<string, ReceiptData>;
  canAdjustInvoice: boolean;
  openAdjustModal: (item: QueueItem) => void;
  cancelInvoice: (item: QueueItem) => Promise<void>;
  markNotServed: (item: QueueItem, reason: string) => Promise<void>;
  handleDeliverClick: (item: QueueItem, lines?: ServedLinePayload[]) => void;
}

export const QueueCard: React.FC<QueueCardProps> = ({ item, detailed = false, queue, deliveryError, setReceipt, receiptCache, canAdjustInvoice, openAdjustModal, cancelInvoice, markNotServed, handleDeliverClick }) => {
    // BUG-177 : une NS n'est jamais « à livrer » ; elle est affichée comme enregistrée.
    const isNonServi = item.isNonServi;
    const isNotServed = item.isNotServed;
    const isPending = item.status === 'En attente' && !isNonServi && !isNotServed;
    const avatarColor = `hsl(${(item.clientName.charCodeAt(0) * 37 + (item.clientCode.charCodeAt(3) || 0) * 13) % 360}, 58%, 38%)`;
    return (
      <div key={item.id} style={{
        borderRadius: 'var(--radius-sm)',
        border: `1px solid hsl(var(--${isPending ? 'color-warning' : 'border-color'}) / ${isPending ? '0.5' : '1'})`,
        backgroundColor: isPending ? 'hsl(var(--color-warning) / 0.04)' : 'hsl(var(--bg-secondary))',
        overflow: 'hidden',
        flexShrink: 0,
      }}>
        {/* Card header — receipt + badge */}
        <div style={{ padding: '8px 12px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid hsl(var(--border-color) / 0.5)`, backgroundColor: 'hsl(var(--bg-tertiary) / 0.5)' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexWrap: 'wrap' }}>
            <span style={{ fontWeight: 800, color: 'hsl(var(--accent-color))', fontSize: '0.72rem' }}>{item.id}</span>
            {item.isRepayment && (
              <span className="badge badge-info" style={{ fontSize: '0.54rem', background: 'hsl(210,80%,50%)', color: '#fff' }}>REMB</span>
            )}
            {!item.isRepayment && item.isSoldee && (
              <span className="badge badge-warning" style={{ fontSize: '0.54rem' }}>SOLDÉE</span>
            )}
            {!item.isRepayment && !item.isSoldee && (
              <span className={`badge ${item.paymentType === 'CASH' ? 'badge-success' : 'badge-secondary'}`} style={{ fontSize: '0.54rem' }}>
                {item.paymentType === 'CASH' ? 'CASH' : 'CRÉDIT'}
              </span>
            )}
            {item.specialCode && (
              <span className="badge badge-info" style={{ fontSize: '0.52rem', opacity: 0.85 }}>{item.specialCode}</span>
            )}
            {/* BUG-109 : trace d'ajustement — badge + référence vers la facture d'origine */}
            {item.isAdjustment && (
              <span
                className="badge"
                title={`Ajustement de la facture ${queue.find(o => o._apiId === item.adjustsId)?.id || item.adjustsId}`}
                style={{ fontSize: '0.52rem', background: item.adjustmentSign === -1 ? 'hsl(0,70%,45%)' : 'hsl(150,60%,35%)', color: '#fff' }}
              >
                AJUST. {item.adjustmentSign === -1 ? '−' : '+'} · réf {queue.find(o => o._apiId === item.adjustsId)?.id || item.adjustsId}
              </span>
            )}
            {!item.isAdjustment && item.adjustmentsCount > 0 && (
              <span className="badge badge-info" style={{ fontSize: '0.5rem' }}>
                {item.adjustmentsCount} ajustement{item.adjustmentsCount > 1 ? 's' : ''}
              </span>
            )}
            {detailed && (
              <span className="badge badge-info" style={{ fontSize: '0.56rem' }}>{item.nodeDisplay}</span>
            )}
            <span style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>
              {detailed ? `${item.invoiceDate ? new Date(item.invoiceDate).toLocaleDateString('fr-FR') : '—'} ${item.timeAdded}` : item.timeAdded}
            </span>
          </div>
          <span className={`badge ${isNotServed || isNonServi ? 'badge-secondary' : isPending ? 'badge-warning' : 'badge-success'}`} style={{ fontSize: '0.58rem' }}>
            {isNotServed ? 'NON SERVI' : isNonServi ? 'NON SERVIE — ENREGISTRÉE' : item.status.toUpperCase()}
          </span>
        </div>

        {/* Card body */}
        <div style={{ padding: '10px 12px', display: 'flex', gap: '12px', alignItems: 'flex-start' }}>

          {/* CLIENT PHOTO — §4.1.2: identification visuelle obligatoire */}
          <div style={{ flexShrink: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '4px' }}>
            <div style={{
              width: '52px', height: '52px', borderRadius: '8px', flexShrink: 0,
              border: `2px solid hsl(var(--${isPending ? 'color-warning' : 'border-color'}) / 0.6)`,
              overflow: 'hidden', backgroundColor: avatarColor,
              display: 'flex', alignItems: 'center', justifyContent: 'center',
            }}>
              {item.clientPhoto ? (
                <img
                  src={item.clientPhoto}
                  alt={`Photo ${item.clientName}`}
                  style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                  onError={e => { (e.target as HTMLImageElement).style.display = 'none'; }}
                />
              ) : (
                <span style={{ color: '#fff', fontWeight: 800, fontSize: '1.1rem', lineHeight: 1 }}>
                  {item.clientName.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase()}
                </span>
              )}
            </div>
            {!item.clientPhoto && (
              <span style={{ fontSize: '0.5rem', color: 'hsl(var(--color-warning))', fontWeight: 700, textAlign: 'center', lineHeight: 1.2 }}>
                PAS DE<br/>PHOTO
              </span>
            )}
          </div>

          {/* Client info + order lines */}
          <div style={{ flex: 1, minWidth: 0 }}>
            <div style={{ marginBottom: '4px' }}>
              <span style={{ fontSize: '0.65rem', fontWeight: 800, color: 'hsl(var(--accent-color))', backgroundColor: 'hsl(var(--accent-glow))', padding: '1px 5px', borderRadius: '3px', marginRight: '6px' }}>
                {item.clientCode}
              </span>
              <span style={{ fontWeight: 800, fontSize: '0.85rem', color: 'hsl(var(--text-primary))' }}>
                {item.clientName}
              </span>
            </div>

            {/* Order lines */}
            <div style={{ display: 'flex', flexDirection: 'column', gap: '2px', marginBottom: '6px' }}>
              {item.lines.map((l, i) => (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem' }}>
                  <span style={{ fontWeight: 800, color: 'hsl(var(--text-primary))', minWidth: '28px' }}>{l.qty}×</span>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>{l.label}</span>
                  <span style={{ marginLeft: 'auto', fontWeight: 700, color: 'hsl(var(--accent-color))' }}>
                    {(l.qty * l.unitPrice).toLocaleString('fr-FR')} FC
                  </span>
                </div>
              ))}
            </div>

            {/* Financial summary */}
            <div style={{ display: 'flex', gap: '12px', fontSize: '0.65rem', flexWrap: 'wrap' }}>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                Total: <strong style={{ color: 'hsl(var(--accent-color))' }}>{item.totalValue.toLocaleString('fr-FR')} FC</strong>
                {item.initialTotal != null && item.initialTotal !== item.totalValue && (
                  <span style={{ color: 'hsl(var(--text-muted))' }}> (commandé initial : {item.initialTotal.toLocaleString('fr-FR')} FC)</span>
                )}
              </span>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                Versé: <strong style={{ color: 'hsl(var(--color-success))' }}>{item.versement.toLocaleString('fr-FR')} FC</strong>
              </span>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>
                BP avant: <strong style={{ color: item.debtBefore > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{item.debtBefore.toLocaleString('fr-FR')} FC</strong>
              </span>
              {item.isSoldee && item.totalLoss > 0 && (
                <span style={{ color: 'hsl(var(--text-secondary))' }} title="Perte attendue du mécanisme de vente soldée (-25% sur le prix catalogue)">
                  Perte (soldée): <strong style={{ color: 'hsl(38, 92%, 38%)' }}>-{item.totalLoss.toLocaleString('fr-FR')} FC</strong>
                </span>
              )}
              {detailed && (
                <>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>
                    Mode: <strong>{item.paymentType === 'CASH' ? 'CASH' : 'CRÉDIT'}</strong>
                  </span>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>
                    BP après: <strong style={{ color: item.debtAfter > 0 ? 'hsl(var(--color-warning))' : 'hsl(var(--text-muted))' }}>{item.debtAfter.toLocaleString('fr-FR')} FC</strong>
                  </span>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>
                    Commission: <strong>{(item.commissionRate * 100).toFixed(0)}%</strong>
                  </span>
                </>
              )}
            </div>

            {detailed && (
              <div style={{ display: 'flex', gap: '12px', fontSize: '0.65rem', flexWrap: 'wrap', marginTop: '4px', color: 'hsl(var(--text-muted))' }}>
                <span>Facturier: <strong style={{ color: 'hsl(var(--text-secondary))' }}>{item.facturierDisplay}</strong></span>
                {item.livreurDisplay && (
                  <span>Livreur: <strong style={{ color: 'hsl(var(--text-secondary))' }}>{item.livreurDisplay}</strong></span>
                )}
              </div>
            )}
          </div>
        </div>

        {/* Action footer */}
        {isPending && (
          <PendingDeliveryActions
            key={`${item._apiId}-${item.lines.map(l => l.qty).join('.')}`}
            item={item}
            errorMessage={deliveryError && deliveryError.id === item._apiId ? deliveryError.message : null}
            onCancel={() => cancelInvoice(item)}
            onDeliver={lines => handleDeliverClick(item, lines)}
            onNotServed={reason => markNotServed(item, reason)}
          />
        )}
        {/* BUG-335 : le detail serveur d'un 409 reste affiche tant qu'aucune autre action n'est lancee. */}
        {!isPending && deliveryError && deliveryError.id === item._apiId && (
          <div role="alert" style={{ padding: '6px 12px', borderTop: '1px solid hsl(var(--color-danger) / 0.4)', backgroundColor: 'hsl(var(--color-danger) / 0.08)', color: 'hsl(var(--color-danger))', fontSize: '0.7rem', fontWeight: 700 }}>
            {deliveryError.message}
          </div>
        )}
        {isNotServed && (
          <div style={{ padding: '6px 12px', borderTop: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--text-secondary))', fontSize: '0.7rem', fontWeight: 700, flexWrap: 'wrap' }}>
            <FiCheckCircle />
            <span>
              Non servi — aucun pain remis{item.notServedReason ? ` (motif : ${item.notServedReason})` : ''}
              {item.initialTotal != null && ` · commandé : ${item.initialTotal.toLocaleString('fr-FR')} FC`}
            </span>
          </div>
        )}
        {isNonServi && (
          <div style={{ padding: '6px 12px', borderTop: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--text-secondary))', fontSize: '0.7rem', fontWeight: 700 }}>
              <FiCheckCircle />
              <span>Non servie — enregistrée (aucun pain remis, rien à livrer)</span>
            </div>
            <button
              onClick={() => cancelInvoice(item)}
              className="btn btn-secondary"
              style={{ padding: '3px 10px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.4)' }}
              title="Annuler cet enregistrement de non servi"
            >
              <FiX />
              <span>Annuler</span>
            </button>
          </div>
        )}
        {!isPending && !isNonServi && !isNotServed && (
          <div style={{ padding: '6px 12px', borderTop: '1px solid hsl(var(--border-color) / 0.5)', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '6px', flexWrap: 'wrap' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'hsl(var(--color-success))', fontSize: '0.7rem', fontWeight: 700 }}>
              <FiCheckCircle />
              <span>Distribué</span>
            </div>
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
              {/* BUG-109 : correction/annulation réservée GERANT+, jamais sur un remboursement
                  ou une facture d'ajustement elle-même (on remonte toujours à l'originale). */}
              {canAdjustInvoice && !item.isAdjustment && !item.isRepayment && (
                <button
                  onClick={() => openAdjustModal(item)}
                  className="btn btn-secondary"
                  style={{ padding: '3px 10px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                  title="Corriger/annuler cette commande via une facture d'ajustement"
                >
                  Ajuster
                </button>
              )}
              {receiptCache[item._apiId] && (
                <button
                  onClick={() => setReceipt(receiptCache[item._apiId])}
                  className="btn btn-secondary"
                  style={{ padding: '3px 10px', fontSize: '0.62rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <FiPrinter /> Ré-imprimer
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    );
};
