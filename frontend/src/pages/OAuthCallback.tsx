import React from 'react';
import { LogoMark } from '../components/ui/Logo';
import { usePageMeta } from '../lib/seo';
import { publishGoogleOAuthResult } from '../lib/googleOAuth';

/**
 * OAuthCallback — minimal page rendered inside the OAuth popup window.
 *
 * Google redirects the popup to /oauth-callback?code=...&state=... after auth.
 * This page:
 *   1. Hands the code/state to the tab that started sign-in (BroadcastChannel; see lib/googleOAuth)
 *   2. Closes the popup; that tab exchanges the code with the backend
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

            publishGoogleOAuthResult({ code, state, error, error_description: errorDescription });
            setTimeout(() => window.close(), 800);
        };

        run();
    }, []);

    const failed = new URLSearchParams(window.location.search).has('error');
    return (
        <div className="min-h-screen bg-background flex flex-col items-center justify-center gap-3 p-6 text-center">
            <LogoMark className="w-10 h-10" />
            <h1 className="font-display mt-3 text-2xl font-semibold text-foreground">
                {failed ? 'Google didn’t connect' : 'Signed in with Google'}
            </h1>
            <p className="text-sm text-muted-foreground">
                {failed ? 'You can close this window and try again.' : 'Finishing up in BizAssist. You can close this window if it doesn’t close on its own.'}
            </p>
        </div>
    );
}
