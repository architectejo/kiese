import React, { useCallback, useEffect, useRef, useState } from 'react';
import axios from 'axios';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { useThemeStore } from '@/store/themeStore';
import {
  FiHome, FiUsers, FiLayers, FiDollarSign,
  FiTrendingUp, FiDatabase, FiSettings, FiLogOut,
  FiShoppingBag, FiUser, FiActivity, FiSun, FiMoon,
  FiCoffee, FiBell, FiX, FiCheck, FiInfo, FiAlertTriangle, FiTrash2, FiList,
  FiMapPin, FiUserCheck, FiMenu, FiSave, FiKey, FiHardDrive, FiCalendar
} from 'react-icons/fi';
import { coreApi, productionApi, SystemNotificationItem, TeamAssignment } from '@/api/services';
import { ForcePasswordChange } from '@/components/auth/ForcePasswordChange';
import { Modal } from '@/components/shared/Modal';
import { extractApiError } from '@/hooks/useProgressiveList';
import { OpeningStockConfirmationModal } from '@/components/production/OpeningStockConfirmationModal';
import { CloseSessionModal } from '@/components/production/CloseSessionModal';
import { useOpeningConfirmationStore } from '@/store/openingConfirmationStore';
import { AutoClosedNoticeModal } from '@/components/production/AutoClosedNoticeModal';
import { TeamAssignmentModal } from '@/components/production/TeamAssignmentModal';
import { useTeamAssignmentStore } from '@/store/teamAssignmentStore';
import { useWorkDateStore } from '@/store/workDateStore';
import { AutoClosedNotice, isAutoClosedStorageKey, useShiftEndStore } from '@/store/shiftEndStore';

interface SidebarItemProps {
  to: string;
  icon: React.ReactNode;
  label: string;
  active: boolean;
}

const SidebarItem: React.FC<SidebarItemProps> = ({ to, icon, label, active }) => (
  <Link
    to={to}
    style={{
      display: 'flex',
      alignItems: 'center',
      gap: '12px',
      padding: '12px 16px',
      color: active ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
      backgroundColor: active ? 'hsl(var(--accent-glow))' : 'transparent',
      borderLeft: active ? '4px solid stroke' : '4px solid transparent',
      borderColor: active ? 'hsl(var(--accent-color))' : 'transparent',
      textDecoration: 'none',
      fontWeight: active ? '700' : '500',
      fontSize: '0.95rem',
      borderRadius: '0 8px 8px 0',
      transition: 'all 0.2s ease',
      marginBottom: '4px'
    }}
    className="sidebar-item"
  >
    {icon}
    <span>{label}</span>
  </Link>
);

export type NotificationItem = SystemNotificationItem;

// BUG-163 : taille de page des notifications (sondage = page 1 ; « Voir plus » = pages suivantes).
const NOTIFICATIONS_PAGE_SIZE = '25';

