import React from 'react';
import { Send, Hash, Paperclip, X, FileText } from 'lucide-react';

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
    const textareaRef = React.useRef<HTMLTextAreaElement>(null);
    const fileInputRef = React.useRef<HTMLInputElement>(null);

    const canSend = (text.trim().length > 0 || attachments.length > 0) && !isLoading;

    const handleSend = async () => {
        const message = text.trim();
        if ((!message && attachments.length === 0) || isLoading) return;

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
                    setWarning(`Unsupported file type: ${file.name}. Only PDF, images, and TXT files are allowed.`);
                    return false;
                }
                if (file.size > MAX_FILE_SIZE) {
                    setWarning(`File "${file.name}" is too large. Maximum size is 10MB.`);
                    return false;
                }
                return true;
            })
            .map(file => {
                const isImage = ALLOWED_IMAGE_TYPES.includes(file.type);
                const attachment: Attachment = {
                    id: `${Date.now()}-${Math.random().toString(36).substr(2, 9)}`,
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

    return (
        <div className="p-4 bg-background border-t border-border">
            {warning && (
                <div className="max-w-3xl mx-auto mb-3 px-4 py-2 rounded-xl border border-destructive/30 bg-destructive/10 text-destructive text-sm font-semibold">
                    {warning}
                </div>
            )}
            {attachments.length > 0 && (
                <div className="max-w-3xl mx-auto mb-3 flex flex-wrap gap-2">
                    {attachments.map(att => (
                        <div
                            key={att.id}
                            className="relative group flex items-center gap-2 bg-muted rounded-lg px-2 py-1 pr-8"
                        >
                            {att.type === 'image' && att.preview ? (
                                <img
                                    src={att.preview}
                                    alt={att.file.name}
                                    className="w-8 h-8 object-cover rounded"
                                />
                            ) : (
                                <div className="w-8 h-8 bg-primary/10 rounded flex items-center justify-center">
                                    <FileText className="w-5 h-5 text-primary" />
                                </div>
                            )}
                            <span className="text-sm text-foreground max-w-[150px] truncate">
                                {att.file.name}
                            </span>
                            <button
                                type="button"
                                onClick={() => removeAttachment(att.id)}
                                className="absolute right-1 top-1/2 -translate-y-1/2 p-1 rounded-full hover:bg-destructive/20 text-muted-foreground hover:text-destructive"
                            >
                                <X className="w-3 h-3" />
                            </button>
                        </div>
                    ))}
                </div>
            )}

            <div className="max-w-3xl mx-auto relative group">
                <textarea
                    ref={textareaRef}
                    value={text}
                    onChange={(e) => setText(e.target.value)}
                    onKeyDown={handleKeyDown}
                    placeholder="Ask BizAssist anything... (paste images with Ctrl+V)"
                    rows={1}
                    disabled={isLoading}
                    className={`w-full bg-card text-foreground border border-border rounded-2xl py-4 pl-5 pr-24 focus:outline-none focus:ring-2 focus:ring-primary/20 focus:border-primary/50 resize-none transition-all shadow-sm group-hover:shadow-md ${isLoading ? 'opacity-50 cursor-not-allowed' : ''}`}
                    style={{ minHeight: '60px', maxHeight: '200px' }}
                />

                <div className="absolute right-2.5 top-2.5 bottom-2.5 flex items-center gap-1">
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
                        disabled={isLoading}
                        className="p-2.5 rounded-xl text-muted-foreground hover:text-foreground hover:bg-muted transition-all disabled:opacity-50"
                        title="Attach files"
                    >
                        <Paperclip className="w-5 h-5" />
                    </button>
                    <button
                        onClick={handleSend}
                        disabled={!canSend}
                        className={`p-2.5 rounded-xl transition-all active:scale-95 ${canSend
                            ? 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-lg shadow-primary/20'
                            : 'text-muted-foreground bg-muted/50 cursor-not-allowed'
                            }`}
                    >
                        <Send className="w-5 h-5" />
                    </button>
                </div>
            </div>

            <div className="max-w-3xl mx-auto mt-3 flex items-center justify-between text-[11px] text-muted-foreground uppercase font-semibold tracking-tight px-1 opacity-70">
                <div className="flex items-center space-x-4">
                    <span className="flex items-center space-x-1.5">
                        <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                        <span>AI Engine Online</span>
                    </span>
                    <span className="hidden sm:inline-block border-l border-border h-3 ml-1" />
                    <span className="hidden sm:flex items-center space-x-1.5">
                        <Hash className="w-3.5 h-3.5" />
                        <span>Financial Analysis Mode</span>
                    </span>
                </div>
                <span className="hidden xs:block">Shift + Enter for new line • Ctrl+V to paste images</span>
            </div>
        </div>
    );
}
