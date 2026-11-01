import React from 'react';

/** Starts tilted back in 3D and flattens as it scrolls toward the middle of the screen. */
export default function ScrollTilt({ children, className = '' }: { children: React.ReactNode; className?: string }) {
    const ref = React.useRef<HTMLDivElement>(null);

    React.useEffect(() => {
        const el = ref.current;
        if (!el || window.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
        let frame = 0;
        const update = () => {
            frame = 0;
            const r = el.getBoundingClientRect();
            const vh = window.innerHeight;
            // 0 when the top sits at the bottom of the screen, 1 once it reaches 25% from the top.
            const p = Math.min(1, Math.max(0, (vh - r.top) / (vh * 0.75)));
            el.style.transform = `perspective(1400px) rotateX(${(1 - p) * 22}deg) scale(${0.9 + p * 0.1})`;
            el.style.opacity = String(0.55 + p * 0.45);
        };
        const onScroll = () => { if (!frame) frame = requestAnimationFrame(update); };
        update();
        window.addEventListener('scroll', onScroll, { passive: true, capture: true });
        window.addEventListener('resize', onScroll);
        return () => {
            window.removeEventListener('scroll', onScroll, { capture: true } as EventListenerOptions);
            window.removeEventListener('resize', onScroll);
            cancelAnimationFrame(frame);
        };
    }, []);

    return (
        <div ref={ref} className={`will-change-transform origin-top transition-[transform,opacity] duration-100 ease-out ${className}`}>
            {children}
        </div>
    );
}
