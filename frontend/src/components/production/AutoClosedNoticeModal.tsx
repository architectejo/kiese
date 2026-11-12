import React, { useEffect, useState } from 'react';
import { FiCheckCircle, FiClock } from 'react-icons/fi';
import { Modal } from '@/components/shared/Modal';
import { AutoClosedNotice } from '@/store/shiftEndStore';

// BUG-157 (docs/qa/REGISTRE_BUGS.md, découle de BUG-156 ; instruction client du
// 2026-11-10 : « La boîte qui annonce une clôture automatique doit rester affichée
// sur l'écran jusqu'à la confirmation du gérant »). Remplace le toast auto-effacé
// de BUG-156 par une boîte modale qui ne se ferme QUE par le bouton de
// confirmation : pas de croix, pas de fermeture par clic sur l'arrière-plan,
// Échap sans effet (même neutralisation que le mode forcé de `CloseSessionModal`),
// aucun minuteur.
//
// Montée une seule fois par `DashboardLayout`, qui lui passe la première annonce
// de la file `autoClosedNotices` (`shiftEndStore.ts`) : s'il y en a plusieurs
// (équipes A et B clôturées coup sur coup), elles sont présentées l'une après
// l'autre, chacune avec sa propre confirmation.

export interface AutoClosedNoticeModalProps {
  /** Annonce affichée (la plus ancienne de la file). */
  notice: AutoClosedNotice;
  /** Nombre total d'annonces en attente, celle-ci comprise. */
  pendingCount: number;
  onConfirm: (notice: AutoClosedNotice) => void;
  /** BUG-188 : masquée pendant la désignation d'équipe (priorité), sans être démontée. */
  suspended?: boolean;
}

const formatNoticeDate = (isoDay: string): string => {
  const [year, month, day] = isoDay.split('-');
  return `${day}/${month}/${year}`;
};

/** Délai pendant lequel le bouton d'une annonce qui vient d'apparaître reste
 *  inactif : un double appui sur « J'ai compris » ne doit pas confirmer aussi
 *  l'annonce suivante sans qu'elle ait été lue. Ce n'est PAS un effacement
 *  automatique : l'annonce reste affichée tant qu'on ne confirme pas. */
const CONFIRM_ARM_DELAY_MS = 700;

export const AutoClosedNoticeModal: React.FC<AutoClosedNoticeModalProps> = ({
  notice, pendingCount, onConfirm, suspended = false,
}) => {
  const [armed, setArmed] = useState(false);

  useEffect(() => {
    setArmed(false);
    const timeout = setTimeout(() => setArmed(true), CONFIRM_ARM_DELAY_MS);
    return () => clearTimeout(timeout);
  }, [notice.team, notice.date]);

  return (
  <Modal
    isOpen={true}
    suspended={suspended}
    onClose={() => { /* non fermable sans confirmation explicite (Échap inclus) */ }}
    title={`Clôture automatique — Équipe ${notice.team}`}
    subtitle={`Constatée le ${formatNoticeDate(notice.date)}`}
    maxWidth="440px"
    closeOnBackdropClick={false}
    showCloseButton={false}
    footer={
      <button
        type="button"
        onClick={() => { if (armed) onConfirm(notice); }}
        aria-disabled={!armed}
        className="btn btn-primary"
        style={{
          opacity: armed ? 1 : 0.6,
          flex: 1, minHeight: '46px', padding: '10px', fontSize: '0.9rem', fontWeight: 700,
          display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px',
        }}
      >
        <FiCheckCircle />
        J'ai compris
      </button>
    }
  >
    <div
      role="alert"
      style={{
        display: 'flex', alignItems: 'flex-start', gap: '10px', fontSize: '0.85rem', lineHeight: 1.45,
        color: 'hsl(var(--text-primary))', backgroundColor: 'hsl(var(--color-warning) / 0.1)',
        border: '1px solid hsl(var(--color-warning) / 0.4)',
        padding: '12px', borderRadius: 'var(--radius-sm)',
      }}
    >
      <FiClock style={{ color: 'hsl(var(--color-warning))', flexShrink: 0, marginTop: '3px' }} />
      <span>
        Le créneau de l'équipe <strong>{notice.team}</strong> est dépassé depuis plus de 30 minutes
        sans validation : la fournée a été <strong>clôturée automatiquement</strong> par le système.
        Le reste du jour a été calculé à partir du stock physique enregistré.
      </span>
    </div>

    <p style={{ fontSize: '0.78rem', color: 'hsl(var(--text-secondary))', marginTop: '12px', lineHeight: 1.4 }}>
      Cette annonce reste affichée jusqu'à votre confirmation. Vérifiez le reste du jour dans
      « Production &amp; Stocks » si le stock réel diffère.
    </p>

    {pendingCount > 1 && (
      <p style={{ fontSize: '0.74rem', fontWeight: 700, color: 'hsl(var(--color-warning))', marginTop: '10px' }}>
        Annonce 1 sur {pendingCount} — la suivante s'affichera après cette confirmation.
      </p>
    )}
  </Modal>
  );
};
