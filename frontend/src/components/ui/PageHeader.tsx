import React from 'react';

/** Shared heading for app pages: a glowing eyebrow pill, a bold title, and an optional note and actions. */
export default function PageHeader({
    eyebrow,
    title,
    description,
    actions,
}: {
    eyebrow?: string;
    title: React.ReactNode;
    description?: React.ReactNode;
    actions?: React.ReactNode;
}) {
    return (
        <header className="rise-in relative flex flex-wrap items-end justify-between gap-4 pb-6">
            <div className="min-w-0 max-w-2xl">
                {eyebrow && (
                    <p className="eyebrow mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-brand-gradient" />
                        {eyebrow}
                    </p>
                )}
                <h1 className="font-display text-3xl sm:text-[2.6rem] leading-[1.05] font-bold text-foreground break-words">{title}</h1>
                {description && <p className="mt-3 text-[15px] text-muted-foreground leading-relaxed">{description}</p>}
            </div>
            {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
            <span className="absolute inset-x-0 bottom-0 h-px bg-gradient-to-r from-primary/60 via-accent/40 to-transparent" aria-hidden="true" />
        </header>
    );
}
