import React, { useEffect, useRef, useState, useCallback } from 'react';
import { Modal } from '@/components/shared/Modal';
import { SignedIntegerField } from '@/components/production/SignedIntegerField';
import { getErrorDetail, isTeamNotAssignedError } from '@/api/errors';
import { useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { useAuthStore } from '@/store/authStore';
import {
  productionApi,
  OpeningConfirmationReport,
  OpeningConfirmationTeam,
} from '@/api/services';

/** Durée d'affichage du bandeau de confirmation d'ajustement (BUG-137). */
const ADJUSTMENT_MESSAGE_DURATION_MS = 7000;

/**
 * BUG-133/134 (docs/qa/REGISTRE_BUGS.md) : boîte modale « stock de départ ».
 *
 * Demande client (remarque.md l.396) : à sa première connexion de la
 * journée, le gérant doit voir une boîte modale qui propose, par catégorie
 * de pain, le stock de départ (`BreadStock.qty_available`). Il peut le
 * modifier ou le valider directement. Précision ajoutée en cours de
 * mission : ce n'est PAS un prompt ponctuel au login — elle doit se
 * réafficher à CHAQUE changement de page tant qu'aucune confirmation
 * n'existe pour (nœud, équipe, aujourd'hui).
 *
 * Monté une seule fois par `DashboardLayout` (pas page par page — consigne
 * explicite du coordinateur). Ce composant porte la logique de requête
 * (montage + changement de route, via `routeKey`) et d'affichage ; le
 * layout ne fait que décider QUAND le monter (rôle GERANT non-HQ).
 */

interface OpeningStockConfirmationModalProps {
  /** Change de valeur à chaque navigation (ex. `location.pathname`) pour
   *  déclencher une nouvelle interrogation du GET, léger par construction
   *  côté backend (voir BUG-133). */
  routeKey: string;
  /**
   * BUG-151 : déclenchement MANUEL, indépendant de l'affichage automatique.
   * Quand non `null`/`undefined`, la boîte modale s'ouvre pour CETTE équipe
   * précise, qu'elle soit « due » ou non du point de vue de
   * `report.needs_confirmation` (qui ne considère que l'équipe du créneau
   * d'ouverture, BUG-141) — ce prop sert le cas où un gérant/facturier veut
   * confirmer volontairement le reste d'hier de l'AUTRE équipe plus tard
   * dans la journée, depuis « Production & Stocks »
   * (`OpeningConfirmationManualSection.tsx`). Le comportement automatique
   * existant (BUG-133 à 141) reste strictement inchangé quand ce prop vaut
   * `null`/`undefined`.
   */
  forceOpenForTeam?: OpeningConfirmationTeam | null;
  /** BUG-151 : appelé quand le flux manuel se termine (fermeture ou
   *  soumission réussie) — permet à l'appelant de réinitialiser son état
   *  (`openingConfirmationStore`) sans que ce composant connaisse son
   *  existence. */
  onManualClose?: () => void;
  /** BUG-188 : masquée mais montée (saisie conservée) pendant la désignation d'équipe. */
  suspended?: boolean;
  /**
   * BUG-161 (rotation de 24 h) : compteur incrémenté par le layout dans son cycle de sondage
   * existant (pas de second `setInterval`). Un changement relit le GET en silence (sans écraser
   * une saisie) : la boîte s'ouvre d'elle-même à l'heure de relève, sans rechargement de page.
   * `undefined` hors rotation : aucun sondage supplémentaire, comportement inchangé.
   */
  pollKey?: number;
  /** BUG-161 : heure de relève de la boulangerie (« HH:MM »), rappelée dans la boîte en rotation. */
  handoverTime?: string | null;
}

type DraftLines = Record<number, string>;

function parseDraft(raw: string | undefined): number {
  const n = raw === undefined || raw === '' ? 0 : parseInt(raw, 10);
  return Number.isFinite(n) ? n : 0;
}

function buildDraftFromProposed(report: OpeningConfirmationReport): DraftLines {
  const draft: DraftLines = {};
  for (const category of report.categories) {
    draft[category.bread_price] = String(category.qty_proposed);
  }
  return draft;
}

/** Équipe à proposer en priorité (filet de sécurité, BUG-134) : s'il n'en
 *  reste qu'une à confirmer, présélectionnée pour l'ergonomie (reste
 *  modifiable), sinon 'A'. Utilisée seulement quand `opening_team` du
 *  backend est `null` (nœud sans créneaux horaires configurés, BUG-130) —
 *  voir `resolveDefaultTeam` ci-dessous (BUG-139/140). */
function pickDefaultTeam(report: OpeningConfirmationReport): OpeningConfirmationTeam {
  const aConfirmed = report.teams.A.confirmed;
  const bConfirmed = report.teams.B.confirmed;
  if (!aConfirmed && bConfirmed) return 'A';
  if (aConfirmed && !bConfirmed) return 'B';
  return 'A';
}

/**
 * BUG-139/140 : résout l'équipe à présélectionner dans le sélecteur A/B.
 * Priorité :
 * 1. `report.opening_team` (équipe active au créneau d'ouverture, calculée
 *    côté serveur via `Node.active_team_at()`, BUG-130) quand elle est
 *    connue — c'est la demande explicite du client (remarque.md l.398).
 * 2. Sinon (nœud sans créneaux configurés, `opening_team === null`) : filet
 *    de sécurité inchangé, `pickDefaultTeam` (équipe non encore confirmée).
 */
function resolveDefaultTeam(
  report: OpeningConfirmationReport,
  userTeam?: OpeningConfirmationTeam | null,
): OpeningConfirmationTeam {
  if (report.opening_team) return report.opening_team;
  // Nœud sans créneaux configurés (BUG-130/131) : à défaut d'équipe active
  // connue, l'équipe propre du facturier (quand elle est disponible et pas
  // déjà confirmée) reste un repère plus pertinent que le filet de sécurité
  // générique ci-dessous.
  if (userTeam && !report.teams[userTeam].confirmed) return userTeam;
  return pickDefaultTeam(report);
}

export const OpeningStockConfirmationModal: React.FC<OpeningStockConfirmationModalProps> = ({
  routeKey, forceOpenForTeam = null, onManualClose, suspended = false, pollKey, handoverTime = null,
}) => {
  const { user } = useAuthStore();
  // `UserProfile.team` est `'A' | 'B' | ''` (facturiers/livreurs) — on ne
  // transmet que les valeurs utiles à `resolveDefaultTeam`.
  const userTeam: OpeningConfirmationTeam | null =
    user && (user.team === 'A' || user.team === 'B') ? user.team : null;
  const [report, setReport] = useState<OpeningConfirmationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTeam, setSelectedTeam] = useState<OpeningConfirmationTeam>('A');
  const [draft, setDraft] = useState<DraftLines>({});
  const [submitting, setSubmitting] = useState(false);
  // Fermeture temporaire (« plus tard ») : ne doit durer que jusqu'au
  // prochain changement de page (CLAUDE.md §7 règle 6 — ergonomie laissée à
  // dev-frontend, pas un prompt qu'on peut ignorer toute la session).
  const [dismissedForRoute, setDismissedForRoute] = useState<string | null>(null);
  // BUG-137 : message temporaire listant les ajustements de stock appliqués
  // par le backend (BUG-136) lors de la dernière soumission réussie. `null`
  // = rien à afficher (cas normal : validation telle que proposée).
  const [adjustmentMessages, setAdjustmentMessages] = useState<string[] | null>(null);
  const adjustmentTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    return () => {
      if (adjustmentTimeoutRef.current) {
        clearTimeout(adjustmentTimeoutRef.current);
      }
    };
  }, []);

  const requestTeamAssignment = useTeamAssignmentStore(st => st.requestAssignment);
  // BUG-161 : en rotation, la proposition (`qty_proposed`) = reste de l'équipe précédente ; elle
  // n'écrase jamais une saisie en cours (`touchedRef`), seulement un formulaire intact.
  const proposalKeyRef = useRef('');
  const touchedRef = useRef(false);

  const fetchReport = useCallback(async (silent = false) => {
    if (!silent) {
      setLoading(true);
      setError(null);
    }
    try {
      const response = await productionApi.openingConfirmation.get();
      const data = response.data;
      setReport(data);
      if (data.rotation) {
        // Rotation : une seule équipe de service par journée (celle désignée), plus de choix A/B.
        const workDay = data.work_date ?? data.date;
        const key = `${workDay}|${data.categories.map(c => `${c.bread_price}:${c.qty_proposed}`).join(',')}`;
        if (!proposalKeyRef.current.startsWith(`${workDay}|`)) touchedRef.current = false;
        if (key !== proposalKeyRef.current) {
          proposalKeyRef.current = key;
          if (!touchedRef.current) setDraft(buildDraftFromProposed(data));
        }
        setSelectedTeam(data.team ?? data.opening_team ?? 'A');
      } else {
        proposalKeyRef.current = '';
        const defaultTeam = resolveDefaultTeam(data, userTeam);
        setSelectedTeam(defaultTeam);
        setDraft(buildDraftFromProposed(data));
      }
    } catch (err: unknown) {
      if (!silent) setError(getErrorDetail(err, "Erreur lors du chargement du stock de départ."));
    } finally {
      if (!silent) setLoading(false);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userTeam]);

  // BUG-161 : relecture silencieuse à chaque tick du sondage du layout (rotation seulement).
  const lastPollKeyRef = useRef(pollKey);
  useEffect(() => {
    if (pollKey === undefined || pollKey === lastPollKeyRef.current) {
      lastPollKeyRef.current = pollKey;
      return;
    }
    lastPollKeyRef.current = pollKey;
    void fetchReport(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pollKey]);

  // Montage + chaque changement de route (routeKey).
  useEffect(() => {
    fetchReport();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [routeKey]);

  // BUG-151 : mode manuel — préselectionne l'équipe demandée par l'appelant,
  // indépendamment de `resolveDefaultTeam` (qui ne regarde que le créneau
  // d'ouverture / le filet de sécurité automatique).
  const isManualMode = forceOpenForTeam != null;
  useEffect(() => {
    if (forceOpenForTeam) {
      setSelectedTeam(forceOpenForTeam);
    }
  }, [forceOpenForTeam]);

  // BUG-139/140 : signal unique renvoyé par le backend (remplace l'ancien
  // calcul `!teams.A.confirmed || !teams.B.confirmed`, qui exigeait les
  // deux équipes — contraire à la demande du client, une seule confirmation
  // suffit pour l'équipe du créneau d'ouverture).
  const needsConfirmation = report != null && report.needs_confirmation;
  // BUG-137 : si la dernière confirmation a complété les DEUX équipes, la
  // boîte modale n'a normalement plus rien à demander — mais on la laisse
  // ouverte le temps d'afficher le bandeau d'ajustement plutôt que de la
  // faire disparaître sans que le gérant ait pu le lire.
  const hasVisibleAdjustmentMessage = adjustmentMessages != null && adjustmentMessages.length > 0;
  // BUG-151 : le mode manuel ouvre la boîte modale indépendamment de
  // `needsConfirmation`/`dismissedForRoute` (qui ne pilotent que
  // l'affichage automatique).
  const isOpen = isManualMode || ((needsConfirmation || hasVisibleAdjustmentMessage) && dismissedForRoute !== routeKey);

  const isRotation = report?.rotation === true;

  const handleQtyChange = (breadPriceId: number, value: string) => {
    touchedRef.current = true;
    setDraft(prev => ({ ...prev, [breadPriceId]: value }));
  };

  const handleSubmit = async () => {
    if (!report) return;
    setSubmitting(true);
    setError(null);
    setAdjustmentMessages(null);
    if (adjustmentTimeoutRef.current) {
      clearTimeout(adjustmentTimeoutRef.current);
      adjustmentTimeoutRef.current = null;
    }
    try {
      const lines = report.categories.map(category => {
        const raw = draft[category.bread_price];
        const parsed = raw === undefined || raw === '' ? 0 : parseInt(raw, 10);
        // BUG-162 : un stock de départ négatif est enregistré tel quel (décision client).
        return { bread_price: category.bread_price, qty: Number.isFinite(parsed) ? parsed : 0 };
      });
      // Rotation : le serveur décide de l'équipe (désignée) et de la journée ; ni `team` ni `date`.
      const { data } = await productionApi.openingConfirmation.submit(
        isRotation ? { lines } : { team: selectedTeam, lines },
      );
      touchedRef.current = false;
      proposalKeyRef.current = '';
      // BUG-137 : la boîte modale confirme toujours UNE catégorie à la fois
      // pour l'équipe sélectionnée au moment de la soumission — on résout
      // les libellés avant que `fetchReport` ne remplace `report`.
      if (data.stock_adjustments.length > 0) {
        const messages = data.stock_adjustments.map(adjustment => {
          const category = report.categories.find(c => c.bread_price === adjustment.bread_price_id);
          const label = category ? category.label : `catégorie #${adjustment.bread_price_id}`;
          return `Stock [${label}] ajusté de ${adjustment.before} à ${adjustment.after}.`;
        });
        setAdjustmentMessages(messages);
        adjustmentTimeoutRef.current = setTimeout(() => {
          setAdjustmentMessages(null);
        }, ADJUSTMENT_MESSAGE_DURATION_MS);
      }
      // Reposer le GET : si l'autre équipe reste à confirmer, la modale
      // doit immédiatement proposer sa confirmation (demande explicite).
      await fetchReport();
      // BUG-151 : le mode manuel est un geste ponctuel pour UNE équipe —
      // une fois soumis avec succès, on referme (l'appelant réinitialise
      // son état via `onManualClose`). Le comportement automatique n'est
      // pas affecté : en dehors du mode manuel, la boîte modale reste
      // ouverte si une autre confirmation est encore due (inchangé).
      if (isManualMode) {
        onManualClose?.();
      }
    } catch (err: unknown) {
      if (isTeamNotAssignedError(err)) {
        // BUG-161 : équipe de service non désignée — la boîte de désignation se rouvre.
        requestTeamAssignment();
      }
      setError(getErrorDetail(err, "Erreur lors de la validation du stock de départ."));
    } finally {
      setSubmitting(false);
    }
  };

  const handleDismiss = () => {
    if (isManualMode) {
      // BUG-151 : fermeture du flux manuel — ne touche pas
      // `dismissedForRoute` (propre à l'affichage automatique).
      onManualClose?.();
      return;
    }
    setDismissedForRoute(routeKey);
  };

  if (!needsConfirmation && !hasVisibleAdjustmentMessage && !isManualMode) {
    return null;
  }

  const otherTeam: OpeningConfirmationTeam = selectedTeam === 'A' ? 'B' : 'A';
  const otherTeamConfirmed = report ? report.teams[otherTeam].confirmed : false;

  return (
    <Modal
      isOpen={isOpen}
      suspended={suspended}
      onClose={handleDismiss}
      title="Stock de départ du jour"
      subtitle={
        isManualMode
          ? `Confirmation volontaire du reste d'hier pour l'équipe ${selectedTeam} (demande manuelle depuis Production & Stocks).`
          : isRotation
            ? `Équipe de service : ${selectedTeam}${handoverTime ? ` — relève de ${handoverTime}` : ''}. Confirmez ou corrigez le reste de l'équipe précédente pour démarrer la journée de travail.`
            : "Confirmez ou corrigez le nombre de pains restants par catégorie pour démarrer la journée."
      }
      maxWidth="560px"
      closeOnBackdropClick={false}
      footer={
        needsConfirmation || isManualMode ? (
          <>
            <button
              onClick={handleDismiss}
              className="btn btn-secondary"
              style={{ padding: '10px 18px', fontSize: '0.85rem' }}
              disabled={submitting}
            >
              {isManualMode ? 'Annuler' : 'Plus tard'}
            </button>
            <button
              onClick={handleSubmit}
              className="btn btn-primary"
              style={{ padding: '10px 18px', fontSize: '0.85rem' }}
              disabled={submitting || loading || !report}
            >
              {submitting ? 'Validation...' : isRotation && !isManualMode ? 'Valider le stock de départ' : `Valider pour l'équipe ${selectedTeam}`}
            </button>
          </>
        ) : (
          // BUG-137 : les deux équipes sont déjà confirmées — seul le
          // bandeau d'ajustement reste à montrer, le temps de le lire.
          <button
            onClick={handleDismiss}
            className="btn btn-primary"
            style={{ padding: '10px 18px', fontSize: '0.85rem' }}
          >
            Fermer
          </button>
        )
      }
    >
      {loading && !report && (
        <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))' }}>
          Chargement du stock disponible...
        </div>
      )}

      {error && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            marginBottom: '16px',
            fontSize: '0.85rem',
            fontWeight: 600,
            backgroundColor: 'hsl(var(--color-danger) / 0.12)',
            color: 'hsl(var(--color-danger))',
            border: '1px solid hsl(var(--color-danger) / 0.3)',
          }}
        >
          {error}
        </div>
      )}

      {hasVisibleAdjustmentMessage && (
        <div
          style={{
            padding: '10px 14px',
            borderRadius: 'var(--radius-md)',
            marginBottom: '16px',
            fontSize: '0.85rem',
            fontWeight: 600,
            backgroundColor: 'hsl(var(--color-success) / 0.12)',
            color: 'hsl(var(--color-success))',
            border: '1px solid hsl(var(--color-success) / 0.3)',
          }}
        >
          {adjustmentMessages!.map((message, index) => (
            <div key={index}>{message}</div>
          ))}
        </div>
      )}

      {report && (needsConfirmation || isManualMode) && (
        <>
          {isRotation && !isManualMode ? (
            <div style={{ marginBottom: '16px', padding: '10px 12px', borderRadius: 'var(--radius-md)', border: '1px solid hsl(var(--border-color))', fontSize: '0.85rem' }}>
              <strong>Équipe de service du jour : {selectedTeam}</strong>
              <div style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', marginTop: '4px' }}>
                Les quantités proposées sont le reste de l'équipe précédente.
              </div>
            </div>
          ) : (
          <div style={{ marginBottom: '16px' }}>
            <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              Équipe concernée
            </label>
            <div style={{ display: 'flex', gap: '8px' }}>
              {(['A', 'B'] as OpeningConfirmationTeam[]).map(team => {
                const alreadyConfirmed = report.teams[team].confirmed;
                return (
                  <button
                    key={team}
                    type="button"
                    onClick={() => setSelectedTeam(team)}
                    disabled={alreadyConfirmed}
                    className={selectedTeam === team ? 'btn btn-primary' : 'btn btn-secondary'}
                    style={{ flex: 1, padding: '12px', fontSize: '0.9rem', fontWeight: 700, opacity: alreadyConfirmed ? 0.5 : 1 }}
                    title={alreadyConfirmed ? `Équipe ${team} déjà confirmée aujourd'hui` : `Confirmer le stock de départ de l'équipe ${team}`}
                  >
                    Équipe {team} {alreadyConfirmed ? '(déjà confirmée)' : ''}
                  </button>
                );
              })}
            </div>
            {otherTeamConfirmed && (
              <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', marginTop: '8px' }}>
                L'équipe {otherTeam} a déjà été confirmée aujourd'hui{report.teams[otherTeam].confirmed_by ? ` par ${report.teams[otherTeam].confirmed_by}` : ''}.
              </p>
            )}
          </div>
          )}

          <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '8px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
            Pains restants par catégorie
          </label>

          {report.categories.some(c => parseDraft(draft[c.bread_price]) < 0) && (
            <div style={{
              fontSize: '0.78rem', marginBottom: '10px', color: 'hsl(var(--color-danger))',
              backgroundColor: 'hsl(var(--color-danger) / 0.08)', padding: '8px 10px', borderRadius: 'var(--radius-sm)',
            }}>
              Stock négatif : la valeur sera enregistrée telle quelle.
            </div>
          )}

          {report.categories.length === 0 ? (
            <div style={{ textAlign: 'center', padding: '24px', color: 'hsl(var(--text-muted))', fontSize: '0.85rem' }}>
              Aucune catégorie de pain active pour cette boulangerie.
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px', maxHeight: '45vh', overflowY: 'auto', paddingRight: '4px' }}>
              {report.categories.map(category => (
                <div
                  key={category.bread_price}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: '12px',
                    padding: '10px 12px',
                    borderRadius: 'var(--radius-md)',
                    border: '1px solid hsl(var(--border-color))',
                  }}
                >
                  <div style={{ minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.9rem', color: 'hsl(var(--text-primary))' }}>
                      {category.label}
                    </div>
                  </div>
                  <SignedIntegerField
                    value={parseDraft(draft[category.bread_price])}
                    onChange={n => handleQtyChange(category.bread_price, String(n))}
                    ariaLabel={`Stock de départ — ${category.label}`}
                    disabled={submitting}
                    width="150px"
                  />
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </Modal>
  );
};
