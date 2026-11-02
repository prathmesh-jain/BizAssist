import React from 'react';
import { AlertTriangle, Check, Loader2, Plus } from 'lucide-react';
import QuestionField from './QuestionField';
import { BasisBadge, SourceLinks } from './Provenance';
import { hostOf } from '../../lib/url';
import type {
    AnswerValue, Basis, Competitor, OnboardingQuestion, OnboardingStep, Opportunity, ResearchField, ResearchResult,
} from '../../types';
import type { Included, ReviewDraft } from './reviewDraft';

const PROFILE_FIELDS = [
    'name', 'website', 'address', 'location', 'industry', 'subdomain', 'business_model', 'scale', 'geography',
    'description', 'products_services', 'customer_segments',
];
const PREFERENCE_FIELDS = ['goals', 'challenges', 'monitoring_preferences'];
const SUBDOMAIN_QUESTION: OnboardingQuestion = {
    id: 'subdomain', label: 'Niche', type: 'text', placeholder: 'e.g. grocery, dental clinic, B2B SaaS',
};

interface Props {
    steps: OnboardingStep[];
    initial: ReviewDraft;
    research?: ResearchResult | null;
    busy: boolean;
    error?: string;
    onConfirm: (draft: ReviewDraft) => void;
    onBack?: () => void;
    confirmLabel?: string;
}

