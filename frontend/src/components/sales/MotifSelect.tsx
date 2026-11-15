import React from 'react';

export type InvoiceMotif = '' | 'RETRAIT_EPARGNE' | 'EMPRUNT_BOULANGER' | 'MANQUANT_EQUIPE' | 'AUTRE';

export const MOTIF_OPTIONS: Array<{ value: InvoiceMotif; label: string }> = [
  { value: '', label: 'Aucun motif' },
  { value: 'RETRAIT_EPARGNE', label: "Retrait d'épargne" },
  { value: 'EMPRUNT_BOULANGER', label: 'Emprunt boulanger' },
  { value: 'MANQUANT_EQUIPE', label: "Manquant d'équipe" },
  { value: 'AUTRE', label: 'Autre' },
];

interface Props {
  value: InvoiceMotif;
  onChange: (m: InvoiceMotif) => void;
}

/** Motif d'un versement (surtout utile lorsque le montant est négatif : sortie de caisse). */
export const MotifSelect: React.FC<Props> = ({ value, onChange }) => (
  <div>
    <label style={{ display: 'block', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', marginBottom: '4px', textTransform: 'uppercase' }}>
      Motif
    </label>
    <select
      value={value}
      onChange={e => onChange(e.target.value as InvoiceMotif)}
      className="form-input"
      style={{ fontSize: '0.78rem', height: '32px', padding: '0 8px' }}
    >
      {MOTIF_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
    </select>
  </div>
);
