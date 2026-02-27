import { Terminal, User as UserIcon, Bot } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Message } from '../../types';

interface MessageBubbleProps {
    message: Message;
    isStreaming?: boolean;
}

export default function MessageBubble({ message, isStreaming = false }: MessageBubbleProps) {
    const isAi = message.role === 'assistant';

    const attachments = message.attachments ?? [];

    const sources = (message.tool_calls || [])
        .filter((t: any) => Boolean(t?.citations?.length))
        .map((t: any) => ({
            name: String(t?.name ?? ''),
            citations: Array.isArray(t?.citations) ? t.citations.map(String) : [],
        }))
        .filter(s => s.name || (s.citations && s.citations.length > 0));

    const resolveUrl = (a: any) => {
        return a.local_url || a.url || '';
    };

    return (
        <div className={`flex w-full mb-8 ${isAi ? 'justify-start' : 'justify-end'}`}>
            <div className={`flex max-w-[90%] md:max-w-[80%] ${isAi ? 'flex-row' : 'flex-row-reverse items-end'}`}>
                {/* Avatar */}
                <div className={`shrink-0 w-9 h-9 rounded-xl flex items-center justify-center shadow-sm border
          ${isAi ? 'bg-primary/10 text-primary border-primary/20 mr-3' : 'bg-primary text-primary-foreground border-primary/20 ml-3'}`}>
                    {isAi ? <Bot className="w-5.5 h-5.5" /> : <UserIcon className="w-5.5 h-5.5" />}
                </div>

                {/* Content */}
                <div className={`flex flex-col space-y-2 ${isAi ? 'items-start' : 'items-end'}`}>
                    {/* Attachments */}
                    {attachments.length > 0 && (
                        <div className={`flex flex-col gap-2 ${isAi ? 'items-start' : 'items-end'}`}>
                            {attachments.map((a) => {
                                const url = resolveUrl(a);
                                const ct = (a.content_type || '').toLowerCase();
                                const isImage = ct.startsWith('image/');
                                const isPdf = ct === 'application/pdf' || (a.filename || '').toLowerCase().endsWith('.pdf');

                                if (isImage && url) {
                                    return (
                                        <div key={a.id} className="max-w-[320px]">
                                            <img
                                                src={url}
                                                alt={a.filename}
                                                className="rounded-xl border border-border shadow-sm max-h-[260px] object-contain bg-card"
                                            />
                                            <div className="mt-1 text-[11px] text-muted-foreground font-medium truncate max-w-[320px]">
                                                {a.filename}
                                            </div>
                                        </div>
                                    );
                                }

                                if (isPdf && url) {
                                    return (
                                        <div key={a.id} className="px-4 py-3 rounded-xl border border-border bg-muted/30 max-w-[360px]">
                                            <div className="text-sm font-semibold text-foreground truncate">{a.filename}</div>
                                        </div>
                                    );
                                }

                                return (
                                    <div key={a.id} className="px-4 py-3 rounded-xl border border-border bg-muted/30 max-w-[360px]">
                                        <div className="text-sm font-semibold text-foreground truncate">{a.filename}</div>
                                    </div>
                                );
                            })}
                        </div>
                    )}

                    {message.content && <div className={`px-5 py-3.5 rounded-2xl text-[15px] leading-relaxed shadow-sm border transition-colors
            ${isAi
                            ? 'bg-card text-foreground border-border rounded-tl-none'
                            : 'bg-primary text-primary-foreground border-primary/20 rounded-br-none'}`}>
                        {isAi ? (
                            <div className="prose prose-sm dark:prose-invert max-w-none
                                prose-headings:text-foreground prose-headings:font-bold prose-headings:mb-2 prose-headings:mt-4
                                prose-p:my-1.5 prose-p:leading-relaxed
                                prose-ul:my-2 prose-ul:pl-4 prose-ol:my-2 prose-ol:pl-4
                                prose-li:my-0.5
                                prose-strong:text-foreground prose-strong:font-bold
                                prose-code:bg-muted prose-code:text-primary prose-code:px-1.5 prose-code:py-0.5 prose-code:rounded-md prose-code:text-sm prose-code:font-mono
                                prose-pre:bg-muted prose-pre:border prose-pre:border-border prose-pre:rounded-xl prose-pre:my-3
                                prose-a:text-primary prose-a:underline prose-a:underline-offset-2
                                prose-blockquote:border-l-primary prose-blockquote:text-muted-foreground
                                prose-table:border prose-table:border-border
                                prose-th:bg-muted/50 prose-th:px-3 prose-th:py-2 prose-th:text-left prose-th:font-bold prose-th:text-foreground
                                prose-td:px-3 prose-td:py-2 prose-td:border-t prose-td:border-border
                            ">
                                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                                    {message.content}
                                </ReactMarkdown>
                            </div>
                        ) : (
                            <div className="whitespace-pre-wrap font-medium">{message.content}</div>
                        )}
                        {isStreaming && (
                            <span className="inline-block w-2 h-5 ml-1 bg-primary animate-pulse align-middle" />
                        )}
                    </div>}

                    {/* Tool Calls */}
                    {message.tool_calls && message.tool_calls.length > 0 && (
                        <div className={`flex flex-wrap gap-2 pt-1 ${isAi ? 'justify-start' : 'justify-end'}`}>
                            {message.tool_calls.map((tool, idx) => (
                                <div
                                    key={idx}
                                    className="flex items-center space-x-2 px-3 py-1.5 bg-muted/50 border border-border rounded-lg text-[11px] uppercase font-bold tracking-tight text-muted-foreground hover:bg-muted transition-colors"
                                >
                                    <Terminal className={`w-3.5 h-3.5 ${tool.status === 'started' ? 'text-primary animate-pulse' : 'text-primary'}`} />
                                    <span>{tool.name}</span>
                                    <div className={`w-1.5 h-1.5 rounded-full ${tool.status === 'started' ? 'bg-primary animate-pulse' : 'bg-primary'}`} />
                                </div>
                            ))}
                        </div>
                    )}

                    {/* Sources (retrieval transparency) */}
                    {isAi && sources.length > 0 && (
                        <div className="text-[11px] text-muted-foreground pt-1 max-w-[560px]">
                            <span className="font-semibold">Sources:</span>{' '}
                            {sources.map((s, idx) => (
                                <span key={`${s.name}-${idx}`}>
                                    {idx > 0 ? ' • ' : ''}
                                    {(s.name || 'SOURCE')}
                                    {s.citations && s.citations.length > 0 ? ` (${s.citations.slice(0, 3).join(', ')}${s.citations.length > 3 ? ', …' : ''})` : ''}
                                </span>
                            ))}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
