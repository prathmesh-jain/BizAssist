import React from 'react';
import { Link } from 'react-router-dom';
import {
    Activity, Brain, Check, Loader2, Pencil, Pin, PinOff, Search, Trash2, Users, User as UserIcon, X,
} from 'lucide-react';
import { apiErrorDetail } from '../../api/client';
import { memoryApi } from '../../lib/memoryApi';
import type { MemoryItem, MemoryKind, MemoryScope } from '../../types';
import PageHeader from '../ui/PageHeader';

type Tab = 'all' | 'shared' | 'personal' | 'activity';
type EditableKind = Exclude<MemoryKind, 'activity'>;

const TABS: { id: Tab; label: string }[] = [
    { id: 'all', label: 'All' },
    { id: 'shared', label: 'Business' },
    { id: 'personal', label: 'Personal' },
    { id: 'activity', label: 'Activity' },
];

const KINDS: { id: EditableKind; label: string; hint: string }[] = [
    { id: 'fact', label: 'Fact', hint: 'Prices, terms, policies, how things work' },
    { id: 'contact', label: 'Contact', hint: 'Suppliers, customers, people and how they relate' },
    { id: 'decision', label: 'Decision', hint: 'Something you decided' },
    { id: 'preference', label: 'Preference', hint: 'How you like answers and reports (always just you)' },
];

const KIND_STYLE: Record<MemoryKind, { label: string; chip: string }> = {
    fact: { label: 'Fact', chip: 'chip-green' },
    contact: { label: 'Contact', chip: 'chip-blue' },
    decision: { label: 'Decision', chip: 'chip-violet' },
    preference: { label: 'Preference', chip: 'chip-amber' },
    activity: { label: 'Activity', chip: 'chip-teal' },
};

const SOURCE_LABEL: Record<MemoryItem['source'], string> = {
    chat: 'Saved from a chat',
    auto: 'Learned from a chat',
    activity: 'Logged automatically',
    manual: 'Added by hand',
};

const PAGE_SIZE = 50;

function relativeDate(iso: string | null): string {
    if (!iso) return '';
    const date = new Date(iso);
    const days = Math.floor((Date.now() - date.getTime()) / 86_400_000);
    if (days <= 0) return 'today';
    if (days === 1) return 'yesterday';
    if (days < 7) return `${days} days ago`;
    return date.toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: days > 300 ? 'numeric' : undefined });
}

