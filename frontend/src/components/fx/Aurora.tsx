/** Slowly drifting, heavily blurred colour blobs. Purely decorative. */
export default function Aurora({ className = '', intensity = 1 }: { className?: string; intensity?: number }) {
    const blobs = [
        { color: 'var(--glow-1)', size: '46vmax', top: '-18%', left: '-8%', dur: '22s', dx: '60px', dy: '40px' },
        { color: 'var(--glow-2)', size: '38vmax', top: '-10%', left: '48%', dur: '26s', dx: '-70px', dy: '50px' },
        { color: 'var(--glow-3)', size: '30vmax', top: '30%', left: '20%', dur: '30s', dx: '50px', dy: '-60px' },
        { color: 'var(--glow-4)', size: '22vmax', top: '42%', left: '70%', dur: '24s', dx: '-40px', dy: '-30px' },
    ];
    return (
        <div aria-hidden="true" className={`pointer-events-none absolute inset-0 overflow-hidden ${className}`}>
            {blobs.map((b, i) => (
                <div
                    key={i}
                    className="aurora-blob absolute rounded-full"
                    style={{
                        width: b.size,
                        height: b.size,
                        top: b.top,
                        left: b.left,
                        background: `radial-gradient(circle at 50% 50%, hsl(${b.color}) 0%, transparent 65%)`,
                        opacity: `calc(var(--glow-opacity) * ${intensity})`,
                        filter: 'blur(60px)',
                        ['--dur' as string]: b.dur,
                        ['--dx' as string]: b.dx,
                        ['--dy' as string]: b.dy,
                    }}
                />
            ))}
        </div>
    );
}
