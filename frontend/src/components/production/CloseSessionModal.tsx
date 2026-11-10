import React, { useEffect, useState } from 'react';
import { FiCheckCircle, FiAlertTriangle } from 'react-icons/fi';
import { productionApi, ProductionSession } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { Modal } from '@/components/shared/Modal';

// BUG-154 (docs/qa/REGISTRE_BUGS.md, demande client remarque.md après l.408, volet
// backend BUG-152) : la clôture d'une fournée doit permettre de déclarer en une seule
// action le « Reste du Jour » par catégorie de pain produite, au lieu d'exiger un passage
// préalable par le formulaire séparé « Stock Restant » (`BreadDisposalViewSet`, type
// REMAINING, toujours disponible en parallèle — voir §3.4 de Production.tsx).
// Contrat API consommé : docs/qa/rapports/dev-backend-2026-11-10-bug152-reste-jour-integre-cloture.md
// — `POST /api/production/sessions/<pk>/close/` avec corps optionnel
// `{"remaining": [{"bread_price": <id>, "quantity": <entier >= 0>}, ...]}`.
//
// Composant extrait de Production.tsx (CLAUDE.md §4 : extraction obligatoire des
// sous-composants ajoutés à une page de plus de ~1000 lignes), à l'image de
// `StockDuJourSection.tsx` (BUG-145) et `OpeningConfirmationManualSection.tsx` (BUG-151).

export interface CloseSessionModalProps {
  isOpen: boolean;
  session: ProductionSession | null;
  onClose: () => void;
  /** Appelé avec la session mise à jour (is_closed=true, closure_summary) après succès. */
  onClosed: (updated: ProductionSession) => void;
}

export const CloseSessionModal: React.FC<CloseSessionModalProps> = ({ isOpen, session, onClose, onClosed }) => {
  const [quantities, setQuantities] = useState<Record<number, number>>({});
  const [loadingExisting, setLoadingExisting] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // À l'ouverture (ou changement de session) : remet les valeurs par défaut à 0 pour chaque
  // catégorie produite par CETTE fournée, puis tente de les pré-remplir avec un éventuel
  // « Stock Restant » (REMAINING) déjà déclaré séparément au préalable pour cette session —
  // un seul appel réseau supplémentaire, scopé par session et type (filterset_fields backend),
  // pas de récupération « triviale » possible depuis les données déjà chargées par
  // Production.tsx (la liste `disposals` de la page n'est ni filtrée par session, ni garantie
  // d'inclure cette fournée — tronquée aux 20 plus récentes). Volontairement découplé du
  // stock physique global (`BreadStock.qty_available`) : on NE pré-remplit PAS avec celui-ci,
  // voir docstring de `DailyBreadStockSnapshot` (backend/production/models.py).
  useEffect(() => {
    if (!isOpen || !session) {
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
  }, [isOpen, session]);

  if (!session) return null;

  const categories = session.lines || [];

  const handleQtyChange = (breadPriceId: number, raw: string) => {
    const n = Math.max(0, Math.floor(Number(raw) || 0));
    setQuantities(prev => ({ ...prev, [breadPriceId]: n }));
  };

  const handleConfirm = async () => {
    setError(null);
    setSubmitting(true);
    try {
      const remaining = categories.map(line => ({
        bread_price: line.bread_price,
        quantity: quantities[line.bread_price] ?? 0,
      }));
      const res = await productionApi.sessions.close(session.id, { remaining });
      onClosed(res.data);
      onClose();
    } catch (err: unknown) {
      setError(getErrorDetail(err, 'Erreur lors de la clôture de la fournée.'));
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={() => { if (!submitting) onClose(); }}
      title="Clôturer la Fournée"
      subtitle="Reste du Jour par catégorie — déclaré en même temps que la clôture."
      maxWidth="460px"
      closeOnBackdropClick={!submitting}
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            disabled={submitting}
            className="btn btn-secondary"
            style={{ flex: 1, padding: '9px', fontSize: '0.8rem' }}
          >
            Annuler
          </button>
          <button
            type="button"
            onClick={handleConfirm}
            disabled={submitting}
            className="btn btn-primary"
            style={{
              flex: 2, padding: '9px', fontSize: '0.8rem', display: 'flex', alignItems: 'center',
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
      <p style={{ fontSize: '0.74rem', color: 'hsl(var(--text-secondary))', marginBottom: '12px' }}>
        Pour chaque catégorie produite par cette fournée, indiquez le reste du jour (pains
        invendus, non livrés). Laissez à 0 si tout a été écoulé. Cette action recoupe
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
          {categories.map(line => (
            <div
              key={line.bread_price}
              style={{
                display: 'grid', gridTemplateColumns: '1fr 100px', alignItems: 'center', gap: '10px',
                padding: '7px 10px', border: '1px solid hsl(var(--border-color))', borderRadius: 'var(--radius-sm)',
              }}
            >
              <div>
                <div style={{ fontWeight: 800, fontSize: '0.78rem', color: 'hsl(var(--accent-color))' }}>
                  {line.bread_price_display || `Pain ${line.unit_price} FC`}
                </div>
                <div style={{ fontSize: '0.6rem', color: 'hsl(var(--text-muted))' }}>
                  Produits : {line.quantity}
                </div>
              </div>
              <input
                type="number"
                min={0}
                step={1}
                value={quantities[line.bread_price] ?? 0}
                onChange={e => handleQtyChange(line.bread_price, e.target.value)}
                disabled={submitting}
                className="form-input"
                style={{ height: '34px', fontSize: '0.85rem', textAlign: 'right', padding: '0 8px' }}
                aria-label={`Reste du jour — ${line.bread_price_display || line.bread_price}`}
              />
            </div>
          ))}
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
