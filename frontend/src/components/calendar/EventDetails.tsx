import React from 'react';
import { Clock, ExternalLink, MapPin, Repeat, Users, Video, X } from 'lucide-react';

export interface CalendarEvent {
    id: string;
    title: string;
    start: string;
    end: string;
    all_day: boolean;
    location: string | null;
    description: string | null;
    organizer: string | null;
    attendees: { email: string; name: string | null; response: string | null }[];
    meet_link: string | null;
    recurring: boolean;
    link: string | null;
}

const RESPONSE_LABEL: Record<string, string> = {
    accepted: 'Going',
    declined: 'Declined',
    tentative: 'Maybe',
    needsAction: 'Not replied',
};

/** Links come from event data anyone can write to by inviting you, so only open real web links. */
function safeLink(url: string | null): string | null {
    return url && url.startsWith('https://') ? url : null;
}

/** Google descriptions are often HTML. Parsing without inserting it keeps any markup inert. */
function plainText(html: string): string {
    const withBreaks = html.replace(/<br\s*\/?>/gi, '\n').replace(/<\/(p|div|li)>/gi, '\n');
    const text = new DOMParser().parseFromString(withBreaks, 'text/html').body.textContent ?? '';
    return text.replace(/\n{3,}/g, '\n\n').trim();
}

function formatWhen(event: CalendarEvent, timeZone: string | undefined): string {
    if (event.all_day) {
        // Bare dates, and Google's end date is exclusive.
        const day = (value: string) => new Date(`${value}T00:00:00Z`);
        const format = new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeZone: 'UTC' });
        const last = new Date(day(event.end).getTime() - 86_400_000);
        return last.getTime() > day(event.start).getTime()
            ? `${format.format(day(event.start))} – ${format.format(last)}`
            : format.format(day(event.start));
    }
    const date = new Intl.DateTimeFormat(undefined, { dateStyle: 'full', timeZone });
    const time = new Intl.DateTimeFormat(undefined, { timeStyle: 'short', timeZone });
    const start = new Date(event.start);
    const end = new Date(event.end);
    return date.format(start) === date.format(end)
        ? `${date.format(start)}, ${time.format(start)} – ${time.format(end)}`
        : `${date.format(start)}, ${time.format(start)} – ${date.format(end)}, ${time.format(end)}`;
}

export default function EventDetails({ event, timeZone, onClose }: { event: CalendarEvent; timeZone?: string; onClose: () => void }) {
    React.useEffect(() => {
        const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
        window.addEventListener('keydown', onKey);
        return () => window.removeEventListener('keydown', onKey);
    }, [onClose]);

    const meet = safeLink(event.meet_link);
    const link = safeLink(event.link);
    const description = event.description ? plainText(event.description) : '';

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-foreground/30 p-4" onClick={onClose}>
            <div
                role="dialog"
                aria-modal="true"
                aria-label={event.title}
                onClick={(e) => e.stopPropagation()}
                className="flex max-h-[85dvh] w-full max-w-lg flex-col overflow-hidden rounded-2xl border border-border bg-card"
            >
                <div className="flex items-start justify-between gap-3 border-b border-border p-5">
                    <h2 className="min-w-0 break-words text-lg font-semibold text-foreground">{event.title}</h2>
                    <button onClick={onClose} aria-label="Close" className="shrink-0 rounded-md p-1 text-muted-foreground hover:bg-muted hover:text-foreground">
                        <X className="h-5 w-5" />
                    </button>
                </div>

                <div className="space-y-4 overflow-y-auto p-5 text-sm text-foreground">
                    <p className="flex items-start gap-2.5">
                        <Clock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                        <span>{formatWhen(event, timeZone)}</span>
                    </p>
                    {event.recurring && (
                        <p className="flex items-start gap-2.5 text-muted-foreground">
                            <Repeat className="mt-0.5 h-4 w-4 shrink-0" />
                            <span>Repeating event</span>
                        </p>
                    )}
                    {event.location && (
                        <p className="flex items-start gap-2.5">
                            <MapPin className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                            <span className="min-w-0 break-words">{event.location}</span>
                        </p>
                    )}
                    {event.attendees.length > 0 && (
                        <div className="flex items-start gap-2.5">
                            <Users className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                            <ul className="min-w-0 flex-1 space-y-1">
                                {event.attendees.map((person) => (
                                    <li key={person.email} className="flex flex-wrap items-baseline justify-between gap-x-3">
                                        <span className="min-w-0 break-all">
                                            {person.name || person.email}
                                            {person.email === event.organizer && <span className="text-muted-foreground"> · organizer</span>}
                                        </span>
                                        <span className="text-xs text-muted-foreground">{RESPONSE_LABEL[person.response ?? ''] ?? ''}</span>
                                    </li>
                                ))}
                            </ul>
                        </div>
                    )}
                    {description && <p className="whitespace-pre-wrap break-words border-t border-border pt-4 text-muted-foreground">{description}</p>}
                </div>

                {(meet || link) && (
                    <div className="flex flex-wrap gap-2 border-t border-border p-4">
                        {meet && (
                            <a href={meet} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-xl px-3 py-2 btn-glow text-sm font-semibold">
                                <Video className="h-4 w-4" /> Join Meet
                            </a>
                        )}
                        {link && (
                            <a href={link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-2 text-sm text-foreground hover:bg-muted">
                                Open in Google Calendar <ExternalLink className="h-3.5 w-3.5" />
                            </a>
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}
