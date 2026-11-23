import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { AlertTriangle, ChevronRight, Link2, Loader2, Plus, Users, Store } from 'lucide-react';
import { apiErrorDetail } from '../../api/client';
import { botsApi, PLATFORM_LABEL, type BotItem } from '../../lib/botsApi';
import PageHeader from '../ui/PageHeader';
import StatusChip from '../ui/StatusChip';
import ConnectBot from './ConnectBot';
import { PlatformBadge, primaryButton, secondaryButton } from './botUi';
import { timeAgo } from './botFormat';

export default function BotsView() {
    const [bots, setBots] = React.useState<BotItem[]>([]);
    const [canView, setCanView] = React.useState(false);
    const [canManage, setCanManage] = React.useState(false);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState('');
    const [connecting, setConnecting] = React.useState(false);
    const navigate = useNavigate();

    const load = React.useCallback(async () => {
        setError('');
        try {
            const data = await botsApi.list();
            setBots(data.bots);
            setCanView(data.can_view);
            setCanManage(data.can_manage);
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t load bots.'));
        } finally {
            setLoading(false);
        }
    }, []);

    React.useEffect(() => { load(); }, [load]);

    if (connecting) {
        return (
            <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8 lg:py-12">
                <div className="mx-auto max-w-2xl">
                    <ConnectBot onCancel={() => setConnecting(false)} onDone={(id) => navigate(`/app/bots/${id}`)} />
                </div>
            </div>
        );
    }

    const teamBots = bots.filter((b) => b.audience === 'team');
    const customerBots = bots.filter((b) => b.audience === 'customer');

    return (
        <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8 lg:py-12">
            <div className="mx-auto max-w-3xl space-y-8">
                <PageHeader
                    eyebrow="Bots"
                    title="WhatsApp and Telegram"
                    description="Answer customers on WhatsApp or Telegram, or use BizAssist from your own phone. Every message the bot gets and sends is kept here, with what it did in between."
                    actions={canManage && (
                        <button onClick={() => setConnecting(true)} className={primaryButton}>
                            <Plus className="h-4 w-4" /> Connect a bot
                        </button>
                    )}
                />

                {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p>}

                {loading ? (
                    <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" /> Loading…</div>
                ) : bots.length === 0 ? (
                    <EmptyState canManage={canManage} onConnect={() => setConnecting(true)} />
                ) : (
                    <>
                        {canView && customerBots.length > 0 && (
                            <Section icon={Store} title="For your customers" note="Anyone can message these. They only do what you switched on.">
                                {customerBots.map((b) => <BotRow key={b.id} bot={b} />)}
                            </Section>
                        )}
                        {teamBots.length > 0 && (
                            <Section icon={Users} title="For your team" note="Only linked team members can use these, with their own access.">
                                {teamBots.map((b) => canView ? <BotRow key={b.id} bot={b} /> : <LinkCard key={b.id} bot={b} onChanged={load} />)}
                            </Section>
                        )}
                        {canView && teamBots.length > 0 && (
                            <ul className="space-y-2.5">
                                {teamBots.map((b) => <LinkCard key={b.id} bot={b} onChanged={load} />)}
                            </ul>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}

function Section({ icon: Icon, title, note, children }: { icon: React.ElementType; title: string; note: string; children: React.ReactNode }) {
    return (
        <section className="space-y-3">
            <div>
                <h2 className="flex items-center gap-2 font-display text-lg font-semibold text-foreground"><Icon className="h-4 w-4 text-primary" /> {title}</h2>
                <p className="text-sm text-muted-foreground">{note}</p>
            </div>
            <ul className="space-y-2.5">{children}</ul>
        </section>
    );
}

function BotRow({ bot }: { bot: BotItem }) {
    const failing = !!bot.last_error && bot.status === 'active';
    return (
        <li>
            <Link to={`/app/bots/${bot.id}`} className="shadow-soft group flex items-center gap-4 rounded-2xl border border-border bg-card p-4 hover:border-primary/40">
                <PlatformBadge platform={bot.platform} />
                <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold text-foreground">{bot.name}</span>
                        {bot.status === 'paused' ? <StatusChip tone="neutral">Paused</StatusChip>
                            : failing ? <StatusChip tone="danger">Needs attention</StatusChip>
                                : <StatusChip tone="success">Live</StatusChip>}
                    </div>
                    <p className="mt-0.5 truncate text-sm text-muted-foreground">
                        {PLATFORM_LABEL[bot.platform]} · {bot.handle} · last message {timeAgo(bot.last_inbound_at)}
                    </p>
                    {failing && bot.last_error_explained && (
                        <p className="mt-1 flex items-start gap-1.5 text-xs text-destructive">
                            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" /> {bot.last_error_explained.what}
                        </p>
                    )}
                </div>
                {bot.stats && (
                    <div className="hidden text-right text-xs text-muted-foreground sm:block">
                        <p><span className="font-semibold text-foreground">{bot.stats.replies_today}</span> replies today</p>
                        {bot.stats.failed_today > 0 && <p className="text-destructive">{bot.stats.failed_today} failed</p>}
                    </div>
                )}
                <ChevronRight className="h-4 w-4 text-muted-foreground group-hover:text-primary" />
            </Link>
        </li>
    );
}

/** A team member links their own WhatsApp/Telegram to a team bot by sending a one-time code. */
function LinkCard({ bot, onChanged }: { bot: BotItem; onChanged: () => void }) {
    const [code, setCode] = React.useState<{ code: string; message: string; chat_link: string | null } | null>(null);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');

    const getCode = async () => {
        setBusy(true);
        setError('');
        try {
            setCode(await botsApi.linkCode(bot.id));
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t create a code.'));
        } finally {
            setBusy(false);
        }
    };
    const unlink = async () => {
        setBusy(true);
        try {
            await botsApi.unlink(bot.id);
            onChanged();
        } finally {
            setBusy(false);
        }
    };

    return (
        <li className="list-none rounded-2xl border border-border bg-card p-4">
            <div className="flex flex-wrap items-center gap-3">
                <PlatformBadge platform={bot.platform} size="sm" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-foreground">Use “{bot.name}” from your phone</p>
                    <p className="text-xs text-muted-foreground">
                        {bot.linked ? `Your ${PLATFORM_LABEL[bot.platform]} is linked. Message ${bot.handle} to use BizAssist.`
                            : `Link your ${PLATFORM_LABEL[bot.platform]} to ask about your calendar, sheets and documents from chat.`}
                    </p>
                </div>
                {bot.linked ? (
                    <button onClick={unlink} disabled={busy} className={secondaryButton}>Unlink</button>
                ) : (
                    <button onClick={getCode} disabled={busy} className={secondaryButton}>
                        {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : <Link2 className="h-4 w-4" />} Link my account
                    </button>
                )}
            </div>
            {code && !bot.linked && (
                <div className="mt-4 rounded-xl bg-highlight px-4 py-3 text-sm">
                    <p className="text-foreground">
                        Send <code className="rounded bg-card px-1.5 py-0.5 font-semibold">{code.message}</code> to {bot.handle} within 15 minutes.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                        {code.chat_link && (
                            <a href={code.chat_link} target="_blank" rel="noreferrer" className={primaryButton}>
                                Open {PLATFORM_LABEL[bot.platform]} with the code
                            </a>
                        )}
                        <button onClick={onChanged} className={secondaryButton}>I’ve sent it</button>
                    </div>
                </div>
            )}
            {error && <p className="mt-2 text-xs text-destructive">{error}</p>}
        </li>
    );
}

function EmptyState({ canManage, onConnect }: { canManage: boolean; onConnect: () => void }) {
    return (
        <div className="rounded-2xl border border-dashed border-border bg-card px-6 py-12 text-center">
            <p className="font-display text-lg font-semibold text-foreground">No bots yet</p>
            <p className="mx-auto mt-2 max-w-md text-sm text-muted-foreground">
                {canManage
                    ? 'Connect a WhatsApp number or a Telegram bot. It takes a few minutes, and we’ll guide you through each step.'
                    : 'An admin in your workspace can connect a WhatsApp or Telegram bot here.'}
            </p>
            {canManage && <button onClick={onConnect} className={`${primaryButton} mt-5`}><Plus className="h-4 w-4" /> Connect a bot</button>}
        </div>
    );
}
