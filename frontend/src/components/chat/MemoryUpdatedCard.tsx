import React from 'react';
import { Link } from 'react-router-dom';
import { Brain, Check, Loader2, Undo2 } from 'lucide-react';
import { apiErrorDetail } from '../../api/client';
import { memoryApi } from '../../lib/memoryApi';
import type { MemoryChange } from '../../types';

const ACTION_LABEL: Record<MemoryChange['action'], string> = {
    added: 'Remembered',
    updated: 'Updated',
    deleted: 'Forgot',
};

/** "Memory updated" note under a reply: what BizAssist saved this turn, with Undo. */
export default function MemoryUpdatedCard({ changes }: { changes: MemoryChange[] }) {
    const [undone, setUndone] = React.useState<Record<string, boolean>>({});
    const [busy, setBusy] = React.useState<string | null>(null);
    const [error, setError] = React.useState('');

    if (!changes.length) return null;

    const undo = async (change: MemoryChange) => {
        setBusy(change.id);
        setError('');
        try {
            await memoryApi.undo(change.id);
            setUndone((u) => ({ ...u, [change.id]: true }));
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t undo that.'));
        } finally {
            setBusy(null);
        }
    };

    return (
        <div className="rise-in mb-6 ml-11 max-w-xl rounded-xl border border-border bg-card/70 px-3.5 py-2.5">
            <div className="flex items-center justify-between gap-3">
                <p className="flex items-center gap-1.5 text-xs font-medium text-muted-foreground">
                    <Brain className="h-3.5 w-3.5 text-primary" /> Memory updated
                </p>
                <Link to="/app/memory" className="text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline">
                    Manage
                </Link>
            </div>
            <ul className="mt-1.5 space-y-1">
                {changes.map((change) => (
                    <li key={`${change.action}-${change.id}`} className="flex items-start gap-2 text-sm">
                        <span className={`min-w-0 flex-1 ${undone[change.id] ? 'text-muted-foreground line-through' : 'text-foreground'}`}>
                            <span className="text-muted-foreground">{ACTION_LABEL[change.action]}:</span> {change.content}
                            <span className="ml-1.5 inline-block whitespace-nowrap rounded-md bg-muted px-1.5 py-px align-[1px] text-[11px] text-muted-foreground">
                                {change.scope === 'shared' ? 'Team' : 'Just you'}
                            </span>
                        </span>
                        {change.action !== 'deleted' && (
                            undone[change.id] ? (
                                <span className="flex shrink-0 items-center gap-1 text-xs text-muted-foreground"><Check className="h-3 w-3" /> Undone</span>
                            ) : (
                                <button
                                    type="button"
                                    onClick={() => undo(change)}
                                    disabled={busy === change.id}
                                    className="flex shrink-0 items-center gap-1 rounded-md px-1.5 py-0.5 text-xs text-muted-foreground hover:bg-muted hover:text-foreground disabled:opacity-50"
                                >
                                    {busy === change.id ? <Loader2 className="h-3 w-3 animate-spin" /> : <Undo2 className="h-3 w-3" />} Undo
                                </button>
                            )
                        )}
                    </li>
                ))}
            </ul>
            {error && <p className="mt-1 text-xs text-destructive">{error}</p>}
        </div>
    );
}
