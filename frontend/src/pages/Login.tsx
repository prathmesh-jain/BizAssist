import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { postLoginPath } from '../lib/session';
import AuthLayout, { Field, FormError, GoogleButton, OrDivider } from '../components/auth/AuthLayout';
import { friendlyAuthError } from '../lib/authErrors';

export default function Login() {
    const navigate = useNavigate();
    const { signInWithEmail, signInWithGoogle } = useAuth();
    const [email, setEmail] = React.useState('');
    const [password, setPassword] = React.useState('');
    const [error, setError] = React.useState<string | null>(null);
    const [loading, setLoading] = React.useState(false);

    const attempt = async (action: () => Promise<void>, fallback: string) => {
        setError(null);
        setLoading(true);
        try {
            await action();
            navigate(postLoginPath(), { replace: true });
        } catch (err: unknown) {
            setError(friendlyAuthError(err, fallback));
        } finally {
            setLoading(false);
        }
    };

    return (
        <AuthLayout
            title="Welcome back"
            subtitle="Sign in to pick up where you left off."
            aside={{
                heading: 'Things to ask it on a Monday',
                points: [
                    'What’s on my calendar this week?',
                    'How much did we spend on ads last month?',
                    'What does the Sharma contract say about late fees?',
                    'Find an hour on Friday for the team review.',
                ],
            }}
        >
            <FormError message={error} />
            <GoogleButton onClick={() => attempt(signInWithGoogle, 'Google sign-in failed.')} disabled={loading} />
            <OrDivider />
            <form
                className="space-y-4"
                onSubmit={(e) => {
                    e.preventDefault();
                    attempt(() => signInWithEmail(email.trim(), password), 'Sign-in failed.');
                }}
            >
                <Field label="Email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="email" required />
                <Field label="Password" value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="current-password" required />
                <button
                    type="submit"
                    disabled={loading}
                    className="btn-glow flex w-full items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-semibold disabled:opacity-60"
                >
                    {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                    Sign in
                </button>
            </form>
            <p className="mt-8 text-sm text-muted-foreground">
                New here?{' '}
                <Link className="font-medium text-primary underline-offset-4 hover:underline" to="/signup">Create an account</Link>
            </p>
        </AuthLayout>
    );
}
