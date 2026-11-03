import React from 'react';

/** Infinite horizontal scroller; content is duplicated so the loop is seamless. Pauses on hover. */
export default function Marquee({ children, duration = 40, className = '' }: { children: React.ReactNode; duration?: number; className?: string }) {
    return (
        <div
            className={`marquee relative overflow-hidden [mask-image:linear-gradient(90deg,transparent,black_10%,black_90%,transparent)] ${className}`}
            style={{ ['--marquee-duration' as string]: `${duration}s` }}
        >
            <div className="marquee-track flex w-max gap-3">
                <div className="flex shrink-0 gap-3">{children}</div>
                <div className="flex shrink-0 gap-3" aria-hidden="true">{children}</div>
            </div>
        </div>
    );
}