export default function ProfileReview({ steps, initial, research, busy, error, onConfirm, onBack, confirmLabel }: Props) {
    const [draft, setDraft] = React.useState<ReviewDraft>(initial);
    const questions = React.useMemo(
        () => Object.fromEntries(steps.flatMap((s) => s.questions).map((q) => [q.id, q])) as Record<string, OnboardingQuestion>,
        [steps],
    );

    const setField = (key: string, value: AnswerValue | undefined) => {
        setDraft((d) => {
            const prev = d.provenance[key];
            // Editing your own answer keeps it yours; editing a researched value marks it edited.
            const basis: Basis = !prev || prev.basis === 'user_provided' ? 'user_provided' : 'edited';
            const provenance = { ...d.provenance, [key]: { basis, sources: basis === 'edited' ? [] : prev?.sources ?? [] } };
            if (key === 'subdomain') return { ...d, subdomain: typeof value === 'string' ? value : '', provenance };
            const answers = { ...d.answers };
            if (value === undefined) delete answers[key];
            else answers[key] = value;
            return { ...d, answers, provenance };
        });
    };

    const applySuggestion = (key: string, suggested: ResearchField) => {
        if (suggested.value === null) return;
        setDraft((d) => ({
            ...d,
            answers: { ...d.answers, [key]: suggested.value as AnswerValue },
            provenance: { ...d.provenance, [key]: { basis: suggested.basis, sources: suggested.sources } },
        }));
    };

    const nameMissing = !String(draft.answers.name ?? '').trim();

    return (
        <div className="space-y-6">
            {research?.warnings?.length ? (
                <div className="rounded-xl border border-warning/30 bg-warning/10 p-4 text-sm text-foreground">
                    <p className="flex items-center gap-2 font-semibold"><AlertTriangle className="w-4 h-4 text-warning" /> Research was incomplete</p>
                    <ul className="mt-1 list-disc pl-5 text-muted-foreground">
                        {research.warnings.map((w) => <li key={w}>{w}</li>)}
                    </ul>
                </div>
            ) : null}

            <Section title="Business profile" subtitle="Check each field. Estimated values are guesses from public evidence; correct anything that's wrong.">
                <div className="grid gap-5 md:grid-cols-2">
                    {PROFILE_FIELDS.map((key) => {
                        const question = key === 'subdomain' ? SUBDOMAIN_QUESTION : questions[key];
                        if (!question) return null;
                        const value = key === 'subdomain' ? draft.subdomain || undefined : draft.answers[key];
                        const prov = draft.provenance[key];
                        const researched = research?.profile[key];
                        const wide = ['description', 'products_services', 'customer_segments', 'business_model'].includes(key);
                        return (
                            <div key={key} className={wide ? 'md:col-span-2' : ''}>
                                <QuestionField
                                    question={{ ...question, help: undefined, required: key === 'name' }}
                                    value={value}
                                    onChange={(v) => setField(key, v)}
                                    adornment={prov && (
                                        <>
                                            <BasisBadge basis={prov.basis} note={researched?.note} />
                                            <SourceLinks sources={prov.sources} />
                                        </>
                                    )}
                                />
                                {prov?.basis === 'estimated' && researched?.note && (
                                    <p className="mt-1 text-xs text-muted-foreground">Estimate based on: {researched.note}</p>
                                )}
                                {researched?.suggested && researched.suggested.value !== null && (
                                    <p className="mt-1.5 text-xs text-muted-foreground">
                                        Research suggests: <span className="text-foreground">{display(researched.suggested.value, question)}</span>{' '}
                                        <button type="button" onClick={() => applySuggestion(key, researched.suggested!)} className="font-semibold text-primary hover:underline">
                                            Use this
                                        </button>
                                    </p>
                                )}
                            </div>
                        );
                    })}
                </div>
            </Section>

            {research?.public_facts?.length ? (
                <Section title="Public facts found">
                    <ul className="space-y-2 text-sm">
                        {research.public_facts.map((f) => (
                            <li key={f.fact} className="flex flex-wrap items-baseline gap-2">
                                <span className="text-foreground">{f.fact}</span><SourceLinks sources={f.sources} />
                            </li>
                        ))}
                    </ul>
                </Section>
            ) : null}

            <Section title="Competitors" subtitle="Keep the ones that really compete with you. Add any research missed.">
                <CompetitorList
                    items={draft.competitors}
                    onChange={(competitors) => setDraft((d) => ({ ...d, competitors }))}
                />
            </Section>

            <Section title="Improvement opportunities" subtitle="Selected items guide BizAssist's suggestions and insights.">
                <OpportunityList
                    items={draft.opportunities}
                    onChange={(opportunities) => setDraft((d) => ({ ...d, opportunities }))}
                />
                {research?.industry_trends?.length ? (
                    <div className="mt-5">
                        <h4 className="text-sm font-semibold text-foreground">Industry trends</h4>
                        <ul className="mt-2 space-y-1.5 text-sm">
                            {research.industry_trends.map((t) => (
                                <li key={t.summary} className="flex flex-wrap items-baseline gap-2">
                                    <span className="text-muted-foreground">{t.summary}</span><SourceLinks sources={t.sources} />
                                </li>
                            ))}
                        </ul>
                    </div>
                ) : null}
            </Section>

            <Section title="What BizAssist should focus on">
                <div className="space-y-5">
                    {PREFERENCE_FIELDS.map((key) => questions[key] && (
                        <QuestionField key={key} question={questions[key]} value={draft.answers[key]} onChange={(v) => setField(key, v)} />
                    ))}
                </div>
            </Section>

            {research?.sources?.length ? (
                <details className="rounded-2xl border border-border bg-card p-5 text-sm">
                    <summary className="cursor-pointer font-semibold text-foreground">
                        {research.sources.length} sources consulted
                    </summary>
                    <ul className="mt-3 space-y-1">
                        {research.sources.map((s) => (
                            <li key={s.url} className="truncate">
                                <span className="text-xs uppercase text-muted-foreground mr-2">{s.kind}</span>
                                <a href={s.url} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{s.title || hostOf(s.url)}</a>
                            </li>
                        ))}
                    </ul>
                </details>
            ) : null}

            {error && <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</div>}

            <div className="flex flex-wrap justify-end gap-3 pb-6">
                {onBack && (
                    <button type="button" onClick={onBack} disabled={busy} className="px-4 py-2.5 rounded-xl border border-border text-foreground hover:bg-muted text-sm disabled:opacity-50">
                        Back
                    </button>
                )}
                <button
                    type="button"
                    disabled={busy || nameMissing}
                    onClick={() => onConfirm(draft)}
                    className="flex items-center gap-2 px-5 py-2.5 rounded-xl btn-glow text-sm font-semibold disabled:opacity-50"
                >
                    {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Check className="w-4 h-4" />}
                    {confirmLabel || 'Confirm profile'}
                </button>
            </div>
        </div>
    );
}

function display(value: string | string[] | null, question: OnboardingQuestion): string {
    const label = (v: string) => question.options?.find((o) => o.value === v)?.label ?? v;
    if (Array.isArray(value)) return value.map(label).join(', ');
    return value ? label(value) : '';
}

