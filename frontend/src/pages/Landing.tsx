import { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, Check, Moon, Sun } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import useThemeStore from '../store/themeStore';
import Logo from '../components/ui/Logo';

const TERMS_URL = 'https://bizassist.prathmeshjain.online/terms-conditions.html';
const PRIVACY_URL = 'https://bizassist.prathmeshjain.online/privacy-policy.html';

const CAPABILITIES = [
    {
        title: 'Learns your business first',
        body: 'Answer a few questions and BizAssist reads what is public about you: your site, listings, and competitors. You correct the draft, and only the version you confirm is used.',
    },
    {
        title: 'Answers from your own documents',
        body: 'Upload price lists, contracts, and policies once. Later, ask in plain words and get the answer with the file it came from.',
    },
    {
        title: 'Keeps your Sheets current',
        body: 'Log an expense, pull last month’s totals, or compare two tabs. It reads and writes the spreadsheets you already use.',
    },
    {
        title: 'Handles the calendar',
        body: 'Check what’s on tomorrow, find a free hour, and book a meeting with a Google Meet link, all from the chat.',
    },
    {
        title: 'Works for the whole team',
        body: 'Invite people as viewers, members, or admins. Everyone shares the business knowledge; chats and calendars stay personal.',
    },
    {
        title: 'Asks before it acts',
        body: 'When something needs your say, like a new meeting or a missing detail, it stops and asks. You see exactly what will happen before it does.',
    },
];

