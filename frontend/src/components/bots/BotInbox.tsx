import React from 'react';
import { AlertTriangle, ChevronDown, Hand, Loader2, Search, Send, ShieldAlert, UserRound, Bot as BotIcon, FlaskConical } from 'lucide-react';
import { apiErrorDetail } from '../../api/client';
import { botsApi, type BotItem, type BotMessageItem, type ConversationDetail, type ConversationItem, type TraceStep } from '../../lib/botsApi';
import StatusChip from '../ui/StatusChip';
import { inputClass, primaryButton, secondaryButton } from './botUi';
import { clock, timeAgo } from './botFormat';

const IN_STATUS: Record<string, { label: string; tone: 'success' | 'warning' | 'neutral' | 'danger' }> = {
    received: { label: 'Waiting', tone: 'neutral' },
    processing: { label: 'Working…', tone: 'neutral' },
    answered: { label: 'Answered', tone: 'success' },
    blocked: { label: 'Off-topic, refused', tone: 'warning' },
    ignored: { label: 'Not answered', tone: 'neutral' },
    failed: { label: 'Failed', tone: 'danger' },
};
const OUT_STATUS: Record<string, string> = { sending: 'Sending', sent: 'Sent', delivered: 'Delivered', read: 'Read', failed: 'Not delivered' };

export default function BotInbox({ bot }: { bot: BotItem }) {
    const [items, setItems] = React.useState<ConversationItem[]>([]);
    const [selected, setSelected] = React.useState<string | null>(null);
    const [query, setQuery] = React.useState('');
    const [problems, setProblems] = React.useState(false);
    const [loading, setLoading] = React.useState(true);

    const load = React.useCallback(async () => {
        try {
            const list = await botsApi.conversations(bot.id, { q: query.trim() || undefined, problems });
            setItems(list);
            setSelected((current) => current ?? list[0]?.id ?? null);
        } finally {
            setLoading(false);
        }
    }, [bot.id, query, problems]);

    React.useEffect(() => {
        const id = window.setTimeout(load, 200);
        const poll = window.setInterval(load, 10_000);
        return () => { window.clearTimeout(id); window.clearInterval(poll); };
    }, [load]);

    return (
        <div className="grid min-w-0 gap-4 lg:grid-cols-[18rem_minmax(0,1fr)]">
            <aside className="min-w-0 space-y-3">
                <label className="relative block">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name or number" className={`${inputClass} pl-9`} />
                </label>
                <label className="flex items-center gap-2 text-sm text-muted-foreground">
                    <input type="checkbox" checked={problems} onChange={(e) => setProblems(e.target.checked)} className="h-4 w-4 accent-[var(--color-primary)]" />
                    Only chats with problems
                </label>
                {loading ? (
                    <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>
                ) : items.length === 0 ? (
                    <p className="rounded-xl border border-dashed border-border px-4 py-6 text-center text-sm text-muted-foreground">
                        No conversations yet. Messages people send to {bot.handle} will appear here.
                    </p>
                ) : (
                    <ul className="max-h-[60vh] space-y-1.5 overflow-y-auto pr-1">
                        {items.map((c) => (
                            <li key={c.id}>
                                <button onClick={() => setSelected(c.id)}
                                    className={`w-full rounded-xl border px-3 py-2.5 text-left ${selected === c.id ? 'border-primary bg-highlight' : 'border-border bg-card hover:bg-muted/50'}`}>
                                    <div className="flex items-center justify-between gap-2">
                                        <span className="flex min-w-0 items-center gap-1.5 truncate text-sm font-semibold text-foreground">
                                            {c.is_test && <FlaskConical className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />}
                                            <span className="truncate">{c.contact_name || c.contact_handle || 'Unknown'}</span>
                                        </span>
                                        <span className="shrink-0 text-[11px] text-muted-foreground">{timeAgo(c.last_message_at)}</span>
                                    </div>
                                    <p className="mt-0.5 truncate text-xs text-muted-foreground">
                                        {c.last_message ? `${c.last_message.direction === 'out' ? 'Bot: ' : ''}${c.last_message.text}` : ''}
                                    </p>
                                    <div className="mt-1 flex flex-wrap gap-1">
                                        {c.mode === 'human' && <span className="chip-amber rounded-full px-2 py-0.5 text-[11px]">With a person</span>}
                                        {c.awaiting_approval && <span className="chip-blue rounded-full px-2 py-0.5 text-[11px]">Awaiting approval</span>}
                                        {c.problems > 0 && <span className="chip-rose rounded-full px-2 py-0.5 text-[11px]">{c.problems} problem{c.problems > 1 ? 's' : ''}</span>}
                                    </div>
                                </button>
                            </li>
                        ))}
                    </ul>
                )}
            </aside>
            {selected ? <Thread key={selected} bot={bot} conversationId={selected} onChanged={load} />
                : <div className="hidden rounded-2xl border border-dashed border-border lg:block" />}
        </div>
    );
}

