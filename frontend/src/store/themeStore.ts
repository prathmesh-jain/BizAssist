import { create } from 'zustand';
import { persist } from 'zustand/middleware';

type Theme = 'light' | 'dark';

interface ThemeState {
    theme: Theme;
    toggleTheme: () => void;
    setTheme: (theme: Theme) => void;
}

// First visit follows the operating system; after that, the user's choice sticks.
const systemTheme = (): Theme =>
    typeof window !== 'undefined' && window.matchMedia?.('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';

const useThemeStore = create<ThemeState>()(
    persist(
        (set) => ({
            theme: systemTheme(),
            toggleTheme: () =>
                set((state) => ({ theme: state.theme === 'light' ? 'dark' : 'light' })),
            setTheme: (theme) => set({ theme }),
        }),
        {
            name: 'theme-storage',
        }
    )
);

export default useThemeStore;
