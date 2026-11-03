/** Firebase errors read like "Firebase: Error (auth/wrong-password)." — turn the common ones into plain words. */
export function friendlyAuthError(err: unknown, fallback: string): string {
    const raw = err instanceof Error ? err.message : '';
    const code = raw.match(/auth\/[a-z-]+/)?.[0];
    const messages: Record<string, string> = {
        'auth/invalid-credential': 'That email and password don’t match. Try again or reset your password.',
        'auth/wrong-password': 'That email and password don’t match.',
        'auth/user-not-found': 'There’s no account with that email yet.',
        'auth/email-already-in-use': 'An account with this email already exists. Try signing in instead.',
        'auth/weak-password': 'Use a password with at least 6 characters.',
        'auth/invalid-email': 'That doesn’t look like a valid email address.',
        'auth/too-many-requests': 'Too many attempts. Wait a minute and try again.',
        'auth/popup-closed-by-user': 'The Google window was closed before signing in finished.',
        'auth/network-request-failed': 'Couldn’t reach the sign-in service. Check your connection.',
    };
    return (code && messages[code]) || raw || fallback;
}
