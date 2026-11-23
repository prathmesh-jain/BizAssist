import React from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ArrowLeft, CheckCircle2, CircleHelp, ExternalLink, Loader2, RefreshCw, Send, XCircle } from 'lucide-react';
import { apiErrorDetail } from '../../api/client';
import {
    botsApi, PLATFORM_LABEL, type BotItem, type BotOptions, type BotSettings, type ConversationDetail, type HealthCheck,
} from '../../lib/botsApi';
import StatusChip from '../ui/StatusChip';
import BotInbox from './BotInbox';
import { Checkbox, CopyField, Field, inputClass, PlatformBadge, primaryButton, secondaryButton } from './botUi';

type Tab = 'inbox' | 'health' | 'settings';

export default function BotDetail() {
    const { botId = '' } = useParams();
    const [bot, setBot] = React.useState<BotItem | null>(null);
    const [error, setError] = React.useState('');
    const [tab, setTab] = React.useState<Tab>('inbox');
    const [canManage, setCanManage] = React.useState(false);

    const load = React.useCallback(async () => {
        try {
            const [item, list] = await Promise.all([botsApi.get(botId), botsApi.list()]);
            setBot(item);
            setCanManage(list.can_manage);
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t load this bot.'));
        }
    }, [botId]);
    React.useEffect(() => { load(); }, [load]);

    if (error) return <Page><p className="text-sm text-destructive">{error}</p></Page>;
    if (!bot) return <Page><p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p></Page>;

    const tabs: { id: Tab; label: string }[] = [
        { id: 'inbox', label: 'Conversations' },
        { id: 'health', label: 'Health and test' },
        ...(canManage ? [{ id: 'settings' as Tab, label: 'Settings' }] : []),
    ];

    return (
        <Page wide={tab === 'inbox'}>
            <Link to="/app/bots" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"><ArrowLeft className="h-4 w-4" /> All bots</Link>
            <header className="flex flex-wrap items-center gap-4">
                <PlatformBadge platform={bot.platform} />
                <div className="min-w-[12rem] flex-1">
                    <h1 className="font-display text-2xl font-semibold text-foreground">{bot.name}</h1>
                    <p className="text-sm text-muted-foreground">
                        {PLATFORM_LABEL[bot.platform]} · {bot.handle} · {bot.audience === 'customer' ? 'for customers' : 'for your team'}
                    </p>
                </div>
                {bot.status === 'paused' ? <StatusChip tone="neutral">Paused</StatusChip> : bot.last_error ? <StatusChip tone="danger">Needs attention</StatusChip> : <StatusChip tone="success">Live</StatusChip>}
                {bot.chat_link && <a href={bot.chat_link} target="_blank" rel="noreferrer" className={secondaryButton}>Open chat <ExternalLink className="h-4 w-4" /></a>}
            </header>

            <div className="flex w-fit rounded-xl border border-border bg-card p-1" role="tablist">
                {tabs.map((t) => (
                    <button key={t.id} role="tab" aria-selected={tab === t.id} onClick={() => setTab(t.id)}
                        className={`rounded-lg px-3 py-1.5 text-sm ${tab === t.id ? 'bg-highlight font-semibold text-primary' : 'text-muted-foreground hover:text-foreground'}`}>
                        {t.label}
                    </button>
                ))}
            </div>

            {tab === 'inbox' && <BotInbox bot={bot} />}
            {tab === 'health' && <HealthTab bot={bot} canManage={canManage} />}
            {tab === 'settings' && canManage && <SettingsTab bot={bot} onSaved={setBot} />}
        </Page>
    );
}

function Page({ children, wide = false }: { children: React.ReactNode; wide?: boolean }) {
    return (
        <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8 lg:py-12">
            <div className={`mx-auto space-y-6 ${wide ? 'max-w-5xl' : 'max-w-3xl'}`}>{children}</div>
        </div>
    );
}

