import React from 'react';
import { FiAlertTriangle, FiLock, FiRefreshCw } from 'react-icons/fi';
import type { CashbookEntry } from '@/api/services';
import { Modal } from '@/components/shared/Modal';
import { fmt } from '@/components/treasury/treasuryShared';

// Détail d'une écriture du Livre de Caisse Direction (lecture seule).
export const CashbookEntryModal: React.FC<{ entry: CashbookEntry; onClose: () => void }> = ({ entry: en, onClose }) => {
  const isEntry = parseFloat(en.entry_amount) > 0;
  return (
      <Modal isOpen={true} onClose={() => onClose()} maxWidth="460px">
          {en.is_tampered && (
            <div style={{ display: 'flex', alignItems: 'center', gap: '6px', backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.3)', borderRadius: 'var(--radius-sm)', padding: '5px 10px', marginBottom: '12px', fontSize: '0.68rem', color: 'hsl(var(--color-danger))' }}>
              <FiAlertTriangle /> ATTENTION — Écriture potentiellement altérée !
            </div>
          )}
          <h3 style={{ fontSize: '1rem', fontWeight: 800, marginBottom: '2px', display: 'flex', alignItems: 'center', gap: '8px' }}>
            <FiLock style={{ color: isEntry ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))', fontSize: '0.9rem' }} />
            {en.piece_number}
            {en.is_correction && (
              <span className="badge badge-warning" style={{ fontSize: '0.56rem', display: 'inline-flex', alignItems: 'center', gap: '3px' }}>
                <FiRefreshCw style={{ fontSize: '0.65rem' }} /> Correction
              </span>
            )}
          </h3>
          <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginBottom: '16px' }}>
            {new Date(en.date).toLocaleDateString('fr-FR', { weekday: 'long', year: 'numeric', month: 'long', day: 'numeric' })}
            {en.node_display ? ` · ${en.node_display}` : ''}
          </p>
          <div style={{ display: 'flex', flexDirection: 'column', gap: '6px' }}>
            {[
              { label: 'Libellé', value: en.label },
              { label: 'Imputation', value: en.imputation || '—' },
              { label: 'Entrée FC', value: parseFloat(en.entry_amount) > 0 ? `+${fmt(en.entry_amount)} FC` : '—', color: 'hsl(var(--color-success))' },
              { label: 'Sortie FC', value: parseFloat(en.exit_amount) > 0 ? `−${fmt(en.exit_amount)} FC` : '—', color: 'hsl(var(--color-danger))' },
              { label: 'Solde Cumulé', value: `${fmt(en.running_balance)} FC`, color: parseFloat(en.running_balance) >= 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--color-danger))' },
            ].map(row => (
              <div key={row.label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '5px 8px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', fontSize: '0.72rem' }}>
                <span style={{ color: 'hsl(var(--text-secondary))' }}>{row.label}</span>
                <strong style={{ color: row.color || 'hsl(var(--text-primary))' }}>{row.value}</strong>
              </div>
            ))}
          </div>
          {en.is_correction && (
            <div style={{ marginTop: '14px', padding: '8px 10px', backgroundColor: 'hsl(var(--color-warning) / 0.08)', border: '1px solid hsl(var(--color-warning) / 0.3)', borderRadius: 'var(--radius-sm)', fontSize: '0.68rem' }}>
              <div style={{ fontWeight: 700, color: 'hsl(var(--color-warning))', marginBottom: '6px', display: 'flex', alignItems: 'center', gap: '5px' }}>
                <FiRefreshCw /> Écriture de correction — traçabilité
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
                <div>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Motif : </span>
                  <strong>{en.correction_reason || '—'}</strong>
                </div>
                <div>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Corrigé par : </span>
                  <strong>{en.corrected_by_display || '—'}</strong>
                </div>
                <div>
                  <span style={{ color: 'hsl(var(--text-secondary))' }}>Facture d'origine : </span>
                  {en.correction_source_invoice ? (
                    <strong style={{ fontFamily: 'monospace', fontSize: '0.6rem' }} title={en.correction_source_invoice}>
                      {en.correction_source_invoice.slice(0, 8)}…
                    </strong>
                  ) : (
                    <strong>—</strong>
                  )}
                </div>
              </div>
            </div>
          )}
          <div style={{ marginTop: '14px', padding: '8px 10px', backgroundColor: 'hsl(var(--bg-tertiary))', borderRadius: 'var(--radius-sm)', fontSize: '0.6rem', fontFamily: 'monospace', color: 'hsl(var(--text-muted))', wordBreak: 'break-all' }}>
            <div style={{ fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '3px', fontSize: '0.62rem' }}>
              <FiLock style={{ marginRight: '4px', verticalAlign: 'middle' }} />
              Empreinte Blockchain
            </div>
            {en.block_hash || '—'}
          </div>
          <button onClick={() => onClose()} className="btn btn-secondary" style={{ width: '100%', marginTop: '14px', padding: '6px', fontSize: '0.75rem' }}>
            Fermer
          </button>
      </Modal>
  );
};
