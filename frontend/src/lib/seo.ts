import React from 'react';

/** Public site URL used for canonical links, sitemaps and social cards. Keep in sync with index.html and public/. */
export const SITE_URL = 'https://bizassist.prathmeshjain.in';
export const SITE_NAME = 'BizAssist';

export const DEFAULT_TITLE = 'BizAssist: AI business assistant for documents, Google Sheets and Calendar';
export const DEFAULT_DESCRIPTION =
    'BizAssist is an AI assistant for small businesses. It learns your business, answers from your documents, ' +
    'updates Google Sheets, books Google Calendar and Meet, and researches competitors, all from one chat.';

type PageMeta = {
    /** Page title; the site name is appended unless the title already contains it. */
    title?: string;
    description?: string;
    /** Path for the canonical URL, e.g. "/signup". */
    path?: string;
    /** Keep private screens (the app, invites, OAuth) out of search results. */
    noindex?: boolean;
};

function setMeta(selector: string, attr: 'name' | 'property', key: string, content: string) {
    let el = document.head.querySelector<HTMLMetaElement>(selector);
    if (!el) {
        el = document.createElement('meta');
        el.setAttribute(attr, key);
        document.head.appendChild(el);
    }
    el.setAttribute('content', content);
}

function setCanonical(href: string) {
    let el = document.head.querySelector<HTMLLinkElement>('link[rel="canonical"]');
    if (!el) {
        el = document.createElement('link');
        el.rel = 'canonical';
        document.head.appendChild(el);
    }
    el.href = href;
}

/** Sets the document title, description, canonical URL, social tags and robots directive for a page. */
export function usePageMeta({ title, description, path, noindex }: PageMeta) {
    React.useEffect(() => {
        const fullTitle = !title ? DEFAULT_TITLE : title.includes(SITE_NAME) ? title : `${title} | ${SITE_NAME}`;
        const desc = description ?? DEFAULT_DESCRIPTION;
        document.title = fullTitle;
        setMeta('meta[name="description"]', 'name', 'description', desc);
        setMeta('meta[property="og:title"]', 'property', 'og:title', fullTitle);
        setMeta('meta[property="og:description"]', 'property', 'og:description', desc);
        setMeta('meta[name="twitter:title"]', 'name', 'twitter:title', fullTitle);
        setMeta('meta[name="twitter:description"]', 'name', 'twitter:description', desc);
        setMeta('meta[name="robots"]', 'name', 'robots', noindex ? 'noindex, nofollow' : 'index, follow, max-image-preview:large');
        if (path !== undefined) {
            const url = `${SITE_URL}${path === '/' ? '/' : path}`;
            setCanonical(url);
            setMeta('meta[property="og:url"]', 'property', 'og:url', url);
        }
    }, [title, description, path, noindex]);
}
