import { create } from 'zustand';
import type { User } from '../types';

interface AuthState {
    dbUser: User | null;
    setDbUser: (user: User | null) => void;
    logout: () => void;
}

const useAuthStore = create<AuthState>((set) => ({
    dbUser: null,
    setDbUser: (user) => set({ dbUser: user }),
    logout: () => set({ dbUser: null }),
}));

export default useAuthStore;
