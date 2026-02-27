import React from 'react';

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
                        provider: 'google_sheets',
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

    return (
        <div style={{
            minHeight: '100vh',
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            fontFamily: 'system-ui, sans-serif',
            background: '#0f172a',
            color: '#f1f5f9',
            gap: 16,
        }}>
            <div style={{ fontSize: 48 }}>✅</div>
            <h2 style={{ margin: 0, fontWeight: 700, fontSize: 20 }}>Google Sheets connected!</h2>
            <p style={{ margin: 0, color: '#94a3b8', fontSize: 14 }}>
                This window will close automatically…
            </p>
        </div>
    );
}
