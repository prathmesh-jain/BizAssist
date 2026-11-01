import React from 'react';
import { CalendarDays, CheckCircle2, Loader2, Unplug, XCircle } from 'lucide-react';
import apiClient, { apiErrorDetail } from '../../api/client';
import { runGoogleOAuthPopup } from '../../lib/googleOAuth';

interface CalendarStatus {
    connected: boolean;
    email?: string;
    timezone?: string;
}

const EXAMPLES = [
    'What meetings do I have tomorrow?',
    'Schedule a Google Meet with rahul@acme.com tomorrow at 3 PM',
    'Find a free hour for me on Friday afternoon',
    'Move my 4 PM meeting to Friday',
];

/** Each member connects their own Google Calendar; BizAssist asks before changing anything. */
export default function GoogleCalendarCard() {
    const [status, setStatus] = React.useState<CalendarStatus | null>(null);
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');

    const refresh = React.useCallback(async () => {
        try {
            const res = await apiClient.get<CalendarStatus>('/integrations/google-calendar/status');
            setStatus(res.data);
        } catch {
            setStatus({ connected: false });
        }
    }, []);

    React.useEffect(() => {
        refresh();
    }, [refresh]);

    const connect = async () => {
        setBusy(true);
        setError('');
        try {
            const { data } = await apiClient.post<{ auth_url: string }>('/integrations/google-calendar/connect');
            const { code, state } = await runGoogleOAuthPopup(data.auth_url);
            await apiClient.post('/integrations/google/callback', { code, state });
            await refresh();
        } catch (e) {
            setError(e instanceof Error && !('isAxiosError' in e) ? e.message : apiErrorDetail(e, 'Could not connect Google Calendar.'));
        } finally {
            setBusy(false);
        }
    };

    const disconnect = async () => {
        setBusy(true);
        setError('');
        try {
            await apiClient.delete('/integrations/google-calendar');
            await refresh();
        } catch (e) {
            setError(apiErrorDetail(e, 'Could not disconnect.'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="bg-card border border-border rounded-2xl p-5 sm:p-7 shadow-sm">
            <div className="flex flex-col sm:flex-row sm:items-start gap-5">
                <div className="w-14 h-14 rounded-2xl border border-border bg-muted flex items-center justify-center shrink-0">
                    <CalendarDays className="w-7 h-7 text-blue-500" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 flex-wrap">
                        <h3 className="text-xl font-bold text-foreground">Google Calendar & Meet</h3>
                        {status === null ? (
                            <span className="px-2.5 py-1 bg-muted border border-border rounded-full text-[11px] font-bold text-muted-foreground">Checking…</span>
                        ) : status.connected ? (
                            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20 rounded-full text-[11px] font-bold uppercase">
                                <CheckCircle2 className="w-3.5 h-3.5" /> Connected
                            </span>
                        ) : (
                            <span className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 rounded-full text-[11px] font-bold uppercase">
                                <XCircle className="w-3.5 h-3.5" /> Not connected
                            </span>
                        )}
                    </div>
                    <p className="text-muted-foreground mt-2 text-sm leading-relaxed max-w-xl">
                        Your own calendar (not shared with your team). BizAssist can check your schedule, find free time,
                        and create meetings with Google Meet links. It always asks you to approve before creating,
                        moving, or cancelling anything.
                    </p>

                    {status?.connected && (status.email || status.timezone) && (
                        <p className="mt-3 text-sm text-foreground">
                            {status.email}{status.email && status.timezone ? ' · ' : ''}{status.timezone}
                        </p>
                    )}

                    {status?.connected && (
                        <ul className="mt-3 flex flex-wrap gap-2">
                            {EXAMPLES.map((e) => (
                                <li key={e} className="rounded-full bg-muted px-3 py-1 text-xs text-muted-foreground">“{e}”</li>
                            ))}
                        </ul>
                    )}

                    {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

                    <div className="mt-5">
                        {status?.connected ? (
                            <button
                                onClick={disconnect}
                                disabled={busy}
                                className="flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-50"
                            >
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Unplug className="w-4 h-4" />} Disconnect
                            </button>
                        ) : (
                            <button
                                onClick={connect}
                                disabled={busy || status === null}
                                className="flex items-center gap-2.5 px-5 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground rounded-xl font-bold text-sm disabled:opacity-60"
                            >
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <CalendarDays className="w-4 h-4" />}
                                {busy ? 'Waiting for Google…' : 'Connect Google Calendar'}
                            </button>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
