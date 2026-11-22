import React, { useState } from 'react';
import { FiBook, FiCheckCircle, FiX } from 'react-icons/fi';
import type { CashClosure } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { BILLS, fmt } from '@/components/treasury/treasuryShared';

interface Props {
  closure: CashClosure;
  onClose: () => void;
  /** Siège (COMPTABLE/DIRECTION/ADMIN) : confirmer, infirmer, inscrire au Livre de Caisse. */
  canConfirm: boolean;
  actionLoading: boolean;
  onValidate: (id: string, notes: string) => void;
  onReject: (id: string, reason: string) => void;
  onPush: (id: string) => void;
}

/** Détail d'une clôture de caisse (billetage, écart) + actions du siège (modale). */
export const ClosureDetailModal: React.FC<Props> = ({ closure: cl, onClose, canConfirm, actionLoading, onValidate, onReject, onPush }) => {
  const [rejectReason, setRejectReason] = useState('');
  const [rejectingClosureId, setRejectingClosureId] = useState<string | null>(null);
  const [validateNotes, setValidateNotes] = useState('');
  const [validatingClosureId, setValidatingClosureId] = useState<string | null>(null);
  const gap = parseFloat(cl.cash_gap);

  return (
    <Modal
      isOpen
      onClose={onClose}
      title={`Rapport de caisse — ${cl.node_display || cl.node}`}
      subtitle={`Date : ${cl.date} · Gérant : ${cl.gerant_display || '—'}`}
      maxWidth="480px"
    >
        <div style={{ fontSize: '0.72rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', marginBottom: '6px' }}>Versement du jour</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', marginBottom: '12px' }}>
          {BILLS.map(b => {
            const qty = cl[b.key as keyof CashClosure] as number;
            if (!qty) return null;
            return (
              <div key={b.key} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem', padding: '2px 6px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: '3px' }}>
                <span>{b.label}</span>
                <span>× {qty} = <strong>{(qty * b.face).toLocaleString('fr-FR')} FC</strong></span>
              </div>
            );
          })}
          {BILLS.every(b => !(cl[b.key as keyof CashClosure] as number)) && (
            <div style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', padding: '4px 6px' }}>Aucun billet saisi</div>
          )}
        </div>
        <div style={{ borderTop: '1px solid hsl(var(--border-color))', paddingTop: '10px', display: 'flex', flexDirection: 'column', gap: '5px' }}>
          {[
            { label: 'Total Espèces Physiques', value: fmt(cl.physical_cash_total) + ' FC', color: 'hsl(var(--color-success))' },
            { label: 'Total Entrées Cash (Ventes)', value: fmt(cl.total_entries) + ' FC', color: 'hsl(var(--text-primary))' },
            { label: 'Total Dépenses Locales', value: '−' + fmt(cl.total_expenses) + ' FC', color: 'hsl(var(--color-danger))' },
            { label: 'Caisse Nette (Net Cash)', value: fmt(cl.net_cash) + ' FC', color: 'hsl(var(--color-warning))' },
          ].map(row => (
            <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.72rem' }}>
              <span style={{ color: 'hsl(var(--text-secondary))' }}>{row.label}</span>
              <strong style={{ color: row.color }}>{row.value}</strong>
            </div>
          ))}
          <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '0.8rem', fontWeight: 800, padding: '6px 8px', marginTop: '4px', borderRadius: 'var(--radius-sm)', backgroundColor: gap === 0 ? 'hsl(var(--color-success) / 0.08)' : 'hsl(var(--color-danger) / 0.08)', border: `1px solid hsl(var(--${gap === 0 ? 'color-success' : 'color-danger'}) / 0.3)` }}>
            <span>ÉCART DE CAISSE</span>
            <span style={{ color: gap === 0 ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))' }}>
              {gap >= 0 ? '+' : ''}{fmt(cl.cash_gap)} FC{gap === 0 ? ' ✓ Équilibré' : gap > 0 ? ' (Excédent)' : ' (Manque)'}
            </span>
          </div>
        </div>
        {cl.notes && (
          <div style={{ marginTop: '10px', fontSize: '0.68rem', color: 'hsl(var(--text-secondary))', backgroundColor: 'hsl(var(--bg-tertiary))', padding: '6px 10px', borderRadius: 'var(--radius-sm)', whiteSpace: 'pre-line' }}>
            <strong>Notes :</strong> {cl.notes}
          </div>
        )}
        {/* Rejection notice */}
        {cl.is_rejected && (
          <div style={{ marginTop: '10px', padding: '8px 12px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-danger) / 0.08)', border: '1px solid hsl(var(--color-danger) / 0.3)', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
            <strong>INFIRMÉE</strong> — Motif : {cl.rejection_reason || 'Non précisé'}
          </div>
        )}

        <div style={{ marginTop: '14px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
          <div style={{ display: 'flex', gap: '8px', alignItems: 'center', flexWrap: 'wrap' }}>
            <span className={`badge ${cl.is_validated ? 'badge-success' : cl.is_rejected ? 'badge-danger' : 'badge-warning'}`} style={{ fontSize: '0.62rem' }}>
              {cl.is_validated ? 'CONFIRMÉE' : cl.is_rejected ? 'INFIRMÉE' : 'EN ATTENTE'}
            </span>

            {/* HQ only: confirm / reject */}
            {canConfirm && !cl.is_validated && (
              <>
                <button
                  onClick={() => { setValidatingClosureId(validatingClosureId === cl.id ? null : cl.id); setRejectingClosureId(null); }}
                  className="btn btn-primary"
                  style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px' }}
                >
                  <FiCheckCircle /> Confirmer
                </button>
                <button
                  onClick={() => { setRejectingClosureId(rejectingClosureId === cl.id ? null : cl.id); setValidatingClosureId(null); }}
                  className="btn btn-secondary"
                  style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', color: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger) / 0.4)' }}
                >
                  <FiX /> Infirmer
                </button>
              </>
            )}

            {/* HQ: push to cashbook after validation */}
            {cl.is_validated && canConfirm && (
              <button
                onClick={() => onPush(cl.id)}
                disabled={actionLoading}
                className="btn btn-secondary"
                style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', opacity: actionLoading ? 0.6 : 1 }}
              >
                <FiBook /> Inscrire au Livre de Caisse
              </button>
            )}
          </div>

          {/* Confirm form (inline, HQ only) */}
          {validatingClosureId === cl.id && (
            <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start', flexDirection: 'column' }}>
              <textarea
                value={validateNotes}
                onChange={e => setValidateNotes(e.target.value)}
                placeholder="Commentaire du comptable (facultatif)…"
                className="form-input"
                rows={2}
                style={{ fontSize: '0.7rem', resize: 'vertical', width: '100%' }}
              />
              <button
                onClick={() => onValidate(cl.id, validateNotes)}
                disabled={actionLoading}
                className="btn btn-primary"
                style={{ padding: '4px 12px', fontSize: '0.7rem', display: 'flex', alignItems: 'center', gap: '4px', opacity: actionLoading ? 0.6 : 1 }}
              >
                <FiCheckCircle /> {actionLoading ? 'Confirmation...' : 'Confirmer la clôture'}
              </button>
            </div>
          )}

          {/* Reject form (inline, HQ only) */}
          {rejectingClosureId === cl.id && (
            <div style={{ display: 'flex', gap: '6px', alignItems: 'flex-start', flexDirection: 'column' }}>
              <textarea
                value={rejectReason}
                onChange={e => setRejectReason(e.target.value)}
                placeholder="Motif du rejet (facultatif)…"
                className="form-input"
                rows={2}
                style={{ fontSize: '0.7rem', resize: 'vertical', width: '100%' }}
              />
              <button
                onClick={() => onReject(cl.id, rejectReason)}
                disabled={actionLoading}
                className="btn btn-primary"
                style={{ padding: '4px 12px', fontSize: '0.7rem', backgroundColor: 'hsl(var(--color-danger))', borderColor: 'hsl(var(--color-danger))', opacity: actionLoading ? 0.6 : 1 }}
              >
                {actionLoading ? 'Rejet...' : 'Confirmer le rejet'}
              </button>
            </div>
          )}
        </div>
    </Modal>
  );
};
