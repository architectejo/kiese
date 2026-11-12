import React, { useEffect, useRef, useState } from 'react';
import { FiUsers, FiClock, FiRefreshCw } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import { getErrorDetail, isPreviousWorkdayOpenError } from '@/api/errors';
import { productionApi, ServiceTeam, TeamAssignment } from '@/api/services';

// BUG-161 (F2) : désignation quotidienne de l'équipe de service (rotation de 24 h).
// Montée UNE SEULE fois par `DashboardLayout`.
//
// - Mode obligatoire (`dismissible = false`, `assignment.team === null`) : ni croix, ni Échap,
//   ni clic sur l'arrière-plan — la facturation est bloquée côté serveur tant que l'équipe
//   n'est pas désignée.
// - Mode correction (`dismissible = true`) : le gérant/facturier change l'équipe de la
//   journée en cours ; fermable.
// Le frontend n'envoie aucune date : le serveur calcule la période de service. BUG-272 : `work_date`
// est le jour calendaire (inchangé à la relève) ; la période de service est identifiée par `shift_date`.

export interface TeamAssignmentModalProps {
  assignment: TeamAssignment;
  dismissible: boolean;
  onAssigned: (assignment: TeamAssignment) => void;
  onClose: () => void;
}

const formatHandover = (hhmm: string): string => hhmm.slice(0, 5).replace(':', 'h');

const formatWorkDate = (isoDay: string): string => {
  const [year, month, day] = isoDay.split('-');
  return `${day}/${month}/${year}`;
};