const WONT_DO = [
    'Create, move, or cancel a calendar event without your approval',
    'Present a guess as a fact. Research is labelled verified, estimated, or not found',
    'Share your personal calendar or chats with the rest of your team',
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

    const primaryCta = user
        ? { to: '/app', label: 'Open your workspace' }
        : { to: '/signup', label: 'Set up your workspace' };

    return (
        <div className="min-h-screen bg-background text-foreground">
            <header className="sticky top-0 z-40 border-b border-border/70 bg-background/90 backdrop-blur-sm">
                <div className="mx-auto flex h-16 max-w-6xl items-center justify-between px-4 sm:px-6">
                    <Link to="/" aria-label="BizAssist home"><Logo /></Link>
                    <nav className="flex items-center gap-1 sm:gap-2">
                        <a href="#what-it-does" className="hidden md:inline px-3 py-2 text-sm text-muted-foreground hover:text-foreground">What it does</a>
                        <a href="#first-week" className="hidden md:inline px-3 py-2 text-sm text-muted-foreground hover:text-foreground">How it starts</a>
                        <button
                            onClick={toggleTheme}
                            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                            className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
                        >
                            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                        </button>
                        {loading ? null : user ? (
                            <Link to="/app" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                                Open app
                            </Link>
                        ) : (
                            <>
                                <Link to="/login" className="px-3 py-2 text-sm font-medium text-foreground hover:underline underline-offset-4">
                                    Sign in
                                </Link>
                                <Link to="/signup" className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90">
                                    Get started
                                </Link>
                            </>
                        )}
                    </nav>
                </div>
            </header>

            <main>
                {/* Hero */}
                <section className="paper-grain">
                    <div className="mx-auto grid max-w-6xl gap-12 px-4 pt-14 pb-20 sm:px-6 lg:grid-cols-[1.05fr_1fr] lg:gap-16 lg:pt-20">
                        <div className="rise-in">
                            <p className="eyebrow">For small teams who would rather run the business than the spreadsheet</p>
                            <h1 className="font-display mt-5 text-[2.6rem] leading-[1.06] font-medium sm:text-6xl">
                                An assistant that actually knows <em className="marker not-italic font-semibold">your</em> business.
                            </h1>
                            <p className="mt-6 max-w-xl text-lg leading-relaxed text-muted-foreground">
                                BizAssist starts by learning what you sell, who you sell to, and who you’re up against.
                                After that it handles the everyday work: finding the clause in a contract, updating the
                                expense sheet, and booking the call with a supplier.
                            </p>
                            <div className="mt-8 flex flex-col gap-3 sm:flex-row sm:items-center">
                                {!loading && (
                                    <Link
                                        to={primaryCta.to}
                                        className="group inline-flex items-center justify-center gap-2 rounded-md bg-primary px-5 py-3 text-[15px] font-medium text-primary-foreground hover:bg-primary/90"
                                    >
                                        {primaryCta.label}
                                        <ArrowRight className="h-4 w-4 transition-transform group-hover:translate-x-0.5" />
                                    </Link>
                                )}
                                <a href="#what-it-does" className="inline-flex items-center justify-center rounded-md border border-border px-5 py-3 text-[15px] font-medium text-foreground hover:bg-muted">
                                    See what it does
                                </a>
                            </div>
                            <p className="mt-5 text-sm text-muted-foreground">
                                Runs on your own OpenAI key, so you always see what it costs.
                            </p>
                        </div>

                        <ConversationPreview />
                    </div>
                </section>

                {/* What it does */}
                <section id="what-it-does" className="border-t border-border">
                    <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
                        <div className="grid gap-10 lg:grid-cols-[0.8fr_2fr]">
                            <div>
                                <p className="eyebrow">What it does</p>
                                <h2 className="font-display mt-3 text-3xl leading-tight font-medium sm:text-4xl">
                                    The work around the work.
                                </h2>
                                <p className="mt-4 text-muted-foreground leading-relaxed">
                                    Not another dashboard to check. You ask it something and it gets done.
                                </p>
                            </div>
                            <ol className="grid gap-x-10 gap-y-10 sm:grid-cols-2">
                                {CAPABILITIES.map((c, i) => (
                                    <li key={c.title} className="border-t border-foreground/80 pt-4">
                                        <span className="font-mono text-xs text-accent">{String(i + 1).padStart(2, '0')}</span>
                                        <h3 className="mt-2 text-lg font-semibold">{c.title}</h3>
                                        <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">{c.body}</p>
                                    </li>
                                ))}
                            </ol>
                        </div>
                    </div>
                </section>

                {/* First week */}
                <section id="first-week" className="border-t border-border bg-sidebar">
                    <div className="mx-auto max-w-6xl px-4 py-20 sm:px-6">
                        <p className="eyebrow">How it starts</p>
                        <h2 className="font-display mt-3 max-w-2xl text-3xl leading-tight font-medium sm:text-4xl">
                            Ten minutes to set up, then it’s just there when you need it.
                        </h2>
                        <div className="mt-12 grid gap-8 md:grid-cols-3">
                            <Step when="Minute one" title="Tell it about the business">
                                Name, website, what you sell. It researches the rest and shows you its sources, so you can
                                keep what’s right and fix what isn’t.
                            </Step>
                            <Step when="Minute five" title="Connect what you already use">
                                Upload a few key documents and connect Google Sheets and Calendar. Invite your team when you’re ready.
                            </Step>
                            <Step when="From then on" title="Just ask">
                                “What did we spend on packaging in March?” “Set up a call with Meera on Thursday.” It does the
                                legwork and checks with you when it needs a decision.
                            </Step>
                        </div>
                    </div>
                </section>

                {/* What it won't do */}
                <section className="border-t border-border">
                    <div className="mx-auto grid max-w-6xl gap-10 px-4 py-20 sm:px-6 lg:grid-cols-2">
                        <div>
                            <p className="eyebrow">Ground rules</p>
                            <h2 className="font-display mt-3 text-3xl leading-tight font-medium sm:text-4xl">
                                What it won’t do.
                            </h2>
                            <p className="mt-4 max-w-md text-muted-foreground leading-relaxed">
                                An assistant with access to your books should be careful. These are enforced by the app
                                itself, not left to the model’s judgement.
                            </p>
                        </div>
                        <ul className="space-y-5 self-center">
                            {WONT_DO.map((item) => (
                                <li key={item} className="flex gap-3 text-[15px] leading-relaxed">
                                    <span className="mt-1 flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-primary/40 text-primary">
                                        <Check className="h-3 w-3" strokeWidth={3} />
                                    </span>
                                    <span>{item}</span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </section>

                {/* Closing */}
                <section className="border-t border-border">
                    <div className="mx-auto max-w-6xl px-4 py-20 text-center sm:px-6">
                        <h2 className="font-display mx-auto max-w-2xl text-3xl leading-tight font-medium sm:text-[2.6rem]">
                            Give it a slow Tuesday afternoon and see what it takes off your plate.
                        </h2>
                        {!loading && (
                            <Link
                                to={primaryCta.to}
                                className="mt-8 inline-flex items-center gap-2 rounded-md bg-primary px-5 py-3 text-[15px] font-medium text-primary-foreground hover:bg-primary/90"
                            >
                                {primaryCta.label} <ArrowRight className="h-4 w-4" />
                            </Link>
                        )}
                    </div>
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

function Step({ when, title, children }: { when: string; title: string; children: React.ReactNode }) {
    return (
        <div className="relative pl-6">
            <span className="absolute left-0 top-1.5 h-2.5 w-2.5 rounded-full bg-accent" />
            <span className="absolute left-[4.5px] top-5 bottom-0 w-px bg-border" />
            <p className="eyebrow">{when}</p>
            <h3 className="mt-2 text-lg font-semibold">{title}</h3>
            <p className="mt-2 text-[15px] leading-relaxed text-muted-foreground">{children}</p>
        </div>
    );
}

/** A static example exchange, so visitors see real output instead of a feature grid. */
function ConversationPreview() {
    return (
        <div className="relative rise-in lg:mt-4" style={{ animationDelay: '120ms' }}>
            <div className="absolute -inset-3 -z-10 rotate-[1.2deg] rounded-xl border border-border bg-sidebar" />
            <div className="rounded-xl border border-border bg-card shadow-[0_1px_0_hsl(var(--border)),0_18px_40px_-24px_hsl(var(--foreground)/0.35)]">
                <div className="flex items-center justify-between border-b border-border px-5 py-3">
                    <span className="text-sm font-medium">Supplier payments</span>
                    <span className="eyebrow">Example</span>
                </div>

                <div className="space-y-5 px-5 py-5">
                    <div className="ml-auto max-w-[85%] rounded-lg rounded-br-sm bg-muted px-4 py-2.5 text-[14px] leading-relaxed">
                        Which suppliers did we pay late in March? And put a call with Meera on Thursday to sort out the Sharma invoice.
                    </div>

                    <div className="space-y-3 text-[14px] leading-relaxed">
                        <p className="font-mono text-[11px] text-muted-foreground">
                            <span className="text-success">✓</span> Read “Expenses 2026 › March”
                        </p>
                        <p>Two payments went out after their due date:</p>
                        <table className="w-full text-[13px] tabular-nums">
                            <thead>
                                <tr className="border-b border-foreground/60 text-left">
                                    <th className="py-1.5 font-medium">Supplier</th>
                                    <th className="py-1.5 font-medium">Due</th>
                                    <th className="py-1.5 text-right font-medium">Late by</th>
                                </tr>
                            </thead>
                            <tbody className="text-muted-foreground">
                                <tr className="border-b border-border">
                                    <td className="py-1.5 text-foreground">Sharma Packaging</td>
                                    <td>4 Mar</td>
                                    <td className="text-right">12 days</td>
                                </tr>
                                <tr className="border-b border-border">
                                    <td className="py-1.5 text-foreground">Northline Freight</td>
                                    <td>18 Mar</td>
                                    <td className="text-right">3 days</td>
                                </tr>
                            </tbody>
                        </table>
                        <p>Meera is free on Thursday at 3:00 PM. Shall I send the invite?</p>
                    </div>

                    <div className="rounded-lg border border-accent/40 bg-accent/5 p-4">
                        <p className="eyebrow !text-accent">Needs your OK</p>
                        <p className="mt-1.5 text-[14px] font-medium">Sharma invoice: catch-up</p>
                        <p className="text-[13px] text-muted-foreground">Thu, 3:00 – 3:30 PM · Google Meet · meera@sharmapack.in</p>
                        <div className="mt-3 flex gap-2">
                            <span className="rounded-md bg-primary px-3 py-1.5 text-[13px] font-medium text-primary-foreground">Send invite</span>
                            <span className="rounded-md border border-border px-3 py-1.5 text-[13px]">Not now</span>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
