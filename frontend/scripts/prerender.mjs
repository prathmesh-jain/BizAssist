// Post-build SEO step (runs after `vite build` and the SSR build in vite.prerender.config.ts):
//   1. Renders the landing page to static HTML inside dist/index.html, so crawlers and link
//      previews see real content without running JavaScript. The app still mounts normally.
//   2. Adds FAQPage structured data generated from src/content/faq.ts.
//   3. Writes per-route HTML shells with their own title/description/canonical:
//      dist/login.html, dist/signup.html, and dist/app.html (noindex) for everything else.
//      vercel.json rewrites /login, /signup and unknown paths to these files.
import { readFile, writeFile, rm } from 'node:fs/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { dirname, resolve } from 'node:path';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const dist = resolve(root, 'dist');
const ssrDir = resolve(root, 'dist-ssr');
const SITE_URL = 'https://bizassist.prathmeshjain.in';
const MARKER = '<!--app-html-->';

const escapeAttr = (s) => s.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;');

/** Replace the content of a tag found by a regex with one capture group for the attribute value. */
function setAttr(html, pattern, value) {
    if (!pattern.test(html)) throw new Error(`prerender: pattern not found: ${pattern}`);
    return html.replace(pattern, (match, current) => match.replace(current, escapeAttr(value)));
}

function withMeta(template, { title, description, path, noindex }) {
    let html = template;
    html = html.replace(/<title>[^<]*<\/title>/, `<title>${escapeAttr(title)}</title>`);
    html = setAttr(html, /<meta\s+name="description"\s+content="([^"]*)"/, description);
    html = setAttr(html, /<meta property="og:title" content="([^"]*)"/, title);
    html = setAttr(html, /<meta\s+property="og:description"\s+content="([^"]*)"/, description);
    html = setAttr(html, /<meta name="twitter:title" content="([^"]*)"/, title);
    html = setAttr(html, /<meta\s+name="twitter:description"\s+content="([^"]*)"/, description);
    html = setAttr(
        html,
        /<meta name="robots" content="([^"]*)"/,
        noindex ? 'noindex, nofollow' : 'index, follow, max-image-preview:large',
    );
    if (path) {
        const url = `${SITE_URL}${path}`;
        html = setAttr(html, /<link rel="canonical" href="([^"]*)"/, url);
        html = setAttr(html, /<meta property="og:url" content="([^"]*)"/, url);
    } else {
        html = html.replace(/\s*<link rel="canonical" href="[^"]*" \/>/, '');
    }
    return html;
}

const template = await readFile(resolve(dist, 'index.html'), 'utf8');
if (!template.includes(MARKER)) throw new Error('prerender: <!--app-html--> marker missing from dist/index.html');

const { renderLanding, faqs } = await import(pathToFileURL(resolve(ssrDir, 'entry.js')).href);

// 1–2. Landing page with real content and FAQ structured data.
const faqJsonLd = {
    '@context': 'https://schema.org',
    '@type': 'FAQPage',
    mainEntity: faqs.map(({ q, a }) => ({
        '@type': 'Question',
        name: q,
        acceptedAnswer: { '@type': 'Answer', text: a },
    })),
};
const landingHtml = renderLanding();
const indexHtml = template
    .replace(MARKER, landingHtml)
    .replace(
        '</head>',
        `    <script type="application/ld+json">${JSON.stringify(faqJsonLd).replace(/</g, '\\u003c')}</script>\n  </head>`,
    );
await writeFile(resolve(dist, 'index.html'), indexHtml);

// 3. Route shells (empty root; the app renders them client-side).
const shells = {
    'login.html': {
        title: 'Sign in | BizAssist',
        description: 'Sign in to BizAssist, the AI assistant that knows your business.',
        path: '/login',
    },
    'signup.html': {
        title: 'Create your workspace | BizAssist',
        description:
            'Create a BizAssist workspace in minutes. Connect your documents, Google Sheets and Calendar, then just ask.',
        path: '/signup',
    },
    'app.html': {
        title: 'BizAssist',
        description: 'BizAssist workspace.',
        noindex: true,
    },
};
for (const [file, meta] of Object.entries(shells)) {
    await writeFile(resolve(dist, file), withMeta(template.replace(MARKER, ''), meta));
}

await rm(ssrDir, { recursive: true, force: true });
console.log(`prerender: landing ${(landingHtml.length / 1024).toFixed(1)} kB, ${faqs.length} FAQs, shells: ${Object.keys(shells).join(', ')}`);
