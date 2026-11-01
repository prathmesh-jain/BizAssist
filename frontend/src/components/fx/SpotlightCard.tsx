import React from 'react';

/** A card whose surface and border light up under the cursor. */
export default function SpotlightCard({
    className = '',
    children,
    ...rest
}: React.HTMLAttributes<HTMLDivElement>) {
    const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
        const r = e.currentTarget.getBoundingClientRect();
        e.currentTarget.style.setProperty('--mx', `${e.clientX - r.left}px`);
        e.currentTarget.style.setProperty('--my', `${e.clientY - r.top}px`);
    };
    return (
        <div onMouseMove={onMove} className={`spotlight ${className}`} {...rest}>
            {children}
        </div>
    );
}
