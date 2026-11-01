import React from 'react';

/** Cycles through words with a flip-in animation. */
export default function RotatingWords({ words, interval = 2400, className = '' }: { words: string[]; interval?: number; className?: string }) {
    const [index, setIndex] = React.useState(0);

    React.useEffect(() => {
        const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
        if (reduce || words.length < 2) return;
        const id = window.setInterval(() => setIndex((i) => (i + 1) % words.length), interval);
        return () => window.clearInterval(id);
    }, [words.length, interval]);

    return (
        <span className={`inline-grid [perspective:600px] ${className}`} aria-live="polite">
            <span key={index} className="word-swap-enter inline-block origin-bottom">
                {words[index]}
            </span>
        </span>
    );
}
