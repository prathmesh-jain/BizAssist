/**
 * Open Google's consent screen in a popup and resolve with the code/state that
 * /oauth-callback posts back. Rejects if the popup is blocked or closed early.
 */
export function runGoogleOAuthPopup(authUrl: string): Promise<{ code: string; state: string }> {
    return new Promise((resolve, reject) => {
        const popup = window.open(authUrl, 'google-oauth', 'width=600,height=700,left=200,top=100');
        if (!popup) {
            reject(new Error('The sign-in popup was blocked. Allow popups for this site and try again.'));
            return;
        }
        let settled = false;
        const finish = (fn: () => void) => {
            if (settled) return;
            settled = true;
            window.removeEventListener('message', onMessage);
            window.clearInterval(watch);
            fn();
        };
        const onMessage = (event: MessageEvent) => {
            if (event.origin !== window.location.origin || event.data?.type !== 'OAUTH_COMPLETE') return;
            const { code, state, error, error_description: description } = event.data;
            finish(() => (error || !code
                ? reject(new Error(description || error || 'Google sign-in was cancelled.'))
                : resolve({ code, state })));
        };
        window.addEventListener('message', onMessage);
        const watch = window.setInterval(() => {
            if (popup.closed) finish(() => reject(new Error('Google sign-in was closed before finishing.')));
        }, 1000);
    });
}
