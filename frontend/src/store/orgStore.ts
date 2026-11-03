import { create } from 'zustand';
import apiClient, { apiErrorDetail } from '../api/client';
import type { Me } from '../types';

interface OrgState {
    me: Me | null;
    isLoading: boolean;
    error: string;
    fetchMe: () => Promise<void>;
}

// Several components ask for /me on mount; share one request instead of firing duplicates.
let inFlight: Promise<void> | null = null;

const useOrgStore = create<OrgState>((set) => ({
    me: null,
    isLoading: false,
    error: '',

    fetchMe: () => {
        if (inFlight) return inFlight;
        inFlight = (async () => {
            set({ isLoading: true, error: '' });
            try {
                const response = await apiClient.get<Me>('/me');
                set({ me: response.data });
            } catch (e) {
                set({ error: apiErrorDetail(e, 'Could not load your organization.') });
            } finally {
                set({ isLoading: false });
                inFlight = null;
            }
        })();
        return inFlight;
    },
}));

/**
 * Permission check derived purely from `me`. Keep it a pure function of its arguments:
 * the React Compiler memoizes calls, so a helper that reads store state internally
 * (instead of taking `me`) would keep returning its first, pre-load answer.
 */
export function hasPermission(me: Me | null, permission: string): boolean {
    return me?.permissions.includes(permission) ?? false;
}

export default useOrgStore;
