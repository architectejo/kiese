import axios from 'axios';

// Mode desktop (Electron) : le port du backend local est choisi
// dynamiquement à chaque démarrage (docs/architecture/DESKTOP.md §5 étape
// 7) — `window.kiese.apiUrl` est injecté de façon synchrone par
// `desktop/src/preload.ts` avant l'évaluation de ce module. En dehors du
// desktop (navigateur, POS Android), `window.kiese` est absent et on
// retombe sur `VITE_API_URL` figé au build, comme avant.
// Le type complet de `window.kiese` (incluant `backup.*`) est déclaré une
// seule fois dans `src/types/kiese.d.ts`.
const API_BASE_URL =
  (typeof window !== 'undefined' && window.kiese?.apiUrl) ||
  import.meta.env.VITE_API_URL ||
  'http://localhost:8000';

// BUG-284 : évènement émis quand l'API exige le changement du mot de passe initial.
export const PASSWORD_CHANGE_REQUIRED_EVENT = 'kiese:password-change-required';

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    'Content-Type': 'application/json',
  },
});

// Request interceptor to automatically add the Authorization header
apiClient.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('kiese_access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
  },
  (error) => {
    return Promise.reject(error);
  }
);

// Response interceptor to handle token refresh and authentication failure
apiClient.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    
    // If token has expired or is invalid, try to refresh
    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;
      const refreshToken = localStorage.getItem('kiese_refresh_token');
      
      if (refreshToken) {
        try {
          const response = await axios.post(`${API_BASE_URL}/api/core/auth/login/refresh/`, {
            refresh: refreshToken,
          });
          
          const newAccessToken = response.data.access;
          localStorage.setItem('kiese_access_token', newAccessToken);
          
          originalRequest.headers.Authorization = `Bearer ${newAccessToken}`;
          return apiClient(originalRequest);
        } catch (refreshError) {
          // If refresh fails, clear tokens and redirect to login
          localStorage.removeItem('kiese_access_token');
          localStorage.removeItem('kiese_refresh_token');
          window.location.href = '/login';
        }
      }
    }
    
    // BUG-284 : mot de passe initial à changer — l'interface affiche l'écran bloquant.
    if (
      error.response?.status === 403 &&
      (error.response?.data as { code?: unknown } | undefined)?.code === 'password_change_required' &&
      typeof window !== 'undefined'
    ) {
      window.dispatchEvent(new CustomEvent(PASSWORD_CHANGE_REQUIRED_EVENT));
    }

    return Promise.reject(error);
  }
);
