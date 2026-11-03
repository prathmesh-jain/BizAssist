import React from 'react';

/** Signed-out auth context used only when prerendering public pages at build time (no Firebase in Node). */
const value = {
    user: null,
    loading: false,
    signInWithGoogle: async () => {},
    signInWithEmail: async () => {},
    signUpWithEmail: async () => {},
    logout: async () => {},
    getIdToken: async () => null,
};

export function AuthProvider({ children }: { children: React.ReactNode }) {
    return <>{children}</>;
}

// eslint-disable-next-line react-refresh/only-export-components -- mirrors AuthContext.tsx exports
export function useAuth() {
    return value;
}