function Thread({ bot, conversationId, onChanged }: { bot: BotItem; conversationId: string; onChanged: () => void }) {
    const [data, setData] = React.useState<ConversationDetail | null>(null);
    const [error, setError] = React.useState('');
    const scroller = React.useRef<HTMLDivElement>(null);

    const load = React.useCallback(async () => {
        try {
            setData(await botsApi.conversation(bot.id, conversationId));
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t load this conversation.'));
        }
    }, [bot.id, conversationId]);

    React.useEffect(() => {
        load();
        const poll = window.setInterval(load, 5000);
        return () => window.clearInterval(poll);
    }, [load]);
    // Scroll only the thread (scrollIntoView would also scroll the page).
    React.useEffect(() => {
        const el = scroller.current;
        if (el) el.scrollTop = el.scrollHeight;
    }, [data?.messages.length]);

    if (error) return <p className="text-sm text-destructive">{error}</p>;
    if (!data) return <p className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</p>;
    const { conversation, messages } = data;

    const setMode = async (mode: 'bot' | 'human') => {
        await botsApi.setMode(bot.id, conversation.id, mode);
        await load();
        onChanged();
    };

    return (
        <section className="flex min-h-[60vh] min-w-0 flex-col rounded-2xl border border-border bg-card">
            <header className="flex flex-wrap items-center justify-between gap-2 border-b border-border px-4 py-3">
                <div>
                    <p className="font-semibold text-foreground">{conversation.contact_name || conversation.contact_handle || 'Unknown'}</p>
                    <p className="text-xs text-muted-foreground">{conversation.is_test ? 'Test conversation (nothing was sent)' : conversation.contact_handle}</p>
                </div>
                {bot.audience === 'customer' && !conversation.is_test && (
                    conversation.mode === 'human' ? (
                        <button onClick={() => setMode('bot')} className={secondaryButton}><BotIcon className="h-4 w-4" /> Let the bot answer again</button>
                    ) : (
                        <button onClick={() => setMode('human')} className={secondaryButton}><Hand className="h-4 w-4" /> Take over</button>
                    )
                )}
            </header>
            {conversation.mode === 'human' && (
                <p className="border-b border-border bg-warning/10 px-4 py-2 text-xs text-foreground">
                    The bot is quiet in this chat until you let it answer again. Reply below.
                </p>
            )}
            <div ref={scroller} className="max-h-[65vh] flex-1 space-y-3 overflow-y-auto px-4 py-4">
                {messages.map((m) => <MessageBubble key={m.id} message={m} />)}
            </div>
            {bot.audience === 'customer' && !conversation.is_test && (
                <StaffReply botId={bot.id} conversationId={conversation.id} canReply={conversation.can_reply}
                    blockedReason={conversation.reply_blocked_reason} onSent={load} />
            )}
        </section>
    );
}

