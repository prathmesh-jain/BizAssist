import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import useThemeStore from '../store/themeStore';
import { useAuth } from '../context/AuthContext';

export default function Signup() {
    useThemeStore();
    const navigate = useNavigate();
    const { signUpWithEmail, signInWithGoogle } = useAuth();
    const [email, setEmail] = React.useState('');
    const [password, setPassword] = React.useState('');
    const [error, setError] = React.useState<string | null>(null);
    const [loading, setLoading] = React.useState(false);

    const handleEmailSignup = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setLoading(true);
        try {
            await signUpWithEmail(email.trim(), password);
            navigate('/app', { replace: true });
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Signup failed');
        } finally {
            setLoading(false);
        }
    };

    const handleGoogleSignup = async () => {
        setError(null);
        setLoading(true);
        try {
            await signInWithGoogle();
            navigate('/app', { replace: true });
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Google sign-in failed');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="flex min-h-screen items-center justify-center bg-background py-6 px-4 sm:px-6 lg:px-8 transition-colors duration-300">
            <div className="absolute inset-0 bg-grid-slate-200/[0.05] mask-[linear-gradient(to_bottom,white,transparent)] pointer-events-none" />
            <div className="z-10 w-full max-w-md rounded-3xl border border-border bg-card p-6 shadow-xl">
                <div className="text-center mb-6">
                    <h2 className="text-2xl font-bold text-foreground tracking-tight">Create Account</h2>
                    <p className="mt-1 text-muted-foreground">Start your business automation journey</p>
                </div>
                {error && (
                    <div className="mb-4 rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                        {error}
                    </div>
                )}

                <button
                    type="button"
                    onClick={handleGoogleSignup}
                    disabled={loading}
                    className="w-full rounded-xl border border-border bg-muted/40 px-4 py-3 text-sm font-semibold text-foreground hover:bg-muted transition-all disabled:opacity-60 flex items-center justify-center gap-2"
                >
                    <img src="https://img.icons8.com/color/48/000000/google-logo.png" alt="Google" className="w-6 h-6 mr-2" />
                    Continue with Google
                </button>

                <div className="mt-6 flex items-center gap-3">
                    <div className="h-px flex-1 bg-border/60" />
                    <span className="text-xs font-bold uppercase tracking-widest text-muted-foreground">or</span>
                    <div className="h-px flex-1 bg-border/60" />
                </div>

                <form className="mt-6 space-y-4" onSubmit={handleEmailSignup}>
                    <div>
                        <label className="block text-xs font-semibold uppercase tracking-tight text-muted-foreground">Email</label>
                        <input
                            value={email}
                            onChange={(e) => setEmail(e.target.value)}
                            type="email"
                            autoComplete="email"
                            required
                            className="mt-1 w-full rounded-xl border border-border bg-muted/20 px-3 py-3 text-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                        />
                    </div>
                    <div>
                        <label className="block text-xs font-semibold uppercase tracking-tight text-muted-foreground">Password</label>
                        <input
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            type="password"
                            autoComplete="new-password"
                            required
                            className="mt-1 w-full rounded-xl border border-border bg-muted/20 px-3 py-3 text-foreground focus:border-primary focus:ring-2 focus:ring-primary/20 outline-none transition-all"
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={loading}
                        className="w-full rounded-xl bg-primary px-4 py-3 text-sm font-bold text-primary-foreground shadow-lg shadow-primary/20 hover:bg-primary/90 transition-all disabled:opacity-60"
                    >
                        Create account
                    </button>
                </form>

                <p className="mt-6 text-center text-sm text-muted-foreground">
                    Already have an account?{' '}
                    <Link className="font-semibold text-primary hover:underline" to="/login">
                        Sign in
                    </Link>
                </p>
            </div>
        </div>
    );
}
