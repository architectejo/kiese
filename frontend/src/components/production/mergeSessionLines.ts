import type { ProductionSessionLine } from '@/api/services';

// BUG-305 : « Détail Fournée » répétait les catégories de pains. Fusionne les lignes de
// même catégorie (bread_price) : une seule ligne par catégorie, quantités et valeurs sommées.
// BUG-310 : le reste d'hier (source CARRYOVER) n'entre pas dans « Pains produits » ni dans
// le TOTAL : il est exclu ici pour que somme des lignes = total ; voir `carryoverLines`.
const isCarryover = (line: ProductionSessionLine): boolean => line.source === 'CARRYOVER';

/** Lignes « reste d'hier » (confirmées au départ de la fournée), fusionnées par catégorie. */
export const carryoverLines = (lines: ProductionSessionLine[]): ProductionSessionLine[] =>
  mergeSessionLines(lines.filter(isCarryover), true);

export const mergeSessionLines = (
  lines: ProductionSessionLine[],
  includeCarryover = false,
): ProductionSessionLine[] => {
  const byCategory = new Map<number, ProductionSessionLine>();
  lines.forEach(line => {
    if (!includeCarryover && isCarryover(line)) return;
    const unit = line.unit_price || 0;
    const lineFc = line.line_fc ?? line.quantity * unit;
    const existing = byCategory.get(line.bread_price);
    if (existing) {
      existing.quantity += line.quantity;
      existing.line_fc = (existing.line_fc ?? 0) + lineFc;
    } else {
      byCategory.set(line.bread_price, { ...line, line_fc: lineFc });
    }
  });
  return Array.from(byCategory.values()).sort((a, b) => (a.unit_price || 0) - (b.unit_price || 0));
};
