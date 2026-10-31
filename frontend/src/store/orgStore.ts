import { create } from 'zustand';
import apiClient, { apiErrorDetail } from '../api/client';
import type { Me } from '../types';

interface OrgState {
    me: Me | null;
    isLoading: boolean;
    error: string;
    fetchMe: () => Promise<void>;
    can: (permission: string) => boolean;
}

const useOrgStore = create<OrgState>((set, get) => ({
    me: null,
    isLoading: false,
    error: '',

    fetchMe: async () => {
        set({ isLoading: true, error: '' });
        try {
            const response = await apiClient.get<Me>('/me');
            set({ me: response.data });
        } catch (e) {
            set({ error: apiErrorDetail(e, 'Could not load your organization.') });
        } finally {
            set({ isLoading: false });
        }
    },

    can: (permission: string) => get().me?.permissions.includes(permission) ?? false,
}));

export default useOrgStore;
