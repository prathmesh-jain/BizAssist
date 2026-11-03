import React from 'react';
import { useNavigate } from 'react-router-dom';
import { Check, Circle, Loader2, Search, Sparkles } from 'lucide-react';
import apiClient, { apiErrorDetail } from '../../api/client';
import useBusinessStore, { isVisible } from '../../store/businessStore';
import useOrgStore, { hasPermission } from '../../store/orgStore';
import QuestionField from './QuestionField';
import ProfileReview from './ProfileReview';
import { confirmPayload, draftFromProfile, draftFromResearch, type ReviewDraft } from './reviewDraft';
import type { Answers, ResearchRun } from '../../types';

type Phase = 'questions' | 'research' | 'review';

export default function OnboardingFlow() {
    const navigate = useNavigate();
    const { me, fetchMe } = useOrgStore();
    const { steps, profile, latestRun, loaded, error: loadError, load, saveAnswers, startResearch, fetchRun, dismissOnboarding } = useBusinessStore();

    const [phase, setPhase] = React.useState<Phase>('questions');
    const [stepIndex, setStepIndex] = React.useState(0);
    const [answers, setAnswers] = React.useState<Answers>({});
    const [run, setRun] = React.useState<ResearchRun | null>(null);
    const [draft, setDraft] = React.useState<ReviewDraft | null>(null);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');
    const initialized = React.useRef(false);

    React.useEffect(() => {
        if (!me) fetchMe();
        load();
    }, [me, fetchMe, load]);

    // Resume where the user left off: an active run, an unreviewed result, or saved answers.
    React.useEffect(() => {
        if (!loaded || initialized.current) return;
        initialized.current = true;
        setAnswers(profile?.answers ?? {});
        if (latestRun && (latestRun.status === 'queued' || latestRun.status === 'running')) {
            setRun(latestRun);
            setPhase('research');
        } else if (latestRun?.status === 'completed' && latestRun.result && profile?.status !== 'confirmed') {
            setRun(latestRun);
            setDraft(draftFromResearch(profile?.answers ?? {}, latestRun.result));
            setPhase('review');
        }
    }, [loaded, profile, latestRun]);

    // Poll the research run until it finishes.
    React.useEffect(() => {
        if (phase !== 'research' || !run || run.status === 'completed' || run.status === 'failed') return;
        const timer = window.setTimeout(async () => {
            try {
                const next = await fetchRun(run.id);
                setRun(next);
                if (next.status === 'completed' && next.result) {
                    setDraft(draftFromResearch(answers, next.result));
                    setPhase('review');
                }
            } catch (e) {
                setError(apiErrorDetail(e, 'Lost track of the research run.'));
            }
        }, 2000);
        return () => window.clearTimeout(timer);
    }, [phase, run, fetchRun, answers]);

    if (!loaded || !me) {
        return <div className="p-8 text-sm text-muted-foreground flex items-center gap-2"><Loader2 className="w-4 h-4 animate-spin" /> Loading…</div>;
    }
    if (!hasPermission(me, 'business.manage')) {
        return (
            <Shell title="Business profile">
                <p className="text-muted-foreground">An admin or owner of {me.organization.name} sets up the business profile. Ask them to complete onboarding.</p>
            </Shell>
        );
    }
    if (loadError) return <Shell title="Business onboarding"><p className="text-destructive">{loadError}</p></Shell>;

    const step = steps[stepIndex];
    const visibleQuestions = step ? step.questions.filter((q) => isVisible(q.show_if, answers)) : [];
    // Skip steps whose questions are all conditional and don't apply.
    const visibleSteps = steps.filter((s) => s.questions.some((q) => isVisible(q.show_if, answers)));
    const position = visibleSteps.indexOf(step);

    const goTo = (direction: 1 | -1) => {
        let i = stepIndex + direction;
        while (steps[i] && !steps[i].questions.some((q) => isVisible(q.show_if, answers))) i += direction;
        if (steps[i]) setStepIndex(i);
    };

    const missing = visibleQuestions.filter((q) => q.required && (answers[q.id] === undefined || answers[q.id] === ''));

    const persist = async () => {
        // Drop answers to conditional questions that no longer apply.
        const applicable = Object.fromEntries(
            Object.entries(answers).filter(([key]) => {
                const q = steps.flatMap((s) => s.questions).find((x) => x.id === key);
                return !q || isVisible(q.show_if, answers);
            }),
        );
        await saveAnswers(applicable);
        return applicable;
    };

    const next = async () => {
        setBusy(true);
        setError('');
        try {
            await persist();
            goTo(1);
        } catch (e) {
            setError(apiErrorDetail(e, 'Could not save your answers.'));
        } finally {
            setBusy(false);
        }
    };

    const research = async () => {
        setBusy(true);
        setError('');
        try {
            await persist();
            const started = await startResearch();
            setRun(started);
            setPhase('research');
        } catch (e) {
            setError(apiErrorDetail(e, 'Could not start research.'));
        } finally {
            setBusy(false);
        }
    };

    const reviewWithoutResearch = async () => {
        setBusy(true);
        setError('');
        try {
            const saved = await persist();
            setDraft(draftFromProfile({ ...(profile ?? emptyProfile()), answers: saved }));
            setPhase('review');
        } catch (e) {
            setError(apiErrorDetail(e, 'Could not save your answers.'));
        } finally {
            setBusy(false);
        }
    };

    const confirm = async (final: ReviewDraft) => {
        setBusy(true);
        setError('');
        try {
            await apiClient.post('/business-profile/confirm', confirmPayload(final));
            await load();
            navigate('/app/business', { replace: true });
        } catch (e) {
            setError(apiErrorDetail(e, 'Could not save the profile.'));
            setBusy(false);
        }
    };

    const skip = async () => {
        try {
            await dismissOnboarding();
        } finally {
            navigate('/app/chat');
        }
    };

    if (phase === 'research' && run) {
        return (
            <Shell title="Researching your business" subtitle="This usually takes a minute or two. You can leave this page; research keeps running.">
                <ResearchProgress run={run} />
                {run.status === 'failed' && (
                    <div className="mt-6 space-y-3">
                        <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{run.error}</div>
                        <div className="flex flex-wrap gap-3">
                            <button onClick={research} disabled={busy} className="px-4 py-2 rounded-xl btn-glow text-sm font-semibold disabled:opacity-50">Try again</button>
                            <button onClick={reviewWithoutResearch} disabled={busy} className="px-4 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted">Continue without research</button>
                        </div>
                    </div>
                )}
                {error && <p className="mt-4 text-sm text-destructive">{error}</p>}
            </Shell>
        );
    }

    if (phase === 'review' && draft) {
        return (
            <Shell title="Review your business profile" subtitle="Nothing is saved to your profile until you confirm. BizAssist uses only the confirmed version.">
                <ProfileReview
                    steps={steps}
                    initial={draft}
                    research={run?.status === 'completed' ? run.result : null}
                    busy={busy}
                    error={error}
                    onConfirm={confirm}
                    onBack={() => setPhase('questions')}
                />
            </Shell>
        );
    }

    const isLast = position === visibleSteps.length - 1;
    return (
        <Shell title="Tell BizAssist about your business" subtitle="A few questions so its answers and suggestions fit you, not some average company.">
            <ol className="flex flex-wrap gap-2 mb-6" aria-label="Onboarding steps">
                {visibleSteps.map((s, i) => (
                    <li key={s.id} className={`flex items-center gap-1.5 rounded-full px-3 py-1 text-xs font-semibold border ${i === position ? 'border-primary/40 bg-primary/10 text-primary' : i < position ? 'border-border text-foreground' : 'border-border text-muted-foreground'}`}>
                        {i < position ? <Check className="w-3.5 h-3.5" /> : <Circle className="w-3 h-3" />}{s.title}
                    </li>
                ))}
            </ol>

            {step && (
                <section className="bg-card border border-border rounded-2xl p-5 sm:p-7">
                    <h3 className="font-display text-xl font-semibold text-foreground">{step.title}</h3>
                    {step.description && <p className="text-sm text-muted-foreground mt-1">{step.description}</p>}
                    <div className="mt-6 space-y-5">
                        {visibleQuestions.map((q) => (
                            <QuestionField
                                key={q.id}
                                question={q}
                                value={answers[q.id]}
                                onChange={(v) => setAnswers((a) => {
                                    const n = { ...a };
                                    if (v === undefined) delete n[q.id]; else n[q.id] = v;
                                    return n;
                                })}
                            />
                        ))}
                    </div>
                </section>
            )}

            {error && (
                <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                    {error.includes('API key') && (
                        <button onClick={() => navigate('/app/settings')} className="block mt-1 font-semibold text-primary hover:underline">Add your AI provider key in Settings</button>
                    )}
                </div>
            )}

            <div className="mt-6 flex flex-wrap items-center justify-between gap-3">
                <button onClick={skip} className="text-sm text-muted-foreground hover:text-foreground">Skip for now</button>
                <div className="flex flex-wrap gap-3">
                    {position > 0 && (
                        <button onClick={() => goTo(-1)} disabled={busy} className="px-4 py-2.5 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-50">Back</button>
                    )}
                    {isLast ? (
                        <>
                            <button onClick={reviewWithoutResearch} disabled={busy || missing.length > 0} className="px-4 py-2.5 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-50">
                                Skip research
                            </button>
                            <button onClick={research} disabled={busy || missing.length > 0} className="flex items-center gap-2 px-5 py-2.5 rounded-xl btn-glow text-sm font-semibold disabled:opacity-50">
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Sparkles className="w-4 h-4" />} Research my business
                            </button>
                        </>
                    ) : (
                        <button onClick={next} disabled={busy || missing.length > 0} className="flex items-center gap-2 px-5 py-2.5 rounded-xl btn-glow text-sm font-semibold disabled:opacity-50">
                            {busy && <Loader2 className="w-4 h-4 animate-spin" />} Continue
                        </button>
                    )}
                </div>
            </div>
        </Shell>
    );
}

