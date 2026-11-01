import React from 'react';
import { CalendarDays, Loader2, Unplug } from 'lucide-react';
import StatusChip from '../ui/StatusChip';
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
        <div className="bg-card border border-border rounded-lg p-5 sm:p-6">
            <div className="flex flex-col sm:flex-row sm:items-start gap-5">
                <div className="w-11 h-11 rounded-md border border-border bg-background flex items-center justify-center shrink-0">
                    <CalendarDays className="w-5 h-5 text-primary" />
                </div>
                <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-3 flex-wrap">
                        <h3 className="text-lg font-semibold text-foreground">Google Calendar & Meet</h3>
                        {status === null ? (
                            <StatusChip tone="neutral">Checking…</StatusChip>
                        ) : status.connected ? (
                            <StatusChip tone="success">Connected</StatusChip>
                        ) : (
                            <StatusChip tone="warning">Not connected</StatusChip>
                        )}
                    </div>
                    <p className="text-muted-foreground mt-2 text-sm leading-relaxed max-w-xl">
                        Your own calendar; your team can’t see it. BizAssist can check your schedule, find free time,
                        and set up meetings with Google Meet links. It asks for your OK before creating, moving, or
                        cancelling anything.
                    </p>

                    {status?.connected && (status.email || status.timezone) && (
                        <p className="mt-3 font-mono text-xs text-muted-foreground">
                            {status.email}{status.email && status.timezone ? ' · ' : ''}{status.timezone}
                        </p>
                    )}

                    {status?.connected && (
                        <ul className="mt-3 flex flex-wrap gap-2">
                            {EXAMPLES.map((e) => (
                                <li key={e} className="rounded-md border border-border bg-background px-2.5 py-1 text-xs text-muted-foreground">“{e}”</li>
                            ))}
                        </ul>
                    )}

                    {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

                    <div className="mt-5">
                        {status?.connected ? (
                            <button
                                onClick={disconnect}
                                disabled={busy}
                                className="flex items-center gap-2 px-3.5 py-2 rounded-md border border-border text-sm text-foreground hover:bg-muted disabled:opacity-50"
                            >
                                {busy ? <Loader2 className="w-4 h-4 animate-spin" /> : <Unplug className="w-4 h-4" />} Disconnect
                            </button>
                        ) : (
                            <button
                                onClick={connect}
                                disabled={busy || status === null}
                                className="flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary/90 text-primary-foreground rounded-md font-medium text-sm disabled:opacity-60"
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
