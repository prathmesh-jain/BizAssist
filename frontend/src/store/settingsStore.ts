import { create } from 'zustand';
import apiClient from '../api/client';
import type { AISettings } from '../types';

interface SettingsState {
    aiSettings: AISettings | null;
    isLoading: boolean;
    error: string;
    fetchAISettings: () => Promise<void>;
    updateAISettings: (payload: {
        openai_api_key?: string;
        clear_api_key?: boolean;
        primary_model?: string;
        fast_model?: string;
        nano_model?: string;
    }) => Promise<AISettings>;
}

const useSettingsStore = create<SettingsState>((set) => ({
    aiSettings: null,
    isLoading: false,
    error: '',

    fetchAISettings: async () => {
        set({ isLoading: true, error: '' });
        try {
            const response = await apiClient.get('/settings/ai');
            set({ aiSettings: response.data, isLoading: false });
        } catch (error: any) {
            set({
                isLoading: false,
                error: error?.response?.data?.detail || 'Failed to load AI settings.',
            });
        }
    },

    updateAISettings: async (payload) => {
        set({ isLoading: true, error: '' });
        try {
            const response = await apiClient.patch('/settings/ai', payload);
            set({ aiSettings: response.data, isLoading: false });
            return response.data;
        } catch (error: any) {
            const detail = error?.response?.data?.detail || 'Failed to save AI settings.';
            set({ isLoading: false, error: detail });
            throw new Error(detail);
        }
    },
}));

export default useSettingsStore;
