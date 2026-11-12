import React, { useEffect, useRef, useState } from 'react';
import { FiCheckCircle, FiAlertTriangle, FiClock } from 'react-icons/fi';
import { productionApi, ProductionSession } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { Modal } from '@/components/shared/Modal';
import { SignedIntegerField } from '@/components/production/SignedIntegerField';
import { ShiftEndPendingState } from '@/store/shiftEndStore';

// BUG-154 (docs/qa/REGISTRE_BUGS.md, demande client remarque.md après l.408, volet
// backend BUG-152) : la clôture d'une fournée doit permettre de déclarer en une seule
// action le « Reste du Jour » par catégorie de pain produite, au lieu d'exiger un passage
// préalable par le formulaire séparé « Stock Restant » (`BreadDisposalViewSet`, type
// REMAINING, toujours disponible en parallèle — voir §3.4 de Production.tsx).
// Contrat API consommé : docs/qa/rapports/dev-backend-2026-11-10-bug152-reste-jour-integre-cloture.md
// — `POST /api/production/sessions/<pk>/close/` avec corps optionnel
// `{"remaining": [{"bread_price": <id>, "quantity": <entier, peut être négatif (BUG-158/159)>}, ...]}`.
//
// Composant extrait de Production.tsx (CLAUDE.md §4 : extraction obligatoire des
// sous-composants ajoutés à une page de plus de ~1000 lignes), à l'image de
// `StockDuJourSection.tsx` (BUG-145) et `OpeningConfirmationManualSection.tsx` (BUG-151).

export interface CloseSessionModalProps {
  isOpen: boolean;
  /** BUG-188 : masquée mais montée (saisie conservée) pendant la désignation d'équipe. */
  suspended?: boolean;
  session: ProductionSession | null;
  onClose: () => void;
  /** Appelé avec la session mise à jour (is_closed=true, closure_summary) après succès. */
  onClosed: (updated: ProductionSession) => void;
  /**
   * BUG-156 : mode clôture FORCÉE (fin de créneau dépassée, fournée pas
   * close — `GET /api/production/sessions/shift-end-status/`, BUG-155),
   * piloté depuis `DashboardLayout` via `shiftEndStore.ts` plutôt que par le
   * bouton volontaire « Clôturer la fournée » ci-dessus (BUG-154). Non
   * `null`/`undefined` => mode forcé actif : `session` (prop ci-dessus) est
   * ignoré, pas de bouton « Annuler », quantités pré-remplies depuis
   * `quantity_suggested` (stock physique actuel) au lieu de 0. Comportement
   * volontaire strictement inchangé quand cette prop vaut `null`/`undefined`.
   */
  forced?: ShiftEndPendingState | null;
  /** Appelé avec la session mise à jour après une clôture FORCÉE réussie.
   *  Distinct de `onClosed` : l'appelant doit re-sonder immédiatement
   *  (CLAUDE.md §7) pour traiter l'autre équipe si elle aussi est en
   *  attente. Requis quand `forced` est fourni. */
  onForcedClose?: (updated: ProductionSession) => void;
}

interface UnifiedCategoryRow {
  bread_price: number;
  label: string;
  /** Quantité produite par la fournée (mode volontaire uniquement — non
   *  disponible en mode forcé, qui ne connaît que le reste suggéré). */
  producedQuantity?: number;
}

const formatWorkDay = (iso: string): string => {
  const [y, m, d] = iso.split('-');
  return `${d}/${m}/${y}`;
};

