import { CalendarDays, Video } from 'lucide-react';
import { Link } from 'react-router-dom';
import type { CalendarChange } from '../../types';

const ACTION_LABEL: Record<CalendarChange['action'], string> = {
    created: 'Added to your calendar',
    updated: 'Updated on your calendar',
    deleted: 'Removed from your calendar',
};

function formatStart(start: string): string {
    if (!start) return '';
    // A bare date is an all-day event; parsing it directly would shift it by the UTC offset.
    if (start.length === 10) return new Date(`${start}T00:00:00`).toLocaleDateString(undefined, { dateStyle: 'full' });
    return new Date(start).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Confirms what the agent just changed on the calendar and links to where it landed. */
export default function CalendarChangeCard({ change }: { change: CalendarChange }) {
    const when = formatStart(change.start);
    const target = change.start ? `/app/calendar?date=${change.start.slice(0, 10)}` : '/app/calendar';

    return (
        <div className="rise-in my-3 flex flex-wrap items-center gap-3 rounded-2xl border border-border bg-card p-4">
            <span className="chip-blue flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
                <CalendarDays className="h-4 w-4" />
            </span>
            <div className="min-w-0 flex-1">
                <p className="eyebrow !text-[10px]">{ACTION_LABEL[change.action]}</p>
                <p className="truncate text-sm font-medium text-foreground">{change.title || 'Calendar event'}</p>
                {when && <p className="text-xs text-muted-foreground">{when}</p>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
                {change.meet_link && (
                    <a href={change.meet_link} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1.5 rounded-xl border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted">
                        <Video className="h-3.5 w-3.5" /> Join Meet
                    </a>
                )}
                <Link to={target} className="inline-flex rounded-xl border border-border px-3 py-1.5 text-sm text-foreground hover:bg-muted">
                    View in calendar
                </Link>
            </div>
        </div>
    );
}
