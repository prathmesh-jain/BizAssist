import React from 'react';

type Tone = 'success' | 'warning' | 'neutral' | 'danger';

const TONES: Record<Tone, string> = {
    success: 'text-success bg-success/10 border-success/25',
    warning: 'text-warning bg-warning/10 border-warning/25',
    danger: 'text-destructive bg-destructive/10 border-destructive/25',
    neutral: 'text-muted-foreground bg-muted border-border',
};

/** A small status label with a dot, e.g. "Connected" or "Not connected". */
export default function StatusChip({ tone, children }: { tone: Tone; children: React.ReactNode }) {
    return (
        <span className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONES[tone]}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {children}
        </span>
    );
}
