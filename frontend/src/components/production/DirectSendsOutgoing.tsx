import React from 'react';
import { FiArrowRight, FiClock } from 'react-icons/fi';
import { BreadTransfer } from '@/api/services';

// BUG-382 : envois directs (flow DIRECT) de MA boulangerie encore en attente de validation
// par la réceptrice. Lecture seule : un envoi direct est figé (le serveur refuse
// `respond_to_request`, PATCH et DELETE) ; seule la réceptrice agit.

const fmt = (n: number): string => n.toLocaleString('fr-FR').replace(/ | /g, ' ');

export const DirectSendsOutgoing: React.FC<{ transfers: BreadTransfer[] }> = ({ transfers }) => {
  if (transfers.length === 0) return null;
  return (
    <div>
      <h3 style={{ fontSize: '0.75rem', fontWeight: 700, marginBottom: '6px', color: 'hsl(var(--text-secondary))' }}>
        Envois directs en attente de validation
        <span className="badge badge-info" style={{ marginLeft: '6px', fontSize: '0.55rem' }}>{transfers.length}</span>
      </h3>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '8px' }}>
        {transfers.map(t => (
          <div key={t.id} style={{ backgroundColor: 'hsl(var(--color-info) / 0.05)', border: '1px solid hsl(var(--color-info) / 0.4)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: '6px', flexWrap: 'wrap', marginBottom: '4px' }}>
              <div style={{ fontSize: '0.72rem' }}>
                <span style={{ fontWeight: 800 }}>{t.from_node_display || t.from_node}</span>
                <FiArrowRight style={{ margin: '0 4px' }} />
                <span style={{ fontWeight: 800 }}>{t.to_node_display || t.to_node}</span>
              </div>
              <span className="badge badge-info" style={{ fontSize: '0.52rem', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                <FiClock /> EN ATTENTE DE VALIDATION
              </span>
            </div>
            <div style={{ fontSize: '0.65rem', color: 'hsl(var(--text-muted))' }}>
              Envoi direct : en attente de la confirmation de réception par {t.to_node_display || 'la boulangerie réceptrice'}.
            </div>
            {t.notes && <div style={{ fontSize: '0.62rem', color: 'hsl(var(--text-muted))', fontStyle: 'italic', marginTop: '3px' }}>{t.notes}</div>}
            <div style={{ fontSize: '0.68rem', marginTop: '4px', color: 'hsl(var(--text-secondary))' }}>
              {(t.lines || []).map(l => (
                <span key={l.bread_price} style={{ marginRight: '8px' }}>{l.bread_price_display}: {fmt(l.quantity_sent)}</span>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
