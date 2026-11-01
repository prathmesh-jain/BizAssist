import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Briefcase, Loader2, Pencil, RefreshCw } from 'lucide-react';
import apiClient, { apiErrorDetail } from '../../api/client';
import useBusinessStore from '../../store/businessStore';
import useOrgStore, { hasPermission } from '../../store/orgStore';
import ProfileReview from './ProfileReview';
import { confirmPayload, draftFromProfile, type ReviewDraft } from './reviewDraft';
import { BasisBadge, SourceLinks } from './Provenance';
import { hostOf } from '../../lib/url';
import type { AnswerValue, OnboardingQuestion } from '../../types';

const SUMMARY_FIELDS = ['location', 'industry', 'business_model', 'scale', 'geography'];
const LIST_FIELDS: [string, string][] = [
    ['products_services', 'Products and services'],
    ['customer_segments', 'Customers'],
    ['goals', 'Goals'],
    ['challenges', 'Challenges'],
    ['monitoring_preferences', 'BizAssist watches'],
    ['existing_tools', 'Tools in use'],
];

export default function BusinessProfileView() {
    const navigate = useNavigate();
    const { me, fetchMe } = useOrgStore();
    const { steps, profile, latestRun, loaded, error, load, startResearch } = useBusinessStore();
    const [editing, setEditing] = React.useState(false);
    const [busy, setBusy] = React.useState(false);
    const [actionError, setActionError] = React.useState('');

    React.useEffect(() => {
        if (!me) fetchMe();
        load();
    }, [me, fetchMe, load]);

    const questions = React.useMemo(
        () => Object.fromEntries(steps.flatMap((s) => s.questions).map((q) => [q.id, q])) as Record<string, OnboardingQuestion>,
        [steps],
    );

    if (!loaded || !me) return <div className="p-8 text-sm text-muted-foreground flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>;
    if (error) return <div className="p-8 text-sm text-destructive">{error}</div>;

    const manager = hasPermission(me, 'business.manage');
    const researching = latestRun?.status === 'queued' || latestRun?.status === 'running';

    if (!profile || profile.status !== 'confirmed') {
        return (
            <Page>
                <div className="bg-card border border-border rounded-2xl p-8 text-center shadow-sm">
                    <Briefcase className="w-10 h-10 mx-auto text-primary" />
                    <h2 className="mt-3 text-xl font-bold text-foreground">No business profile yet</h2>
                    <p className="mt-1 text-muted-foreground max-w-md mx-auto">
                        {manager
                            ? 'Tell BizAssist about your business. It researches public information and you confirm what is right.'
                            : `An admin of ${me.organization.name} hasn't set up the business profile yet.`}
                    </p>
                    {manager && (
                        <button onClick={() => navigate('/app/onboarding')} className="mt-5 px-5 py-2.5 rounded-xl bg-primary text-primary-foreground text-sm font-bold">
                            {researching ? 'View research progress' : profile ? 'Continue setup' : 'Set up business profile'}
                        </button>
                    )}
                </div>
            </Page>
        );
    }

    const save = async (draft: ReviewDraft) => {
        setBusy(true);
        setActionError('');
        try {
            await apiClient.post('/business-profile/confirm', confirmPayload(draft));
            await load();
            setEditing(false);
        } catch (e) {
            setActionError(apiErrorDetail(e, 'Could not save the profile.'));
        } finally {
            setBusy(false);
        }
    };

    const rerun = async () => {
        setBusy(true);
        setActionError('');
        try {
            if (!researching) await startResearch();
            navigate('/app/onboarding');
        } catch (e) {
            setActionError(apiErrorDetail(e, 'Could not start research.'));
            setBusy(false);
        }
    };

    if (editing) {
        return (
            <Page>
                <h2 className="text-2xl font-bold text-foreground mb-6">Edit business profile</h2>
                <ProfileReview steps={steps} initial={draftFromProfile(profile)} busy={busy} error={actionError}
                    onConfirm={save} onBack={() => setEditing(false)} confirmLabel="Save changes" />
            </Page>
        );
    }

    const a = profile.answers;
    const label = (key: string, value: AnswerValue | undefined) => format(value, questions[key]);

    return (
        <Page>
            <div className="flex flex-wrap items-start justify-between gap-4">
                <div className="min-w-0">
                    <h2 className="text-3xl font-bold text-foreground tracking-tight break-words">{String(a.name ?? '')}</h2>
                    <p className="text-muted-foreground mt-1">
                        {[profile.subdomain, label('industry', a.industry)].filter(Boolean).join(' · ')}
                        {a.website && (
                            <> · <a href={String(a.website).includes('://') ? String(a.website) : `https://${a.website}`} target="_blank" rel="noopener noreferrer" className="text-primary hover:underline">{hostOf(String(a.website).includes('://') ? String(a.website) : `https://${a.website}`)}</a></>
                        )}
                    </p>
                    {profile.confirmed_at && <p className="text-xs text-muted-foreground mt-1">Confirmed {new Date(profile.confirmed_at).toLocaleDateString()}</p>}
                </div>
                {manager && (
                    <div className="flex flex-wrap gap-2">
                        <button onClick={rerun} disabled={busy} className="flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-50">
                            <RefreshCw className={`w-4 h-4 ${researching ? 'animate-spin' : ''}`} /> {researching ? 'Research running' : 'Research again'}
                        </button>
                        <button onClick={() => setEditing(true)} className="flex items-center gap-2 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-bold">
                            <Pencil className="w-4 h-4" /> Edit
                        </button>
                    </div>
                )}
            </div>
            {actionError && <p className="mt-3 text-sm text-destructive">{actionError}</p>}

            {a.description && <p className="mt-5 text-foreground leading-relaxed">{String(a.description)}</p>}

            <dl className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
                {SUMMARY_FIELDS.filter((k) => a[k] !== undefined).map((k) => (
                    <div key={k} className="rounded-xl border border-border bg-card p-4">
                        <dt className="flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
                            {questions[k]?.label ?? k}
                            {profile.provenance[k] && <BasisBadge basis={profile.provenance[k].basis} />}
                        </dt>
                        <dd className="mt-1 text-foreground">{label(k, a[k])}</dd>
                    </div>
                ))}
            </dl>

            <div className="mt-6 grid gap-4 md:grid-cols-2">
                {LIST_FIELDS.filter(([k]) => Array.isArray(a[k]) && (a[k] as string[]).length).map(([k, title]) => (
                    <div key={k} className="rounded-2xl border border-border bg-card p-5">
                        <h3 className="font-bold text-foreground">{title}</h3>
                        <div className="mt-2 flex flex-wrap gap-2">
                            {(a[k] as string[]).map((v) => (
                                <span key={v} className="rounded-full bg-muted px-3 py-1 text-sm text-foreground">{label(k, v)}</span>
                            ))}
                        </div>
                    </div>
                ))}
            </div>

            {profile.competitors.length > 0 && (
                <section className="mt-6 rounded-2xl border border-border bg-card p-5">
                    <h3 className="font-bold text-foreground">Competitors</h3>
                    <ul className="mt-3 divide-y divide-border">
                        {profile.competitors.map((c) => (
                            <li key={c.name} className="py-3">
                                <div className="flex flex-wrap items-center gap-2">
                                    <span className="font-semibold text-foreground">{c.name}</span>
                                    <span className="text-xs uppercase font-bold text-muted-foreground">{c.competition}</span>
                                    <SourceLinks sources={c.sources} />
                                </div>
                                {c.rationale && <p className="text-sm text-muted-foreground mt-0.5">{c.rationale}</p>}
                            </li>
                        ))}
                    </ul>
                </section>
            )}

            {profile.opportunities.length > 0 && (
                <section className="mt-6 rounded-2xl border border-border bg-card p-5">
                    <h3 className="font-bold text-foreground">Focus areas</h3>
                    <ul className="mt-3 space-y-3">
                        {profile.opportunities.map((o) => (
                            <li key={o.title}>
                                <p className="font-semibold text-foreground">{o.title}</p>
                                {o.rationale && <p className="text-sm text-muted-foreground">{o.rationale}</p>}
                            </li>
                        ))}
                    </ul>
                </section>
            )}
        </Page>
    );
}

function format(value: AnswerValue | undefined, question?: OnboardingQuestion): string {
    const one = (v: string) => question?.options?.find((o) => o.value === v)?.label ?? v.replace(/_/g, ' ');
    if (value === undefined) return '';
    if (Array.isArray(value)) return value.map(one).join(', ');
    return typeof value === 'string' ? one(value) : String(value);
}

function Page({ children }: { children: React.ReactNode }) {
    return (
        <div className="flex-1 overflow-y-auto bg-background p-4 sm:p-6 lg:p-8">
            <div className="max-w-4xl mx-auto">{children}</div>
        </div>
    );
}
