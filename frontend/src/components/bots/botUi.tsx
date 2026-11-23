import React from 'react';
import { Check, Copy, MessageCircle, Send } from 'lucide-react';
import type { BotPlatform } from '../../lib/botsApi';

export function PlatformBadge({ platform, size = 'md' }: { platform: BotPlatform; size?: 'sm' | 'md' }) {
    const Icon = platform === 'whatsapp' ? MessageCircle : Send;
    const box = size === 'sm' ? 'h-7 w-7' : 'h-10 w-10';
    const icon = size === 'sm' ? 'h-3.5 w-3.5' : 'h-5 w-5';
    const tone = platform === 'whatsapp' ? 'chip-green' : 'chip-blue';
    return (
        <span className={`${tone} inline-flex ${box} shrink-0 items-center justify-center rounded-xl`} aria-hidden="true">
            <Icon className={icon} />
        </span>
    );
}

/** A read-only value with a copy button, for webhook URLs and tokens people paste elsewhere. */
export function CopyField({ label, value, hint }: { label: string; value: string; hint?: string }) {
    const [copied, setCopied] = React.useState(false);
    const copy = async () => {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(true);
            window.setTimeout(() => setCopied(false), 1500);
        } catch {
            /* clipboard blocked: the value is still selectable */
        }
    };
    return (
        <div>
            <p className="text-xs font-medium text-muted-foreground">{label}</p>
            <div className="mt-1 flex items-center gap-2 rounded-xl border border-input bg-background px-3 py-2">
                <code className="min-w-0 flex-1 truncate text-sm text-foreground select-all">{value || '—'}</code>
                <button
                    type="button"
                    onClick={copy}
                    disabled={!value}
                    className="inline-flex shrink-0 items-center gap-1 rounded-lg px-2 py-1 text-xs font-medium text-primary hover:bg-highlight disabled:opacity-50"
                >
                    {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                    {copied ? 'Copied' : 'Copy'}
                </button>
            </div>
            {hint && <p className="mt-1 text-xs text-muted-foreground">{hint}</p>}
        </div>
    );
}

export function Field({ label, hint, children }: { label: string; hint?: React.ReactNode; children: React.ReactNode }) {
    return (
        <label className="block">
            <span className="text-sm font-medium text-foreground">{label}</span>
            <div className="mt-1.5">{children}</div>
            {hint && <span className="mt-1 block text-xs text-muted-foreground leading-relaxed">{hint}</span>}
        </label>
    );
}

export const inputClass =
    'w-full rounded-xl border border-input bg-background px-3 py-2.5 text-sm outline-none focus:border-primary focus:ring-4 focus:ring-primary/10 disabled:opacity-60';

export const primaryButton =
    'inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-60';

export const secondaryButton =
    'inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-card px-4 py-2.5 text-sm font-medium text-foreground hover:bg-muted disabled:opacity-60';

export function Checkbox({ checked, onChange, label, hint }: { checked: boolean; onChange: (v: boolean) => void; label: string; hint?: string }) {
    return (
        <label className="flex cursor-pointer items-start gap-3 rounded-xl border border-border bg-card px-3 py-2.5 hover:bg-muted/50">
            <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} className="mt-0.5 h-4 w-4 accent-[var(--color-primary)]" />
            <span>
                <span className="block text-sm text-foreground">{label}</span>
                {hint && <span className="block text-xs text-muted-foreground">{hint}</span>}
            </span>
        </label>
    );
}