function HealthTab({ bot, canManage }: { bot: BotItem; canManage: boolean }) {
    const [checks, setChecks] = React.useState<HealthCheck[] | null>(null);
    const [busy, setBusy] = React.useState(false);
    const run = React.useCallback(async () => {
        setBusy(true);
        try {
            setChecks(await botsApi.health(bot.id));
        } catch {
            setChecks([]);
        } finally {
            setBusy(false);
        }
    }, [bot.id]);
    React.useEffect(() => { run(); }, [run]);

    const reconnect = async () => {
        setBusy(true);
        try {
            await botsApi.reconnect(bot.id);
        } finally {
            await run();
        }
    };

    return (
        <div className="space-y-6">
            <section className="rounded-2xl border border-border bg-card p-5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                    <h2 className="font-semibold text-foreground">Is everything working?</h2>
                    <div className="flex gap-2">
                        {canManage && <button onClick={reconnect} disabled={busy} className={secondaryButton}>Reconnect</button>}
                        <button onClick={run} disabled={busy} className={secondaryButton}><RefreshCw className={`h-4 w-4 ${busy ? 'animate-spin' : ''}`} /> Check again</button>
                    </div>
                </div>
                <ul className="mt-4 space-y-3">
                    {(checks || []).map((c) => (
                        <li key={c.id} className="flex gap-3">
                            {c.ok === true ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-success" />
                                : c.ok === false ? <XCircle className="mt-0.5 h-5 w-5 shrink-0 text-destructive" />
                                    : <CircleHelp className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />}
                            <div className="min-w-0">
                                <p className="text-sm font-medium text-foreground">{c.label}</p>
                                {c.detail && <p className="break-words text-xs text-muted-foreground">{c.detail}</p>}
                                {c.fix && <p className="mt-0.5 text-xs text-foreground">{c.fix}</p>}
                            </div>
                        </li>
                    ))}
                    {checks === null && <li className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Checking…</li>}
                </ul>
                {bot.platform === 'whatsapp' && bot.setup && (
                    <div className="mt-5 grid gap-3 border-t border-border pt-4 sm:grid-cols-2">
                        <CopyField label="Callback URL (Meta webhook)" value={bot.setup.webhook_url} />
                        <CopyField label="Verify token" value={bot.setup.verify_token || ''} />
                    </div>
                )}
            </section>
            <TestBox bot={bot} />
        </div>
    );
}

function TestBox({ bot }: { bot: BotItem }) {
    const [text, setText] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const [result, setResult] = React.useState<ConversationDetail | null>(null);
    const [error, setError] = React.useState('');
    const send = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!text.trim()) return;
        setBusy(true);
        setError('');
        try {
            setResult(await botsApi.test(bot.id, text.trim()));
        } catch (err) {
            setError(apiErrorDetail(err, 'The test didn’t run.'));
        } finally {
            setBusy(false);
        }
    };
    const reply = result?.messages.find((m) => m.direction === 'out');
    const inbound = result?.messages.find((m) => m.direction === 'in');
    return (
        <section className="rounded-2xl border border-border bg-card p-5">
            <h2 className="font-semibold text-foreground">Try a message</h2>
            <p className="mt-1 text-sm text-muted-foreground">
                Runs the message through the bot exactly as a {bot.audience === 'customer' ? 'customer' : 'linked team member (you)'} would, without sending anything to {PLATFORM_LABEL[bot.platform]}.
            </p>
            <form onSubmit={send} className="mt-3 flex gap-2">
                <input value={text} onChange={(e) => setText(e.target.value)} className={inputClass}
                    placeholder={bot.audience === 'customer' ? 'e.g. What are your opening hours?' : 'e.g. What’s on my calendar tomorrow?'} />
                <button type="submit" disabled={busy || !text.trim()} className={primaryButton}>{busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />} Test</button>
            </form>
            {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
            {result && (
                <div className="mt-4 space-y-2 rounded-xl bg-muted/50 p-4 text-sm">
                    <p className="text-xs font-medium text-muted-foreground">Bot would reply{inbound?.latency_ms != null ? ` (${(inbound.latency_ms / 1000).toFixed(1)}s)` : ''}:</p>
                    <p className="whitespace-pre-wrap text-foreground">{reply?.text || '(no reply)'}</p>
                    {inbound?.explained && <p className="text-xs text-destructive">{inbound.explained.what} {inbound.explained.fix}</p>}
                    {inbound && inbound.status === 'blocked' && <p className="text-xs text-warning">Refused as off-topic by the business-only check.</p>}
                    <p className="text-xs text-muted-foreground">Steps: {inbound?.trace.filter((s) => s.step !== 'received').map((s) => (s.tool as string) || s.step).join(' → ')}</p>
                </div>
            )}
        </section>
    );
}