export const CloseSessionModal: React.FC<CloseSessionModalProps> = ({
  isOpen, session, onClose, onClosed, forced = null, onForcedClose, suspended = false,
}) => {
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [loadingExisting, setLoadingExisting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isForced = forced != null;
  // BUG-161 : boulangerie en rotation de 24 h — « journée de travail » au lieu de « créneau ».
  const isRotationForced = isForced && forced.rotation === true;
  // BUG-166 : clé stable du mode forcé (équipe + fournée). L'identité de l'objet
  // `forced` change à chaque sondage ; seule cette clé doit réinitialiser le formulaire.
  const forcedKey = forced ? `${forced.team}:${forced.session}` : null;
  const forcedRef = useRef<ShiftEndPendingState | null>(forced);
  forcedRef.current = forced;
  // Catégories saisies par l'utilisateur (jamais écrasées par un re-sondage).
  const touchedRef = useRef<Set<number>>(new Set());

  // À l'ouverture (ou changement de session/du mode) : remet les valeurs par
  // défaut pour chaque catégorie de CETTE fournée — 0 en mode volontaire (puis
  // tente de les pré-remplir avec un éventuel « Stock Restant » REMAINING déjà
  // déclaré séparément au préalable), `quantity_suggested` (stock physique
  // actuel) directement en mode forcé (BUG-156 — pas de REMAINING à relire :
  // le mode forcé ne peut survenir qu'avant toute clôture, donc avant toute
  // déclaration de reste pour cette session).
  useEffect(() => {
    touchedRef.current = new Set();
    if (!isOpen) {
      setQuantities({});
      setError(null);
      return;
    }
    if (isForced) {
      const defaults: Record<number, number> = {};
      (forcedRef.current?.remaining ?? []).forEach(line => { defaults[line.bread_price] = line.quantity_suggested; });
      setQuantities(defaults);
      setError(null);
      setLoadingExisting(false);
      return;
    }
    if (!session) {
      setQuantities({});
      setError(null);
      return;
    }
    const defaults: Record<number, number> = {};
    (session.lines || []).forEach(line => { defaults[line.bread_price] = 0; });
    setQuantities(defaults);
    setError(null);

    let cancelled = false;
    setLoadingExisting(true);
    productionApi.disposals.list({ session: session.id, disposal_type: 'REMAINING' })
      .then(res => {
        if (cancelled) return;
        const rows = Array.isArray(res.data) ? res.data : [];
        if (rows.length === 0) return;
        setQuantities(prev => {
          const next = { ...prev };
          rows.forEach(d => { next[d.bread_price] = d.quantity; });
          return next;
        });
      })
      .catch(() => { /* non bloquant : on garde les valeurs par défaut à 0 */ })
      .finally(() => { if (!cancelled) setLoadingExisting(false); });

    return () => { cancelled = true; };
  }, [isOpen, session, isForced, forcedKey]);

  // BUG-166 : si le serveur change `quantity_suggested` pendant la saisie, on ne
  // rafraîchit que les catégories jamais touchées par l'utilisateur.
  useEffect(() => {
    if (!isOpen || !forced) return;
    setQuantities(prev => {
      let changed = false;
      const next = { ...prev };
      forced.remaining.forEach(line => {
        if (!touchedRef.current.has(line.bread_price) && next[line.bread_price] !== line.quantity_suggested) {
          next[line.bread_price] = line.quantity_suggested;
          changed = true;
        }
      });
      return changed ? next : prev;
    });
  }, [isOpen, forced]);

  if (!isForced && !session) return null;

  const categories: UnifiedCategoryRow[] = isForced
    ? forced!.remaining.map(line => ({ bread_price: line.bread_price, label: line.label }))
    : (session!.lines || []).map(line => ({
        bread_price: line.bread_price,
        label: line.bread_price_display || `Pain ${line.unit_price} FC`,
        producedQuantity: line.quantity,
      }));

  const hasNegative = categories.some(cat => (quantities[cat.bread_price] ?? 0) < 0);

  const handleConfirm = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const remaining = categories.map(cat => ({
        bread_price: cat.bread_price,
        quantity: quantities[cat.bread_price] ?? 0,
      }));
      const sessionId = isForced ? forced!.session : session!.id;
      const res = await productionApi.sessions.close(sessionId, { remaining });
      if (isForced) {
        onForcedClose?.(res.data);
      } else {
        onClosed(res.data);
        onClose();
      }
    } catch (err: unknown) {
      setError(getErrorDetail(err, 'Erreur lors de la clôture de la fournée.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      suspended={suspended}
      onClose={() => { if (!submitting && !isForced) onClose(); }}
      title={isForced
        ? (isRotationForced ? `Clôture de la journée de travail — Équipe ${forced!.team}` : `Clôture du créneau — Équipe ${forced!.team}`)
        : 'Clôturer la Fournée'}
      subtitle={
        isForced
          ? (isRotationForced
            ? `La journée de travail${forced!.workDate ? ` du ${formatWorkDay(forced!.workDate)}` : ''} de l'équipe ${forced!.team} est terminée (heure de relève) et la fournée n'a pas encore été clôturée. Confirmez le reste du jour pour continuer.`
            : "Le créneau de cette équipe est terminé et la fournée n'a pas encore été clôturée. Confirmez le reste du jour pour continuer.")
          : 'Reste du Jour par catégorie — déclaré en même temps que la clôture.'
      }
      maxWidth="460px"
      closeOnBackdropClick={!submitting && !isForced}
      showCloseButton={!isForced}
      footer={
        <>
          {!isForced && (
            <button
              type="button"
              onClick={onClose}
              disabled={submitting}
              className="btn btn-secondary"
              style={{ flex: 1, padding: '9px', fontSize: '0.8rem' }}
            >
              Annuler
            </button>
          )}
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            className="btn btn-primary"
            style={{
              flex: isForced ? 1 : 2, padding: '9px', fontSize: '0.8rem', display: 'flex', alignItems: 'center',
              justifyContent: 'center', gap: '6px', opacity: submitting ? 0.6 : 1,
              backgroundColor: 'hsl(var(--color-success))', borderColor: 'hsl(var(--color-success))',
            }}
          >
            <FiCheckCircle />
            {submitting ? 'Clôture en cours...' : 'Confirmer la clôture'}
          </button>
        </>
      }
    >
      {isForced && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '8px', fontSize: '0.74rem',
          color: 'hsl(var(--color-warning))', backgroundColor: 'hsl(var(--color-warning) / 0.1)',
          padding: '8px 10px', borderRadius: 'var(--radius-sm)', marginBottom: '12px',
        }}>
          <FiClock style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>
            Cette boîte ne peut pas être fermée sans validation : passé un délai de 30 minutes
            après {isRotationForced ? "l'heure de relève" : 'la fin du créneau'}, le serveur clôturera automatiquement cette fournée avec le
            stock physique actuel.
          </span>
        </div>
      )}

      <p style={{ fontSize: '0.74rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
        Pour chaque catégorie produite par cette fournée, indiquez le reste du jour (pains
        invendus, non livrés). Laissez à 0 si tout a été écoulé. Le reste peut être négatif
        si les ventes et sorties dépassent la production (stock négatif enregistré tel quel). Cette action recoupe
        automatiquement les ventes et dispositions du jour avec la production déclarée —
        elle est <strong>irréversible</strong> : la fournée ne sera plus modifiable.
      </p>

      {loadingExisting && (
        <p style={{ fontSize: '0.68rem', color: 'hsl(var(--text-muted))', marginBottom: '8px' }}>
          Vérification d'un éventuel reste déjà déclaré séparément…
        </p>
      )}

      {categories.length === 0 ? (
        <div style={{ textAlign: 'center', padding: '14px', color: 'hsl(var(--text-muted))', fontSize: '0.72rem' }}>
          Aucune catégorie de pain produite sur cette fournée.
        </div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', marginBottom: '14px' }}>
          {categories.map(cat => (
            <div
              key={cat.bread_price}
              style={{
                display: 'grid', gridTemplateColumns: '1fr 140px', alignItems: 'center', gap: '10px',
                padding: '7px 10px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)',
              }}
            >
              <div>
                <div style={{ fontWeight: 800, fontSize: '0.78rem', color: 'hsl(var(--accent-color))' }}>
                  {cat.label}
                </div>
                {cat.producedQuantity !== undefined && (
                  <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>
                    Produits : {cat.producedQuantity}
                  </div>
                )}
              </div>
              <SignedIntegerField
                value={quantities[cat.bread_price] ?? 0}
                onChange={n => {
                  touchedRef.current.add(cat.bread_price);
                  setQuantities(prev => ({ ...prev, [cat.bread_price]: n }));
                }}
                disabled={submitting}
                ariaLabel={`Reste du jour — ${cat.label}`}
              />
            </div>
          ))}
        </div>
      )}

      {hasNegative && (
        <div style={{
          display: 'flex', alignItems: 'flex-start', gap: '6px', fontSize: '0.7rem', marginBottom: '10px',
          color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)',
          padding: '7px 10px', borderRadius: 'var(--radius-sm)',
        }}>
          <FiAlertTriangle style={{ flexShrink: 0, marginTop: '1px' }} />
          <span>Stock négatif : ventes/sorties supérieures à la production. La valeur sera enregistrée telle quelle.</span>
        </div>
      )}

      {error && (
        <div style={{
          display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.72rem',
          color: 'hsl(var(--color-danger))', backgroundColor: 'hsl(var(--color-danger) / 0.08)',
          padding: '8px 10px', borderRadius: 'var(--radius-sm)',
        }}>
          <FiAlertTriangle style={{ flexShrink: 0 }} /> {error}
        </div>
      )}
    </Modal>
  );
};
