import { create } from 'zustand';
import apiClient, { apiErrorDetail } from '../api/client';
import type { Answers, BusinessProfile, OnboardingStep, ResearchRun } from '../types';

interface BusinessState {
    steps: OnboardingStep[];
    profile: BusinessProfile | null;
    latestRun: ResearchRun | null;
    loaded: boolean;
    error: string;
    load: () => Promise<void>;
    saveAnswers: (answers: Answers) => Promise<BusinessProfile>;
    startResearch: () => Promise<ResearchRun>;
    fetchRun: (id: string) => Promise<ResearchRun>;
    dismissOnboarding: () => Promise<void>;
}

let inFlight: Promise<void> | null = null;

const useBusinessStore = create<BusinessState>((set) => ({
    steps: [],
    profile: null,
    latestRun: null,
    loaded: false,
    error: '',

    load: () => {
        if (inFlight) return inFlight;
        inFlight = (async () => {
            try {
                const [questions, current] = await Promise.all([
                    apiClient.get<{ steps: OnboardingStep[] }>('/business-profile/questions'),
                    apiClient.get<{ profile: BusinessProfile | null; latest_run: ResearchRun | null }>('/business-profile'),
                ]);
                set({
                    steps: questions.data.steps,
                    profile: current.data.profile,
                    latestRun: current.data.latest_run,
                    loaded: true,
                    error: '',
                });
            } catch (e) {
                set({ error: apiErrorDetail(e, 'Could not load the business profile.'), loaded: true });
            } finally {
                inFlight = null;
            }
        })();
        return inFlight;
    },

    saveAnswers: async (answers) => {
        const res = await apiClient.put<{ profile: BusinessProfile }>('/business-profile/answers', { answers });
        set({ profile: res.data.profile });
        return res.data.profile;
    },

    startResearch: async () => {
        const res = await apiClient.post<{ run: ResearchRun }>('/business-profile/research');
        set({ latestRun: res.data.run });
        return res.data.run;
    },

    fetchRun: async (id) => {
        const res = await apiClient.get<{ run: ResearchRun }>(`/business-profile/research/${id}`);
        set({ latestRun: res.data.run });
        return res.data.run;
    },

    dismissOnboarding: async () => {
        await apiClient.post('/business-profile/dismiss-onboarding');
        set((s) => ({ profile: s.profile ? { ...s.profile, onboarding_dismissed: true } : s.profile }));
    },
}));

/** Whether a question should be asked, given the answers so far. */
export function isVisible(showIf: { field: string; in: string[] } | undefined, answers: Answers): boolean {
    if (!showIf) return true;
    const value = answers[showIf.field];
    if (Array.isArray(value)) return value.some((v) => showIf.in.includes(v));
    return typeof value === 'string' && showIf.in.includes(value);
}

export default useBusinessStore;
