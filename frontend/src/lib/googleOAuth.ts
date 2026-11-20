/**
 * Google OAuth in a popup.
 *
 * Google's sign-in pages send a Cross-Origin-Opener-Policy header. Once the popup is on
 * accounts.google.com, browsers sever the link between this tab and the popup: `popup.closed`
 * reads true while the window is still open, and when Google redirects back to
 * /oauth-callback, `window.opener` is null. So the result can't be posted through the
 * opener, and "closed" can't be trusted.
 *
 * Instead, /oauth-callback publishes the result on a same-origin BroadcastChannel (with a
 * localStorage event as a fallback for older browsers), and we match it to this attempt by
 * the OAuth `state`. The user can cancel; otherwise we give up after a generous timeout.
 */

const CHANNEL_NAME = 'bizassist-google-oauth';
const STORAGE_KEY = 'bizassist-google-oauth-result';
const TIMEOUT_MS = 10 * 60 * 1000;

export interface GoogleOAuthResult {
    code: string;
    state: string;
    error?: string;
    error_description?: string;
}

/** Called by /oauth-callback: hand the result to whichever tab started the sign-in. */
export function publishGoogleOAuthResult(result: GoogleOAuthResult) {
    const message = { type: 'OAUTH_COMPLETE', provider: 'google', ...result };
    try {
        const channel = new BroadcastChannel(CHANNEL_NAME);
        channel.postMessage(message);
        channel.close();
    } catch {
        /* BroadcastChannel unavailable; the fallbacks below still work */
    }
    try {
        if (window.opener && !window.opener.closed) window.opener.postMessage(message, window.location.origin);
    } catch {
        /* opener severed by Cross-Origin-Opener-Policy */
    }
    try {
        // Fires a `storage` event in other tabs of this origin; removed right after.
        localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...message, at: Date.now() }));
        window.setTimeout(() => localStorage.removeItem(STORAGE_KEY), 2000);
    } catch {
        /* storage blocked */
    }
}

export class GoogleOAuthCancelled extends Error {
    constructor() {
        super('Google sign-in was cancelled.');
        this.name = 'GoogleOAuthCancelled';
    }
}

/**
 * Open Google's consent screen and resolve with the code and state from /oauth-callback.
 * Pass an AbortSignal to let the user cancel (rejects with GoogleOAuthCancelled).
 */
export function runGoogleOAuthPopup(
    authUrl: string,
    { signal }: { signal?: AbortSignal } = {},
): Promise<{ code: string; state: string }> {
    return new Promise((resolve, reject) => {
        let expectedState: string | null = null;
        try {
            expectedState = new URL(authUrl).searchParams.get('state');
        } catch {
            /* keep null: accept the first result */
        }

        const popup = window.open(authUrl, 'google-oauth', 'width=520,height=680,left=200,top=80');
        if (!popup) {
            reject(new Error('The sign-in window was blocked. Allow pop-ups for this site and try again.'));
            return;
        }

        let channel: BroadcastChannel | null = null;
        let settled = false;
        let timer = 0;
        const cleanup = () => {
            window.removeEventListener('message', onWindowMessage);
            window.removeEventListener('storage', onStorage);
            channel?.close();
            window.clearTimeout(timer);
            signal?.removeEventListener('abort', onAbort);
        };
        const finish = (fn: () => void) => {
            if (settled) return;
            settled = true;
            cleanup();
            fn();
        };

        const handle = (data: unknown) => {
            const msg = data as Partial<GoogleOAuthResult & { type: string }> | null;
            if (!msg || msg.type !== 'OAUTH_COMPLETE') return;
            if (expectedState && msg.state !== expectedState) return; // another tab's sign-in
            const { code, state, error, error_description: description } = msg;
            finish(() => {
                if (error || !code || !state) {
                    reject(new Error(
                        error === 'access_denied'
                            ? 'Google access wasn’t granted. Try again and allow the requested permissions.'
                            : description || error || 'Google sign-in didn’t complete.',
                    ));
                } else {
                    resolve({ code, state });
                }
            });
        };

        const onWindowMessage = (event: MessageEvent) => {
            if (event.origin === window.location.origin) handle(event.data);
        };
        const onStorage = (event: StorageEvent) => {
            if (event.key !== STORAGE_KEY || !event.newValue) return;
            try {
                handle(JSON.parse(event.newValue));
            } catch {
                /* ignore malformed values */
            }
        };
        const onAbort = () => {
            finish(() => reject(new GoogleOAuthCancelled()));
            try {
                popup.close(); // may be ignored once the popup has been severed
            } catch {
                /* ignore */
            }
        };

        try {
            channel = new BroadcastChannel(CHANNEL_NAME);
            channel.onmessage = (event) => handle(event.data);
        } catch {
            channel = null;
        }
        window.addEventListener('message', onWindowMessage);
        window.addEventListener('storage', onStorage);
        signal?.addEventListener('abort', onAbort);
        timer = window.setTimeout(
            () => finish(() => reject(new Error('Google sign-in took too long. Try again.'))),
            TIMEOUT_MS,
        );
        if (signal?.aborted) onAbort();
    });
}