export default function MemoryView() {
    const [tab, setTab] = React.useState<Tab>('all');
    const [query, setQuery] = React.useState('');
    const [debouncedQuery, setDebouncedQuery] = React.useState('');
    const [items, setItems] = React.useState<MemoryItem[]>([]);
    const [total, setTotal] = React.useState(0);
    const [enabled, setEnabled] = React.useState<boolean | null>(null);
    const [canWriteShared, setCanWriteShared] = React.useState(false);
    const [vectorSearch, setVectorSearch] = React.useState<boolean | null>(null);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState('');
    const [toggling, setToggling] = React.useState(false);

    React.useEffect(() => {
        const id = window.setTimeout(() => setDebouncedQuery(query.trim()), 250);
        return () => window.clearTimeout(id);
    }, [query]);

    const params = React.useMemo(() => ({
        scope: tab === 'shared' || tab === 'personal' ? (tab as MemoryScope) : undefined,
        kind: tab === 'activity' ? ('activity' as MemoryKind) : undefined,
        q: debouncedQuery || undefined,
    }), [tab, debouncedQuery]);

    const load = React.useCallback(async (offset = 0) => {
        setLoading(true);
        setError('');
        try {
            const data = await memoryApi.list({ ...params, limit: PAGE_SIZE, offset });
            setItems((prev) => (offset ? [...prev, ...data.memories] : data.memories));
            setTotal(data.total);
            setEnabled(data.enabled);
            setCanWriteShared(data.can_write_shared);
            setVectorSearch(data.vector_search);
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t load memories.'));
        } finally {
            setLoading(false);
        }
    }, [params]);

    React.useEffect(() => {
        load(0);
    }, [load]);

    const toggle = async () => {
        if (enabled === null) return;
        setToggling(true);
        try {
            setEnabled(await memoryApi.setEnabled(!enabled));
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t change the memory setting.'));
        } finally {
            setToggling(false);
        }
    };

    // An edit can return a new version with a new id; it takes the old item's place.
    const replaceItem = (updated: MemoryItem, previousId: string) =>
        setItems((prev) => prev.map((m) => (m.id === previousId ? { ...m, ...updated } : m)));
    const removeItem = (id: string) => {
        setItems((prev) => prev.filter((m) => m.id !== id));
        setTotal((t) => Math.max(0, t - 1));
    };

    return (
        <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8 lg:py-12">
            <div className="mx-auto max-w-3xl space-y-6">
                <PageHeader
                    eyebrow="Memory"
                    title="What BizAssist remembers"
                    description="Facts, contacts, decisions and your preferences, kept across conversations so you don’t have to repeat yourself. Business memories are shared with your team; personal ones are only for you."
                    actions={
                        <button
                            type="button"
                            role="switch"
                            aria-checked={!!enabled}
                            onClick={toggle}
                            disabled={enabled === null || toggling}
                            className="flex items-center gap-2.5 rounded-xl border border-border bg-card px-3 py-2 text-sm hover:bg-muted disabled:opacity-60"
                        >
                            <span className={`relative inline-flex h-5 w-9 shrink-0 items-center rounded-full transition-colors ${enabled ? 'bg-primary' : 'bg-input'}`}>
                                <span className={`inline-block h-3.5 w-3.5 rounded-full bg-card shadow transition-transform ${enabled ? 'translate-x-[18px]' : 'translate-x-[3px]'}`} />
                            </span>
                            Memory {enabled ? 'on' : 'off'}
                        </button>
                    }
                />

                {enabled === false && (
                    <div className="rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
                        Memory is off for you. BizAssist won’t use or save memories in your conversations until you turn it back on.
                        What’s already saved stays here.
                    </div>
                )}

                {vectorSearch === false && (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-xl border border-border bg-card px-4 py-3 text-sm">
                        <span className="text-muted-foreground">
                            Memory search matches keywords. Add an OpenAI API key to also find memories by meaning
                            (for example, “cartons” finding “boxes”).
                        </span>
                        <Link to="/app/settings" className="font-medium text-primary underline underline-offset-4">Add a key</Link>
                    </div>
                )}

                {tab !== 'activity' && (
                    <AddMemory canWriteShared={canWriteShared} disabled={enabled === false} onAdded={() => load(0)} />
                )}

                <div className="flex flex-wrap items-center justify-between gap-3">
                    <div className="flex rounded-xl border border-border bg-card p-1" role="tablist" aria-label="Memory filter">
                        {TABS.map((t) => (
                            <button
                                key={t.id}
                                role="tab"
                                aria-selected={tab === t.id}
                                onClick={() => setTab(t.id)}
                                className={`rounded-lg px-3 py-1.5 text-sm ${tab === t.id ? 'bg-highlight font-semibold text-primary' : 'text-muted-foreground hover:text-foreground'}`}
                            >
                                {t.label}
                            </button>
                        ))}
                    </div>
                    <label className="relative min-w-48 flex-1 sm:max-w-64">
                        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                        <input
                            value={query}
                            onChange={(e) => setQuery(e.target.value)}
                            placeholder="Search memories"
                            aria-label="Search memories"
                            className="w-full rounded-xl border border-input bg-card py-2 pl-9 pr-3 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                        />
                    </label>
                </div>

                {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p>}

                {loading && items.length === 0 ? (
                    <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
                ) : items.length === 0 ? (
                    <EmptyState tab={tab} searching={!!debouncedQuery} />
                ) : (
                    <ul className="space-y-2.5">
                        {items.map((m) => (
                            <MemoryRow key={m.id} memory={m} onChanged={replaceItem} onRemoved={removeItem} />
                        ))}
                    </ul>
                )}

                {items.length < total && (
                    <div className="flex justify-center">
                        <button
                            onClick={() => load(items.length)}
                            disabled={loading}
                            className="rounded-xl border border-border px-4 py-2 text-sm hover:bg-muted disabled:opacity-60"
                        >
                            {loading ? 'Loading…' : `Show more (${total - items.length})`}
                        </button>
                    </div>
                )}
            </div>
        </div>
    );
}

