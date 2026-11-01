import React from 'react';

/** Shared heading for app pages: a mono eyebrow, a serif title, and an optional note and actions. */
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
        <header className="flex flex-wrap items-end justify-between gap-4 border-b border-border pb-6">
            <div className="min-w-0 max-w-2xl">
                {eyebrow && <p className="eyebrow mb-2">{eyebrow}</p>}
                <h1 className="font-display text-3xl sm:text-[2.1rem] leading-tight font-medium text-foreground break-words">{title}</h1>
                {description && <p className="mt-2 text-[15px] text-muted-foreground leading-relaxed">{description}</p>}
            </div>
            {actions && <div className="flex flex-wrap gap-2">{actions}</div>}
        </header>
    );
}
