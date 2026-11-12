import React, { useEffect, useState } from 'react';
import { BrowserRouter, HashRouter, Routes, Route, Navigate, Link } from 'react-router-dom';
import { useAuthStore, type UserProfile } from '@/store/authStore';
import { apiClient } from '@/api/client';
import { DashboardLayout } from '@/components/layout/DashboardLayout';
import { Login } from '@/pages/auth/Login';
import { Dashboard } from '@/pages/dashboard/Dashboard';
import { Vitrine } from '@/pages/website/Vitrine';
import { Activities } from '@/pages/dashboard/Activities';
import { Clients } from '@/pages/dashboard/Clients';
import { Sales } from '@/pages/dashboard/Sales';
import { Production } from '@/pages/dashboard/Production';
import { ClotureJournaliere } from '@/pages/dashboard/ClotureJournaliere';
import { Commissions } from '@/pages/dashboard/Commissions';
import { Treasury } from '@/pages/dashboard/Treasury';
import { Finance } from '@/pages/dashboard/Finance';
import { Blockchain } from '@/pages/dashboard/Blockchain';
import { Nodes } from '@/pages/dashboard/Nodes';
import { Users } from '@/pages/dashboard/Users';
import { Settings } from '@/pages/dashboard/Settings';
import { Administration } from '@/pages/dashboard/Administration';

// Sous Electron, l'application est chargée via le protocole file:// :
// history.pushState (utilisé par BrowserRouter) y déclenche une
// SecurityError dès la première navigation. On bascule alors sur
// HashRouter (URLs en #/...), inoffensif pour une app desktop.
// Sur le web (cloud, http/https), on conserve BrowserRouter pour des
// URLs propres.
const Router = typeof window !== 'undefined' && window.location.protocol === 'file:'
  ? HashRouter
  : BrowserRouter;

// BUG-102 : garde de rôle générique pour `ProtectedRoute`. Le menu latéral
// (`DashboardLayout.tsx`) filtre déjà les liens par rôle, mais rien n'empêchait
// un accès direct par URL : depuis le correctif BUG-101, l'API finance renvoie
// 403 pour GERANT/FACTURIER/LIVREUR, ce qui affichait des erreurs brutes au lieu
// d'un message propre. `isAllowed` reçoit l'utilisateur courant et décide si la
// route est accessible ; par défaut (non fourni) la route reste ouverte à tout
// utilisateur authentifié, comme avant.
const AccessDenied: React.FC = () => (
  <div style={{ padding: '2rem', textAlign: 'center' }}>
    <h2 style={{ color: 'hsl(var(--color-danger))', marginBottom: '0.5rem' }}>Accès refusé</h2>
    <p style={{ marginBottom: '1rem' }}>
      Votre rôle ne vous permet pas d'accéder à cette page.
    </p>
    <Link to="/dashboard" style={{ color: 'hsl(var(--amber-accent))' }}>
      Retourner au tableau de bord
    </Link>
  </div>
);

const ProtectedRoute: React.FC<{
  children: React.ReactNode;
  isAllowed?: (user: UserProfile) => boolean;
}> = ({ children, isAllowed }) => {
  const { user, isAuthenticated, isLoading, fetchCurrentUser } = useAuthStore();
  const [checked, setChecked] = useState(false);

  useEffect(() => {
    const initAuth = async () => {
      await fetchCurrentUser();
      setChecked(true);
    };
    initAuth();
  }, [fetchCurrentUser]);

  if (isLoading || !checked) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: 'hsl(var(--bg-primary))',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'hsl(var(--amber-accent))',
        fontSize: '1.2rem',
        fontWeight: 600
      }}>
        Initialisation de la session sécurisée...
      </div>
    );
  }

  if (!isAuthenticated) {
    return <Navigate to="/login" replace />;
  }

  if (isAllowed && user && !user.is_superuser && !isAllowed(user)) {
    return <DashboardLayout><AccessDenied /></DashboardLayout>;
  }

  return <DashboardLayout>{children}</DashboardLayout>;
};

