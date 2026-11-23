import React, { useEffect, useState } from 'react';
import { clientsApi, ClientHistory } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { Modal } from '@/components/shared/Modal';

const MONTHS_FR = [
  'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
  'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
];

export const monthLabel = (m: string): string => {
  const [y, mo] = m.split('-');
  return `${MONTHS_FR[Number(mo) - 1] ?? mo} ${y}`;
};

/** Montant au format « 12 500 FC » (espaces simples, sans décimales). */
const fc = (v: string | number | null | undefined): string => {
  if (v == null || v === '') return '—';
  const n = Math.round(Number(v));
  const s = Math.abs(n).toString().replace(/\B(?=(\d{3})+(?!\d))/g, ' ');
  return `${n < 0 ? '-' : ''}${s} FC`;
};

const TYPE_LABEL: Record<string, string> = {
  ACHAT: 'Achat', DEPOT: 'Dépôt', RETRAIT: 'Retrait',
  REMBOURSEMENT: 'Remboursement', AJUSTEMENT: 'Ajustement',
};
const STATUS_LABEL: Record<string, string> = {
  DELIVERED: 'Livrée', PENDING: 'En attente de livraison',
  CANCELLED: 'Annulée', NOT_SERVED: 'Non servi',
};

const fmtDateTime = (iso: string | null, date: string): string => {
  if (!iso) return date.split('-').reverse().join('/');
  const d = new Date(iso);
  return `${d.toLocaleDateString('fr-FR')} ${d.toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' })}`;
};

interface Props {
  clientId: string | null;
  clientName?: string;
  /** BUG-412 : mois de départ « AAAA-MM » (mois filtré de l'écran appelant) ; défaut = mois courant. */
  initialMonth?: string;
  onClose: () => void;
}

export const ClientHistoryModal: React.FC<Props> = ({ clientId, clientName, initialMonth, onClose }) => {
  const [month, setMonth] = useState<string | undefined>(undefined);
  const [data, setData] = useState<ClientHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => { setMonth(initialMonth); setData(null); setError(null); }, [clientId, initialMonth]);

  useEffect(() => {
    if (!clientId) return;
    let cancelled = false;
    setLoading(true);
    setError(null);
    clientsApi.history(clientId, month)
      .then(r => { if (!cancelled) setData(r.data); })
      .catch(e => { if (!cancelled) setError(getErrorDetail(e, "Impossible de charger l'historique du client.")); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [clientId, month]);

  const months = data?.available_months ?? [];
  const idx = data ? months.indexOf(data.month) : -1;
  // available_months est trié du plus récent au plus ancien.
  const older = idx >= 0 && idx < months.length - 1 ? months[idx + 1] : null;
  const newer = idx > 0 ? months[idx - 1] : null;
  const cell: React.CSSProperties = { padding: '6px 8px', whiteSpace: 'nowrap' };

  return (
    <Modal
      isOpen={!!clientId}
      onClose={onClose}
      title="Historique du client"
      subtitle={data ? `${data.client.full_name} · ${data.client.code} · BP actuelle : ${fc(data.client.current_debt)}` : clientName}
      maxWidth="960px"
    >
      <div style={{ display: 'flex', gap: '6px', alignItems: 'center', flexWrap: 'wrap', marginBottom: '12px' }}>
        <button className="btn btn-secondary" disabled={!older || loading} onClick={() => older && setMonth(older)}
          aria-label="Mois précédent" style={{ padding: '6px 12px' }}>‹ Précédent</button>
        <select
          className="form-input"
          aria-label="Choisir le mois"
          value={data?.month ?? ''}
          disabled={!data || loading}
          onChange={e => setMonth(e.target.value)}
          style={{ minWidth: '170px', width: 'auto' }}
        >
          {months.map(m => (
            <option key={m} value={m}>{monthLabel(m)}{m === data?.current_month ? ' (mois courant)' : ''}</option>
          ))}
        </select>
        <button className="btn btn-secondary" disabled={!newer || loading} onClick={() => newer && setMonth(newer)}
          aria-label="Mois suivant" style={{ padding: '6px 12px' }}>Suivant ›</button>
      </div>

      {loading && <div role="status" style={{ padding: '16px', textAlign: 'center' }}>Chargement...</div>}
      {error && <div role="alert" style={{ padding: '10px', color: 'hsl(var(--color-danger))' }}>{error}</div>}

      {data && !error && (
        <div style={{ opacity: loading ? 0.5 : 1 }}>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: '8px', marginBottom: '12px', fontSize: '0.75rem' }}>
            {([
              ['Commandé', fc(data.totals.total_orders)],
              ['Versé', fc(data.totals.total_payments)],
              ['Retraits', fc(data.totals.total_withdrawals)],
              ['Variation BP', fc(data.totals.net_balance_change)],
              ['BP début', fc(data.totals.bp_start)],
              ['BP fin', fc(data.totals.bp_end)],
            ] as const).map(([k, v]) => (
              <div key={k} className="glass-card" style={{ padding: '8px 10px' }}>
                <div style={{ color: 'hsl(var(--text-muted))', fontSize: '0.65rem', textTransform: 'uppercase' }}>{k}</div>
                <div style={{ fontWeight: 800 }}>{v}</div>
              </div>
            ))}
          </div>

          {data.operations.length === 0 ? (
            <div style={{ padding: '16px', textAlign: 'center', color: 'hsl(var(--text-secondary))' }}>
              Aucune opération en {monthLabel(data.month)}.
            </div>
          ) : (
            <div style={{ overflowX: 'auto' }}>
              <table className="premium-table" style={{ fontSize: '0.72rem', width: '100%' }}>
                <thead>
                  <tr style={{ textTransform: 'uppercase', fontSize: '0.65rem' }}>
                    <th style={cell}>Date</th><th style={cell}>Libellé</th><th style={cell}>Type</th>
                    <th style={cell}>Commande</th><th style={cell}>Paiement</th>
                    <th style={cell}>BP avant</th><th style={cell}>BP après</th>
                  </tr>
                </thead>
                <tbody>
                  {data.operations.map(op => {
                    const delivered = op.status === 'DELIVERED';
                    return (
                      <tr key={op.id} style={delivered ? undefined : { opacity: 0.5 }}>
                        <td style={cell}>{fmtDateTime(op.datetime, op.date)}</td>
                        <td style={{ ...cell, whiteSpace: 'normal' }}>
                          {op.label}
                          {!delivered && (
                            <div style={{ fontSize: '0.62rem', fontStyle: 'italic' }}>{STATUS_LABEL[op.status] ?? op.status}</div>
                          )}
                        </td>
                        <td style={cell}>{TYPE_LABEL[op.type] ?? op.type}</td>
                        <td style={cell}>{fc(op.order_value)}</td>
                        <td style={cell}>{fc(op.payment)}</td>
                        <td style={cell}>{delivered ? fc(op.bp_before) : '—'}</td>
                        <td style={cell}>{delivered ? fc(op.bp_after) : '—'}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </Modal>
  );
};
