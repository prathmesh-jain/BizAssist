import React from 'react';
import { Navigate } from 'react-router-dom';
import { sendEmailVerification } from 'firebase/auth';
import { Loader2, Users } from 'lucide-react';
import apiClient, { apiErrorDetail } from '../api/client';
import { useAuth } from '../context/AuthContext';
import { firebaseAuth } from '../firebase';
import { getPendingInviteToken, setPendingInviteToken, switchOrganization } from '../lib/session';
import type { InvitationPreview } from '../types';

const tokenFromHash = () => new URLSearchParams(window.location.hash.replace(/^#/, '')).get('token');

const errorDetail = apiErrorDetail;

export default function InvitePage() {
    const { user, loading, logout } = useAuth();
    // Remember the token across the sign-in redirect, then drop it from the address bar.
    const [token] = React.useState(() => {
        const fromHash = tokenFromHash();
        if (fromHash) {
            setPendingInviteToken(fromHash);
            window.history.replaceState(null, '', window.location.pathname);
        }
        return fromHash || getPendingInviteToken();
    });
    const [preview, setPreview] = React.useState<InvitationPreview | null>(null);
    const [error, setError] = React.useState('');
    const [busy, setBusy] = React.useState(false);
    const [notice, setNotice] = React.useState('');

    const loadPreview = React.useCallback(async () => {
        if (!token) return;
        setError('');
        try {
            const res = await apiClient.post<InvitationPreview>('/invitations/preview', { token });
            setPreview(res.data);
            setError(''); // the effect can fire more than once; a later success wins

        } catch (e) {
            setError(errorDetail(e, 'This invitation could not be loaded.'));
        }
    }, [token]);

    React.useEffect(() => {
        if (user) loadPreview();
    }, [user, loadPreview]);

    if (loading) return <Shell><Loader2 className="w-5 h-5 animate-spin text-primary" /></Shell>;
    if (!user) return <Navigate to="/login" replace />;

    const accept = async () => {
        setBusy(true);
        setError('');
        try {
            // Pick up a just-completed email verification before the server checks it.
            await firebaseAuth.currentUser?.getIdToken(true);
            const res = await apiClient.post('/invitations/accept', { token });
            setPendingInviteToken(null);
            switchOrganization(res.data.organization_id);
        } catch (e) {
            setError(errorDetail(e, 'Could not accept the invitation.'));
            setBusy(false);
        }
    };

    const sendVerification = async () => {
        const current = firebaseAuth.currentUser;
        if (!current) return;
        try {
            await sendEmailVerification(current);
            setNotice(`Verification email sent to ${current.email}. Open it, then come back and press Accept.`);
        } catch {
            setNotice('Could not send the verification email. Try again in a minute.');
        }
    };

    const dismiss = () => {
        setPendingInviteToken(null);
        window.location.assign('/app');
    };

    if (!token) {
        return (
            <Shell>
                <h1 className="text-xl font-bold text-foreground">No invitation found</h1>
                <p className="mt-2 text-sm text-muted-foreground">Open the full invitation link you were sent.</p>
                <button onClick={dismiss} className="mt-6 px-4 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-semibold">Go to BizAssist</button>
            </Shell>
        );
    }

    const needsVerification = error.toLowerCase().includes('verify your email');

    return (
        <Shell>
            <div className="w-12 h-12 rounded-2xl bg-primary/15 flex items-center justify-center">
                <Users className="w-6 h-6 text-primary" />
            </div>

            {!preview && !error && <p className="mt-4 text-sm text-muted-foreground">Loading invitation…</p>}

            {preview && (
                <>
                    <h1 className="mt-4 text-xl font-bold text-foreground">
                        Join <span className="text-primary">{preview.organization_name}</span>
                    </h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        You've been invited as <span className="font-semibold text-foreground">{preview.role}</span>.
                    </p>
                    {!preview.email_matches && (
                        <div className="mt-4 rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-foreground">
                            This invitation is for <span className="font-semibold">{preview.email}</span>, but you're signed in as{' '}
                            <span className="font-semibold">{user.email}</span>.
                            <button
                                onClick={() => logout().then(() => window.location.assign('/login'))}
                                className="block mt-2 text-primary font-semibold hover:underline"
                            >
                                Sign in with a different account
                            </button>
                        </div>
                    )}
                </>
            )}

            {error && (
                <div className="mt-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                    {error}
                    {needsVerification && (
                        <button onClick={sendVerification} className="block mt-2 font-semibold text-primary hover:underline">
                            Send verification email
                        </button>
                    )}
                </div>
            )}
            {notice && <p className="mt-3 text-sm text-muted-foreground">{notice}</p>}

            <div className="mt-6 flex flex-wrap justify-end gap-3">
                <button onClick={dismiss} className="px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted text-sm">
                    Not now
                </button>
                {preview && preview.email_matches && (
                    <button
                        onClick={accept}
                        disabled={busy}
                        className="flex items-center gap-2 px-5 py-2 rounded-xl bg-primary text-primary-foreground text-sm font-bold disabled:opacity-60"
                    >
                        {busy && <Loader2 className="w-4 h-4 animate-spin" />}
                        Accept invitation
                    </button>
                )}
            </div>
        </Shell>
    );
}

function Shell({ children }: { children: React.ReactNode }) {
    return (
        <div className="min-h-screen bg-background flex items-center justify-center p-4">
            <div className="w-full max-w-md rounded-3xl border border-border bg-card p-6 sm:p-7 shadow-xl">{children}</div>
        </div>
    );
}
