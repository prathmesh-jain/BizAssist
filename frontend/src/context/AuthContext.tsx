import React from 'react';
import type { User } from 'firebase/auth';
import {
    onAuthStateChanged,
    signInWithEmailAndPassword,
    createUserWithEmailAndPassword,
    signInWithPopup,
    signOut,
} from 'firebase/auth';

import { firebaseAuth, googleProvider } from '../firebase';

type AuthContextValue = {
    user: User | null;
    loading: boolean;
    signInWithGoogle: () => Promise<void>;
    signInWithEmail: (email: string, password: string) => Promise<void>;
    signUpWithEmail: (email: string, password: string) => Promise<void>;
    logout: () => Promise<void>;
    getIdToken: () => Promise<string | null>;
};

const AuthContext = React.createContext<AuthContextValue | undefined>(undefined);

export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [user, setUser] = React.useState<User | null>(null);
    const [loading, setLoading] = React.useState(true);

    React.useEffect(() => {
        const unsub = onAuthStateChanged(firebaseAuth, (u: User | null) => {
            setUser(u);
            setLoading(false);
        });
        return () => unsub();
    }, []);

    const signInWithGoogle = React.useCallback(async () => {
        await signInWithPopup(firebaseAuth, googleProvider);
    }, []);

    const signInWithEmail = React.useCallback(async (email: string, password: string) => {
        await signInWithEmailAndPassword(firebaseAuth, email, password);
    }, []);

    const signUpWithEmail = React.useCallback(async (email: string, password: string) => {
        await createUserWithEmailAndPassword(firebaseAuth, email, password);
    }, []);

    const logout = React.useCallback(async () => {
        await signOut(firebaseAuth);
    }, []);

    const getIdTokenFn = React.useCallback(async () => {
        const u = firebaseAuth.currentUser;
        if (!u) return null;
        return await u.getIdToken(true);
    }, []);

    const value: AuthContextValue = {
        user,
        loading,
        signInWithGoogle,
        signInWithEmail,
        signUpWithEmail,
        logout,
        getIdToken: getIdTokenFn,
    };

    return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
    const ctx = React.useContext(AuthContext);
    if (!ctx) throw new Error('useAuth must be used within AuthProvider');
    return ctx;
}
