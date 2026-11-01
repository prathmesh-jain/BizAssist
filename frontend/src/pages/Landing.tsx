import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import {
    ArrowRight, CalendarDays, Check, FileSpreadsheet, FileText, Globe, Moon, ShieldCheck,
    Store, Sun, TrendingUp, Users, Zap,
} from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import useThemeStore from '../store/themeStore';
import Logo, { LogoMark } from '../components/ui/Logo';
import Reveal from '../components/fx/Reveal';
import RotatingWords from '../components/fx/RotatingWords';
import Marquee from '../components/fx/Marquee';
import ScrollTilt from '../components/fx/ScrollTilt';
import SpotlightCard from '../components/fx/SpotlightCard';
import useTypewriter from '../components/fx/useTypewriter';

const TERMS_URL = 'https://bizassist.prathmeshjain.online/terms-conditions.html';
const PRIVACY_URL = 'https://bizassist.prathmeshjain.online/privacy-policy.html';

const PROMPTS = [
    'What’s on my calendar this week?',
    'Which suppliers did we pay late in March?',
    'What does our rent agreement say about renewal?',
    'Who are our closest competitors?',
    'Log ₹2,400 for packaging in the expense sheet',
    'Find an hour on Friday for the team review',
    'Summarise the returns policy for a new hire',
    'Set up a Meet with Meera on Thursday at 3',
];

