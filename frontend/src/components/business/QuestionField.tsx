import React from 'react';
import { X } from 'lucide-react';
import type { AnswerValue, OnboardingQuestion } from '../../types';

const inputClass =
    'w-full rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-primary/40';

interface Props {
    question: OnboardingQuestion;
    value: AnswerValue | undefined;
    onChange: (value: AnswerValue | undefined) => void;
    disabled?: boolean;
    /** Extra content under the label, e.g. a provenance badge. */
    adornment?: React.ReactNode;
}

export default function QuestionField({ question, value, onChange, disabled, adornment }: Props) {
    const id = `q-${question.id}`;
    return (
        <div>
            <div className="flex flex-wrap items-center gap-2 mb-1.5">
                <label htmlFor={id} className="text-sm font-semibold text-foreground">
                    {question.label}
                    {question.required && <span className="text-destructive"> *</span>}
                </label>
                {adornment}
            </div>
            <Control id={id} question={question} value={value} onChange={onChange} disabled={disabled} />
            {question.help && <p className="mt-1 text-xs text-muted-foreground">{question.help}</p>}
        </div>
    );
}

function Control({ id, question, value, onChange, disabled }: Omit<Props, 'adornment'> & { id: string }) {
    switch (question.type) {
        case 'textarea':
            return (
                <textarea
                    id={id}
                    rows={3}
                    disabled={disabled}
                    value={typeof value === 'string' ? value : ''}
                    placeholder={question.placeholder}
                    onChange={(e) => onChange(e.target.value || undefined)}
                    className={inputClass}
                />
            );
        case 'number':
            return (
                <input
                    id={id}
                    type="number"
                    min={0}
                    disabled={disabled}
                    value={value === undefined ? '' : String(value)}
                    onChange={(e) => onChange(e.target.value === '' ? undefined : Number(e.target.value))}
                    className={`${inputClass} max-w-40`}
                />
            );
        case 'select':
            return (
                <select
                    id={id}
                    disabled={disabled}
                    value={typeof value === 'string' ? value : ''}
                    onChange={(e) => onChange(e.target.value || undefined)}
                    className={`${inputClass} max-w-md`}
                >
                    <option value="">Choose…</option>
                    {question.options?.map((o) => (
                        <option key={o.value} value={o.value}>{o.label}</option>
                    ))}
                </select>
            );
        case 'multiselect':
            return <MultiSelect id={id} question={question} value={value} onChange={onChange} disabled={disabled} />;
        case 'tags':
            return <Tags id={id} question={question} value={value} onChange={onChange} disabled={disabled} />;
        default:
            return (
                <input
                    id={id}
                    type="text"
                    inputMode={question.type === 'url' ? 'url' : undefined}
                    disabled={disabled}
                    value={typeof value === 'string' ? value : ''}
                    placeholder={question.placeholder}
                    onChange={(e) => onChange(e.target.value || undefined)}
                    className={`${inputClass} max-w-md`}
                />
            );
    }
}

function MultiSelect({ id, question, value, onChange, disabled }: Omit<Props, 'adornment'> & { id: string }) {
    const selected = Array.isArray(value) ? value : [];
    const known = new Set(question.options?.map((o) => o.value));
    const others = selected.filter((v) => !known.has(v));
    const toggle = (v: string) => {
        const next = selected.includes(v) ? selected.filter((s) => s !== v) : [...selected, v];
        onChange(next.length ? next : undefined);
    };
    return (
        <div id={id} role="group" aria-label={question.label}>
            <div className="flex flex-wrap gap-2">
                {question.options?.map((o) => {
                    const on = selected.includes(o.value);
                    return (
                        <button
                            key={o.value}
                            type="button"
                            disabled={disabled}
                            aria-pressed={on}
                            onClick={() => toggle(o.value)}
                            className={`px-3 py-1.5 rounded-full border text-sm transition-colors ${on
                                ? 'bg-primary/15 border-primary/40 text-primary font-semibold'
                                : 'border-border text-muted-foreground hover:text-foreground hover:bg-muted'}`}
                        >
                            {o.label}
                        </button>
                    );
                })}
            </div>
            {question.allow_other && (
                <div className="mt-2">
                    <Tags
                        id={`${id}-other`}
                        question={{ ...question, placeholder: 'Other — type and press Enter' }}
                        value={others}
                        disabled={disabled}
                        onChange={(next) => {
                            const merged = [...selected.filter((v) => known.has(v)), ...((next as string[]) || [])];
                            onChange(merged.length ? merged : undefined);
                        }}
                    />
                </div>
            )}
        </div>
    );
}

function Tags({ id, question, value, onChange, disabled }: Omit<Props, 'adornment'> & { id: string }) {
    const [draft, setDraft] = React.useState('');
    const tags = Array.isArray(value) ? value : [];
    const add = () => {
        const t = draft.trim();
        if (t && !tags.includes(t)) onChange([...tags, t]);
        setDraft('');
    };
    return (
        <div className="flex flex-wrap items-center gap-2 rounded-xl border border-border bg-background px-2 py-2">
            {tags.map((t) => (
                <span key={t} className="flex items-center gap-1 rounded-full bg-muted px-2.5 py-1 text-sm text-foreground">
                    {t}
                    {!disabled && (
                        <button
                            type="button"
                            aria-label={`Remove ${t}`}
                            onClick={() => {
                                const next = tags.filter((x) => x !== t);
                                onChange(next.length ? next : undefined);
                            }}
                            className="text-muted-foreground hover:text-foreground"
                        >
                            <X className="w-3.5 h-3.5" />
                        </button>
                    )}
                </span>
            ))}
            <input
                id={id}
                disabled={disabled}
                value={draft}
                placeholder={question.placeholder || 'Type and press Enter'}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ',') {
                        e.preventDefault();
                        add();
                    } else if (e.key === 'Backspace' && !draft && tags.length) {
                        onChange(tags.slice(0, -1).length ? tags.slice(0, -1) : undefined);
                    }
                }}
                onBlur={add}
                className="flex-1 min-w-32 bg-transparent px-1 py-1 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none"
            />
        </div>
    );
}
