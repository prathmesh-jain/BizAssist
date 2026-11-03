import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { CalendarDays, ExternalLink, RefreshCw } from 'lucide-react';
import PageHeader from '../ui/PageHeader';
import apiClient from '../../api/client';

interface CalendarStatus {
    connected: boolean;
    email?: string;
    timezone?: string;
}

const DATE_PARAM = /^\d{4}-\d{2}-\d{2}$/;

/** Google's own embed, so this is the user's real calendar rather than a copy of it. */
function calendarEmbedUrl(email: string, timezone: string | undefined, date: string | null, compact: boolean) {
    const params = new URLSearchParams({
        src: email,
        authuser: email,
        mode: compact ? 'AGENDA' : 'WEEK',
        showTitle: '0',
        showPrint: '0',
        showCalendars: '0',
        showTz: '0',
    });
    if (timezone) params.set('ctz', timezone);
    if (date && DATE_PARAM.test(date)) {
        const next = new Date(`${date}T00:00:00Z`);
        next.setUTCDate(next.getUTCDate() + 1);
        params.set('dates', `${date.replaceAll('-', '')}/${next.toISOString().slice(0, 10).replaceAll('-', '')}`);
    }
    return `https://calendar.google.com/calendar/embed?${params}`;
}

function googleCalendarUrl(email: string | undefined, date: string | null) {
    const path = date && DATE_PARAM.test(date) ? `r/week/${date.replaceAll('-', '/')}` : 'r';
    return `https://calendar.google.com/calendar/${path}${email ? `?authuser=${encodeURIComponent(email)}` : ''}`;
}

export default function CalendarView() {
    const [searchParams] = useSearchParams();
    const [status, setStatus] = React.useState<CalendarStatus | null>(null);
    const [frameKey, setFrameKey] = React.useState(0);
    const date = searchParams.get('date');

    React.useEffect(() => {
        apiClient.get<CalendarStatus>('/integrations/google-calendar/status')
            .then(res => setStatus(res.data))
            .catch(() => setStatus({ connected: false }));
    }, []);

    const openLink = (
        <a
            href={googleCalendarUrl(status?.email, date)}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-foreground hover:bg-muted"
        >
            Open in Google Calendar <ExternalLink className="w-3.5 h-3.5" />
        </a>
    );

    return (
        <div className="flex min-h-full flex-col px-4 py-8 sm:px-8 lg:py-10">
            <div className="mx-auto flex w-full max-w-6xl flex-1 flex-col">
                <PageHeader
                    eyebrow="Calendar"
                    title="Your Google Calendar"
                    description={status?.email ? `Showing ${status.email}. Anything BizAssist schedules appears here.` : 'Anything BizAssist schedules appears here.'}
                    actions={status?.connected ? (
                        <>
                            <button
                                onClick={() => setFrameKey(key => key + 1)}
                                className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-foreground hover:bg-muted"
                            >
                                <RefreshCw className="w-3.5 h-3.5" /> Refresh
                            </button>
                            {openLink}
                        </>
                    ) : undefined}
                />

                {status === null ? (
                    <p className="mt-6 text-sm text-muted-foreground">Checking your calendar connection…</p>
                ) : !status.connected ? (
                    <div className="mt-6 rounded-2xl border border-border bg-card p-6">
                        <div className="chip-blue flex h-11 w-11 items-center justify-center rounded-xl">
                            <CalendarDays className="h-5 w-5" />
                        </div>
                        <h2 className="mt-4 text-lg font-semibold text-foreground">Connect your calendar</h2>
                        <p className="mt-1 max-w-lg text-sm text-muted-foreground">
                            Connect Google Calendar to see it here and let BizAssist schedule meetings for you.
                        </p>
                        <Link to="/app/settings" className="mt-4 inline-flex rounded-xl px-4 py-2 btn-glow text-sm font-semibold">
                            Connect in Settings
                        </Link>
                    </div>
                ) : !status.email ? (
                    <div className="mt-6 rounded-2xl border border-border bg-card p-6 text-sm text-muted-foreground">
                        <p>BizAssist doesn’t know which Google account this is. Reconnect it in <Link to="/app/settings" className="font-medium text-primary underline underline-offset-4">Settings</Link> to show the calendar here.</p>
                        <div className="mt-4">{openLink}</div>
                    </div>
                ) : (
                    <>
                        <div className="mt-6 flex-1 overflow-hidden rounded-2xl border border-border bg-white">
                            <iframe
                                key={frameKey}
                                title="Google Calendar"
                                src={calendarEmbedUrl(status.email, status.timezone, date, window.innerWidth < 640)}
                                className="h-full min-h-[600px] w-full border-0"
                            />
                        </div>
                        <p className="mt-3 text-xs text-muted-foreground">
                            Google shows your events here only if your browser is signed in to {status.email} and allows Google’s third-party cookies on this site. If it stays blank, asks you to sign in, or says it couldn’t load your events, check those two things or use “Open in Google Calendar”.
                        </p>
                    </>
                )}
            </div>
        </div>
    );
}
