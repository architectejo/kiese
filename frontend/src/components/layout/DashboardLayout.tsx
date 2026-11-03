import React, { useEffect, useState } from 'react';
import axios from 'axios';
import { Link, useNavigate, useLocation } from 'react-router-dom';
import { useAuthStore } from '@/store/authStore';
import { useThemeStore } from '@/store/themeStore';
import { apiClient } from '@/api/client';
import {
  FiHome, FiUsers, FiLayers, FiDollarSign,
  FiTrendingUp, FiDatabase, FiSettings, FiLogOut,
  FiShoppingBag, FiUser, FiActivity, FiSun, FiMoon,
  FiCoffee, FiBell, FiX, FiCheck, FiInfo, FiAlertTriangle, FiTrash2, FiList,
  FiMapPin, FiUserCheck, FiMenu, FiSave, FiKey, FiHardDrive, FiCalendar
} from 'react-icons/fi';
import { coreApi } from '@/api/services';
import { Modal } from '@/components/shared/Modal';

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

export interface NotificationItem {
  id: string;
  title: string;
  message: string;
  severity: 'INFO' | 'SUCCESS' | 'WARNING' | 'DANGER';
  is_read: boolean;
  node_origin: string;
  created_at: string;
}

export const DashboardLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, logout, fetchCurrentUser } = useAuthStore();
  const { theme, setTheme } = useThemeStore();
  const navigate = useNavigate();
  const location = useLocation();
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);

  // Notification States
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
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
      const response = await apiClient.get('/api/core/notifications/');
      const data = Array.isArray(response.data) ? response.data : (response.data.results || []);
      setNotifications(data);
    } catch (error) {
      console.error("Failed to fetch notifications", error);
    }
  };

  useEffect(() => {
    if (!user) {
      fetchCurrentUser();
    }
  }, [user, fetchCurrentUser]);

  useEffect(() => {
    fetchNotifications();
    const interval = setInterval(fetchNotifications, 10000);
    return () => clearInterval(interval);
  }, []);

  const handleLogout = async () => {
    await logout();
    navigate('/login');
  };

  const markRead = async (id: string) => {
    try {
      await apiClient.post(`/api/core/notifications/${id}/mark_read/`);
      fetchNotifications();
    } catch (error) {
      console.error(error);
    }
  };

  const markAllRead = async () => {
    try {
      await apiClient.post(`/api/core/notifications/mark_all_read/`);
      fetchNotifications();
    } catch (error) {
      console.error(error);
    }
  };

  const deleteNotification = async (id: string) => {
    try {
      await apiClient.delete(`/api/core/notifications/${id}/`);
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
              {notifications.length === 0 ? (
                <div style={{ textAlign: 'center', color: 'hsl(var(--text-muted))', padding: '32px' }}>
                  Aucune notification présente dans le registre.
                </div>
              ) : (
                notifications.map((notif) => {
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
    </div>
  );
};