function Section({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
    return (
        <section className="bg-card border border-border rounded-2xl p-5 sm:p-6">
            <h3 className="font-display text-xl font-semibold text-foreground">{title}</h3>
            {subtitle && <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>}
            <div className="mt-4">{children}</div>
        </section>
    );
}

const SCALE_LABEL: Record<Competitor['relative_scale'], string> = {
    similar: 'similar size', smaller: 'smaller', larger: 'larger', much_larger: 'much larger', unknown: 'size unknown',
};

function CompetitorList({ items, onChange }: { items: Included<Competitor>[]; onChange: (items: Included<Competitor>[]) => void }) {
    const [name, setName] = React.useState('');
    const [website, setWebsite] = React.useState('');
    const add = () => {
        if (!name.trim()) return;
        onChange([...items, {
            name: name.trim(), website: website.trim() || null, competition: 'direct', relative_scale: 'unknown',
            rationale: '', sources: [], added_by_user: true, include: true,
        }]);
        setName('');
        setWebsite('');
    };
    return (
        <div className="space-y-3">
            {items.length === 0 && <p className="text-sm text-muted-foreground">No competitors yet.</p>}
            {items.map((c, i) => (
                <label key={`${c.name}-${i}`} className={`flex gap-3 rounded-xl border p-3.5 cursor-pointer transition-colors ${c.include ? 'border-border bg-background' : 'border-border/60 opacity-60'}`}>
                    <input
                        type="checkbox"
                        checked={c.include}
                        onChange={() => onChange(items.map((x, j) => (j === i ? { ...x, include: !x.include } : x)))}
                        className="mt-1 h-4 w-4"
                    />
                    <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-foreground">{c.name}</span>
                            <span className={`px-2 py-0.5 rounded-full text-[11px] font-semibold uppercase border ${c.competition === 'direct' ? 'border-primary/30 text-primary bg-primary/10' : 'border-border text-muted-foreground bg-muted'}`}>
                                {c.competition}
                            </span>
                            <span className="text-xs text-muted-foreground">{SCALE_LABEL[c.relative_scale]}</span>
                            {c.added_by_user && <span className="text-xs text-muted-foreground">added by you</span>}
                        </div>
                        {c.website && <a href={c.website.includes('://') ? c.website : `https://${c.website}`} target="_blank" rel="noopener noreferrer" className="text-xs text-primary hover:underline">{hostOf(c.website.includes('://') ? c.website : `https://${c.website}`)}</a>}
                        {c.rationale && <p className="mt-1 text-sm text-muted-foreground">{c.rationale}</p>}
                        {c.sources.length > 0 && <div className="mt-1"><SourceLinks sources={c.sources} /></div>}
                    </div>
                </label>
            ))}
            <div className="flex flex-wrap gap-2 pt-1">
                <input value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} placeholder="Competitor name" aria-label="Competitor name"
                    className="flex-1 min-w-40 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground" />
                <input value={website} onChange={(e) => setWebsite(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} placeholder="Website (optional)" aria-label="Competitor website"
                    className="flex-1 min-w-40 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground" />
                <button type="button" onClick={add} className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted">
                    <Plus className="w-4 h-4" /> Add
                </button>
            </div>
        </div>
    );
}

function OpportunityList({ items, onChange }: { items: Included<Opportunity>[]; onChange: (items: Included<Opportunity>[]) => void }) {
    const [title, setTitle] = React.useState('');
    const add = () => {
        if (!title.trim()) return;
        onChange([...items, { title: title.trim(), area: '', rationale: '', basis: 'user_added', sources: [], include: true }]);
        setTitle('');
    };
    return (
        <div className="space-y-3">
            {items.length === 0 && <p className="text-sm text-muted-foreground">No suggestions yet.</p>}
            {items.map((o, i) => (
                <label key={`${o.title}-${i}`} className={`flex gap-3 rounded-xl border p-3.5 cursor-pointer ${o.include ? 'border-border bg-background' : 'border-border/60 opacity-60'}`}>
                    <input
                        type="checkbox"
                        checked={o.include}
                        onChange={() => onChange(items.map((x, j) => (j === i ? { ...x, include: !x.include } : x)))}
                        className="mt-1 h-4 w-4"
                    />
                    <div className="min-w-0 flex-1">
                        <div className="flex flex-wrap items-center gap-2">
                            <span className="font-semibold text-foreground">{o.title}</span>
                            {o.area && <span className="text-xs text-muted-foreground capitalize">{o.area}</span>}
                            <span className="text-[11px] text-muted-foreground">
                                {o.basis === 'evidence' ? '· based on evidence' : o.basis === 'general_practice' ? '· common practice' : '· added by you'}
                            </span>
                        </div>
                        {o.rationale && <p className="mt-1 text-sm text-muted-foreground">{o.rationale}</p>}
                        {o.sources.length > 0 && <div className="mt-1"><SourceLinks sources={o.sources} /></div>}
                    </div>
                </label>
            ))}
            <div className="flex flex-wrap gap-2 pt-1">
                <input value={title} onChange={(e) => setTitle(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && add()} placeholder="Add something you want to improve" aria-label="New opportunity"
                    className="flex-1 min-w-48 rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground" />
                <button type="button" onClick={add} className="flex items-center gap-1.5 px-3 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted">
                    <Plus className="w-4 h-4" /> Add
                </button>
            </div>
        </div>
    );
}
