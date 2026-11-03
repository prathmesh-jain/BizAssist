import type { Answers, Basis, BusinessProfile, Competitor, Opportunity, ResearchResult } from '../../types';

// Review state shared by onboarding (after research) and profile editing.

export type Included<T> = T & { include: boolean };

export interface ReviewDraft {
    answers: Answers;
    subdomain: string;
    provenance: Record<string, { basis: Basis; sources: string[] }>;
    competitors: Included<Competitor>[];
    opportunities: Included<Opportunity>[];
}

export function draftFromResearch(answers: Answers, result: ResearchResult): ReviewDraft {
    const next: Answers = { ...answers };
    const provenance: ReviewDraft['provenance'] = {};
    let subdomain = '';
    for (const [key, field] of Object.entries(result.profile)) {
        provenance[key] = { basis: field.basis, sources: field.sources };
        if (field.value === null || (Array.isArray(field.value) && !field.value.length)) continue;
        if (key === 'subdomain') subdomain = String(field.value);
        else if (next[key] === undefined) next[key] = field.value;
    }
    return {
        answers: next,
        subdomain,
        provenance,
        competitors: result.competitors.map((c) => ({ ...c, include: true })),
        opportunities: result.opportunities.map((o) => ({ ...o, include: true })),
    };
}

export function draftFromProfile(profile: BusinessProfile): ReviewDraft {
    return {
        answers: { ...profile.answers },
        subdomain: profile.subdomain || '',
        provenance: { ...profile.provenance },
        competitors: profile.competitors.map((c) => ({ ...c, include: true })),
        opportunities: profile.opportunities.map((o) => ({ ...o, include: true })),
    };
}

export function confirmPayload(draft: ReviewDraft) {
    const strip = <T extends { include: boolean }>(items: T[]) =>
        items.filter((i) => i.include).map((i) => {
            const copy: Partial<T> = { ...i };
            delete copy.include;
            return copy;
        });
    return {
        answers: draft.answers,
        subdomain: draft.subdomain || null,
        competitors: strip(draft.competitors),
        opportunities: strip(draft.opportunities),
        provenance: draft.provenance,
    };
}

