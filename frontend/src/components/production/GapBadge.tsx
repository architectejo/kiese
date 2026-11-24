import React from 'react';
import { classifyGap, formatGapFc, GAP_LABELS, sessionGap, type GapKind, type GapSessionLike } from '@/utils/fourneeGap';

const COLORS: Record<GapKind, string> = {
  EXCEDENT: 'hsl(var(--color-success))',
  EQUILIBRE: 'hsl(var(--text-secondary))',
  MANQUANT: 'hsl(var(--color-danger))',
};

export interface GapBadgeProps {
  /** Écart = théorique − produit (FC) ; `null` si non calculable. */
  ecart?: number | null;
  /** Alternative : passer la fournée, l'écart est alors calculé. */
  session?: GapSessionLike;
  fontSize?: string;
}

/** Badge « Excédent / Équilibre / Manquant » + valeur FC ; « — » si non calculable. */
export const GapBadge: React.FC<GapBadgeProps> = ({ ecart, session, fontSize = '0.62rem' }) => {
  const value = session ? sessionGap(session) : (ecart ?? null);
  if (value === null || !Number.isFinite(value)) {
    return <span data-testid="gap-badge" data-gap="NA" title="Écart non calculable" style={{ fontSize, color: 'hsl(var(--text-muted))' }}>—</span>;
  }
  const kind = classifyGap(value);
  const color = COLORS[kind];
  return (
    <span
      data-testid="gap-badge"
      data-gap={kind}
      style={{
        display: 'inline-flex', flexWrap: 'wrap', alignItems: 'center', gap: '4px', fontSize, fontWeight: 800,
        color, backgroundColor: `color-mix(in srgb, ${color} 12%, transparent)`,
        border: `1px solid color-mix(in srgb, ${color} 35%, transparent)`,
        borderRadius: '999px', padding: '1px 8px', whiteSpace: 'nowrap', maxWidth: '100%',
      }}
    >
      {GAP_LABELS[kind]} · {formatGapFc(value)}
    </span>
  );
};
