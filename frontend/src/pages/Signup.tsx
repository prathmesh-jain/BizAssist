import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Loader2 } from 'lucide-react';
import { useAuth } from '../context/AuthContext';
import { postLoginPath } from '../lib/session';
import AuthLayout, { Field, FormError, GoogleButton, OrDivider } from '../components/auth/AuthLayout';
import { friendlyAuthError } from '../lib/authErrors';

export default function Signup() {
    const navigate = useNavigate();
    const { signUpWithEmail, signInWithGoogle } = useAuth();
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
            title="Set up your workspace"
            subtitle="It takes a couple of minutes. You can invite your team later."
            aside={{
                heading: 'What happens next',
                points: [
                    'A few questions about your business',
                    'BizAssist researches what’s public and shows its sources',
                    'You keep what’s right and correct the rest',
                    'Add your OpenAI key, then start asking',
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
                    attempt(() => signUpWithEmail(email.trim(), password), 'Sign-up failed.');
                }}
            >
                <Field label="Work email" value={email} onChange={(e) => setEmail(e.target.value)} type="email" autoComplete="email" placeholder="you@yourbusiness.com" required />
                <Field label="Password" value={password} onChange={(e) => setPassword(e.target.value)} type="password" autoComplete="new-password" minLength={6} placeholder="At least 6 characters" required />
                <button
                    type="submit"
                    disabled={loading}
                    className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-60"
                >
                    {loading && <Loader2 className="h-4 w-4 animate-spin" />}
                    Create account
                </button>
            </form>
            <p className="mt-8 text-sm text-muted-foreground">
                Already have an account?{' '}
                <Link className="font-medium text-primary underline-offset-4 hover:underline" to="/login">Sign in</Link>
            </p>
        </AuthLayout>
    );
}