export const TeamAssignmentModal: React.FC<TeamAssignmentModalProps> = ({
  assignment, dismissible, onAssigned, onClose,
}) => {
  const [selected, setSelected] = useState<ServiceTeam>(assignment.team ?? assignment.suggested);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Nouvelle période de service (relève passée : `shift_date` change, `team` repasse à null) ou
  // nouvelle suggestion : on repart de la proposition.
  useEffect(() => {
    setSelected(assignment.team ?? assignment.suggested);
    setError(null);
  }, [assignment.shift_date, assignment.team, assignment.suggested]);

  // BUG-196 : le serveur refuse (400 PREVIOUS_WORKDAY_OPEN) tant que le reste du jour précédent
  // n'est pas confirmé. Message dédié (pas d'erreur générique) + relance automatique.
  const [blockedMessage, setBlockedMessage] = useState<string | null>(null);
  const inFlight = useRef(false);

  const attempt = async (silent: boolean) => {
    if (inFlight.current) return;
    inFlight.current = true;
    if (!silent) { setSubmitting(true); setError(null); }
    try {
      await productionApi.teamAssignment.set(selected);
      // Relecture : le serveur reste la source de vérité (journée, désignant, suggestion).
      const { data } = await productionApi.teamAssignment.get();
      setBlockedMessage(null);
      onAssigned(data);
    } catch (err: unknown) {
      if (isPreviousWorkdayOpenError(err)) {
        setError(null);
        setBlockedMessage(getErrorDetail(err, "Confirmez d'abord le reste du jour précédent."));
      } else if (!silent) {
        setBlockedMessage(null);
        setError(getErrorDetail(err, "Impossible d'enregistrer l'équipe de service."));
      }
    } finally {
      inFlight.current = false;
      if (!silent) setSubmitting(false);
    }
  };
  const submit = () => attempt(false);

  // Tant que le refus persiste, on retente toutes les 5 s : dès que la clôture (forcée ou
  // confirmée) a eu lieu, la désignation passe sans action de l'utilisateur.
  useEffect(() => {
    if (!blockedMessage) return;
    const id = setInterval(() => { void attempt(true); }, 5000);
    return () => clearInterval(id);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [blockedMessage, selected]);

  const teamButton = (team: ServiceTeam) => {
    const active = selected === team;
    return (
      <button
        key={team}
        type="button"
        onClick={() => setSelected(team)}
        aria-pressed={active}
        disabled={submitting}
        style={{
          flex: 1, minHeight: '84px', fontSize: '1.4rem', fontWeight: 800, cursor: 'pointer',
          borderRadius: 'var(--radius-md)',
          border: `2px solid ${active ? 'hsl(var(--accent-color))' : 'hsl(var(--border-color))'}`,
          backgroundColor: active ? 'hsl(var(--accent-glow))' : 'hsl(var(--bg-tertiary))',
          color: active ? 'hsl(var(--accent-color))' : 'hsl(var(--text-primary))',
          display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', gap: '4px',
        }}
      >
        <span>Équipe {team}</span>
        {assignment.suggested === team && (
          <span style={{ fontSize: '0.68rem', fontWeight: 700, color: 'hsl(var(--color-info))' }}>
            Suggestion
          </span>
        )}
      </button>
    );
  };

  const submitLabel = submitting
    ? 'Enregistrement...'
    : error || blockedMessage
      ? 'Réessayer'
      : assignment.team === null
        ? `Confirmer l'équipe ${selected}`
        : `Changer pour l'équipe ${selected}`;

  return (
    <Modal
      isOpen={true}
      onClose={() => { if (dismissible) onClose(); }}
      title={assignment.team === null ? 'Équipe de service' : "Changer l'équipe de service"}
      subtitle={`Service du ${formatWorkDate(assignment.shift_date ?? assignment.work_date)} (relève de ${formatHandover(assignment.handover_time)})`}
      maxWidth="460px"
      closeOnBackdropClick={dismissible}
      showCloseButton={dismissible}
      footer={
        <>
          {dismissible && (
            <button type="button" className="btn btn-secondary" onClick={onClose} disabled={submitting}
              style={{ minHeight: '46px', padding: '10px 16px', fontSize: '0.9rem' }}>
              Annuler
            </button>
          )}
          <button
            type="button"
            className="btn btn-primary"
            onClick={submit}
            disabled={submitting || (assignment.team !== null && selected === assignment.team)}
            style={{
              flex: 1, minHeight: '46px', padding: '10px', fontSize: '0.9rem', fontWeight: 700,
              display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
            }}
          >
            {error || blockedMessage ? <FiRefreshCw /> : <FiUsers />}
            {submitLabel}
          </button>
        </>
      }
    >
      <p style={{ fontSize: '0.85rem', lineHeight: 1.45, color: 'hsl(var(--text-primary))', marginBottom: '14px' }}>
        {assignment.team === null
          ? "Choisissez l'équipe qui assure le service jusqu'à la prochaine relève. La facturation reste bloquée tant que l'équipe n'est pas désignée."
          : `Équipe actuellement désignée : ${assignment.team}. Utilisez ce choix pour corriger une erreur de désignation.`}
      </p>

      <div style={{ display: 'flex', gap: '12px' }}>
        {(['A', 'B'] as ServiceTeam[]).map(teamButton)}
      </div>

      <p style={{ fontSize: '0.74rem', color: 'hsl(var(--text-secondary))', marginTop: '10px', lineHeight: 1.4 }}>
        Suggestion : l'autre équipe que la dernière période de service (équipe {assignment.suggested}). Vous pouvez choisir librement.
      </p>

      <p style={{ display: 'flex', alignItems: 'center', gap: '6px', fontSize: '0.74rem', color: 'hsl(var(--text-secondary))', marginTop: '8px' }}>
        <FiClock />
        Relève des équipes à {formatHandover(assignment.handover_time)} chaque jour (la date, elle, change à minuit).
      </p>

      {blockedMessage && (
        <div role="status" style={{
          marginTop: '12px', fontSize: '0.8rem', color: 'hsl(var(--color-warning))',
          backgroundColor: 'hsl(var(--color-warning) / 0.1)', border: '1px solid hsl(var(--color-warning) / 0.4)',
          padding: '10px', borderRadius: 'var(--radius-sm)', lineHeight: 1.4,
        }}>
          <strong>Confirmez d'abord le reste du jour précédent.</strong>
          <div style={{ marginTop: '4px' }}>{blockedMessage}</div>
          <div style={{ marginTop: '4px', fontSize: '0.72rem' }}>
            Nouvelle tentative automatique toutes les 5 secondes ; vous pouvez aussi appuyer sur « Réessayer ».
          </div>
        </div>
      )}

      {error && (
        <div role="alert" style={{
          marginTop: '12px', fontSize: '0.8rem', color: 'hsl(var(--color-danger))',
          backgroundColor: 'hsl(var(--color-danger) / 0.1)', border: '1px solid hsl(var(--color-danger) / 0.4)',
          padding: '10px', borderRadius: 'var(--radius-sm)',
        }}>
          {error}
        </div>
      )}
    </Modal>
  );
};
