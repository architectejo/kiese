import { create } from 'zustand';

export type Theme = 'dark' | 'light' | 'classic';

interface ThemeState {
  theme: Theme;
  setTheme: (theme: Theme) => void;
}

export const useThemeStore = create<ThemeState>((set) => {
  // Read initial theme from localStorage or default to dark
  const savedTheme = (localStorage.getItem('kiese_theme') as Theme) || 'dark';
  
  // Set initial class on documentElement
  document.documentElement.className = `theme-${savedTheme}`;

  return {
    theme: savedTheme,
    setTheme: (theme: Theme) => {
      localStorage.setItem('kiese_theme', theme);
      document.documentElement.className = `theme-${theme}`;
      set({ theme });
    },
  };
});
