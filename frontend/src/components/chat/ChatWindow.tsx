import React from 'react';
import type { Message, ToolStatus } from '../../types';
import MessageBubble from './MessageBubble';
import useChatStore from '../../store/chatStore';
import { CheckCircle2, Loader2, XCircle, FileSpreadsheet, Search, FileText, Brain } from 'lucide-react';

interface ChatWindowProps {
    messages: Message[];
    streamingMessage: string;
    activeTools: { name: string; status: ToolStatus }[];
    isLoading: boolean;
}

const SUGGESTIONS = [
    'Analyze recent invoice',
    'Check monthly expenses',
    'List what documents are uploaded',
    'From documents analyze the expense trends',
];

/** Pretty display name + icon for known tool names */
function resolveToolDisplay(rawName: string): { label: string; icon: React.ReactNode; verb: string } {
    const n = rawName.toLowerCase();

    if (n.includes('sheet') || n.includes('spreadsheet') || n.includes('google')) {
        if (n.includes('add') || n.includes('write') || n.includes('update') || n.includes('row'))
            return { label: 'Google Sheets', icon: <FileSpreadsheet className="w-3.5 h-3.5" />, verb: 'Editing spreadsheet…' };
        if (n.includes('read') || n.includes('get') || n.includes('values') || n.includes('range'))
            return { label: 'Google Sheets', icon: <FileSpreadsheet className="w-3.5 h-3.5" />, verb: 'Reading spreadsheet…' };
        return { label: 'Google Sheets', icon: <FileSpreadsheet className="w-3.5 h-3.5" />, verb: 'Accessing spreadsheet…' };
    }
    if (n.includes('search') || n.includes('web'))
        return { label: 'Web Search', icon: <Search className="w-3.5 h-3.5" />, verb: 'Searching the web…' };
    if (n.includes('retriev') || n.includes('rag') || n.includes('document') || n.includes('chunk'))
        return { label: 'Knowledge Base', icon: <FileText className="w-3.5 h-3.5" />, verb: 'Searching documents…' };
    if (n.includes('analys') || n.includes('invoice'))
        return { label: 'Analysing data', icon: <Brain className="w-3.5 h-3.5" />, verb: 'Analysing data…' };

    // Fallback: humanize the raw name
    const label = rawName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    return { label, icon: <Brain className="w-3.5 h-3.5" />, verb: `Using ${label}…` };
}

/** Single tool pill shown in the activity bar */
function ToolPill({ tool }: { tool: { name: string; status: ToolStatus } }) {
    const { label, icon, verb } = resolveToolDisplay(tool.name);

    const stateClasses = {
        started: 'bg-primary/10 border-primary/30 text-primary',
        completed: 'bg-green-500/10 border-green-500/30 text-green-600 dark:text-green-400',
        failed: 'bg-destructive/10 border-destructive/30 text-destructive',
    }[tool.status];

    return (
        <div className={`inline-flex items-center gap-2 px-3 py-1.5 rounded-full border text-[12px] font-semibold transition-all ${stateClasses}`}>
            {tool.status === 'started' && (
                <Loader2 className="w-3.5 h-3.5 animate-spin shrink-0" />
            )}
            {tool.status === 'completed' && (
                <CheckCircle2 className="w-3.5 h-3.5 shrink-0" />
            )}
            {tool.status === 'failed' && (
                <XCircle className="w-3.5 h-3.5 shrink-0" />
            )}
            <span className="flex items-center gap-1.5">
                {icon}
                {tool.status === 'started' ? verb : label}
            </span>
        </div>
    );
}

/** The thinking / tool activity bar shown below the thinking indicator */
function AgentActivityBar({ activeTools }: { activeTools: { name: string; status: ToolStatus }[] }) {
    const hasActive = activeTools.some(t => t.status === 'started');

    return (
        <div className="flex flex-col items-start gap-2.5 mt-3">
            {/* Thinking bubble */}
            <div className="flex items-center gap-3 bg-card border border-border rounded-2xl px-4 py-2.5 shadow-sm">
                <div className="flex gap-1.5">
                    <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '0ms' }} />
                    <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '150ms' }} />
                    <span className="w-2 h-2 bg-primary rounded-full animate-bounce" style={{ animationDelay: '300ms' }} />
                </div>
                <span className="text-sm font-semibold text-foreground">
                    {hasActive ? 'Working on it…' : 'BizAssist is thinking'}
                </span>
            </div>

            {/* Tool pills */}
            {activeTools.length > 0 && (
                <div className="flex flex-wrap gap-2 pl-1 animate-fadeIn">
                    {activeTools.map((tool, idx) => (
                        <ToolPill key={`${tool.name}-${idx}`} tool={tool} />
                    ))}
                </div>
            )}
        </div>
    );
}