function AddMemory({ canWriteShared, disabled, onAdded }: { canWriteShared: boolean; disabled: boolean; onAdded: () => void }) {
    const [content, setContent] = React.useState('');
    const [kind, setKind] = React.useState<EditableKind>('fact');
    const [scope, setScope] = React.useState<MemoryScope>('shared');
    const [saving, setSaving] = React.useState(false);
    const [note, setNote] = React.useState<{ tone: 'ok' | 'error'; text: string } | null>(null);

    const effectiveScope: MemoryScope = kind === 'preference' || !canWriteShared ? 'personal' : scope;

    const save = async (e: React.FormEvent) => {
        e.preventDefault();
        if (!content.trim()) return;
        setSaving(true);
        setNote(null);
        try {
            const { action } = await memoryApi.create({ content: content.trim(), kind, scope: effectiveScope });
            setContent('');
            setNote({ tone: 'ok', text: action === 'unchanged' ? 'BizAssist already remembers that.' : 'Saved.' });
            onAdded();
        } catch (err) {
            setNote({ tone: 'error', text: apiErrorDetail(err, 'Couldn’t save that.') });
        } finally {
            setSaving(false);
        }
    };

    return (
        <form onSubmit={save} className="shadow-soft rounded-2xl border border-border bg-card p-4 sm:p-5">
            <label htmlFor="new-memory" className="text-sm font-semibold text-foreground">Add a memory</label>
            <textarea
                id="new-memory"
                value={content}
                onChange={(e) => setContent(e.target.value)}
                rows={2}
                maxLength={500}
                disabled={disabled}
                placeholder="e.g. Sharma Packaging is our main box supplier; ask for Meera."
                className="mt-2 w-full resize-none rounded-xl border border-input bg-background px-3 py-2.5 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 disabled:opacity-60"
            />
            <div className="mt-3 flex flex-wrap items-center gap-2">
                <select
                    value={kind}
                    onChange={(e) => setKind(e.target.value as EditableKind)}
                    aria-label="Kind of memory"
                    title={KINDS.find((k) => k.id === kind)?.hint}
                    className="rounded-xl border border-input bg-background px-3 py-2 text-sm"
                >
                    {KINDS.map((k) => <option key={k.id} value={k.id}>{k.label}</option>)}
                </select>
                <div className="flex rounded-xl border border-input p-0.5" role="radiogroup" aria-label="Who it’s for">
                    {([
                        { id: 'shared', label: 'Team', icon: Users, allowed: canWriteShared && kind !== 'preference' },
                        { id: 'personal', label: 'Just me', icon: UserIcon, allowed: true },
                    ] as const).map((opt) => (
                        <button
                            key={opt.id}
                            type="button"
                            role="radio"
                            aria-checked={effectiveScope === opt.id}
                            disabled={!opt.allowed}
                            title={!opt.allowed ? (kind === 'preference' ? 'Preferences are always personal' : 'Viewers can only save personal memories') : undefined}
                            onClick={() => setScope(opt.id)}
                            className={`flex items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50 ${effectiveScope === opt.id ? 'bg-highlight font-medium text-primary' : 'text-muted-foreground hover:text-foreground'}`}
                        >
                            <opt.icon className="h-3.5 w-3.5" /> {opt.label}
                        </button>
                    ))}
                </div>
                <span className="flex-1" />
                {note && <span className={`text-sm ${note.tone === 'ok' ? 'text-success' : 'text-destructive'}`} role="status">{note.text}</span>}
                <button
                    type="submit"
                    disabled={saving || disabled || !content.trim()}
                    className="btn-glow flex items-center gap-2 rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
                >
                    {saving && <Loader2 className="h-4 w-4 animate-spin" />} Remember
                </button>
            </div>
        </form>
    );
}

