// Small per-browser preferences. Storage can be unavailable (private mode,
// blocked site data), so every access is guarded and failures fall back to defaults.

const ACTIVE_ORG_KEY = 'bizassist.activeOrganizationId';
const PENDING_INVITE_KEY = 'bizassist.pendingInviteToken';

function read(storage: () => Storage, key: string): string | null {
    try {
        return storage().getItem(key);
    } catch {
        return null;
    }
}

function write(storage: () => Storage, key: string, value: string | null) {
    try {
        if (value === null) storage().removeItem(key);
        else storage().setItem(key, value);
    } catch {
        // Ignore: the app still works, the preference just isn't remembered.
    }
}

export const getActiveOrganizationId = () => read(() => localStorage, ACTIVE_ORG_KEY);
export const setActiveOrganizationId = (id: string | null) => write(() => localStorage, ACTIVE_ORG_KEY, id);

export const getPendingInviteToken = () => read(() => sessionStorage, PENDING_INVITE_KEY);
export const setPendingInviteToken = (token: string | null) => write(() => sessionStorage, PENDING_INVITE_KEY, token);

/** Where to go after signing in: back to a pending invitation, otherwise the app. */
export const postLoginPath = () => (getPendingInviteToken() ? '/invite' : '/app');

/** Switch organization with a full reload so every store starts clean in the new context. */
export function switchOrganization(id: string) {
    setActiveOrganizationId(id);
    window.location.assign('/app/chat');
}
