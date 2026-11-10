import React, { useEffect, useState, useCallback } from 'react';
import { FiCheckCircle } from 'react-icons/fi';
import { productionApi, OpeningConfirmationReport, OpeningConfirmationTeam } from '@/api/services';
import { getErrorDetail } from '@/api/errors';
import { useOpeningConfirmationStore } from '@/store/openingConfirmationStore';

/**
 * BUG-151 (docs/qa/REGISTRE_BUGS.md, remarque.md après l.406) : « Une fois les restes
 * d'hier d'une équipe sont confirmés, dans "Production & Stocks" les gérants doivent
 * avoir la possibilité de confirmer les restes d'hier pour une autre équipe ».
 *
 * Depuis BUG-139/140/141, une seule confirmation (celle de l'équipe du créneau
 * d'ouverture) suffit à faire disparaître la boîte modale AUTOMATIQUE
 * (`OpeningStockConfirmationModal.tsx`, montée par `DashboardLayout.tsx`) — ce qui ne
 * laisse plus aucun moyen de confirmer volontairement le reste d'hier de l'AUTRE
 * équipe plus tard dans la journée. Ce composant propose, pour chaque équipe PAS
 * encore confirmée aujourd'hui, un bouton qui déclenche cette même boîte modale en
 * mode manuel (`openingConfirmationStore.requestManualConfirmation`), sans dupliquer
 * sa logique de formulaire/soumission.
 *
 * Extrait dans son propre fichier (CLAUDE.md §4 — `Production.tsx` dépasse ~1000
 * lignes) plutôt que codé en ligne dans `Production.tsx`, à l'image de
 * `StockDuJourSection.tsx` (BUG-145).
 */
export interface OpeningConfirmationManualSectionProps {
  /** Rafraîchi après une confirmation manuelle réussie (mêmes effets de bord que la
   *  confirmation automatique : BUG-142 lie la confirmation à la fournée du jour,
   *  BUG-136 ajuste le stock disponible — `Production.tsx` recharge tout avec
   *  `loadData()`). */
  onConfirmed: () => void;
}

export const OpeningConfirmationManualSection: React.FC<OpeningConfirmationManualSectionProps> = ({ onConfirmed }) => {
  const { forceOpenForTeam, requestManualConfirmation } = useOpeningConfirmationStore();
  const [report, setReport] = useState<OpeningConfirmationReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Mémorise l'équipe demandée par CE composant pour détecter sa clôture
  // (la boîte modale se referme en remettant `forceOpenForTeam` à `null` via
  // `onManualClose` — on en profite pour rafraîchir et recharger le rapport).
  const [pendingTeam, setPendingTeam] = useState<OpeningConfirmationTeam | null>(null);

  const fetchReport = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const { data } = await productionApi.openingConfirmation.get();
      setReport(data);
    } catch (err: unknown) {
      setError(getErrorDetail(err, "Erreur lors du chargement de l'état des confirmations."));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchReport();
  }, [fetchReport]);

  // Quand la boîte modale manuelle se referme (soumission réussie ou annulation),
  // `forceOpenForTeam` redevient `null` — on en profite pour recharger l'état des
  // confirmations et prévenir `Production.tsx` (stocks/fournées à rafraîchir).
  useEffect(() => {
    if (pendingTeam && forceOpenForTeam == null) {
      setPendingTeam(null);
      fetchReport();
      onConfirmed();
    }
  }, [forceOpenForTeam, pendingTeam, fetchReport, onConfirmed]);

  const handleRequest = (team: OpeningConfirmationTeam) => {
    setPendingTeam(team);
    requestManualConfirmation(team);
  };

  if (loading && !report) {
    return null; // discret pendant le premier chargement, pas de clignotement de page
  }

  if (error) {
    return (
      <div className="glass-card" style={{ padding: '10px 14px', fontSize: '0.7rem', color: 'hsl(var(--color-danger))' }}>
        {error}
      </div>
    );
  }

  if (!report) return null;

  const unconfirmedTeams: OpeningConfirmationTeam[] = (['A', 'B'] as OpeningConfirmationTeam[])
    .filter(team => !report.teams[team].confirmed);

  if (unconfirmedTeams.length === 0) {
    return (
      <div
        className="glass-card"
        style={{ padding: '10px 14px', fontSize: '0.7rem', color: 'hsl(var(--color-success))', display: 'flex', alignItems: 'center', gap: '6px' }}
      >
        <FiCheckCircle />
        <span>Stock de départ confirmé aujourd'hui pour les équipes A et B.</span>
      </div>
    );
  }

  return (
    <div className="glass-card" style={{ padding: '10px 14px' }}>
      <h3 style={{ fontSize: '0.75rem', fontWeight: 800, marginBottom: '6px' }}>
        Confirmer le reste d'hier d'une autre équipe
      </h3>
      <p style={{ fontSize: '0.66rem', color: 'hsl(var(--text-muted))', marginBottom: '8px' }}>
        La boîte automatique ne se réaffiche qu'une fois par jour. Utilisez ce bouton pour
        confirmer volontairement le stock de départ d'une équipe qui ne l'a pas encore été.
      </p>
      <div style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
        {unconfirmedTeams.map(team => (
          <button
            key={team}
            type="button"
            onClick={() => handleRequest(team)}
            className="btn btn-secondary"
            disabled={pendingTeam != null}
            style={{ padding: '8px 14px', fontSize: '0.72rem', fontWeight: 700 }}
          >
            Confirmer le reste d'hier — Équipe {team}
          </button>
        ))}
      </div>
    </div>
  );
};