export const DashboardLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, logout, fetchCurrentUser } = useAuthStore();
  const { theme, setTheme } = useThemeStore();
  // BUG-151 : équipe dont la confirmation manuelle du reste d'hier a été
  // demandée depuis « Production & Stocks » (null = aucune, comportement
  // automatique inchangé).
  const { forceOpenForTeam, clearManualConfirmation } = useOpeningConfirmationStore();
  // BUG-156 : boîte modale forcée « fin de créneau » (volet frontend de
  // BUG-155) — même store partagé que BUG-151 ci-dessus.
  // BUG-157 : `autoClosedNotices` = file des annonces de clôture automatique
  // à confirmer (remplace le toast éphémère `autoClosedTeam` de BUG-156).
  const {
    pending: shiftEndPending, autoClosedNotices, setPending: setShiftEndPending,
    loadAutoClosedNotices, notifyAutoClosed, confirmAutoClosedNotice,
  } = useShiftEndStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Notification States
  // `notifications` = page 1, relue toutes les 10 s par le sondage. `olderNotifications` =
  // pages suivantes demandées par « Voir plus » (BUG-163) : jamais écrasées par le sondage.
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [olderNotifications, setOlderNotifications] = useState<NotificationItem[]>([]);
  const [notifTotal, setNotifTotal] = useState<number | null>(null);
  const [notifHasMore, setNotifHasMore] = useState(false);
  const [notifLoadingMore, setNotifLoadingMore] = useState(false);
  const [notifMoreError, setNotifMoreError] = useState<string | null>(null);
  const notifLastPageRef = useRef(1);
  // BUG-171 : états lus de façon synchrone par le sondage pour détecter un décalage de rangs.
  const notifPage1IdsRef = useRef<Set<string>>(new Set());
  const notifOlderIdsRef = useRef<Set<string>>(new Set());
  const notifTotalRef = useRef<number | null>(null);
  const [isDropdownOpen, setIsDropdownOpen] = useState(false);
  const [isModalOpen, setIsModalOpen] = useState(false);

  // Profile modal state
  const [isProfileOpen, setIsProfileOpen] = useState(false);
  const [profileForm, setProfileForm] = useState({ username: '', first_name: '', last_name: '', email: '', phone: '' });
  const [oldPassword, setOldPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [profileSaving, setProfileSaving] = useState(false);
  const [profileMsg, setProfileMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const fetchNotifications = async () => {
    try {
      const response = await coreApi.notifications.page({ page: '1', page_size: NOTIFICATIONS_PAGE_SIZE });
      const results = response.data.results ?? [];
      // BUG-171 : si des pages suivantes ont été chargées et que la liste a bougé hors de
      // nos actions (nouvelle notification => décalage de rangs, un « trou » entre la page 1 et
      // les pages chargées ; suppression par un autre utilisateur => élément périmé), on
      // abandonne les pages suivantes : l'utilisateur les relit par « Voir plus », sans trou.
      if (notifLastPageRef.current > 1) {
        const known = notifPage1IdsRef.current;
        const older = notifOlderIdsRef.current;
        const hasUnknown = results.some(n => !known.has(n.id) && !older.has(n.id));
        const totalChanged = notifTotalRef.current !== null && notifTotalRef.current !== response.data.count;
        if (hasUnknown || totalChanged) {
          notifLastPageRef.current = 1;
          notifOlderIdsRef.current = new Set();
          setOlderNotifications([]);
          setNotifMoreError(null);
        }
      }
      notifPage1IdsRef.current = new Set(results.map(n => n.id));
      notifTotalRef.current = response.data.count;
      setNotifications(results);
      setNotifTotal(response.data.count);
      // Tant qu'aucune page suivante n'a été demandée (ou après réinitialisation), `next` de
      // la page 1 fait foi.
      if (notifLastPageRef.current === 1) setNotifHasMore(response.data.next != null);
    } catch (error) {
      console.error("Failed to fetch notifications", error);
    }
  };

  // BUG-156 : même garde que `OpeningStockConfirmationModal` (BUG-134/138) —
  // un GERANT ou un FACTURIER non-HQ a un stock physique propre à sa
  // boulangerie et peut déclencher/voir la détection de fin de créneau
  // (backend : `IsAuthenticated`, délibérément plus permissif que `close()`
  // qui reste `IsGerant` — un facturier seul après l'heure de fin doit
  // pouvoir faire remonter l'alerte, remarque.md, même s'il ne peut pas
  // soumettre lui-même la clôture).
  const canSeeShiftEnd = !!user && (user.role === 'GERANT' || user.role === 'FACTURIER') && !user.can_access_all_nodes;
  // BUG-157 : identifiant de la boulangerie de l'utilisateur, utilisé dans la
  // clé `localStorage` des annonces de clôture automatique en attente (une
  // clé par boulangerie : un poste partagé ne mélange pas deux nœuds).
  // `null` = utilisateur non concerné (même garde de rôle que BUG-156).
  const shiftEndNodeKey = canSeeShiftEnd ? (user?.node ?? 'sans-boulangerie') : null;

  // BUG-156 : interroge `GET /api/production/sessions/shift-end-status/`
  // (BUG-155). Les créneaux A/B ne se chevauchent jamais (CLAUDE.md §5.2) :
  // une seule équipe est signalée par appel. `allowImmediateRetry` permet de
  // re-sonder IMMÉDIATEMENT (sans attendre le prochain intervalle de 10 s)
  // après la résolution de la première équipe — clôture automatique
  // (résolue par l'appel lui-même) ou clôture forcée soumise par
  // l'utilisateur (résolue par `handleForcedClosed` ci-dessous) — pour
  // traiter l'autre équipe si elle aussi est en attente, au lieu d'attendre
  // le prochain cycle de sondage.
  const fetchShiftEndStatus = useCallback(async (allowImmediateRetry = true): Promise<void> => {
    if (!canSeeShiftEnd) return;
    try {
      const { data } = await productionApi.sessions.shiftEndStatus();
      if (data.pending_validation) {
        // Rotation : `work_date` = date de la session concernée, `current_work_date` = jour
        // calendaire (n'existe qu'en rotation). Hors rotation ces clés sont absentes : inchangé.
        setShiftEndPending({
          team: data.team, session: data.session, remaining: data.remaining,
          ...(data.current_work_date ? { workDate: data.work_date, rotation: true } : {}),
        });
      } else if (data.auto_closed) {
        // BUG-157 : annonce ajoutée à la file ET persistée — le backend ne
        // renverra plus `auto_closed: true` pour cette fournée.
        // Rotation : date de l'annonce = `work_date` de la session clôturée (serveur), pas la date
        // du poste. BUG-272 : `work_date` antérieure au jour calendaire courant = clôture au
        // passage de minuit (même équipe, aucune relève) : annonce dédiée, sans validation forcée.
        const midnight = !!data.current_work_date && !!data.work_date && data.work_date < data.current_work_date;
        if (shiftEndNodeKey) notifyAutoClosed(shiftEndNodeKey, data.team, data.current_work_date ? data.work_date : undefined, midnight);
        if (allowImmediateRetry) {
          await fetchShiftEndStatus(false);
        }
      } else {
        setShiftEndPending(null);
      }
    } catch (error) {
      console.error('Failed to fetch shift-end status', error);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [canSeeShiftEnd, shiftEndNodeKey, setShiftEndPending, notifyAutoClosed]);

  // BUG-157 : au montage (donc aussi après un rechargement de page), ré-affiche
  // toute annonce de clôture automatique non encore confirmée pour la
  // boulangerie de l'utilisateur. Aucun minuteur d'effacement : seule la
  // confirmation explicite (`handleAutoClosedConfirm`) retire une annonce.
  // L'écoute de `storage` garde plusieurs onglets du même poste cohérents
  // (annonce confirmée ou reçue dans un autre onglet).
  useEffect(() => {
    if (!shiftEndNodeKey) return;
    loadAutoClosedNotices(shiftEndNodeKey);
    const onStorage = (e: StorageEvent) => {
      if (isAutoClosedStorageKey(e.key, shiftEndNodeKey)) loadAutoClosedNotices(shiftEndNodeKey);
    };
    window.addEventListener('storage', onStorage);
    return () => window.removeEventListener('storage', onStorage);
  }, [shiftEndNodeKey, loadAutoClosedNotices]);

  // BUG-161 (F2) : équipe de service du jour (rotation de 24 h). Actif seulement si la
  // boulangerie de l'utilisateur a `team_rotation_enabled`. Même garde de rôle que ci-dessus.
  // Interrogé dans le MÊME cycle de sondage que `fetchShiftEndStatus` (pas de second
  // `setInterval`) : après l'heure de relève, le serveur renvoie `team: null` (nouvelle période,
  // nouveau `shift_date`) et la boîte se rouvre d'elle-même. `work_date` reste calendaire (BUG-272).
  const [rotationEnabled, setRotationEnabled] = useState(false);
  const rotationEnabledRef = useRef(false);
  const [teamAssignment, setTeamAssignment] = useState<TeamAssignment | null>(null);
  const [teamEditOpen, setTeamEditOpen] = useState(false);
  const rotationCheckedAtRef = useRef(0);
  const { requestTick } = useTeamAssignmentStore();
  // BUG-188 : numéro de la dernière requête lancée / numéro de la dernière requête déjà
  // « dépassée » par une désignation réussie. Un sondage parti AVANT la désignation (réponse
  // `team: null` tardive) est ignoré : il ne doit pas rouvrir la boîte.
  const teamReqSeqRef = useRef(0);
  const teamAssignedSeqRef = useRef(0);
  // BUG-161 : compteur de sondage transmis à la boîte « stock de départ » (rotation seulement)
  // pour qu'elle relise `opening-confirmation` à l'heure de relève sans rechargement de page.
  // Incrémenté par le sondage de 10 s existant, après désignation et après clôture forcée.
  const [openingPollTick, setOpeningPollTick] = useState(0);

  const fetchTeamAssignment = useCallback(async (forceFlagRefresh = false): Promise<void> => {
    if (!canSeeShiftEnd || !user?.node) return;
    const seq = ++teamReqSeqRef.current;
    try {
      // Le drapeau change rarement : relu au plus toutes les 60 s (ou sur demande).
      let enabled = rotationEnabledRef.current;
      if (forceFlagRefresh || Date.now() - rotationCheckedAtRef.current > 60000) {
        const { data: nodes } = await coreApi.nodes.list();
        enabled = !!nodes.find(n => n.id === user.node)?.team_rotation_enabled;
        rotationCheckedAtRef.current = Date.now();
        rotationEnabledRef.current = enabled;
        setRotationEnabled(enabled);
      }
      if (seq <= teamAssignedSeqRef.current) return;
      if (!enabled) {
        setTeamAssignment(null);
        // Plus de rotation : l'indicateur « rotation » annoncé par le serveur n'est plus valable.
        if (useWorkDateStore.getState().rotation) useWorkDateStore.getState().clearWorkDate();
        return;
      }
      const { data } = await productionApi.teamAssignment.get();
      if (seq <= teamAssignedSeqRef.current) return;
      setTeamAssignment(data);
    } catch (error) {
      console.error('Failed to fetch team assignment', error);
    }
  }, [canSeeShiftEnd, user?.node]);

  // Signal d'une page (ex. Sales : 403 TEAM_NOT_ASSIGNED) : on sait que le serveur exige la
  // désignation, on relit tout de suite sans attendre le sondage.
  useEffect(() => {
    if (requestTick === 0) return;
    rotationEnabledRef.current = true;
    setRotationEnabled(true);
    setTeamEditOpen(false);
    fetchTeamAssignment(true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [requestTick]);

  // Priorité des boîtes forcées (BUG-188 + BUG-161) : tant que l'équipe du jour n'est pas
  // désignée, la boîte « stock de départ » reste MONTÉE mais « suspendue » (masquée et
  // neutralisée, prop `suspended` de `Modal`), sa saisie n'est jamais perdue. Ordre en rotation
  // à la relève : reste du jour -> désignation -> stock de départ (voir `restStepActive`).
  const teamAssignmentRequired = canSeeShiftEnd && rotationEnabled && teamAssignment !== null && teamAssignment.team === null;
  // BUG-161 : ordre à la relève, en rotation : (1) reste du jour de la journée qui se termine
  // (boîte forcée BUG-156 ou annonce de clôture automatique BUG-157), (2) désignation de l'équipe
  // de service, (3) stock de départ. La désignation attend donc la fin de l'étape (1) ; les boîtes
  // (1) ne sont plus suspendues par la désignation (leur saisie, y compris négative, est ainsi
  // préservée : BUG-188). Hors rotation, `teamAssignmentRequired` est toujours faux : inchangé.
  // BUG-272 : une annonce de clôture « à minuit » ne concerne pas la relève : elle ne retarde pas la désignation.
  const restStepActive = canSeeShiftEnd && rotationEnabled
    && (shiftEndPending !== null || autoClosedNotices.some(n => !n.midnight));
  const teamAssignmentBlocking = teamAssignmentRequired && !restStepActive;
  const teamAssignmentOpen = teamAssignmentBlocking || (canSeeShiftEnd && rotationEnabled && teamAssignment !== null && teamEditOpen);

  const handleAutoClosedConfirm = (notice: AutoClosedNotice) => {
    if (shiftEndNodeKey) confirmAutoClosedNotice(shiftEndNodeKey, notice);
  };

  const handleForcedClosed = () => {
    setShiftEndPending(null);
    // BUG-161 : le reste du jour confirmé devient le stock de départ proposé (snapshot) : la
    // boîte « stock de départ » relit tout de suite sa proposition.
    setOpeningPollTick(t => t + 1);
    // Re-sonde immédiatement : l'autre équipe peut elle aussi être en
    // attente (ou déjà clôturée automatiquement) au moment où celle-ci
    // vient d'être traitée.
    fetchShiftEndStatus();
  };

  useEffect(() => {
    if (!user) {
      fetchCurrentUser();
    }
  }, [user, fetchCurrentUser]);

  useEffect(() => {
    fetchNotifications();
    fetchShiftEndStatus();
    fetchTeamAssignment();
    const interval = setInterval(() => {
      fetchNotifications();
      fetchShiftEndStatus();
      fetchTeamAssignment();
      // BUG-161 : même cycle (pas de second `setInterval`) ; sans effet hors rotation.
      if (rotationEnabledRef.current) setOpeningPollTick(t => t + 1);
    }, 10000);
    return () => clearInterval(interval);
  }, [fetchShiftEndStatus, fetchTeamAssignment]);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const loadMoreNotifications = async () => {
    if (notifLoadingMore || !notifHasMore) return;
    setNotifLoadingMore(true);
    setNotifMoreError(null);
    try {
      const page = notifLastPageRef.current + 1;
      const response = await coreApi.notifications.page({ page: String(page), page_size: NOTIFICATIONS_PAGE_SIZE });
      notifLastPageRef.current = page;
      notifTotalRef.current = response.data.count;
      setNotifHasMore(response.data.next != null);
      setNotifTotal(response.data.count);
      setOlderNotifications(prev => {
        const seen = new Set(prev.map(n => n.id));
        const merged = prev.concat((response.data.results ?? []).filter(n => !seen.has(n.id)));
        notifOlderIdsRef.current = new Set(merged.map(n => n.id));
        return merged;
      });
    } catch (error) {
      setNotifMoreError(extractApiError(error, 'Impossible de charger les notifications suivantes.'));
    } finally {
      setNotifLoadingMore(false);
    }
  };

  const markRead = async (id: string) => {
    try {
      await coreApi.notifications.markRead(id);
      setOlderNotifications(prev => prev.map(n => (n.id === id ? { ...n, is_read: true } : n)));
      fetchNotifications();
    } catch (error) {
      console.error(error);
    }
  };

  const markAllRead = async () => {
    try {
      await coreApi.notifications.markAllRead();
      setOlderNotifications(prev => prev.map(n => ({ ...n, is_read: true })));
      fetchNotifications();
    } catch (error) {
      console.error(error);
    }
  };

  const deleteNotification = async (id: string) => {
    try {
      await coreApi.notifications.delete(id);
      // Suppression faite ici : on anticipe le nouveau total pour que le sondage ne la prenne
      // pas pour une modification externe (BUG-171).
      if (notifTotalRef.current !== null) notifTotalRef.current -= 1;
      notifOlderIdsRef.current.delete(id);
      setOlderNotifications(prev => prev.filter(n => n.id !== id));
      fetchNotifications();
    } catch (error) {
      console.error(error);
    }
  };

  const openProfileModal = () => {
    if (user) {
      setProfileForm({
        username: user.username || '',
        first_name: user.first_name || '',
        last_name: user.last_name || '',
        email: user.email || '',
        phone: user.phone || '',
      });
    }
    setOldPassword('');
    setNewPassword('');
    setProfileMsg(null);
    setIsProfileOpen(true);
  };

  const handleProfileSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setProfileSaving(true);
    setProfileMsg(null);
    try {
      const payload: Record<string, string> = { ...profileForm };
      if (newPassword) {
        payload.old_password = oldPassword;
        payload.new_password = newPassword;
      }
      await coreApi.me.update(payload);
      await fetchCurrentUser();
      setOldPassword('');
      setNewPassword('');
      setProfileMsg({ type: 'success', text: 'Profil mis à jour avec succès.' });
      setTimeout(() => { setProfileMsg(null); setIsProfileOpen(false); }, 1800);
    } catch (err: unknown) {
      const d = axios.isAxiosError(err)
        ? (err.response?.data as { old_password?: string; detail?: string } | undefined)
        : undefined;
      const msg = d?.old_password || d?.detail || (d ? JSON.stringify(d) : undefined) || 'Erreur lors de la mise à jour.';
      setProfileMsg({ type: 'error', text: msg });
    } finally {
      setProfileSaving(false);
    }
  };

  const navItems = [
    { to: '/dashboard', icon: <FiHome />, label: 'Tableau de Bord', roles: ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'] },
    { to: '/clients', icon: <FiUsers />, label: 'Gestion Clientèle', roles: ['ADMIN', 'DIRECTION', 'GERANT', 'FACTURIER'] },
    { to: '/sales/create', icon: <FiShoppingBag />, label: 'Facturation (Facturier)', roles: ['ADMIN', 'DIRECTION', 'GERANT', 'FACTURIER'] },
{ to: '/production', icon: <FiLayers />, label: 'Production & Stocks', roles: ['ADMIN', 'DIRECTION', 'GERANT'] },
    { to: '/commissions', icon: <FiTrendingUp />, label: 'Commissions CM', roles: ['ADMIN', 'DIRECTION', 'COMPTABLE'] },
    { to: '/treasury', icon: <FiDollarSign />, label: 'Clôture & Caisse', roles: ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'] },
    // BUG-120 (volet frontend) : écran dédié au rapport de clôture journalier consolidé
    // par catégorie de pain (document Excel réel du client), même garde que l'API (IsGerant).
    { to: '/cloture-journaliere', icon: <FiCalendar />, label: 'Clôture Journalière', roles: ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'] },
    { to: '/finance', icon: <FiActivity />, label: 'États Financiers N/N-1', roles: ['ADMIN', 'DIRECTION', 'COMPTABLE'] },
    { to: '/activities', icon: <FiList />, label: "Journal d'Activités", roles: ['ADMIN', 'DIRECTION', 'COMPTABLE'] },
    { to: '/blockchain', icon: <FiDatabase />, label: 'Registre Blockchain', roles: ['ADMIN', 'DIRECTION', 'COMPTABLE'] },
    { to: '/admin/nodes', icon: <FiMapPin />, label: 'Succursales (Boulangeries)', roles: ['ADMIN', 'DIRECTION'] },
    { to: '/admin/users', icon: <FiUserCheck />, label: 'Personnel (Utilisateurs)', roles: ['ADMIN', 'DIRECTION'] },
    { to: '/settings', icon: <FiSettings />, label: 'Configuration', roles: ['ADMIN', 'DIRECTION'] },
    { to: '/admin/backups', icon: <FiHardDrive />, label: 'Sauvegarde & Restauration', roles: ['ADMIN', 'DIRECTION'] },
  ];

  // Superuser has access to ALL navigation items
  const filteredNavItems = navItems.filter(item => 
    user ? (user.is_superuser || item.roles.includes(user.role)) : false
  );

  const unreadCount = notifications.filter(n => !n.is_read).length;
  // Liste complète affichée dans la boîte « Toutes les Notifications » : page 1 + pages
  // chargées par « Voir plus » (sans doublon). Le compteur de non lues reste celui de la page 1.
  const page1Ids = new Set(notifications.map(n => n.id));
  const allNotifications = notifications.concat(olderNotifications.filter(n => !page1Ids.has(n.id)));

  const getSeverityStyle = (severity: string) => {
    switch (severity) {
      case 'DANGER':
        return { borderLeft: '4px solid hsl(var(--color-danger))', bg: 'hsl(var(--color-danger) / 0.1)', icon: <FiAlertTriangle style={{ color: 'hsl(var(--color-danger))' }} /> };
      case 'WARNING':
        return { borderLeft: '4px solid hsl(var(--color-warning))', bg: 'hsl(var(--color-warning) / 0.1)', icon: <FiAlertTriangle style={{ color: 'hsl(var(--color-warning))' }} /> };
      case 'SUCCESS':
        return { borderLeft: '4px solid hsl(var(--color-success))', bg: 'hsl(var(--color-success) / 0.1)', icon: <FiCheck style={{ color: 'hsl(var(--color-success))' }} /> };
      default:
        return { borderLeft: '4px solid hsl(var(--color-info))', bg: 'hsl(var(--color-info) / 0.1)', icon: <FiInfo style={{ color: 'hsl(var(--color-info))' }} /> };
    }
  };

  return (
    <div className="dashboard-grid" style={{ position: 'relative' }}>
      {/* Mobile overlay */}
      <div
        className={`mobile-overlay${mobileMenuOpen ? ' mobile-open' : ''}`}
        onClick={() => setMobileMenuOpen(false)}
      />

      {/* Sidebar */}
      <aside className={`dashboard-sidebar${mobileMenuOpen ? ' mobile-open' : ''}`} style={{ padding: '24px 12px', overflowY: 'auto' }}>
        {/* Brand / Logo */}
        <div style={{ padding: '0 16px 32px 16px', display: 'flex', flexDirection: 'column' }}>
          <span style={{ fontSize: '1.5rem', fontWeight: 800, color: 'hsl(var(--accent-color))', letterSpacing: '0.05em', transition: 'color 0.3s ease' }}>
            ETS. KIESE
          </span>
          <span style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', fontWeight: 700, textTransform: 'uppercase' }}>
            Système Boulangeries
          </span>
        </div>

        {/* Navigation Items */}
        <nav style={{ flex: 1, overflowY: 'auto' }}>
          {filteredNavItems.map(item => (
            <div key={item.to} onClick={() => setMobileMenuOpen(false)}>
              <SidebarItem
                to={item.to}
                icon={item.icon}
                label={item.label}
                active={location.pathname === item.to}
              />
            </div>
          ))}
        </nav>

        {/* User Card & Logout */}
        {user && (
          <div style={{ 
            marginTop: 'auto', 
            padding: '16px', 
            borderRadius: 'var(--radius-md)', 
            backgroundColor: 'hsl(var(--bg-tertiary))',
            border: '1px solid hsl(var(--border-color))'
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', marginBottom: '12px' }}>
              <button
                onClick={openProfileModal}
                title="Modifier mon profil"
                style={{
                  width: '40px', height: '40px', borderRadius: '50%',
                  backgroundColor: 'hsl(var(--accent-color) / 0.1)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'hsl(var(--accent-color))', fontSize: '1.2rem',
                  border: '2px solid hsl(var(--accent-color) / 0.3)',
                  cursor: 'pointer', transition: 'all 0.2s ease', flexShrink: 0,
                }}
                onMouseEnter={e => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'hsl(var(--accent-color) / 0.2)'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'hsl(var(--accent-color))'; }}
                onMouseLeave={e => { (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'hsl(var(--accent-color) / 0.1)'; (e.currentTarget as HTMLButtonElement).style.borderColor = 'hsl(var(--accent-color) / 0.3)'; }}
              >
                {user.photo ? <img src={user.photo} alt={user.username} style={{ width: '100%', height: '100%', borderRadius: '50%', objectFit: 'cover' }} /> : <FiUser />}
              </button>
              <div style={{ display: 'flex', flexDirection: 'column', minWidth: 0 }}>
                <span style={{ fontWeight: 700, fontSize: '0.9rem', color: 'hsl(var(--text-primary))', whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                  {user.full_name}
                </span>
                <span style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))' }}>
                  {user.role_display}
                </span>
              </div>
            </div>

            {user.node_display && (
              <div style={{ 
                fontSize: '0.8rem', 
                color: 'hsl(var(--accent-color))', 
                backgroundColor: 'hsl(var(--accent-glow))',
                padding: '6px 8px',
                borderRadius: '6px',
                textAlign: 'center',
                fontWeight: 700,
                marginBottom: '12px',
                transition: 'all 0.3s ease'
              }}>
                BOULANGERIE : {user.node_display}
              </div>
            )}

            {canSeeShiftEnd && rotationEnabled && teamAssignment && (
              <button
                type="button"
                onClick={() => setTeamEditOpen(true)}
                title="Changer l'équipe de service de la journée en cours"
                style={{
                  width: '100%', fontSize: '0.8rem', fontWeight: 700, cursor: 'pointer', minHeight: '38px',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px',
                  color: 'hsl(var(--text-primary))', backgroundColor: 'hsl(var(--bg-tertiary))',
                  border: '1px solid hsl(var(--border-color))', borderRadius: '6px',
                  padding: '6px 8px', marginBottom: '12px',
                }}
              >
                <FiUsers />
                <span>
                  Équipe de service : {teamAssignment.team ?? 'non désignée'}
                  {teamAssignment.team !== null && (
                    <span style={{ color: 'hsl(var(--accent-color))' }}> (changer)</span>
                  )}
                </span>
              </button>
            )}

            {user.is_superuser && (
              <div style={{ 
                fontSize: '0.75rem', 
                color: 'hsl(var(--color-success))', 
                backgroundColor: 'hsl(var(--color-success) / 0.15)',
                border: '1px solid hsl(var(--color-success) / 0.3)',
                padding: '4px 8px',
                borderRadius: '4px',
                textAlign: 'center',
                fontWeight: 800,
                marginBottom: '12px'
              }}>
                SUPER-UTILISATEUR
              </div>
            )}

            <button 
              onClick={handleLogout}
              className="btn btn-secondary" 
              style={{ width: '100%', padding: '8px 12px', fontSize: '0.85rem' }}
            >
              <FiLogOut />
              <span>Déconnexion</span>
            </button>
          </div>
        )}
      </aside>

      {/* Main Content Area */}
      <main className="dashboard-main">
        {/* Header */}
        <header
          className="dashboard-main-header"
          style={{
            borderBottom: '1px solid hsl(var(--border-color))',
            backgroundColor: 'hsl(var(--bg-secondary) / 0.8)',
            backdropFilter: 'blur(8px)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            position: 'sticky',
            top: 0,
            zIndex: 10
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            {/* §6.5 Mobile hamburger button */}
            <button
              className="mobile-hamburger"
              onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
              title="Menu de navigation"
            >
              {mobileMenuOpen ? <FiX /> : <FiMenu />}
            </button>
            <h2 style={{ fontSize: '1.25rem', fontWeight: 800, letterSpacing: '-0.02em' }}>
              {filteredNavItems.find(item => location.pathname === item.to)?.label || 'Console de Gestion'}
            </h2>
          </div>
          
          <div style={{ display: 'flex', alignItems: 'center', gap: '20px' }}>
            {/* Notification Bell with Badge Count */}
            <div style={{ position: 'relative' }}>
              <button 
                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                style={{
                  border: 'none',
                  background: 'hsl(var(--bg-tertiary))',
                  borderWidth: '1px',
                  borderStyle: 'solid',
                  borderColor: 'hsl(var(--border-color))',
                  color: unreadCount > 0 ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                  padding: '8px',
                  borderRadius: 'var(--radius-md)',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'center',
                  fontSize: '1.15rem',
                  transition: 'all 0.2s ease',
                  position: 'relative'
                }}
              >
                <FiBell className={unreadCount > 0 ? 'animate-pulse' : ''} />
                {unreadCount > 0 && (
                  <span style={{
                    position: 'absolute',
                    top: '-6px',
                    right: '-6px',
                    backgroundColor: 'hsl(var(--color-danger))',
                    color: '#ffffff',
                    fontSize: '0.65rem',
                    fontWeight: 900,
                    borderRadius: '50%',
                    width: '16px',
                    height: '16px',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    boxShadow: '0 0 6px hsl(var(--color-danger))'
                  }}>
                    {unreadCount}
                  </span>
                )}
              </button>

              {/* Dropdown Container */}
              {isDropdownOpen && (
                <div 
                  className="animate-fade-in"
                  style={{
                    position: 'absolute',
                    top: '46px',
                    right: 0,
                    width: 'min(380px, calc(100vw - 32px))',
                    backgroundColor: 'hsl(var(--bg-secondary))',
                    opacity: 1,
                    border: '1px solid var(--glass-border)',
                    boxShadow: 'var(--glass-shadow)',
                    borderRadius: 'var(--radius-md)',
                    padding: '16px',
                    zIndex: 30,
                    display: 'flex',
                    flexDirection: 'column',
                    gap: '12px'
                  }}
                >
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '1px solid hsl(var(--border-color))', paddingBottom: '8px' }}>
                    <span style={{ fontWeight: 800, fontSize: '0.9rem' }}>Notifications Réseau</span>
                    {unreadCount > 0 && (
                      <button 
                        onClick={markAllRead}
                        style={{ border: 'none', background: 'transparent', color: 'hsl(var(--accent-color))', fontSize: '0.75rem', fontWeight: 700, cursor: 'pointer' }}
                      >
                        Tout marquer lu
                      </button>
                    )}
                  </div>

                  <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', maxHeight: '280px', overflowY: 'auto' }}>
                    {notifications.length === 0 ? (
                      <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '16px', fontSize: '0.85rem' }}>
                        Aucune notification disponible.
                      </div>
                    ) : (
                      notifications.slice(0, 4).map((notif) => {
                        const style = getSeverityStyle(notif.severity);
                        return (
                          <div 
                            key={notif.id}
                            style={{
                              borderLeft: style.borderLeft,
                              backgroundColor: notif.is_read ? 'transparent' : style.bg,
                              padding: '10px',
                              borderRadius: '4px',
                              border: '1px solid hsl(var(--border-color))',
                              borderLeftWidth: '4px',
                              display: 'flex',
                              gap: '10px',
                              alignItems: 'flex-start',
                              opacity: notif.is_read ? 0.6 : 1,
                              transition: 'all 0.2s ease'
                            }}
                          >
                            <span style={{ marginTop: '2px' }}>{style.icon}</span>
                            <div style={{ flex: 1, minWidth: 0 }}>
                              <h4 style={{ fontWeight: 700, fontSize: '0.8rem', marginBottom: '2px', color: 'hsl(var(--text-primary))' }}>
                                {notif.title}
                              </h4>
                              <p style={{ fontSize: '0.75rem', color: 'hsl(var(--text-secondary))', lineHeight: 1.3, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis' }}>
                                {notif.message}
                              </p>
                            </div>
                            {!notif.is_read && (
                              <button 
                                onClick={() => markRead(notif.id)}
                                style={{ border: 'none', background: 'transparent', color: 'hsl(var(--accent-color))', cursor: 'pointer', display: 'flex', padding: 0 }}
                                title="Marquer comme lu"
                              >
                                <FiCheck />
                              </button>
                            )}
                          </div>
                        );
                      })
                    )}
                  </div>

                  <button 
                    onClick={() => {
                      setIsDropdownOpen(false);
                      setIsModalOpen(true);
                    }}
                    className="btn btn-secondary"
                    style={{ width: '100%', padding: '8px', fontSize: '0.8rem', fontWeight: 700, display: 'flex', justifyContent: 'center' }}
                  >
                    Voir plus
                  </button>
                </div>
              )}
            </div>

            {/* Interactive Theme Switcher Button Group */}
            <div style={{ 
              display: 'flex', 
              alignItems: 'center', 
              backgroundColor: 'hsl(var(--bg-tertiary))', 
              border: '1px solid hsl(var(--border-color))', 
              borderRadius: 'var(--radius-md)',
              padding: '2px'
            }}>
              <button 
                onClick={() => setTheme('dark')} 
                title="Thème Sombre"
                style={{
                  border: 'none',
                  background: theme === 'dark' ? 'hsl(var(--accent-glow))' : 'transparent',
                  color: theme === 'dark' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  transition: 'all 0.2s ease'
                }}
              >
                <FiMoon />
                <span className="hidden-mobile">Dark</span>
              </button>
              <button 
                onClick={() => setTheme('light')} 
                title="Thème Clair"
                style={{
                  border: 'none',
                  background: theme === 'light' ? 'hsl(var(--accent-glow))' : 'transparent',
                  color: theme === 'light' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  transition: 'all 0.2s ease'
                }}
              >
                <FiSun />
                <span className="hidden-mobile">Light</span>
              </button>
              <button 
                onClick={() => setTheme('classic')} 
                title="Thème Classic (Boulangerie)"
                style={{
                  border: 'none',
                  background: theme === 'classic' ? 'hsl(var(--accent-glow))' : 'transparent',
                  color: theme === 'classic' ? 'hsl(var(--accent-color))' : 'hsl(var(--text-secondary))',
                  padding: '6px 10px',
                  borderRadius: '6px',
                  cursor: 'pointer',
                  display: 'flex',
                  alignItems: 'center',
                  gap: '4px',
                  fontWeight: 600,
                  fontSize: '0.8rem',
                  transition: 'all 0.2s ease'
                }}
              >
                <FiCoffee />
                <span className="hidden-mobile">Classic</span>
              </button>
            </div>

            {/* System Status */}
            <div className="hidden-mobile" style={{ display: 'flex', alignItems: 'center', gap: '8px', fontSize: '0.85rem' }}>
              <span style={{ 
                width: '8px', 
                height: '8px', 
                borderRadius: '50%', 
                backgroundColor: 'hsl(var(--color-success))',
                display: 'inline-block' 
              }}></span>
              <span style={{ color: 'hsl(var(--text-secondary))', fontWeight: 600 }}>Nœud Central Cloud</span>
            </div>
          </div>
        </header>

        {/* Content Body */}
        <div className="dashboard-content-area" style={{ flex: 1 }}>
          <div className="animate-fade-in">
            {children}
          </div>
        </div>
        <ForcePasswordChange />
      </main>

      {/* --- Full Glass Notification Modal Box --- */}
      <Modal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        title="Toutes les Notifications Système"
        subtitle="Journal consolidé des alertes clients, audits de sécurité et synchronisations."
        maxWidth="650px"
        footer={<button onClick={() => setIsModalOpen(false)} className="btn btn-primary" style={{ padding: '10px 24px', fontSize: '0.85rem' }}>Fermer la boîte</button>}
      >
            {/* Actions Bar */}
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '16px' }}>
              <span style={{ fontSize: '0.85rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>
                {unreadCount} notification(s) non lue(s)
              </span>
              {unreadCount > 0 && (
                <button 
                  onClick={markAllRead}
                  className="btn btn-secondary"
                  style={{ padding: '6px 12px', fontSize: '0.75rem', fontWeight: 700 }}
                >
                  <FiCheck style={{ marginRight: '4px' }} /> Tout marquer comme lu
                </button>
              )}
            </div>

            {/* Notifications Scroll List */}
            <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', paddingRight: '8px', marginBottom: '16px' }}>
              {allNotifications.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '32px' }}>
                  Aucune notification présente dans le registre.
                </div>
              ) : (
                allNotifications.map((notif) => {
                  const style = getSeverityStyle(notif.severity);
                  return (
                    <div 
                      key={notif.id}
                      style={{
                        borderLeft: style.borderLeft,
                        backgroundColor: notif.is_read ? 'transparent' : style.bg,
                        padding: '16px',
                        borderRadius: 'var(--radius-md)',
                        border: '1px solid hsl(var(--border-color))',
                        borderLeftWidth: '4px',
                        display: 'flex',
                        gap: '16px',
                        alignItems: 'flex-start',
                        opacity: notif.is_read ? 0.65 : 1,
                        transition: 'all 0.2s ease'
                      }}
                    >
                      <span style={{ fontSize: '1.2rem', marginTop: '3px' }}>{style.icon}</span>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '4px' }}>
                          <h4 style={{ fontWeight: 800, fontSize: '0.95rem', color: 'hsl(var(--text-primary))' }}>
                            {notif.title}
                          </h4>
                          <span className="badge badge-info" style={{ fontSize: '0.65rem' }}>
                            Nœud : {notif.node_origin}
                          </span>
                        </div>
                        <p style={{ fontSize: '0.85rem', color: 'hsl(var(--text-secondary))', lineHeight: 1.45, marginBottom: '8px' }}>
                          {notif.message}
                        </p>
                        <span style={{ fontSize: '0.7rem', color: 'hsl(var(--text-muted))', fontWeight: 600 }}>
                          Reçu le : {new Date(notif.created_at).toLocaleString('fr-FR')}
                        </span>
                      </div>
                      
                      <div style={{ display: 'flex', gap: '8px', flexShrink: 0 }}>
                        {!notif.is_read && (
                          <button 
                            onClick={() => markRead(notif.id)}
                            style={{
                              border: 'none',
                              background: 'hsl(var(--bg-tertiary))',
                              color: 'hsl(var(--accent-color))',
                              padding: '6px',
                              borderRadius: '4px',
                              cursor: 'pointer',
                              display: 'flex'
                            }}
                            title="Marquer comme lu"
                          >
                            <FiCheck />
                          </button>
                        )}
                        <button 
                          onClick={() => deleteNotification(notif.id)}
                          style={{
                            border: 'none',
                            background: 'hsl(var(--bg-tertiary))',
                            color: 'hsl(var(--color-danger))',
                            padding: '6px',
                            borderRadius: '4px',
                            cursor: 'pointer',
                            display: 'flex'
                          }}
                          title="Supprimer la notification"
                        >
                          <FiTrash2 />
                        </button>
                      </div>
                    </div>
                  );
                })
              )}
              {allNotifications.length > 0 && (
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '8px', padding: '4px 0 8px' }}>
                  <span role="status" style={{ fontSize: '0.75rem', color: 'hsl(var(--text-muted))', fontWeight: 700 }}>
                    {allNotifications.length.toLocaleString('fr-FR')} affichée(s) / {Math.max(notifTotal ?? 0, allNotifications.length).toLocaleString('fr-FR')} au total
                  </span>
                  {notifMoreError && (
                    <span role="alert" style={{ fontSize: '0.75rem', color: 'hsl(var(--color-danger))', fontWeight: 700 }}>
                      {notifMoreError}
                    </span>
                  )}
                  {notifHasMore && (
                    <button
                      onClick={loadMoreNotifications}
                      disabled={notifLoadingMore}
                      className="btn btn-secondary"
                      style={{ padding: '10px 20px', minHeight: '44px', fontSize: '0.8rem', fontWeight: 700 }}
                    >
                      {notifLoadingMore ? 'Chargement…' : 'Voir plus'}
                    </button>
                  )}
                </div>
              )}
            </div>
      </Modal>

      {/* ── Modal Profil Utilisateur ─────────────────────────────────── */}
      {isProfileOpen && (
        <Modal isOpen={true} onClose={() => setIsProfileOpen(false)} maxWidth="520px" showCloseButton={false}>
            {/* Header */}
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: '24px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                <div style={{
                  width: '36px', height: '36px', borderRadius: '50%',
                  backgroundColor: 'hsl(var(--accent-color) / 0.15)',
                  display: 'flex', alignItems: 'center', justifyContent: 'center',
                  color: 'hsl(var(--accent-color))', fontSize: '1.1rem',
                }}>
                  <FiUser />
                </div>
                <h2 style={{ fontWeight: 800, fontSize: '1.15rem', color: 'hsl(var(--text-primary))' }}>
                  Mon Profil
                </h2>
              </div>
              <button
                onClick={() => setIsProfileOpen(false)}
                style={{ background: 'none', border: 'none', cursor: 'pointer', color: 'hsl(var(--text-secondary))', fontSize: '1.2rem', padding: '4px' }}
              >
                ✕
              </button>
            </div>

            {/* Message feedback */}
            {profileMsg && (
              <div style={{
                padding: '10px 14px', borderRadius: 'var(--radius-md)', marginBottom: '16px', fontSize: '0.85rem', fontWeight: 600,
                backgroundColor: profileMsg.type === 'success' ? 'hsl(var(--color-success) / 0.12)' : 'hsl(var(--color-danger) / 0.12)',
                color: profileMsg.type === 'success' ? 'hsl(var(--color-success))' : 'hsl(var(--color-danger))',
                border: `1px solid ${profileMsg.type === 'success' ? 'hsl(var(--color-success) / 0.3)' : 'hsl(var(--color-danger) / 0.3)'}`,
              }}>
                {profileMsg.text}
              </div>
            )}

            <form onSubmit={handleProfileSave}>
              {/* Nom d'utilisateur */}
              <div style={{ marginBottom: '16px' }}>
                <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 700, color: 'hsl(var(--accent-color))', marginBottom: '6px', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                  Nom d'utilisateur
                </label>
                <input
                  type="text"
                  value={profileForm.username}
                  onChange={e => setProfileForm(p => ({ ...p, username: e.target.value }))}
                  placeholder="username"
                  className="form-input"
                  style={{ width: '100%' }}
                />
              </div>

              {/* Prénom / Nom */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '16px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Prénom</label>
                  <input type="text" value={profileForm.first_name} onChange={e => setProfileForm(p => ({ ...p, first_name: e.target.value }))} placeholder="Prénom" className="form-input" style={{ width: '100%' }} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Nom</label>
                  <input type="text" value={profileForm.last_name} onChange={e => setProfileForm(p => ({ ...p, last_name: e.target.value }))} placeholder="Nom" className="form-input" style={{ width: '100%' }} />
                </div>
              </div>

              {/* Email / Téléphone */}
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px', marginBottom: '24px' }}>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Email</label>
                  <input type="email" value={profileForm.email} onChange={e => setProfileForm(p => ({ ...p, email: e.target.value }))} placeholder="email@exemple.com" className="form-input" style={{ width: '100%' }} />
                </div>
                <div>
                  <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Téléphone</label>
                  <input type="text" value={profileForm.phone} onChange={e => setProfileForm(p => ({ ...p, phone: e.target.value }))} placeholder="+243..." className="form-input" style={{ width: '100%' }} />
                </div>
              </div>

              {/* Changement de mot de passe */}
              <div style={{
                borderTop: '1px solid hsl(var(--border-color))',
                paddingTop: '20px', marginBottom: '24px',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '14px' }}>
                  <FiKey style={{ color: 'hsl(var(--text-secondary))' }} />
                  <span style={{ fontSize: '0.85rem', fontWeight: 700, color: 'hsl(var(--text-secondary))', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    Changer le mot de passe
                  </span>
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Mot de passe actuel</label>
                    <input type="password" value={oldPassword} onChange={e => setOldPassword(e.target.value)} placeholder="••••••••" className="form-input" style={{ width: '100%' }} autoComplete="current-password" />
                  </div>
                  <div>
                    <label style={{ display: 'block', fontSize: '0.8rem', fontWeight: 600, color: 'hsl(var(--text-secondary))', marginBottom: '6px' }}>Nouveau mot de passe</label>
                    <input type="password" value={newPassword} onChange={e => setNewPassword(e.target.value)} placeholder="••••••••" className="form-input" style={{ width: '100%' }} autoComplete="new-password" />
                  </div>
                </div>
              </div>

              {/* Bouton submit */}
              <button
                type="submit"
                disabled={profileSaving}
                className="btn btn-primary"
                style={{ width: '100%', padding: '12px', fontSize: '0.9rem', fontWeight: 700, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '8px' }}
              >
                <FiSave />
                {profileSaving ? 'Enregistrement...' : 'Enregistrer le profil'}
              </button>
            </form>
        </Modal>
      )}

      {/* BUG-133/134/138/140 : boîte modale « stock de départ » — pour un
          GERANT ou un FACTURIER non-HQ (un rôle Siège supervise plusieurs
          boulangeries et n'a pas de stock de départ personnel à confirmer,
          cf. fiche BUG-134 du registre ; remarque.md l.398 : « le facturier
          peut aussi faire ça », BUG-138 côté API). Montée une seule fois ici
          (pas page par page) ; le composant réinterroge le GET à chaque
          changement de route via `routeKey`. */}
      {user && (user.role === 'GERANT' || user.role === 'FACTURIER') && !user.can_access_all_nodes && (
        <OpeningStockConfirmationModal
          // BUG-161 : ordre à la relève = reste du jour de la journée qui se termine (boîte forcée
          // BUG-156) -> désignation d'équipe -> stock de départ. En rotation, la boîte reste montée
          // mais masquée tant que la désignation est requise OU qu'un reste du jour est à confirmer.
          suspended={teamAssignmentRequired || restStepActive}
          pollKey={rotationEnabled ? openingPollTick : undefined}
          handoverTime={teamAssignment?.handover_time ? teamAssignment.handover_time.slice(0, 5) : null}
          routeKey={location.pathname}
          // BUG-151 : déclenchement manuel depuis « Production & Stocks »
          // (`OpeningConfirmationManualSection.tsx`), porté par un petit
          // store partagé plutôt que par des props — le composant reste
          // monté une seule fois ici (consigne inchangée, BUG-134).
          forceOpenForTeam={rotationEnabled ? null : forceOpenForTeam}
          onManualClose={clearManualConfirmation}
        />
      )}

      {/* BUG-156 (volet frontend de BUG-155) : boîte modale forcée « fin de
          créneau » — même garde de rôle que ci-dessus (`canSeeShiftEnd`),
          montée une seule fois ici (pas page par page), pilotée par
          `shiftEndStore.ts` rempli par le sondage périodique ci-dessus. */}
      {canSeeShiftEnd && shiftEndPending && (
        <CloseSessionModal
          isOpen={true}
          session={null}
          onClose={() => { /* non fermable sans soumission en mode forcé */ }}
          onClosed={() => { /* non utilisé en mode forcé, voir onForcedClose */ }}
          forced={shiftEndPending}
          onForcedClose={handleForcedClosed}
        />
      )}

      {/* BUG-157 (remplace le toast auto-effacé de BUG-156) : annonce de
          clôture AUTOMATIQUE (créneau dépassé de plus de 30 min, personne
          n'avait validé) — boîte modale qui reste à l'écran jusqu'à la
          confirmation explicite. La file est traitée une annonce à la fois
          (équipes A puis B). Rendue APRÈS la modale forcée ci-dessus : si les
          deux coexistent (annonce pour une équipe, saisie forcée pour
          l'autre), l'annonce est au premier plan, puis sa confirmation rend
          la main à la modale forcée restée montée (saisie conservée). */}
      {canSeeShiftEnd && autoClosedNotices.length > 0 && (
        <AutoClosedNoticeModal
          notice={autoClosedNotices[0]}
          pendingCount={autoClosedNotices.length}
          onConfirm={handleAutoClosedConfirm}
        />
      )}

      {/* BUG-161 (F2) : désignation de l'équipe de service du jour (rotation de 24 h).
          Montée une seule fois ici. Obligatoire (non fermable) tant que `team` est nul ;
          fermable en mode correction (indicateur « Équipe de service » de la barre
          latérale). Passe APRÈS le reste du jour de la journée qui se termine (boîte forcée /
          annonce) et AVANT le stock de départ (voir `restStepActive`). */}
      {teamAssignmentOpen && teamAssignment && (
        <TeamAssignmentModal
          assignment={teamAssignment}
          dismissible={teamAssignment.team !== null}
          onAssigned={(a) => {
            teamAssignedSeqRef.current = teamReqSeqRef.current;
            setTeamAssignment(a);
            setTeamEditOpen(false);
            // BUG-161 : l'équipe désignée déclenche la demande du stock de départ sans attendre 10 s.
            setOpeningPollTick(t => t + 1);
          }}
          onClose={() => setTeamEditOpen(false)}
        />
      )}
    </div>
  );
};