function MemoryRow({ memory, onChanged, onRemoved }: {
    memory: MemoryItem;
    onChanged: (m: MemoryItem, previousId: string) => void;
    onRemoved: (id: string) => void;
}) {
    const [editing, setEditing] = React.useState(false);
    const [draft, setDraft] = React.useState(memory.content);
    const [confirmDelete, setConfirmDelete] = React.useState(false);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');
    const style = KIND_STYLE[memory.kind];
    const isActivity = memory.kind === 'activity';

    const run = async (fn: () => Promise<void>) => {
        setBusy(true);
        setError('');
        try {
            await fn();
        } catch (e) {
            setError(apiErrorDetail(e, 'That change didn’t save.'));
        } finally {
            setBusy(false);
        }
    };

    const meta = [
        memory.scope === 'shared' ? 'Team' : 'Just you',
        isActivity && memory.created_by?.name ? memory.created_by.name : SOURCE_LABEL[memory.source],
        !isActivity && memory.scope === 'shared' && memory.created_by?.name ? `by ${memory.created_by.name}` : null,
        relativeDate(memory.updated_at || memory.created_at),
    ].filter(Boolean);

    return (
        <li className="group shadow-soft rounded-2xl border border-border bg-card p-4 transition-colors hover:border-foreground/15">
            <div className="flex items-start gap-3">
                <span className={`${style.chip} mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg`} title={style.label}>
                    {isActivity ? <Activity className="h-4 w-4" /> : <Brain className="h-4 w-4" />}
                </span>
                <div className="min-w-0 flex-1">
                    {editing ? (
                        <div>
                            <textarea
                                value={draft}
                                onChange={(e) => setDraft(e.target.value)}
                                rows={2}
                                maxLength={500}
                                autoFocus
                                aria-label="Edit memory"
                                className="w-full resize-none rounded-xl border border-input bg-background px-3 py-2 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10"
                            />
                            <div className="mt-2 flex gap-2">
                                <button
                                    onClick={() => run(async () => { onChanged(await memoryApi.update(memory.id, { content: draft }), memory.id); setEditing(false); })}
                                    disabled={busy || !draft.trim()}
                                    className="btn-glow flex items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-50"
                                >
                                    <Check className="h-3.5 w-3.5" /> Save
                                </button>
                                <button onClick={() => { setEditing(false); setDraft(memory.content); }} className="rounded-lg px-3 py-1.5 text-sm text-muted-foreground hover:bg-muted">
                                    Cancel
                                </button>
                            </div>
                        </div>
                    ) : (
                        <p className="text-[15px] leading-relaxed text-foreground">{memory.content}</p>
                    )}
                    <p className="mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-muted-foreground">
                        <span className="font-medium">{style.label}</span>
                        {meta.map((part) => <span key={part as string}>· {part}</span>)}
                        {memory.pinned && <span className="text-primary">· Pinned</span>}
                        {memory.source_chat_id && (
                            <Link to={`/app/chat/${memory.source_chat_id}`} className="underline-offset-2 hover:text-foreground hover:underline">· Open chat</Link>
                        )}
                    </p>
                    {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
                </div>

                {memory.can_edit && !editing && (
                    <div className="flex shrink-0 items-center gap-0.5 opacity-100 transition-opacity sm:opacity-0 sm:group-hover:opacity-100 sm:focus-within:opacity-100">
                        {confirmDelete ? (
                            <>
                                <button
                                    onClick={() => run(async () => { await memoryApi.remove(memory.id); onRemoved(memory.id); })}
                                    disabled={busy}
                                    className="rounded-lg bg-destructive/10 px-2.5 py-1 text-xs font-medium text-destructive hover:bg-destructive/15"
                                >
                                    {busy ? 'Deleting…' : 'Delete'}
                                </button>
                                <button onClick={() => setConfirmDelete(false)} aria-label="Keep memory" className="rounded-lg p-1.5 text-muted-foreground hover:bg-muted">
                                    <X className="h-3.5 w-3.5" />
                                </button>
                            </>
                        ) : (
                            <>
                                {!isActivity && (
                                    <>
                                        <IconButton
                                            label={memory.pinned ? 'Unpin' : 'Pin (always use this memory)'}
                                            onClick={() => run(async () => onChanged(await memoryApi.update(memory.id, { pinned: !memory.pinned }), memory.id))}
                                        >
                                            {memory.pinned ? <PinOff className="h-4 w-4" /> : <Pin className="h-4 w-4" />}
                                        </IconButton>
                                        <IconButton label="Edit" onClick={() => setEditing(true)}><Pencil className="h-4 w-4" /></IconButton>
                                    </>
                                )}
                                <IconButton label="Delete" danger onClick={() => setConfirmDelete(true)}><Trash2 className="h-4 w-4" /></IconButton>
                            </>
                        )}
                    </div>
                )}
            </div>
        </li>
    );
}

function IconButton({ label, onClick, danger, children }: { label: string; onClick: () => void; danger?: boolean; children: React.ReactNode }) {
    return (
        <button
            type="button"
            onClick={onClick}
            aria-label={label}
            title={label}
            className={`rounded-lg p-1.5 text-muted-foreground hover:bg-muted ${danger ? 'hover:text-destructive' : 'hover:text-foreground'}`}
        >
            {children}
        </button>
    );
}

function EmptyState({ tab, searching }: { tab: Tab; searching: boolean }) {
    const text = searching
        ? 'Nothing matches that search.'
        : tab === 'activity'
            ? 'Actions BizAssist takes for you (meetings booked, rows added, documents uploaded) will be listed here.'
            : tab === 'personal'
                ? 'Nothing personal yet. Tell BizAssist how you like things, like “show amounts in lakhs”, and it will remember.'
                : 'Nothing remembered yet. Mention a supplier, a price or a decision in chat, or add one above.';
    return (
        <div className="rounded-2xl border border-dashed border-border px-6 py-12 text-center">
            <Brain className="mx-auto h-6 w-6 text-muted-foreground" />
            <p className="mx-auto mt-3 max-w-sm text-sm text-muted-foreground">{text}</p>
        </div>
    );
}
