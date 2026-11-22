import React from 'react';
import { Modal } from '@/components/shared/Modal';
import type { ClientImportResult } from '@/api/services';

interface ImportClientsModalProps {
  isImportModalOpen: boolean;
  setIsImportModalOpen: (open: boolean) => void;
  importFile: File | null;
  setImportFile: (file: File | null) => void;
  importPreview: ClientImportResult | null;
  setImportPreview: (p: ClientImportResult | null) => void;
  importResult: ClientImportResult | null;
  setImportResult: (r: ClientImportResult | null) => void;
  importLoading: boolean;
  importError: string | null;
  setImportError: (e: string | null) => void;
  handleImportPreview: () => void | Promise<void>;
  handleImportConfirm: () => void | Promise<void>;
}

/** Import des clients depuis un classeur Excel (Direction centrale). */
export const ImportClientsModal: React.FC<ImportClientsModalProps> = ({
  isImportModalOpen, setIsImportModalOpen, importFile, setImportFile, importPreview, setImportPreview,
  importResult, setImportResult, importLoading, importError, setImportError,
  handleImportPreview, handleImportConfirm,
}) => {
  return (
      <Modal
        isOpen={isImportModalOpen}
        onClose={() => { if (!importLoading) setIsImportModalOpen(false); }}
        title="Importer les Clients depuis Excel"
        maxWidth="560px"
      >
        <div style={{ display: 'flex', flexDirection: 'column', gap: '14px' }}>
          <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>
            Sélectionnez le classeur "Liste des Clients par Boulangeries" (une feuille par boulangerie).
            Les codes clients sont générés automatiquement par l'application selon la boulangerie.
            Les clients déjà présents (même nom, même boulangerie) sont ignorés — l'import peut être relancé sans créer de doublons.
          </p>

          <input
            type="file"
            accept=".xlsx"
            disabled={importLoading}
            onChange={(e) => {
              setImportFile(e.target.files?.[0] || null);
              setImportPreview(null);
              setImportResult(null);
              setImportError(null);
            }}
            className="form-input"
            style={{ height: 'auto', padding: '8px 12px', fontSize: '0.78rem' }}
          />

          {importError && (
            <div style={{ fontSize: '0.75rem', color: 'hsl(var(--color-danger))', fontWeight: 600 }}>{importError}</div>
          )}

          {importPreview && (
            <div style={{ border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)', overflow: 'hidden' }}>
              <table className="premium-table" style={{ fontSize: '0.72rem' }}>
                <thead>
                  <tr>
                    <th style={{ padding: '6px 8px' }}>Boulangerie</th>
                    <th style={{ padding: '6px 8px', textAlign: 'right' }}>Dans le fichier</th>
                    <th style={{ padding: '6px 8px', textAlign: 'right' }}>À importer</th>
                    <th style={{ padding: '6px 8px', textAlign: 'right' }}>Déjà existants</th>
                  </tr>
                </thead>
                <tbody>
                  {importPreview.report.map(r => (
                    <tr key={r.node}>
                      <td style={{ padding: '6px 8px', fontWeight: 700 }}>{r.node} — {r.node_name}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right' }}>{r.total_in_file}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--color-success))', fontWeight: 700 }}>{r.to_import}</td>
                      <td style={{ padding: '6px 8px', textAlign: 'right', color: 'hsl(var(--text-secondary))' }}>{r.already_existing}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {importPreview.unknown_nodes.length > 0 && (
                <div style={{ padding: '8px', fontSize: '0.7rem', color: 'hsl(var(--color-warning))' }}>
                  Boulangeries non reconnues dans le fichier (ignorées) : {importPreview.unknown_nodes.join(', ')}
                </div>
              )}
              {importPreview.report.some(r => (r.invalid ?? 0) > 0) && (
                <div style={{ padding: '8px', fontSize: '0.7rem', color: 'hsl(var(--color-warning))' }}>
                  Noms trop longs (non importés) : {importPreview.report.flatMap(r => r.invalid_names ?? []).join(', ')}
                </div>
              )}
              {importPreview.skipped_sheets.length > 0 && (
                <div style={{ padding: '0 8px 8px', fontSize: '0.7rem', color: 'hsl(var(--text-muted))' }}>
                  Feuilles ignorées (hors périmètre) : {importPreview.skipped_sheets.join(', ')}
                </div>
              )}
            </div>
          )}

          {importResult && (
            <div style={{ padding: '10px', borderRadius: 'var(--radius-sm)', backgroundColor: 'hsl(var(--color-success) / 0.1)', color: 'hsl(var(--color-success))', fontWeight: 700, fontSize: '0.78rem' }}>
              {importResult.created} client(s) importé(s) avec succès.
            </div>
          )}

          <div style={{ display: 'flex', justifyContent: 'flex-end', gap: '10px' }}>
            <button className="btn btn-secondary" disabled={importLoading} onClick={() => setIsImportModalOpen(false)}>Fermer</button>
            {!importResult && (
              <>
                <button
                  className="btn btn-secondary"
                  disabled={!importFile || importLoading}
                  onClick={handleImportPreview}
                >
                  {importLoading && !importPreview ? 'Lecture…' : 'Aperçu'}
                </button>
                {importPreview && (
                  <button
                    className="btn btn-primary"
                    disabled={importLoading}
                    onClick={handleImportConfirm}
                  >
                    {importLoading ? 'Import en cours…' : `Confirmer l'import (${importPreview.report.reduce((s, r) => s + r.to_import, 0)})`}
                  </button>
                )}
              </>
            )}
          </div>
        </div>
      </Modal>
  );
};