function MessageBubble({ message: m }: { message: BotMessageItem }) {
    const [open, setOpen] = React.useState(false);
    const inbound = m.direction === 'in';
    const failed = m.status === 'failed';
    const status = inbound ? IN_STATUS[m.status] : null;
    const steps = m.trace.filter((s) => s.step !== 'received');
    return (
        <div className={`flex ${inbound ? 'justify-start' : 'justify-end'}`}>
            <div className={`max-w-[85%] space-y-1 ${inbound ? '' : 'items-end text-right'}`}>
                <div className={`flex items-center gap-1.5 text-[11px] text-muted-foreground ${inbound ? '' : 'justify-end'}`}>
                    {inbound ? <UserRound className="h-3 w-3" /> : m.author === 'staff' ? <UserRound className="h-3 w-3" /> : <BotIcon className="h-3 w-3" />}
                    {inbound ? 'Customer' : m.author === 'staff' ? 'You (team)' : 'Bot'} · {clock(m.created_at)}
                    {!inbound && <span className={failed ? 'text-destructive' : ''}>· {OUT_STATUS[m.status] || m.status}</span>}
                    {inbound && m.latency_ms != null && <span>· replied in {(m.latency_ms / 1000).toFixed(1)}s</span>}
                </div>
                <div className={`whitespace-pre-wrap rounded-2xl px-3.5 py-2.5 text-left text-sm ${inbound ? 'bg-muted text-foreground' : failed ? 'border border-destructive/40 bg-destructive/5 text-foreground' : 'bg-highlight text-foreground'}`}>
                    {m.text || <span className="italic text-muted-foreground">({m.kind} message)</span>}
                </div>
                {status && m.status !== 'answered' && <div><StatusChip tone={status.tone}>{status.label}</StatusChip></div>}
                {(m.explained || (failed && m.error)) && (
                    <div className="rounded-xl border border-destructive/25 bg-destructive/5 px-3 py-2 text-left text-xs text-foreground">
                        <p className="flex items-start gap-1.5 font-medium"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0 text-destructive" />{m.explained?.what || m.error}</p>
                        {m.explained?.fix && <p className="mt-1 text-muted-foreground">{m.explained.fix}</p>}
                        {m.explained && m.error && <p className="mt-1 font-mono text-[11px] text-muted-foreground">{m.error_code ? `${m.error_code}: ` : ''}{m.error}</p>}
                    </div>
                )}
                {inbound && steps.length > 0 && (
                    <div>
                        <button onClick={() => setOpen(!open)} className="inline-flex items-center gap-1 text-[11px] font-medium text-primary">
                            <ChevronDown className={`h-3 w-3 transition-transform ${open ? 'rotate-180' : ''}`} /> What happened
                        </button>
                        {open && <Trace steps={steps} />}
                    </div>
                )}
            </div>
        </div>
    );
}

function describe(step: TraceStep): string {
    switch (step.step) {
        case 'guardrail': return step.verdict === 'ON_TOPIC' ? 'Checked: about the business' : `Refused: ${String(step.verdict).toLowerCase().replace('_', '-')}`;
        case 'identity': return step.linked ? `Linked team member (${step.role})` : 'Sender isn’t a linked team member';
        case 'link': return step.ok ? 'Linked a team member’s account' : 'Link code was invalid or expired';
        case 'tool': return `Used ${String(step.tool).replace(/_/g, ' ')}${step.ok === false ? ' (failed)' : ''}${step.error ? `: ${step.error}` : ''}`;
        case 'tool_done': return `Finished ${String(step.tool).replace(/_/g, ' ')}`;
        case 'tool_error': return `Tool error in ${step.tool}: ${step.error}`;
        case 'approval_requested': return `Asked to approve: ${step.question}`;
        case 'answer': return `Got the answer: ${String(step.value)}`;
        case 'awaiting_answer': return 'Still waiting for an approval answer';
        case 'calendar_change': return `Calendar ${step.action}: ${step.title}`;
        case 'memory': return `Updated memory (${step.changes})`;
        case 'handoff': return `Handed to a person: ${step.reason}`;
        case 'skipped': return `Not answered: ${step.reason}`;
        case 'greeting': return 'Sent the greeting';
        case 'assistant': return 'Assistant finished';
        case 'reply': return `Wrote the reply (${step.chars} characters)`;
        default: return step.step;
    }
}

function Trace({ steps }: { steps: TraceStep[] }) {
    return (
        <ol className="mt-1.5 space-y-1 border-l-2 border-border pl-3 text-left">
            {steps.map((s, i) => (
                <li key={i} className="text-[11px] text-muted-foreground">
                    <span className="text-foreground">{describe(s)}</span>
                    {typeof s.ms === 'number' && <span> · {s.ms} ms</span>}
                    {s.step === 'guardrail' && s.verdict !== 'ON_TOPIC' && <ShieldAlert className="ml-1 inline h-3 w-3 text-warning" />}
                </li>
            ))}
        </ol>
    );
}

function StaffReply({ botId, conversationId, canReply, blockedReason, onSent }: {
    botId: string; conversationId: string; canReply: boolean; blockedReason: string | null; onSent: () => void;
}) {
    const [text, setText] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');
    const send = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!text.trim()) return;
        setBusy(true);
        setError('');
        try {
            await botsApi.reply(botId, conversationId, text.trim());
            setText('');
            onSent();
        } catch (err) {
            setError(apiErrorDetail(err, 'Couldn’t send.'));
        } finally {
            setBusy(false);
        }
    };
    if (!canReply) return <p className="border-t border-border px-4 py-3 text-xs text-muted-foreground">{blockedReason}</p>;
    return (
        <form onSubmit={send} className="border-t border-border p-3">
            <div className="flex gap-2">
                <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Reply as the business…" className={inputClass} />
                <button type="submit" disabled={busy || !text.trim()} className={primaryButton} aria-label="Send reply">
                    {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
                </button>
            </div>
            {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
        </form>
    );
}