export default function Landing() {
    const { user, loading } = useAuth();
    const { theme, toggleTheme } = useThemeStore();

    // Wake the backend early so the app is ready by the time someone signs in.
    useEffect(() => {
        const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
        const root = base.endsWith('/api') ? base.slice(0, -4) : base;
        fetch(`${root}/health`).catch(() => undefined);
    }, []);

    const cta = user ? { to: '/app', label: 'Open your workspace' } : { to: '/signup', label: 'Create your workspace' };

    return (
        <div className="min-h-screen overflow-x-clip bg-background text-foreground">
            {/* Floating pill navigation */}
            <header className="fixed inset-x-0 top-3 z-50 px-3">
                <nav className="glass mx-auto flex h-14 max-w-5xl items-center justify-between rounded-full pl-4 pr-2 shadow-soft">
                    <Link to="/" aria-label="BizAssist home"><Logo size="sm" /></Link>
                    <div className="hidden items-center gap-1 md:flex">
                        {[['#features', 'Features'], ['#how', 'How it works'], ['#trust', 'Trust']].map(([href, label]) => (
                            <a key={href} href={href} className="rounded-full px-3.5 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-foreground/5 hover:text-foreground">
                                {label}
                            </a>
                        ))}
                    </div>
                    <div className="flex items-center gap-1">
                        <button
                            onClick={toggleTheme}
                            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                            className="rounded-full p-2 text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
                        >
                            {theme === 'dark' ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
                        </button>
                        {!loading && !user && (
                            <Link to="/login" className="hidden rounded-full px-3.5 py-1.5 text-sm font-medium hover:bg-foreground/5 sm:inline">
                                Sign in
                            </Link>
                        )}
                        {!loading && (
                            <Link to={cta.to} className="btn-glow rounded-full px-4 py-2 text-sm font-semibold">
                                {user ? 'Open app' : 'Get started'}
                            </Link>
                        )}
                    </div>
                </nav>
            </header>

            <main>
                {/* Hero */}
                <section className="relative isolate px-4 pt-36 pb-10 sm:pt-44">
                    <div className="dot-grid absolute inset-0 -z-10" aria-hidden="true" />

                    <div className="mx-auto max-w-4xl text-center">
                        <div className="rise-in shadow-soft group inline-flex items-center gap-2 rounded-full border border-border bg-card py-1 pl-1 pr-3 text-xs font-medium">
                            <span className="rounded-full bg-highlight px-2 py-0.5 font-semibold text-primary">New</span>
                            Google Calendar &amp; Meet, right inside the chat
                            <ArrowRight className="h-3 w-3" />
                        </div>

                        <h1 className="rise-in font-display mt-7 text-[2.6rem] font-semibold leading-[1.02] sm:text-6xl md:text-7xl" style={{ animationDelay: '80ms' }}>
                            Run your business,
                            <br />
                            not your{' '}
                            <RotatingWords
                                className="text-primary"
                                words={['spreadsheets.', 'calendar.', 'paperwork.', 'inbox of invoices.', 'guesswork.']}
                            />
                        </h1>

                        <p className="rise-in mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-muted-foreground sm:text-xl" style={{ animationDelay: '160ms' }}>
                            BizAssist learns what you sell, who you sell to and who you’re up against. Then it answers from your
                            documents, updates your Sheets and books your meetings, all from one chat.
                        </p>

                        <div className="rise-in mt-9 flex flex-col items-center justify-center gap-3 sm:flex-row" style={{ animationDelay: '240ms' }}>
                            {!loading && (
                                <Link to={cta.to} className="btn-glow group inline-flex items-center gap-2 rounded-full px-6 py-3.5 text-[15px] font-semibold">
                                    {cta.label}
                                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                                </Link>
                            )}
                            <a href="#features" className="glass inline-flex items-center gap-2 rounded-full px-6 py-3.5 text-[15px] font-medium hover:bg-card">
                                See it in action
                            </a>
                        </div>
                        <p className="rise-in mt-5 text-sm text-muted-foreground" style={{ animationDelay: '320ms' }}>
                            Runs on your own OpenAI key · Your calendar and chats stay yours
                        </p>
                    </div>

                    <div className="relative mx-auto mt-16 max-w-5xl">
                        <FloatingChip className="-left-4 top-24 hidden lg:flex" delay="900ms" icon={<FileSpreadsheet className="h-3.5 w-3.5" />} tone="success">
                            Read “Expenses › March”
                        </FloatingChip>
                        <FloatingChip className="-right-6 top-10 hidden lg:flex" delay="1100ms" icon={<CalendarDays className="h-3.5 w-3.5" />} tone="primary">
                            Meet link ready
                        </FloatingChip>
                        <FloatingChip className="-right-2 bottom-24 hidden lg:flex" delay="1300ms" icon={<TrendingUp className="h-3.5 w-3.5" />} tone="accent">
                            3 competitors found
                        </FloatingChip>
                        <ScrollTilt>
                            <ProductPreview />
                        </ScrollTilt>
                    </div>
                </section>

                {/* Prompt marquee */}
                <section className="py-10">
                    <p className="eyebrow mb-5 text-center">Ask it anything about your business</p>
                    <Marquee duration={50}>
                        {PROMPTS.map((p) => (
                            <span key={p} className="whitespace-nowrap rounded-full border border-border bg-card px-4 py-2 text-sm text-muted-foreground">
                                “{p}”
                            </span>
                        ))}
                    </Marquee>
                </section>

                {/* Bento features */}
                <section id="features" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-20 sm:px-6">
                    <Reveal className="mx-auto max-w-2xl text-center">
                        <p className="eyebrow">Features</p>
                        <h2 className="font-display mt-3 text-4xl font-semibold leading-tight sm:text-5xl">
                            One chat. <span className="text-gradient">Your whole business.</span>
                        </h2>
                        <p className="mt-4 text-lg text-muted-foreground">
                            No new dashboards to learn. Ask in plain words, and BizAssist reaches into the right place.
                        </p>
                    </Reveal>

                    <div className="mt-14 grid auto-rows-[minmax(240px,auto)] gap-4 md:grid-cols-6">
                        <Reveal className="md:col-span-4 md:row-span-2" delay={0}>
                            <Bento
                                className="h-full"
                                title="It learns your business first"
                                body="A few questions, then it reads what’s public about you: your website, listings and competitors. You confirm what’s right. Every fact is tagged verified, estimated or not found."
                                visual={<OrbitVisual />}
                            />
                        </Reveal>
                        <Reveal className="md:col-span-2" delay={80}>
                            <Bento title="Answers from your documents" body="Contracts, price lists, policies, each answer citing the file it came from." visual={<DocsVisual />} />
                        </Reveal>
                        <Reveal className="md:col-span-2" delay={160}>
                            <Bento title="Lives in your Sheets" body="Logs expenses, pulls totals and compares tabs in the spreadsheets you already use." visual={<SheetVisual />} />
                        </Reveal>
                        <Reveal className="md:col-span-2" delay={0}>
                            <Bento title="Books the meeting" body="Finds a free slot and sends the invite with a Google Meet link." visual={<CalendarVisual />} />
                        </Reveal>
                        <Reveal className="md:col-span-2" delay={80}>
                            <Bento title="Built for teams" body="Owners, admins, members and viewers, all sharing one source of truth." visual={<TeamVisual />} />
                        </Reveal>
                        <Reveal className="md:col-span-2" delay={160}>
                            <Bento title="Asks before it acts" body="Calendar changes wait for your “go ahead”. You see exactly what will happen first." visual={<ApprovalVisual />} />
                        </Reveal>
                    </div>
                </section>

                {/* How it works */}
                <section id="how" className="relative isolate scroll-mt-24 overflow-hidden border-y border-border bg-sidebar px-4 py-24 sm:px-6">
                    <div className="dot-grid absolute inset-0 -z-10 opacity-60" aria-hidden="true" />
                    <div className="mx-auto max-w-6xl">
                        <Reveal className="max-w-2xl">
                            <p className="eyebrow">How it works</p>
                            <h2 className="font-display mt-3 text-4xl font-semibold leading-tight sm:text-5xl">
                                Set up over coffee.<br />Useful by lunch.
                            </h2>
                        </Reveal>
                        <div className="relative mt-16 grid gap-10 md:grid-cols-3">
                            <div className="absolute left-0 right-0 top-6 hidden h-px bg-border md:block" aria-hidden="true" />
                            {[
                                { n: '01', title: 'Tell it about the business', body: 'Name, website, what you sell. It researches the rest and shows its sources. Keep what’s right, fix what isn’t.' },
                                { n: '02', title: 'Connect your tools', body: 'Drop in key documents, connect Google Sheets and Calendar, and invite your team when you’re ready.' },
                                { n: '03', title: 'Just ask', body: '“What did we spend on packaging in March?” “Set up a call with Meera.” It does the legwork and checks in when it needs a decision.' },
                            ].map((s, i) => (
                                <Reveal key={s.n} delay={i * 120}>
                                    <div className="relative">
                                        <span className="font-display relative z-10 flex h-12 w-12 items-center justify-center rounded-2xl bg-card text-lg font-semibold shadow-soft border border-border">
                                            <span className="font-mono text-sm text-primary">{s.n}</span>
                                        </span>
                                        <h3 className="font-display mt-6 text-xl font-semibold">{s.title}</h3>
                                        <p className="mt-2 leading-relaxed text-muted-foreground">{s.body}</p>
                                    </div>
                                </Reveal>
                            ))}
                        </div>
                    </div>
                </section>

                {/* Trust */}
                <section id="trust" className="mx-auto max-w-6xl scroll-mt-24 px-4 py-24 sm:px-6">
                    <div className="grid gap-12 lg:grid-cols-[1fr_1.2fr] lg:items-center">
                        <Reveal>
                            <p className="eyebrow">Ground rules</p>
                            <h2 className="font-display mt-3 text-4xl font-semibold leading-tight sm:text-5xl">
                                Powerful, <span className="text-gradient">on a short leash.</span>
                            </h2>
                            <p className="mt-4 max-w-md text-lg text-muted-foreground">
                                An assistant with access to your books should be careful. These rules are enforced by the app,
                                not left to the model’s judgement.
                            </p>
                        </Reveal>
                        <div className="grid gap-3">
                            {[
                                { icon: <CalendarDays className="h-5 w-5" />, title: 'No surprise calendar changes', body: 'Creating, moving or cancelling an event always needs your approval.' },
                                { icon: <ShieldCheck className="h-5 w-5" />, title: 'No guesses dressed up as facts', body: 'Research is labelled verified, estimated or not found, with sources.' },
                                { icon: <Users className="h-5 w-5" />, title: 'Private stays private', body: 'Your calendar and chats aren’t shared with the rest of your team.' },
                            ].map((r, i) => (
                                <Reveal key={r.title} delay={i * 100}>
                                    <SpotlightCard className="flex gap-4 rounded-2xl border border-border bg-card p-5">
                                        <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/10 text-primary">{r.icon}</span>
                                        <div>
                                            <h3 className="font-semibold">{r.title}</h3>
                                            <p className="mt-1 text-sm text-muted-foreground">{r.body}</p>
                                        </div>
                                    </SpotlightCard>
                                </Reveal>
                            ))}
                        </div>
                    </div>
                </section>

                {/* Closing CTA */}
                <section className="px-4 pb-24 sm:px-6">
                    <Reveal className="mx-auto max-w-6xl">
                        <div className="relative isolate overflow-hidden rounded-2xl border border-border bg-sidebar px-6 py-20 text-center">
                            <div className="dot-grid absolute inset-0 -z-10" aria-hidden="true" />
                            <LogoMark className="mx-auto h-11 w-11" />
                            <h2 className="font-display mx-auto mt-8 max-w-3xl text-4xl font-semibold leading-tight sm:text-6xl">
                                Give it one slow afternoon.<br />
                                <span className="text-muted-foreground">See what it takes off your plate.</span>
                            </h2>
                            {!loading && (
                                <Link to={cta.to} className="btn-glow group mt-10 inline-flex items-center gap-2 rounded-full px-7 py-4 text-base font-semibold">
                                    {cta.label}
                                    <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-1" />
                                </Link>
                            )}
                        </div>
                    </Reveal>
                </section>
            </main>

            <footer className="border-t border-border">
                <div className="mx-auto flex max-w-6xl flex-col gap-4 px-4 py-8 text-sm text-muted-foreground sm:px-6 md:flex-row md:items-center md:justify-between">
                    <div className="flex items-center gap-3">
                        <Logo size="sm" />
                        <span>© {new Date().getFullYear()}</span>
                    </div>
                    <div className="flex items-center gap-5">
                        <a className="hover:text-foreground" href={PRIVACY_URL}>Privacy</a>
                        <a className="hover:text-foreground" href={TERMS_URL}>Terms</a>
                    </div>
                </div>
            </footer>
        </div>
    );
}

/* ---------- Hero product preview ---------- */

const ANSWER = [
    'Two payments went out late in March: Sharma Packaging (12 days) and Northline Freight (3 days).',
    'Meera is free Thursday at 3:00 PM. Want me to send the invite?',
];

function ProductPreview() {
    const [a, b] = useTypewriter(ANSWER, { speed: 18, startDelay: 900, gap: 400 });
    const done = b === ANSWER[1].length;

    return (
        <div className="shadow-lifted rounded-2xl border border-border bg-muted/60 p-1.5">
            <div className="overflow-hidden rounded-[1.1rem] border border-border bg-background">
                {/* Window chrome */}
                <div className="flex items-center gap-2 border-b border-border px-4 py-2.5">
                    <span className="h-2.5 w-2.5 rounded-full bg-foreground/15" />
                    <span className="h-2.5 w-2.5 rounded-full bg-foreground/15" />
                    <span className="h-2.5 w-2.5 rounded-full bg-foreground/15" />
                    <span className="mx-auto rounded-md bg-muted px-3 py-0.5 font-mono text-[11px] text-muted-foreground">app.bizassist · Supplier payments</span>
                </div>
                <div className="grid min-h-[340px] text-left md:grid-cols-[200px_1fr]">
                    <aside className="hidden border-r border-border bg-sidebar p-3 md:block">
                        <div className="rounded-lg bg-card px-2.5 py-2 text-xs font-medium shadow-[0_0_0_1px_hsl(var(--border))]">+ New conversation</div>
                        <p className="eyebrow mt-4 px-1 !text-[10px]">Today</p>
                        {['Supplier payments', 'Diwali stock plan', 'Rent renewal clause'].map((t, i) => (
                            <div key={t} className={`mt-1 truncate rounded-md px-2.5 py-1.5 text-xs ${i === 0 ? 'bg-primary/10 font-medium text-primary' : 'text-muted-foreground'}`}>{t}</div>
                        ))}
                    </aside>
                    <div className="space-y-4 p-4 sm:p-6">
                        <div className="ml-auto max-w-[80%] rounded-2xl rounded-br-md bg-foreground px-4 py-2.5 text-sm text-background">
                            Which suppliers did we pay late in March? And book a call with Meera on Thursday.
                        </div>
                        <div className="flex gap-3">
                            <LogoMark className="h-7 w-7 shrink-0" />
                            <div className="min-w-0 space-y-2.5 text-sm leading-relaxed">
                                <div className="flex flex-wrap gap-1.5">
                                    <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] text-success"><Check className="h-3 w-3" /> Expenses › March</span>
                                    <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2 py-0.5 text-[11px] text-success"><Check className="h-3 w-3" /> Calendar</span>
                                </div>
                                <p className={a < ANSWER[0].length ? 'caret' : ''}>{ANSWER[0].slice(0, a)}</p>
                                {b > 0 && <p className={!done ? 'caret' : ''}>{ANSWER[1].slice(0, b)}</p>}
                                <div className={`relative max-w-sm overflow-hidden rounded-lg border border-border bg-card p-3 pl-4 transition-all duration-500 before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-primary ${done ? 'opacity-100' : 'translate-y-2 opacity-0'}`}>
                                    <p className="eyebrow !text-accent !text-[10px]">Needs your OK</p>
                                    <p className="mt-1 text-[13px] font-medium">Sharma invoice: catch-up · Thu 3:00 PM</p>
                                    <div className="mt-2 flex gap-2">
                                        <span className="btn-glow rounded-md px-3 py-1 text-xs font-medium">Go ahead</span>
                                        <span className="rounded-full border border-border bg-card px-3 py-1 text-xs">Not now</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}

function FloatingChip({ children, icon, className, delay, tone }: { children: React.ReactNode; icon: React.ReactNode; className: string; delay: string; tone: 'success' | 'primary' | 'accent' }) {
    const toneClass = { success: 'text-success', primary: 'text-primary', accent: 'text-accent' }[tone];
    return (
        <div className={`rise-in shadow-lifted absolute z-10 items-center gap-2 rounded-full border border-border bg-card px-3.5 py-2 text-xs font-medium ${className}`} style={{ animationDelay: delay }}>
            <span className={toneClass}>{icon}</span>
            {children}
        </div>
    );
}

/* ---------- Bento cards and their mini visuals ---------- */

function Bento({ title, body, visual, className = '' }: { title: string; body: string; visual: React.ReactNode; className?: string }) {
    return (
        <SpotlightCard className={`group shadow-soft flex h-full flex-col rounded-2xl border border-border bg-card p-6 hover:-translate-y-0.5 ${className}`}>
            <div className="relative flex flex-1 items-center justify-center overflow-hidden rounded-xl border border-border/60 bg-muted/40 p-4">{visual}</div>
            <h3 className="font-display mt-5 text-xl font-semibold">{title}</h3>
            <p className="mt-1.5 text-[15px] leading-relaxed text-muted-foreground">{body}</p>
        </SpotlightCard>
    );
}

function OrbitVisual() {
    const items = [
        { icon: <Globe className="h-4 w-4" />, label: 'Website' },
        { icon: <Store className="h-4 w-4" />, label: 'Listings' },
        { icon: <TrendingUp className="h-4 w-4" />, label: 'Trends' },
        { icon: <Users className="h-4 w-4" />, label: 'Competitors' },
        { icon: <FileText className="h-4 w-4" />, label: 'Your answers' },
    ];
    return (
        <div className="relative h-[300px] w-[300px] sm:h-[340px] sm:w-[340px]">
            <div className="absolute inset-[12%] rounded-full border border-dashed border-border" />
            <div className="absolute inset-[32%] rounded-full border border-border" />
            <div className="absolute inset-0 flex items-center justify-center">
                <div className="relative">
                    
                    <LogoMark className="relative h-16 w-16" />
                </div>
            </div>
            <div className="orbit absolute inset-[12%]" style={{ ['--orbit-duration' as string]: '28s' }}>
                {items.map((it, i) => {
                    const angle = (i / items.length) * 2 * Math.PI;
                    return (
                        <div
                            key={it.label}
                            className="absolute"
                            style={{ left: `${50 + 50 * Math.cos(angle)}%`, top: `${50 + 50 * Math.sin(angle)}%`, transform: 'translate(-50%, -50%)' }}
                        >
                            <div className="orbit-counter" style={{ ['--orbit-duration' as string]: '28s' }}>
                                <span className="flex items-center gap-1.5 whitespace-nowrap rounded-full border border-border bg-card px-2.5 py-1.5 text-xs font-medium shadow-md">
                                    <span className="text-primary">{it.icon}</span>{it.label}
                                </span>
                            </div>
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

function DocsVisual() {
    return (
        <div className="relative w-full max-w-[220px]">
            {['rent-agreement.docx', 'supplier-terms.pdf', 'price-list.pdf'].map((f, i) => (
                <div
                    key={f}
                    className="flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-2 text-xs shadow-sm transition-transform duration-300 group-hover:translate-x-1"
                    style={{ marginTop: i ? -6 : 0, marginLeft: i * 10, transitionDelay: `${i * 60}ms` }}
                >
                    <FileText className="h-3.5 w-3.5 text-accent" />
                    <span className="truncate">{f}</span>
                </div>
            ))}
            <div className="mt-3 rounded-lg bg-primary/10 px-3 py-2 text-[11px] text-primary">
                “Late fee: 2% after 7 days” <span className="opacity-70">· supplier-terms.pdf</span>
            </div>
        </div>
    );
}

function SheetVisual() {
    const rows = [['Packaging', '₹2,400'], ['Freight', '₹8,150'], ['Rent', '₹45,000'], ['Ads', '₹6,200']];
    return (
        <div className="w-full max-w-[230px] overflow-hidden rounded-lg border border-border bg-card text-[11px] shadow-sm">
            <div className="flex items-center gap-1.5 border-b border-border bg-success/10 px-2.5 py-1.5 font-medium text-success">
                <FileSpreadsheet className="h-3.5 w-3.5" /> Expenses 2026
            </div>
            {rows.map(([k, v], i) => (
                <div key={k} className={`flex justify-between border-b border-border px-2.5 py-1.5 last:border-0 ${i === 0 ? 'bg-highlight/25 font-medium' : ''}`}>
                    <span>{k}</span><span className="tabular-nums">{v}</span>
                </div>
            ))}
        </div>
    );
}

function CalendarVisual() {
    const days = ['M', 'T', 'W', 'T', 'F'];
    return (
        <div className="grid w-full max-w-[230px] grid-cols-5 gap-1.5">
            {days.map((d, i) => <span key={i} className="text-center font-mono text-[10px] text-muted-foreground">{d}</span>)}
            {Array.from({ length: 15 }).map((_, i) => {
                const busy = [1, 5, 7, 12].includes(i);
                const pick = i === 8;
                return (
                    <span
                        key={i}
                        className={`relative h-7 rounded-md ${pick ? 'pulse-ring bg-primary text-primary' : busy ? 'bg-muted-foreground/20' : 'border border-dashed border-border'}`}
                    >
                        {pick && <Zap className="absolute inset-0 m-auto h-3.5 w-3.5 text-primary-foreground" />}
                    </span>
                );
            })}
        </div>
    );
}

function TeamVisual() {
    const people = [['PJ', 'bg-foreground text-background'], ['AK', 'bg-highlight text-primary'], ['RS', 'bg-muted text-foreground'], ['MN', 'bg-card text-muted-foreground']];
    return (
        <div className="flex flex-col items-center gap-3">
            <div className="flex -space-x-3">
                {people.map(([n, g], i) => (
                    <span
                        key={n}
                        className={`flex h-11 w-11 items-center justify-center rounded-full border-2 border-card ring-1 ring-border ${g} text-xs font-semibold transition-transform duration-300 group-hover:-translate-y-0.5`}
                        style={{ transitionDelay: `${i * 50}ms` }}
                    >
                        {n}
                    </span>
                ))}
            </div>
            <div className="flex gap-1.5 text-[10px]">
                {['owner', 'admin', 'member', 'viewer'].map((r) => (
                    <span key={r} className="rounded-full border border-border bg-card px-2 py-0.5 text-muted-foreground">{r}</span>
                ))}
            </div>
        </div>
    );
}

function ApprovalVisual() {
    return (
        <div className="relative w-full max-w-[230px] overflow-hidden rounded-lg border border-border bg-card p-3 pl-4 shadow-sm before:absolute before:inset-y-0 before:left-0 before:w-[3px] before:bg-primary">
            <p className="eyebrow !text-[10px] !text-accent">Needs your OK</p>
            <p className="mt-1 text-xs font-medium">Move “Team review” to Fri 4 PM?</p>
            <div className="mt-2.5 flex gap-1.5">
                <span className="btn-glow rounded-md px-2.5 py-1 text-[11px] font-medium">Go ahead</span>
                <span className="rounded-full border border-border px-2.5 py-1 text-[11px]">Not now</span>
            </div>
        </div>
    );
}
