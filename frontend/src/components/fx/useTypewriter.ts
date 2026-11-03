import React from 'react';

/**
 * Types out a sequence of strings one after another, then holds.
 * Returns how many characters of each string are currently shown.
 */
export default function useTypewriter(texts: string[], { speed = 22, startDelay = 400, gap = 500, loop = true } = {}) {
    const reduce = typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    const [counts, setCounts] = React.useState<number[]>(() => texts.map((t) => (reduce ? t.length : 0)));

    React.useEffect(() => {
        if (reduce) return;
        let cancelled = false;
        const timers: number[] = [];
        const wait = (ms: number) => new Promise<void>((r) => timers.push(window.setTimeout(r, ms)));

        const run = async () => {
            while (!cancelled) {
                setCounts(texts.map(() => 0));
                await wait(startDelay);
                for (let i = 0; i < texts.length && !cancelled; i++) {
                    for (let c = 1; c <= texts[i].length && !cancelled; c++) {
                        setCounts((prev) => prev.map((v, j) => (j === i ? c : v)));
                        await wait(speed);
                    }
                    await wait(gap);
                }
                if (!loop) break;
                await wait(5000);
            }
        };
        run();
        return () => {
            cancelled = true;
            timers.forEach((t) => window.clearTimeout(t));
        };
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [reduce]);

    return counts;
}
