/** BizAssist mark: a drawn "B" on ledger green with a clay dot, plus an optional serif wordmark. */
export function LogoMark({ className = 'w-8 h-8' }: { className?: string }) {
    return (
        <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
            <rect width="32" height="32" rx="8" className="fill-primary" />
            <path
                d="M10 8.5v15h6.6c3.1 0 5.1-1.7 5.1-4.3 0-1.9-1.1-3.2-2.8-3.6 1.3-.5 2.1-1.6 2.1-3.1 0-2.4-1.9-4-4.8-4H10z"
                fill="none"
                className="stroke-primary-foreground"
                strokeWidth="2.2"
                strokeLinejoin="round"
            />
            <path d="M10 15.6h6.4" className="stroke-primary-foreground" strokeWidth="2.2" strokeLinecap="round" />
            <circle cx="24" cy="23.5" r="2.2" className="fill-accent" />
        </svg>
    );
}

export default function Logo({ size = 'md' }: { size?: 'sm' | 'md' | 'lg' }) {
    const mark = { sm: 'w-7 h-7', md: 'w-8 h-8', lg: 'w-10 h-10' }[size];
    const text = { sm: 'text-lg', md: 'text-xl', lg: 'text-2xl' }[size];
    return (
        <span className="inline-flex items-center gap-2.5">
            <LogoMark className={mark} />
            <span className={`font-display ${text} font-semibold tracking-tight text-foreground`}>BizAssist</span>
        </span>
    );
}
