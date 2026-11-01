import React from 'react';
import { ArrowUp, Paperclip, X, FileText } from 'lucide-react';
import { Link } from 'react-router-dom';
import useSettingsStore from '../../store/settingsStore';

interface Attachment {
    id: string;
    file: File;
    preview?: string;
    type: 'image' | 'file';
}

interface ChatInputProps {
    onSend: (message: string, attachments: Attachment[]) => Promise<void>;
    isLoading: boolean;
}

const MAX_FILE_SIZE = 10 * 1024 * 1024; // 10MB
const ALLOWED_IMAGE_TYPES = ['image/jpeg', 'image/png', 'image/gif', 'image/webp'];
const ALLOWED_FILE_TYPES = ['application/pdf', 'text/plain'];
const ALLOWED_ALL_TYPES = new Set([...ALLOWED_IMAGE_TYPES, ...ALLOWED_FILE_TYPES]);

export default function ChatInput({ onSend, isLoading }: ChatInputProps) {
    const [text, setText] = React.useState('');
    const [attachments, setAttachments] = React.useState<Attachment[]>([]);
    const [warning, setWarning] = React.useState<string>('');
    const { aiSettings, isLoaded, fetchAISettings } = useSettingsStore();
    const textareaRef = React.useRef<HTMLTextAreaElement>(null);
    const fileInputRef = React.useRef<HTMLInputElement>(null);

    const chatEnabled = !!aiSettings?.chat_enabled;
    const settingsPending = !isLoaded && !aiSettings;
    const canSend = (text.trim().length > 0 || attachments.length > 0) && !isLoading && chatEnabled;

    React.useEffect(() => {
        if (!aiSettings) {
            fetchAISettings();
        }
    }, [aiSettings, fetchAISettings]);

    const handleSend = async () => {
        const message = text.trim();
        if ((!message && attachments.length === 0) || isLoading || !chatEnabled) return;

        const attsToSend = attachments;

        setText('');
        setAttachments([]);

        try {
            await onSend(message, attsToSend);
        } catch (e) {
            console.error('Failed to send message:', e);
        }

        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
        }
    };

    const handleKeyDown = (e: React.KeyboardEvent) => {
        if (e.key === 'Enter' && !e.shiftKey) {
            e.preventDefault();
            handleSend();
        }
    };

    const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
        const files = Array.from(e.target.files || []);
        addFiles(files);
        if (fileInputRef.current) {
            fileInputRef.current.value = '';
        }
    };

    const addFiles = (files: File[]) => {
        setWarning('');
        const newAttachments: Attachment[] = files
            .filter(file => {
                if (!ALLOWED_ALL_TYPES.has(file.type)) {
                    setWarning(`${file.name} can’t be attached. Use a PDF, an image, or a .txt file.`);
                    return false;
                }
                if (file.size > MAX_FILE_SIZE) {
                    setWarning(`${file.name} is over 10 MB. Try a smaller file.`);
                    return false;
                }
                return true;
            })
            .map(file => {
                const isImage = ALLOWED_IMAGE_TYPES.includes(file.type);
                const attachment: Attachment = {
                    id: `${Date.now()}-${Math.random().toString(36).slice(2, 11)}`,
                    file,
                    type: isImage ? 'image' : 'file',
                };

                // Use object URLs for local previews (not persisted in chat history)
                attachment.preview = URL.createObjectURL(file);

                return attachment;
            });

        setAttachments(prev => [...prev, ...newAttachments]);
    };

    const handlePaste = React.useCallback((e: ClipboardEvent) => {
        const items = e.clipboardData?.items;
        if (!items) return;

        const files: File[] = [];
        for (let i = 0; i < items.length; i++) {
            if (items[i].type.indexOf('image') !== -1) {
                const file = items[i].getAsFile();
                if (file) files.push(file);
            }
        }

        if (files.length > 0) {
            e.preventDefault();
            addFiles(files);
        }
    }, []);

    React.useEffect(() => {
        document.addEventListener('paste', handlePaste);
        return () => document.removeEventListener('paste', handlePaste);
    }, [handlePaste]);

    React.useEffect(() => {
        if (textareaRef.current) {
            textareaRef.current.style.height = 'auto';
            textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`;
        }
    }, [text]);

    const removeAttachment = (id: string) => {
        setAttachments(prev => {
            const att = prev.find(a => a.id === id);
            if (att?.preview) {
                URL.revokeObjectURL(att.preview);
            }
            return prev.filter(a => a.id !== id);
        });
    };

    const disabled = isLoading || (!settingsPending && !chatEnabled);

    return (
        <div className="shrink-0 px-4 sm:px-6 pb-4 pt-2">
            <div className="max-w-3xl mx-auto">
                {!settingsPending && !chatEnabled && (
                    <div className="mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/30 bg-warning/10 px-4 py-2.5 text-sm text-foreground">
                        <span>Chat needs an OpenAI API key before it can answer.</span>
                        <Link to="/app/settings" className="font-medium text-primary underline underline-offset-4">Add it in Settings</Link>
                    </div>
                )}
                {warning && (
                    <div role="alert" className="mb-3 rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-2 text-sm text-destructive">
                        {warning}
                    </div>
                )}

                <div className={`beam-border beam-on-focus shadow-soft rounded-xl bg-card transition-[border-color,box-shadow] duration-200 ${disabled ? 'opacity-70' : ''}`}>
                    {attachments.length > 0 && (
                        <div className="flex flex-wrap gap-2 px-3 pt-3">
                            {attachments.map(att => (
                                <div key={att.id} className="flex items-center gap-2 rounded-md border border-border bg-background py-1 pl-1 pr-1.5">
                                    {att.type === 'image' && att.preview ? (
                                        <img src={att.preview} alt="" className="w-7 h-7 object-cover rounded" />
                                    ) : (
                                        <span className="w-7 h-7 rounded bg-muted flex items-center justify-center">
                                            <FileText className="w-4 h-4 text-muted-foreground" />
                                        </span>
                                    )}
                                    <span className="text-sm text-foreground max-w-40 truncate">{att.file.name}</span>
                                    <button
                                        type="button"
                                        onClick={() => removeAttachment(att.id)}
                                        aria-label={`Remove ${att.file.name}`}
                                        className="p-0.5 rounded text-muted-foreground hover:text-destructive"
                                    >
                                        <X className="w-3.5 h-3.5" />
                                    </button>
                                </div>
                            ))}
                        </div>
                    )}

                    <textarea
                        ref={textareaRef}
                        value={text}
                        onChange={(e) => setText(e.target.value)}
                        onKeyDown={handleKeyDown}
                        placeholder={!settingsPending && !chatEnabled ? 'Add your OpenAI key in Settings to start' : 'Ask about your business, documents, sheets, or calendar…'}
                        rows={1}
                        disabled={disabled}
                        aria-label="Message"
                        className="block w-full resize-none bg-transparent px-4 pt-3.5 pb-1 text-[15px] leading-relaxed text-foreground placeholder:text-muted-foreground/80 focus:outline-none disabled:cursor-not-allowed"
                        style={{ minHeight: '52px', maxHeight: '200px' }}
                    />

                    <div className="flex items-center justify-between px-2 pb-2">
                        <input
                            type="file"
                            ref={fileInputRef}
                            onChange={handleFileSelect}
                            multiple
                            accept={ALLOWED_IMAGE_TYPES.concat(ALLOWED_FILE_TYPES).join(',')}
                            className="hidden"
                        />
                        <button
                            type="button"
                            onClick={() => fileInputRef.current?.click()}
                            disabled={disabled}
                            className="flex items-center gap-1.5 rounded-md px-2 py-1.5 text-sm text-muted-foreground hover:text-foreground hover:bg-muted disabled:opacity-50"
                            title="Attach a PDF, image, or text file (or paste an image)"
                        >
                            <Paperclip className="w-4 h-4" />
                            <span className="hidden sm:inline">Attach</span>
                        </button>
                        <div className="flex items-center gap-3">
                            <span className="hidden md:inline text-xs text-muted-foreground">
                                <kbd className="font-mono">Shift</kbd> + <kbd className="font-mono">Enter</kbd> for a new line
                            </span>
                            <button
                                onClick={handleSend}
                                disabled={!canSend}
                                aria-label="Send message"
                                className={`flex h-8 w-8 items-center justify-center rounded-lg ${canSend
                                    ? 'btn-glow'
                                    : 'bg-muted text-muted-foreground'}`}
                            >
                                <ArrowUp className="w-4 h-4" strokeWidth={2.5} />
                            </button>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    );
}