export const App: React.FC = () => {
  const { fetchCurrentUser } = useAuthStore();
  const [online, setOnline] = useState<boolean | null>(null);

  useEffect(() => {
    // On app mount, fetch global config to check online status
    const checkConfig = async () => {
      try {
        const response = await apiClient.get('/api/core/config/');
        setOnline(response.data.on_line);
      } catch (error) {
        setOnline(true); // default to vitrine if offline
      }
    };
    checkConfig();
    fetchCurrentUser();
  }, [fetchCurrentUser]);

  if (online === null) {
    return (
      <div style={{
        minHeight: '100vh',
        backgroundColor: 'hsl(var(--bg-primary))',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        color: 'hsl(var(--amber-accent))',
        fontSize: '1.2rem',
        fontWeight: 600
      }}>
        Connexion au serveur central...
      </div>
    );
  }

  return (
    <Router>
      <Routes>
        {/* Public landing page / Redirection based on online config */}
        <Route 
          path="/" 
          element={online ? <Vitrine /> : <Navigate to="/login" replace />} 
        />
        
        {/* Auth page */}
        <Route path="/login" element={<Login />} />
        
        {/* Protected Dashboard Routes */}
        <Route 
          path="/dashboard" 
          element={
            <ProtectedRoute>
              <Dashboard />
            </ProtectedRoute>
          } 
        />

        {/* Temporary placeholders for nav items */}
        <Route 
          path="/clients" 
          element={
            <ProtectedRoute>
              <Clients />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/sales/*" 
          element={
            <ProtectedRoute>
              <Sales />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/production" 
          element={
            <ProtectedRoute>
              <Production />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/commissions" 
          element={
            <ProtectedRoute>
              <Commissions />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/treasury" 
          element={
            // BUG-242 : même garde que le menu et l'API (`IsGerant`) — pas de FACTURIER/LIVREUR.
            <ProtectedRoute isAllowed={(u) => ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(u.role)}>
              <Treasury />
            </ProtectedRoute>
          } 
        />

        <Route
          path="/cloture-journaliere"
          element={
            // BUG-120 (volet frontend) : même garde que l'API (`IsGerant`, core/permissions.py)
            // — GERANT et au-delà, jamais FACTURIER/LIVREUR.
            <ProtectedRoute isAllowed={(u) => ['ADMIN', 'DIRECTION', 'COMPTABLE', 'GERANT'].includes(u.role)}>
              <ClotureJournaliere />
            </ProtectedRoute>
          }
        />

        <Route
          path="/finance"
          element={
            // BUG-102 : correspond exactement à `IsHeadquarters` côté API
            // (`core/permissions.py`), appliqué par le backend depuis BUG-101.
            <ProtectedRoute isAllowed={(u) => u.is_headquarters}>
              <Finance />
            </ProtectedRoute>
          }
        />

        <Route
          path="/blockchain"
          element={
            // BUG-102 : même situation que /finance, `blockchain/views.py`
            // impose aussi `IsHeadquarters` sur tous les endpoints du registre.
            <ProtectedRoute isAllowed={(u) => u.is_headquarters}>
              <Blockchain />
            </ProtectedRoute>
          }
        />

        <Route 
          path="/activities" 
          element={
            <ProtectedRoute>
              <Activities />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/admin/nodes" 
          element={
            <ProtectedRoute>
              <Nodes />
            </ProtectedRoute>
          } 
        />

        <Route 
          path="/admin/users" 
          element={
            <ProtectedRoute>
              <Users />
            </ProtectedRoute>
          } 
        />

        <Route
          path="/settings"
          element={
            <ProtectedRoute>
              <Settings />
            </ProtectedRoute>
          }
        />

        <Route
          path="/admin/backups"
          element={
            <ProtectedRoute>
              <Administration />
            </ProtectedRoute>
          }
        />

        {/* Fallback route */}
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </Router>
  );
};
