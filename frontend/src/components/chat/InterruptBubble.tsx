import React from 'react';
import { Check, X, Upload, ArrowUp } from 'lucide-react';
import type { Interrupt } from '../../types';
import useChatStore from '../../store/chatStore';

interface InterruptBubbleProps {
    chatId: string;
    interrupt: Interrupt;
}

const InterruptBubble: React.FC<InterruptBubbleProps> = ({ chatId, interrupt }) => {
    const resolveInterrupt = useChatStore(state => state.resolveInterrupt);
    const resolveInterruptWithFiles = useChatStore(state => state.resolveInterruptWithFiles);
    const isLoading = useChatStore(state => state.isLoading);
    const [textValue, setTextValue] = React.useState('');
    const [fileName, setFileName] = React.useState('');

    const handleAction = async (action: 'accept' | 'reject') => {
        await resolveInterrupt(chatId, action, interrupt.data);
    };

    const handleTextSubmit = async () => {
        const value = textValue.trim();
        if (!value) return;
        await resolveInterrupt(chatId, 'accept', value);
    };

    const handleFileChange = async (event: React.ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        if (!file) return;
        setFileName(file.name);
        await resolveInterruptWithFiles(chatId, [file]);
    };

    const interruptType = interrupt.interrupt_type || 'accept_decline';
    const label = {
        accept_decline: 'Needs your OK',
        yes_no_confirmation: 'Quick question',
        text_input: 'Missing a detail',
        file_upload: 'Needs a file',
    }[interruptType];

    return (
        <div className="interrupt-bubble-enter mb-8 ml-11 max-w-xl rounded-lg border border-accent/40 bg-accent/[0.06] p-4 sm:p-5" role="group" aria-label={label}>
            <p className="eyebrow !text-accent">{label}</p>
            <h3 className="mt-1.5 text-[15px] font-medium leading-snug text-foreground">
                {interrupt.question || 'Can I go ahead?'}
            </h3>

            {interrupt.data !== undefined && interrupt.data !== null && <InterruptDetails data={interrupt.data} />}

            {interruptType === 'text_input' && (
                <div className="mt-4 flex items-center gap-2">
                    <input
                        value={textValue}
                        onChange={(event) => setTextValue(event.target.value)}
                        onKeyDown={(event) => {
                            if (event.key === 'Enter') handleTextSubmit();
                        }}
                        disabled={isLoading}
                        className="min-w-0 flex-1 rounded-md border border-input bg-card px-3 py-2 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                        placeholder="Type your answer"
                        aria-label="Your answer"
                    />
                    <button
                        onClick={handleTextSubmit}
                        disabled={isLoading || !textValue.trim()}
                        className="flex h-9 w-9 items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                        aria-label="Send answer"
                    >
                        <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
                    </button>
                </div>
            )}

            {interruptType === 'file_upload' && (
                <label className="mt-4 flex cursor-pointer flex-col items-center justify-center rounded-md border border-dashed border-input bg-card px-4 py-5 text-center hover:border-primary">
                    <Upload className="mb-1.5 h-5 w-5 text-muted-foreground" />
                    <span className="text-sm text-foreground">{fileName || 'Choose a file'}</span>
                    <input type="file" className="hidden" disabled={isLoading} onChange={handleFileChange} />
                </label>
            )}

            {(interruptType === 'accept_decline' || interruptType === 'yes_no_confirmation') && (
                <div className="mt-4 flex flex-wrap items-center gap-2">
                    <button
                        onClick={() => handleAction('accept')}
                        disabled={isLoading}
                        className="flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary/90 disabled:opacity-50"
                    >
                        <Check className="w-4 h-4" />
                        {interruptType === 'yes_no_confirmation' ? 'Yes' : 'Go ahead'}
                    </button>
                    <button
                        onClick={() => handleAction('reject')}
                        disabled={isLoading}
                        className="flex items-center gap-1.5 rounded-md border border-border bg-card px-4 py-2 text-sm text-foreground hover:bg-muted disabled:opacity-50"
                    >
                        <X className="w-4 h-4" />
                        {interruptType === 'yes_no_confirmation' ? 'No' : 'Not now'}
                    </button>
                </div>
            )}
        </div>
    );
};

/** Show what the assistant is about to do as a readable list rather than raw JSON when possible. */
function InterruptDetails({ data }: { data: unknown }) {
    const isPlainRecord = (v: unknown): v is Record<string, unknown> =>
        !!v && typeof v === 'object' && !Array.isArray(v);
    const printable = (v: unknown) =>
        v === null || ['string', 'number', 'boolean'].includes(typeof v) ||
        (Array.isArray(v) && v.every((x) => ['string', 'number'].includes(typeof x)));

    if (isPlainRecord(data) && Object.values(data).every(printable)) {
        const entries = Object.entries(data).filter(([, v]) => v !== null && v !== '' && !(Array.isArray(v) && !v.length));
        if (!entries.length) return null;
        return (
            <dl className="mt-3 grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1.5 rounded-md border border-border bg-card px-3.5 py-3 text-sm">
                {entries.map(([k, v]) => (
                    <React.Fragment key={k}>
                        <dt className="text-muted-foreground capitalize">{k.replace(/_/g, ' ')}</dt>
                        <dd className="min-w-0 break-words text-foreground">{Array.isArray(v) ? v.join(', ') : typeof v === 'boolean' ? (v ? 'Yes' : 'No') : String(v)}</dd>
                    </React.Fragment>
                ))}
            </dl>
        );
    }

    if (typeof data === 'string') {
        return <p className="mt-3 text-sm text-muted-foreground whitespace-pre-wrap">{data}</p>;
    }

    return (
        <pre className="mt-3 max-h-60 overflow-auto rounded-md border border-border bg-card p-3 font-mono text-xs text-muted-foreground whitespace-pre-wrap">
            {JSON.stringify(data, null, 2)}
        </pre>
    );
}

export default InterruptBubble;
