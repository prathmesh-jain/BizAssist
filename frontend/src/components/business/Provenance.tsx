import { ExternalLink } from 'lucide-react';
import type { Basis } from '../../types';
import { hostOf } from '../../lib/url';

const BASIS_STYLE: Record<Basis, { label: string; className: string; title: string }> = {
    user_provided: { label: 'From you', className: 'bg-muted text-muted-foreground border-border', title: 'You entered this during onboarding.' },
    verified: { label: 'Verified', className: 'bg-green-500/10 text-green-700 dark:text-green-400 border-green-500/25', title: 'Stated by a cited public source.' },
    estimated: { label: 'Estimated', className: 'bg-amber-500/10 text-amber-700 dark:text-amber-400 border-amber-500/25', title: 'Inferred from evidence; check it.' },
    unknown: { label: 'Not found', className: 'bg-muted text-muted-foreground border-border', title: 'Research found no evidence.' },
    edited: { label: 'Edited', className: 'bg-primary/10 text-primary border-primary/25', title: 'You changed the researched value.' },
};

export function BasisBadge({ basis, note }: { basis: Basis; note?: string }) {
    const style = BASIS_STYLE[basis] ?? BASIS_STYLE.unknown;
    return (
        <span
            title={note ? `${style.title} ${note}` : style.title}
            className={`px-2 py-0.5 rounded-full border text-[11px] font-bold uppercase tracking-wide ${style.className}`}
        >
            {style.label}
        </span>
    );
}

export function SourceLinks({ sources }: { sources: string[] }) {
    if (!sources?.length) return null;
    return (
        <span className="inline-flex flex-wrap gap-x-2 gap-y-1">
            {sources.map((url) => (
                <a
                    key={url}
                    href={url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
                >
                    {hostOf(url)} <ExternalLink className="w-3 h-3" />
                </a>
            ))}
        </span>
    );
}
