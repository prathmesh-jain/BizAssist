import React from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import FullCalendar from '@fullcalendar/react';
import dayGridPlugin from '@fullcalendar/daygrid';
import timeGridPlugin from '@fullcalendar/timegrid';
import listPlugin from '@fullcalendar/list';
import luxonPlugin from '@fullcalendar/luxon3';
import type { DatesSetArg, EventClickArg, EventSourceFuncArg } from '@fullcalendar/core';
import { CalendarDays, ExternalLink, Loader2, RefreshCw } from 'lucide-react';
import PageHeader from '../ui/PageHeader';
import apiClient, { apiErrorDetail } from '../../api/client';
import EventDetails, { type CalendarEvent } from './EventDetails';
import './calendar.css';

interface CalendarStatus {
    connected: boolean;
    email?: string;
    timezone?: string;
}

const DATE_PARAM = /^\d{4}-\d{2}-\d{2}$/;

function googleCalendarUrl(email: string | undefined, date: string | null) {
    const path = date && DATE_PARAM.test(date) ? `r/week/${date.replaceAll('-', '/')}` : 'r';
    return `https://calendar.google.com/calendar/${path}${email ? `?authuser=${encodeURIComponent(email)}` : ''}`;
}

/** The member's real Google Calendar, read live through the API. Changes go through the assistant. */
export default function CalendarView() {
    const [searchParams] = useSearchParams();
    const dateParam = searchParams.get('date');
    const date = dateParam && DATE_PARAM.test(dateParam) ? dateParam : null;
    const calendarRef = React.useRef<FullCalendar>(null);
    const [status, setStatus] = React.useState<CalendarStatus | null>(null);
    const [selected, setSelected] = React.useState<CalendarEvent | null>(null);
    const [visibleDate, setVisibleDate] = React.useState(date);
    const [loading, setLoading] = React.useState(false);
    const [error, setError] = React.useState('');

    React.useEffect(() => {
        apiClient.get<CalendarStatus>('/integrations/google-calendar/status')
            .then(res => setStatus(res.data))
            .catch(() => setStatus({ connected: false }));
    }, []);

    const refresh = React.useCallback(() => calendarRef.current?.getApi().refetchEvents(), []);

    // Pick up changes made in Google or by the assistant when the user comes back to this tab.
    React.useEffect(() => {
        const onVisible = () => { if (document.visibilityState === 'visible') refresh(); };
        document.addEventListener('visibilitychange', onVisible);
        return () => document.removeEventListener('visibilitychange', onVisible);
    }, [refresh]);

    React.useEffect(() => {
        if (date) calendarRef.current?.getApi().gotoDate(date);
    }, [date]);

    const loadEvents = React.useCallback(async (info: EventSourceFuncArg) => {
        setError('');
        try {
            const { data } = await apiClient.get<{ events: CalendarEvent[] }>('/integrations/google-calendar/events', {
                params: { start: info.start.toISOString(), end: info.end.toISOString() },
            });
            return data.events.map(event => ({
                id: event.id,
                title: event.title,
                start: event.start,
                end: event.end,
                allDay: event.all_day,
                extendedProps: { event },
            }));
        } catch (e) {
            setError(apiErrorDetail(e, 'Could not load your calendar.'));
            return [];
        }
    }, []);

    const onDatesSet = React.useCallback((arg: DatesSetArg) => {
        setVisibleDate(arg.view.calendar.formatIso(arg.view.currentStart, true));
    }, []);

    const onEventClick = React.useCallback((arg: EventClickArg) => {
        setSelected(arg.event.extendedProps.event as CalendarEvent);
    }, []);

    const closeDetails = React.useCallback(() => setSelected(null), []);

    const compact = window.innerWidth < 640;

    return (
        <div className="px-4 py-8 sm:px-8 lg:py-10">
            <div className="mx-auto w-full max-w-6xl">
                <PageHeader
                    eyebrow="Calendar"
                    title="Your Google Calendar"
                    description={status?.email ? `Showing ${status.email}. Ask the assistant to schedule, move, or cancel anything.` : 'Ask the assistant to schedule, move, or cancel anything.'}
                    actions={status?.connected ? (
                        <>
                            <button
                                onClick={refresh}
                                disabled={loading}
                                className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-foreground hover:bg-muted disabled:opacity-60"
                            >
                                {loading ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RefreshCw className="h-3.5 w-3.5" />}
                                Refresh
                            </button>
                            <a
                                href={googleCalendarUrl(status.email, visibleDate)}
                                target="_blank"
                                rel="noreferrer"
                                className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-foreground hover:bg-muted"
                            >
                                Open in Google Calendar <ExternalLink className="h-3.5 w-3.5" />
                            </a>
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
                ) : (
                    <>
                        {error && (
                            <p role="alert" className="mt-6 rounded-xl border border-destructive/20 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                                {error}
                            </p>
                        )}
                        <div className="biz-calendar mt-6 rounded-2xl border border-border bg-card p-3 sm:p-4">
                            <FullCalendar
                                ref={calendarRef}
                                plugins={[dayGridPlugin, timeGridPlugin, listPlugin, luxonPlugin]}
                                timeZone={status.timezone || 'local'}
                                initialView={compact ? 'listWeek' : 'timeGridWeek'}
                                initialDate={date ?? undefined}
                                headerToolbar={{
                                    left: 'prev,next today',
                                    center: 'title',
                                    right: compact ? 'listWeek,timeGridDay,dayGridMonth' : 'dayGridMonth,timeGridWeek,timeGridDay,listWeek',
                                }}
                                buttonText={{ today: 'Today', month: 'Month', week: 'Week', day: 'Day', list: 'List' }}
                                height={compact ? 'auto' : 720}
                                views={{ timeGridWeek: { dayHeaderFormat: { weekday: 'short', month: 'short', day: 'numeric', omitCommas: true } } }}
                                nowIndicator
                                scrollTime="08:00:00"
                                dayMaxEvents
                                events={loadEvents}
                                loading={setLoading}
                                datesSet={onDatesSet}
                                eventClick={onEventClick}
                            />
                        </div>
                    </>
                )}
            </div>

            {selected && <EventDetails event={selected} timeZone={status?.timezone} onClose={closeDetails} />}
        </div>
    );
}
