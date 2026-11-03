import React from 'react';

/** Fades and un-blurs its children the first time they scroll into view. */
export default function Reveal({
    children,
    delay = 0,
    className = '',
    as: Tag = 'div',
}: {
    children: React.ReactNode;
    delay?: number;
    className?: string;
    as?: React.ElementType;
}) {
    const ref = React.useRef<HTMLElement>(null);
    const [visible, setVisible] = React.useState(false);

    React.useEffect(() => {
        const el = ref.current;
        if (!el) return;
        if (typeof IntersectionObserver === 'undefined') {
            setVisible(true);
            return;
        }
        const io = new IntersectionObserver(
            ([entry]) => {
                if (entry.isIntersecting) {
                    setVisible(true);
                    io.disconnect();
                }
            },
            { threshold: 0.15, rootMargin: '0px 0px -40px 0px' },
        );
        io.observe(el);
        return () => io.disconnect();
    }, []);

    return (
        <Tag
            ref={ref}
            className={`reveal ${visible ? 'is-visible' : ''} ${className}`}
            style={{ ['--reveal-delay' as string]: `${delay}ms` }}
        >
            {children}
        </Tag>
    );
}
