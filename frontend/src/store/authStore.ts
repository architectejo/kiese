import { create } from 'zustand';
import { apiClient } from '@/api/client';

export interface UserProfile {
  id: string;
  username: string;
  first_name: string;
  last_name: string;
  full_name: string;
  email: string;
  role: 'ADMIN' | 'DIRECTION' | 'COMPTABLE' | 'GERANT' | 'FACTURIER' | 'LIVREUR';
  role_display: string;
  team: 'A' | 'B' | '';
  team_display: string;
  node: string | null;
  node_display: string | null;
  phone: string;
  photo: string | null;
  is_active: boolean;
  is_headquarters: boolean;
  can_access_all_nodes: boolean;
  is_superuser?: boolean;
}

interface AuthState {
  user: UserProfile | null;
  accessToken: string | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  error: string | null;
  login: (username: string, password: string) => Promise<boolean>;
  logout: () => Promise<void>;
  fetchCurrentUser: () => Promise<void>;
}

export const useAuthStore = create<AuthState>((set) => ({
  user: null,
  accessToken: localStorage.getItem('kiese_access_token'),
  isAuthenticated: !!localStorage.getItem('kiese_access_token'),
  isLoading: false,
  error: null,

  login: async (username, password) => {
    set({ isLoading: true, error: null });
    try {
      const response = await apiClient.post('/api/core/auth/login/', { username, password });
      const { access, refresh, user } = response.data;
      
      localStorage.setItem('kiese_access_token', access);
      localStorage.setItem('kiese_refresh_token', refresh);
      
      set({
        user,
        accessToken: access,
        isAuthenticated: true,
        isLoading: false,
        error: null,
      });
      return true;
    } catch (error: any) {
      const errorMsg = error.response?.data?.detail || 'Identifiants ou mot de passe incorrects.';
      set({ isLoading: false, error: errorMsg });
      return false;
    }
  },

  logout: async () => {
    const refresh = localStorage.getItem('kiese_refresh_token');
    try {
      await apiClient.post('/api/core/auth/logout/', { refresh });
    } catch (e) {
      // Ignore network errors on logout
    }
    localStorage.removeItem('kiese_access_token');
    localStorage.removeItem('kiese_refresh_token');
    set({ user: null, accessToken: null, isAuthenticated: false });
  },

  fetchCurrentUser: async () => {
    if (!localStorage.getItem('kiese_access_token')) {
      set({ isAuthenticated: false, user: null });
      return;
    }
    set({ isLoading: true });
    try {
      const response = await apiClient.get('/api/core/auth/me/');
      set({ user: response.data, isAuthenticated: true, isLoading: false });
    } catch (error) {
      localStorage.removeItem('kiese_access_token');
      localStorage.removeItem('kiese_refresh_token');
      set({ user: null, accessToken: null, isAuthenticated: false, isLoading: false });
    }
  },
}));
