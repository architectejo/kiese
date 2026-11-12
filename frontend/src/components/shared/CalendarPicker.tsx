import React, { useState } from 'react';
import { FiChevronLeft, FiChevronRight } from 'react-icons/fi';
import { useWorkDate } from '@/store/workDateStore';

// BUG-128 (docs/qa/REGISTRE_BUGS.md) : calendrier mensuel léger, sans dépendance npm,
// destiné à remplacer le sélecteur natif `<input type="date">` à l'intérieur d'une
// boîte modale (réutilise components/shared/Modal.tsx — ne gère pas sa propre
// modale). Un seul mois affiché, sélection d'un jour unique, pas de plage de dates.

const JOURS_SEMAINE = ['Lun', 'Mar', 'Mer', 'Jeu', 'Ven', 'Sam', 'Dim'];
const MOIS = [
  'Janvier', 'Février', 'Mars', 'Avril', 'Mai', 'Juin',
  'Juillet', 'Août', 'Septembre', 'Octobre', 'Novembre', 'Décembre',
];

export interface CalendarPickerProps {
  /** Date actuellement sélectionnée, au format AAAA-MM-JJ. */
  value: string;
  /** Appelé avec la date choisie (AAAA-MM-JJ) au clic sur un jour valide. */
  onSelect: (isoDate: string) => void;
  /**
   * Dernier jour sélectionnable (inclus), au format AAAA-MM-JJ. Les jours
   * suivants sont affichés mais désactivés (grisés, non cliquables).
   * Par défaut : aujourd'hui — un rapport de clôture d'un jour futur n'existe
   * pas (CLAUDE.md §5.4 ; le serveur renvoie un rapport vide plutôt qu'une
   * erreur, mais autoriser la sélection n'aurait aucun sens métier).
   */
  maxDate?: string;
}

const toIso = (d: Date): string => {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
};

const parseIso = (iso: string): Date => {
  const [y, m, d] = iso.split('-').map(Number);
  return new Date(y, (m || 1) - 1, d || 1);
};

export const CalendarPicker: React.FC<CalendarPickerProps> = ({ value, onSelect, maxDate }) => {
  const selected = value ? parseIso(value) : new Date();
  // BUG-161 (F3) : par défaut, dernier jour sélectionnable = jour calendaire du serveur (BUG-272).
  const workDate = useWorkDate();
  const effectiveMaxDate = maxDate ?? workDate;
  const [viewYear, setViewYear] = useState(selected.getFullYear());
  const [viewMonth, setViewMonth] = useState(selected.getMonth());

  const firstOfMonth = new Date(viewYear, viewMonth, 1);
  // getDay() : 0 = dimanche … 6 = samedi. On veut une grille commençant le lundi.
  const startWeekday = (firstOfMonth.getDay() + 6) % 7;
  const daysInMonth = new Date(viewYear, viewMonth + 1, 0).getDate();

  const cells: Array<{ day: number; iso: string } | null> = [];
  for (let i = 0; i < startWeekday; i++) cells.push(null);
  for (let day = 1; day <= daysInMonth; day++) {
    cells.push({ day, iso: toIso(new Date(viewYear, viewMonth, day)) });
  }

  const goToPrevMonth = () => {
    if (viewMonth === 0) { setViewYear(y => y - 1); setViewMonth(11); } else { setViewMonth(m => m - 1); }
  };
  const goToNextMonth = () => {
    if (viewMonth === 11) { setViewYear(y => y + 1); setViewMonth(0); } else { setViewMonth(m => m + 1); }
  };

  const today = workDate;

  return (
    <div style={{ width: '100%', userSelect: 'none' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: '10px' }}>
        <button
          type="button"
          onClick={goToPrevMonth}
          aria-label="Mois précédent"
          className="btn btn-secondary"
          style={{ padding: '6px 10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <FiChevronLeft />
        </button>
        <div style={{ fontWeight: 800, fontSize: '0.9rem' }}>
          {MOIS[viewMonth]} {viewYear}
        </div>
        <button
          type="button"
          onClick={goToNextMonth}
          aria-label="Mois suivant"
          className="btn btn-secondary"
          style={{ padding: '6px 10px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}
        >
          <FiChevronRight />
        </button>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '4px', marginBottom: '4px' }}>
        {JOURS_SEMAINE.map(j => (
          <div key={j} style={{ textAlign: 'center', fontSize: '0.65rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase' }}>
            {j}
          </div>
        ))}
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(7, 1fr)', gap: '4px' }}>
        {cells.map((cell, idx) => {
          if (!cell) return <div key={`vide-${idx}`} />;
          const isSelected = cell.iso === value;
          const isToday = cell.iso === today;
          const isDisabled = cell.iso > effectiveMaxDate;
          return (
            <button
              key={cell.iso}
              type="button"
              disabled={isDisabled}
              onClick={() => !isDisabled && onSelect(cell.iso)}
              aria-current={isToday ? 'date' : undefined}
              aria-pressed={isSelected}
              style={{
                aspectRatio: '1 / 1',
                minHeight: '36px',
                border: isToday ? '1px solid hsl(var(--accent-color))' : '1px solid transparent',
                borderRadius: 'var(--radius-md)',
                background: isSelected ? 'hsl(var(--accent-color))' : 'transparent',
                color: isDisabled
                  ? 'hsl(var(--text-muted))'
                  : isSelected
                    ? 'white'
                    : 'hsl(var(--text-primary))',
                fontWeight: isSelected || isToday ? 800 : 500,
                fontSize: '0.8rem',
                cursor: isDisabled ? 'not-allowed' : 'pointer',
                opacity: isDisabled ? 0.4 : 1,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
              }}
            >
              {cell.day}
            </button>
          );
        })}
      </div>
    </div>
  );
};