function ResearchProgress({ run }: { run: ResearchRun }) {
    const active = run.status === 'queued' || run.status === 'running';
    const steps = run.progress.length ? run.progress : [{ message: 'Starting research', at: run.created_at }];
    return (
        <ol className="space-y-3" aria-live="polite">
            {steps.map((p, i) => {
                const current = active && i === steps.length - 1;
                return (
                    <li key={`${p.message}-${i}`} className="flex items-center gap-3 text-sm">
                        {current ? <Loader2 className="w-4 h-4 animate-spin text-primary" /> : <Check className="w-4 h-4 text-success" />}
                        <span className={current ? 'text-foreground font-medium' : 'text-muted-foreground'}>{p.message}</span>
                    </li>
                );
            })}
            {!active && run.status === 'completed' && (
                <li className="flex items-center gap-3 text-sm text-foreground"><Search className="w-4 h-4 text-primary" /> Preparing your review…</li>
            )}
        </ol>
    );
}

function Shell({ title, subtitle, children }: { title: string; subtitle?: string; children: React.ReactNode }) {
    return (
        <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8 lg:py-12">
            <div className="max-w-3xl mx-auto">
                <p className="eyebrow mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1"><span className="h-1.5 w-1.5 rounded-full bg-brand-gradient" />Getting set up</p>
                <h1 className="font-display text-3xl sm:text-[2.25rem] leading-[1.1] font-semibold text-foreground">{title}</h1>
                {subtitle && <p className="text-muted-foreground text-[15px] mt-2 mb-8">{subtitle}</p>}
                {!subtitle && <div className="mb-6" />}
                {children}
            </div>
        </div>
    );
}

function emptyProfile() {
    return {
        status: 'draft' as const, answers: {}, subdomain: null, competitors: [], opportunities: [],
        provenance: {}, confirmed_at: null, onboarding_dismissed: false,
    };
}