export default function ChatWindow({ messages, streamingMessage, activeTools, isLoading }: ChatWindowProps) {
    const scrollRef = React.useRef<HTMLDivElement>(null);
    const { hasMoreMessages, isLoadingMore, loadMoreMessages, sendMessage } = useChatStore();
    const isAutoScrollEnabled = React.useRef(true);
    const prevMessageCount = React.useRef(messages.length);

    React.useEffect(() => {
        const isNewMessage = messages.length > prevMessageCount.current;
        prevMessageCount.current = messages.length;

        if (scrollRef.current && (isNewMessage || streamingMessage) && isAutoScrollEnabled.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [messages, streamingMessage]);

    const handleScroll = React.useCallback(() => {
        if (!scrollRef.current) return;
        const { scrollTop, scrollHeight, clientHeight } = scrollRef.current;

        isAutoScrollEnabled.current = scrollHeight - scrollTop - clientHeight < 120;

        if (scrollTop < 100 && !isLoadingMore && hasMoreMessages) {
            loadMoreMessages();
        }
    }, [isLoadingMore, hasMoreMessages, loadMoreMessages]);

    const handleSuggestion = React.useCallback((text: string) => {
        if (!isLoading) sendMessage(text);
    }, [isLoading, sendMessage]);

    if (messages.length === 0 && !streamingMessage && !isLoading) {
        return (
            <div className="flex-1 flex flex-col items-center justify-center p-4 text-center bg-background">
                <div className="w-16 h-16 bg-primary/10 rounded-3xl flex items-center justify-center mb-8 border border-primary/20 shadow-inner">
                    <div className="w-10 h-10 bg-primary rounded-2xl animate-pulse shadow-lg shadow-primary/40 flex items-center justify-center text-primary-foreground font-bold text-xl">B</div>
                </div>
                <h2 className="text-2xl font-bold text-foreground mb-3 tracking-tight">How can I help today?</h2>
                <p className="text-muted-foreground max-w-sm text-sm leading-relaxed">
                    Analyze invoices, review financial documents, or get strategic business insights in seconds.
                </p>
                <div className="mt-12 grid grid-cols-1 sm:grid-cols-2 gap-3 w-full max-w-lg">
                    {SUGGESTIONS.map(s => (
                        <button
                            key={s}
                            onClick={() => handleSuggestion(s)}
                            className="p-3 text-sm font-medium text-muted-foreground bg-card border border-border rounded-xl hover:border-primary/50 hover:bg-primary/5 hover:text-foreground transition-all text-left cursor-pointer active:scale-[0.98]"
                        >
                            {s}
                        </button>
                    ))}
                </div>
            </div>
        );
    }

    return (
        <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto p-4 bg-background scroll-smooth"
        >
            <div className="max-w-3xl mx-auto w-full pb-10 space-y-1">
                {/* Load-more indicator */}
                {isLoadingMore && (
                    <div className="flex justify-center py-4">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            <span>Loading older messages…</span>
                        </div>
                    </div>
                )}

                {messages.map(msg => (
                    <MessageBubble key={msg.id} message={msg} />
                ))}

                {/* Streaming response */}
                {streamingMessage && (
                    <MessageBubble
                        message={{
                            id: 'streaming',
                            role: 'assistant',
                            content: streamingMessage,
                            tool_calls: activeTools,
                            created_at: new Date().toISOString()
                        }}
                        isStreaming
                    />
                )}

                {/* Agent activity bar — shown when loading but no tokens yet */}
                {isLoading && !streamingMessage && (
                    <div className="flex items-start gap-3 ml-1 py-2">
                        {/* AI avatar */}
                        <div className="shrink-0 w-9 h-9 rounded-xl flex items-center justify-center border bg-primary/10 text-primary border-primary/20">
                            <svg viewBox="0 0 24 24" className="w-5 h-5 fill-current"><path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 0 2h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1 0-2h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2zm0 7a5 5 0 0 0-5 5v3h10v-3a5 5 0 0 0-5-5zM9 16a1 1 0 1 1 0-2 1 1 0 0 1 0 2zm6 0a1 1 0 1 1 0-2 1 1 0 0 1 0 2z" /></svg>
                        </div>
                        <AgentActivityBar activeTools={activeTools} />
                    </div>
                )}
            </div>
        </div>
    );
}
