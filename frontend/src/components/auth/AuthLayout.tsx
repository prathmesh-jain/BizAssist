import React from 'react';
import { Link } from 'react-router-dom';
import GoogleIcon from '../ui/GoogleIcon';
import Logo from '../ui/Logo';

/** Two-column sign-in/sign-up frame: the form on the left, a quiet note on the right. */
export default function AuthLayout({
    title,
    subtitle,
    aside,
    children,
}: {
    title: string;
    subtitle: string;
    aside: { heading: string; points: string[] };
    children: React.ReactNode;
}) {
    return (
        <div className="min-h-screen bg-background lg:grid lg:grid-cols-[1fr_minmax(0,0.9fr)]">
            <div className="flex min-h-screen flex-col px-5 py-6 sm:px-10">
                <Link to="/" aria-label="BizAssist home" className="w-fit"><Logo /></Link>
                <div className="flex flex-1 items-center">
                    <div className="mx-auto w-full max-w-sm py-10 rise-in">
                        <h1 className="font-display text-3xl font-medium">{title}</h1>
                        <p className="mt-2 text-muted-foreground">{subtitle}</p>
                        <div className="mt-8">{children}</div>
                    </div>
                </div>
                <p className="text-xs text-muted-foreground">
                    By continuing you agree to the{' '}
                    <a className="underline underline-offset-2 hover:text-foreground" href="https://bizassist.prathmeshjain.online/terms-conditions.html">Terms</a>
                    {' '}and{' '}
                    <a className="underline underline-offset-2 hover:text-foreground" href="https://bizassist.prathmeshjain.online/privacy-policy.html">Privacy Policy</a>.
                </p>
            </div>

            <aside className="hidden lg:flex flex-col justify-center border-l border-border bg-sidebar paper-grain px-14">
                <div className="paper-lines max-w-md py-1">
                    <p className="eyebrow leading-8">{aside.heading}</p>
                    <ul className="text-[17px] leading-8 text-foreground">
                        {aside.points.map((p) => (
                            <li key={p} className="flex gap-3">
                                <span className="text-accent">—</span>
                                <span>{p}</span>
                            </li>
                        ))}
                    </ul>
                </div>
            </aside>
        </div>
    );
}

export function GoogleButton({ onClick, disabled }: { onClick: () => void; disabled: boolean }) {
    return (
        <button
            type="button"
            onClick={onClick}
            disabled={disabled}
            className="flex w-full items-center justify-center gap-2.5 rounded-md border border-input bg-card px-4 py-2.5 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-60"
        >
            <GoogleIcon />
            Continue with Google
        </button>
    );
}

export function OrDivider() {
    return (
        <div className="my-6 flex items-center gap-3">
            <div className="h-px flex-1 bg-border" />
            <span className="text-xs text-muted-foreground">or with email</span>
            <div className="h-px flex-1 bg-border" />
        </div>
    );
}

export function Field({ label, ...props }: { label: string } & React.InputHTMLAttributes<HTMLInputElement>) {
    const id = React.useId();
    return (
        <div>
            <label htmlFor={id} className="block text-sm font-medium text-foreground">{label}</label>
            <input
                id={id}
                {...props}
                className="mt-1.5 w-full rounded-md border border-input bg-card px-3 py-2.5 text-foreground outline-none transition-colors placeholder:text-muted-foreground/70 focus:border-primary focus:ring-2 focus:ring-primary/15"
            />
        </div>
    );
}

export function FormError({ message }: { message: string | null }) {
    if (!message) return null;
    return (
        <div role="alert" className="mb-5 rounded-md border border-destructive/30 bg-destructive/10 px-3.5 py-2.5 text-sm text-destructive">
            {message}
        </div>
    );
}
