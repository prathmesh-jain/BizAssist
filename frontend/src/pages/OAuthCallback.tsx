import React from 'react';
import { LogoMark } from '../components/ui/Logo';
import { usePageMeta } from '../lib/seo';

/**
 * OAuthCallback — minimal page rendered inside the OAuth popup window.
 *
 * Google redirects the popup to /oauth-callback?code=...&state=... after auth.
 * This page:
 *   1. Exchanges the OAuth code for tokens via the backend
 *   2. Posts a message to the opener so the main window can refresh its status
 *   3. Closes the popup
 *
 * It must NOT render the full Dashboard (that's what was happening before).
 */
export default function OAuthCallback() {
    usePageMeta({ title: 'Connecting Google', noindex: true });
    React.useEffect(() => {
        const run = async () => {
            const params = new URLSearchParams(window.location.search);
            const code = params.get('code') || '';
            const state = params.get('state') || '';
            const error = params.get('error') || '';
            const errorDescription = params.get('error_description') || '';

            if (window.opener && !window.opener.closed) {
                window.opener.postMessage(
                    {
                        type: 'OAUTH_COMPLETE',
                        // Generic: the opener knows which Google integration it started.
                        provider: 'google',
                        code,
                        state,
                        error,
                        error_description: errorDescription,
                    },
                    window.location.origin
                );
            }
            setTimeout(() => window.close(), 800);
        };

        run();
    }, []);

    const failed = new URLSearchParams(window.location.search).has('error');
    return (
        <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-3 p-6 text-center">
            <LogoMark className="w-10 h-10" />
            <h1 className="font-display mt-3 text-2xl font-semibold text-foreground">
                {failed ? 'Google didn’t connect' : 'Connected to Google'}
            </h1>
            <p className="text-sm text-muted-foreground">
                {failed ? 'You can close this window and try again.' : 'This window will close on its own.'}
            </p>
        </div>
    );
}
