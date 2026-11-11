import React, { useEffect, useState } from 'react';

// BUG-159 / BUG-162 : saisie d'un entier signé partagée (reste du jour à la clôture,
// stock de départ du jour). Un stock de pain négatif est enregistré tel quel (décision
// client) : saisie du « - », bouton « ± », champ en rouge + libellé « Stock négatif ».

interface SignedIntegerFieldProps {
  value: number;
  onChange: (value: number) => void;
  ariaLabel: string;
  disabled?: boolean;
  /** Largeur du bloc (défaut : 100 %). */
  width?: string;
  /** Affiche le libellé « Stock négatif » sous le champ (défaut : oui). */
  showNegativeLabel?: boolean;
}

export const SignedIntegerField: React.FC<SignedIntegerFieldProps> = ({
  value, onChange, ariaLabel, disabled = false, width = '100%', showNegativeLabel = true,
}) => {
  // Saisie brute en cours : permet l'état intermédiaire « - » sans l'écraser.
  const [raw, setRaw] = useState<string | null>(null);

  // Valeur modifiée de l'extérieur (pré-remplissage, rechargement) : abandonne la saisie brute.
  useEffect(() => {
    setRaw(prev => (prev !== null && (Math.trunc(Number(prev)) || 0) !== value ? null : prev));
  }, [value]);

  const handleChange = (text: string) => {
    const cleaned = text.replace(/[^0-9-]/g, '').replace(/(?!^)-/g, '');
    setRaw(cleaned);
    onChange(Math.trunc(Number(cleaned)) || 0);
  };

  const toggleSign = () => {
    setRaw(null);
    onChange(-value);
  };

  const negative = value < 0;

  return (
    <div style={{ width, minWidth: 0 }}>
      <div style={{ display: 'flex', gap: '4px' }}>
        <button
          type="button"
          onClick={toggleSign}
          disabled={disabled}
          className="btn btn-secondary"
          style={{ height: '34px', minWidth: '34px', padding: 0, fontSize: '0.9rem' }}
          aria-label={`Changer le signe — ${ariaLabel}`}
          title="Changer le signe (+/-)"
        >
          ±
        </button>
        <input
          type="text"
          inputMode="text"
          pattern="-?[0-9]*"
          value={raw ?? String(value)}
          onChange={e => handleChange(e.target.value)}
          disabled={disabled}
          className="form-input"
          style={{
            height: '34px', fontSize: '0.85rem', textAlign: 'right', padding: '0 8px', minWidth: 0, width: '100%',
            color: negative ? 'hsl(var(--color-danger))' : undefined,
          }}
          aria-label={ariaLabel}
        />
      </div>
      {negative && showNegativeLabel && (
        <div style={{ fontSize: '0.58rem', color: 'hsl(var(--color-danger))', textAlign: 'right', marginTop: '2px' }}>
          Stock négatif
        </div>
      )}
    </div>
  );
};