function SettingsTab({ bot, onSaved }: { bot: BotItem; onSaved: (bot: BotItem) => void }) {
    const navigate = useNavigate();
    const [options, setOptions] = React.useState<BotOptions | null>(null);
    const [documents, setDocuments] = React.useState<string[]>([]);
    const [name, setName] = React.useState(bot.name);
    const [settings, setSettings] = React.useState<BotSettings>(bot.settings || { daily_cap: 500 });
    const [creds, setCreds] = React.useState<Record<string, string>>({});
    const [busy, setBusy] = React.useState(false);
    const [note, setNote] = React.useState<{ ok: boolean; text: string } | null>(null);
    const [confirmDelete, setConfirmDelete] = React.useState(false);

    React.useEffect(() => {
        botsApi.options().then(setOptions).catch(() => undefined);
        if (bot.audience === 'customer') botsApi.documents().then((d) => setDocuments(d.map((x) => x.filename))).catch(() => undefined);
    }, [bot.audience]);

    const patch = (part: Partial<BotSettings>) => setSettings((s) => ({ ...s, ...part }));
    const toggleIn = (key: 'tools' | 'capabilities' | 'documents', id: string, on: boolean) =>
        setSettings((s) => {
            const list = new Set(s[key] || []);
            if (on) list.add(id); else list.delete(id);
            return { ...s, [key]: [...list] };
        });

    const save = async (extra: { status?: 'active' | 'paused' } = {}) => {
        setBusy(true);
        setNote(null);
        try {
            const hasCreds = Object.values(creds).some((v) => v.trim());
            const { bot: updated } = await botsApi.update(bot.id, { name, settings, ...extra, ...(hasCreds ? { credentials: creds } : {}) });
            onSaved(updated);
            setCreds({});
            setNote({ ok: true, text: 'Saved.' });
        } catch (e) {
            setNote({ ok: false, text: apiErrorDetail(e, 'Couldn’t save.') });
        } finally {
            setBusy(false);
        }
    };
    const remove = async () => {
        setBusy(true);
        try {
            await botsApi.remove(bot.id);
            navigate('/app/bots');
        } finally {
            setBusy(false);
        }
    };
    const booking = settings.booking!;

    return (
        <div className="space-y-6">
            <Card title="General">
                <Field label="Name"><input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={80} /></Field>
                <Field label="Replies per day" hint="The bot stops replying for the rest of the day (UTC) after this many replies, so spam can’t run up your AI bill.">
                    <input type="number" min={1} max={10000} className={`${inputClass} max-w-40`} value={settings.daily_cap}
                        onChange={(e) => patch({ daily_cap: Number(e.target.value) || 1 })} />
                </Field>
                <div className="flex flex-wrap items-center gap-3">
                    <button onClick={() => save({ status: bot.status === 'active' ? 'paused' : 'active' })} disabled={busy} className={secondaryButton}>
                        {bot.status === 'active' ? 'Pause the bot' : 'Resume the bot'}
                    </button>
                    <span className="text-xs text-muted-foreground">{bot.status === 'active' ? 'While paused, messages are kept but not answered.' : 'Paused: messages are kept but not answered.'}</span>
                </div>
            </Card>

            {bot.audience === 'team' ? (
                <Card title="What team members can do here" note="Each person also keeps their own role’s limits. Changes to the calendar always ask them to approve first.">
                    {options?.team_tools.map((t) => (
                        <Checkbox key={t.id} label={t.label} checked={!!settings.tools?.includes(t.id)} onChange={(on) => toggleIn('tools', t.id, on)} />
                    ))}
                </Card>
            ) : (
                <>
                    <Card title="What the bot can do" note="It always stays on your business and refuses anything else, like coding or homework.">
                        {options?.customer_capabilities.map((c) => (
                            <Checkbox key={c.id} label={c.label} checked={!!settings.capabilities?.includes(c.id)} onChange={(on) => toggleIn('capabilities', c.id, on)} />
                        ))}
                    </Card>
                    <Card title="What customers should know" note="The bot answers only from this, your public business profile (name, website, location, about, products) and the documents you pick below.">
                        <Field label="Information for customers" hint="Opening hours, prices, delivery areas, payment methods, return policy, contact numbers…">
                            <textarea rows={6} className={inputClass} value={settings.about || ''} maxLength={6000} onChange={(e) => patch({ about: e.target.value })} />
                        </Field>
                        <Field label="Greeting (optional)" hint="Sent when someone starts a chat.">
                            <input className={inputClass} value={settings.greeting || ''} maxLength={1000} onChange={(e) => patch({ greeting: e.target.value })}
                                placeholder="Hi! Thanks for messaging. How can we help?" />
                        </Field>
                        {documents.length > 0 && (
                            <div className="space-y-2">
                                <p className="text-sm font-medium text-foreground">Documents the bot may quote (up to 3)</p>
                                <p className="text-xs text-muted-foreground">Only pick documents meant for customers, like a catalogue or price list. Others stay private.</p>
                                {documents.map((d) => (
                                    <Checkbox key={d} label={d} checked={!!settings.documents?.includes(d)}
                                        onChange={(on) => (!on || (settings.documents?.length || 0) < 3) && toggleIn('documents', d, on)} />
                                ))}
                            </div>
                        )}
                    </Card>
                    {settings.capabilities?.includes('booking') && booking && (
                        <Card title="Bookings" note={`Booked into the Google Calendar of the person who connected this bot.`}>
                            <div className="grid gap-4 sm:grid-cols-3">
                                <Field label="From"><input type="time" className={inputClass} value={booking.start} onChange={(e) => patch({ booking: { ...booking, start: e.target.value } })} /></Field>
                                <Field label="Until"><input type="time" className={inputClass} value={booking.end} onChange={(e) => patch({ booking: { ...booking, end: e.target.value } })} /></Field>
                                <Field label="Minutes each"><input type="number" min={10} max={240} className={inputClass} value={booking.duration_minutes} onChange={(e) => patch({ booking: { ...booking, duration_minutes: Number(e.target.value) } })} /></Field>
                                <Field label="Days ahead"><input type="number" min={1} max={60} className={inputClass} value={booking.days_ahead} onChange={(e) => patch({ booking: { ...booking, days_ahead: Number(e.target.value) } })} /></Field>
                                <Field label="Max upcoming per customer"><input type="number" min={0} max={10} className={inputClass} value={booking.max_per_contact} onChange={(e) => patch({ booking: { ...booking, max_per_contact: Number(e.target.value) } })} /></Field>
                            </div>
                            <Checkbox label="Weekdays only" checked={booking.weekdays_only} onChange={(v) => patch({ booking: { ...booking, weekdays_only: v } })} />
                            <Checkbox label="Add a Google Meet link" checked={booking.add_meet} onChange={(v) => patch({ booking: { ...booking, add_meet: v } })} />
                        </Card>
                    )}
                    {settings.capabilities?.includes('leads') && (
                        <Card title="Enquiries" note="Saved as rows (date, name, contact, channel, details) in your BizAssist spreadsheet, or one you choose.">
                            <Field label="Sheet tab"><input className={inputClass} value={settings.leads?.tab || 'Leads'} onChange={(e) => patch({ leads: { ...settings.leads, tab: e.target.value } })} /></Field>
                            <Field label="Spreadsheet ID (optional)" hint="From the sheet’s URL: docs.google.com/spreadsheets/d/<this part>/edit">
                                <input className={inputClass} value={settings.leads?.spreadsheet_id || ''} onChange={(e) => patch({ leads: { tab: settings.leads?.tab || 'Leads', spreadsheet_id: e.target.value || null } })} />
                            </Field>
                        </Card>
                    )}
                </>
            )}

            <Card title="Credentials" note="Paste new values only if the token changed. Leave empty to keep what’s saved.">
                {bot.platform === 'telegram' ? (
                    <Field label="New bot token"><input className={inputClass} autoComplete="off" value={creds.token || ''} onChange={(e) => setCreds({ token: e.target.value })} /></Field>
                ) : (
                    <>
                        <Field label="New access token"><input className={inputClass} autoComplete="off" value={creds.access_token || ''} onChange={(e) => setCreds({ ...creds, access_token: e.target.value })} /></Field>
                        <Field label="New app secret"><input type="password" className={inputClass} autoComplete="off" value={creds.app_secret || ''} onChange={(e) => setCreds({ ...creds, app_secret: e.target.value })} /></Field>
                    </>
                )}
            </Card>

            <div className="flex flex-wrap items-center justify-between gap-3">
                <div className="flex items-center gap-3">
                    <button onClick={() => save()} disabled={busy} className={primaryButton}>{busy && <Loader2 className="h-4 w-4 animate-spin" />} Save changes</button>
                    {note && <span className={`text-sm ${note.ok ? 'text-success' : 'text-destructive'}`}>{note.text}</span>}
                </div>
                {confirmDelete ? (
                    <div className="flex items-center gap-2">
                        <span className="text-sm text-foreground">Delete the bot and its conversations?</span>
                        <button onClick={() => setConfirmDelete(false)} className={secondaryButton}>Keep</button>
                        <button onClick={remove} disabled={busy} className="rounded-xl bg-destructive px-4 py-2.5 text-sm font-medium text-destructive-foreground hover:bg-destructive/90">Delete</button>
                    </div>
                ) : (
                    <button onClick={() => setConfirmDelete(true)} className="text-sm font-medium text-destructive hover:underline">Delete bot</button>
                )}
            </div>
        </div>
    );
}

function Card({ title, note, children }: { title: string; note?: string; children: React.ReactNode }) {
    return (
        <section className="space-y-4 rounded-2xl border border-border bg-card p-5">
            <div>
                <h2 className="font-semibold text-foreground">{title}</h2>
                {note && <p className="mt-1 text-sm text-muted-foreground">{note}</p>}
            </div>
            {children}
        </section>
    );
}
