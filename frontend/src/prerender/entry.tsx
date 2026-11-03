import { renderToString } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom';
import Landing from '../pages/Landing';
import { FAQS } from '../content/faq';

/** Server-render the public landing page to static HTML (see scripts/prerender.mjs). */
export function renderLanding(): string {
    return renderToString(
        <StaticRouter location="/">
            <Landing />
        </StaticRouter>,
    );
}

export const faqs = FAQS;
