import React from 'react';
import type { Message, ToolStatus } from '../../types';
import MessageBubble from './MessageBubble';
import InterruptBubble from './InterruptBubble';
import useChatStore from '../../store/chatStore';
import { ArrowUpRight, CalendarDays, FileSpreadsheet, FileText, Loader2, TrendingUp } from 'lucide-react';
import Aurora from '../fx/Aurora';
import SpotlightCard from '../fx/SpotlightCard';
import ToolLine from './ToolLine';
import { useAuth } from '../../context/AuthContext';
import useOrgStore from '../../store/orgStore';
import { LogoMark } from '../ui/Logo';

interface ChatWindowProps {
    messages: Message[];
    streamingMessage: string;
    activeTools: { name: string; status: ToolStatus }[];
    isLoading: boolean;
}

const SUGGESTIONS = [
    { text: 'What’s on my calendar this week?', hint: 'Calendar', icon: CalendarDays, tint: 'from-violet-500 to-indigo-500' },
    { text: 'Which documents have I uploaded, and what’s in them?', hint: 'Documents', icon: FileText, tint: 'from-orange-400 to-rose-500' },
    { text: 'Who are our closest competitors, and what do they do better?', hint: 'Business', icon: TrendingUp, tint: 'from-cyan-400 to-blue-500' },
    { text: 'Summarise last month’s biggest expenses from my sheet', hint: 'Sheets', icon: FileSpreadsheet, tint: 'from-lime-400 to-emerald-500' },
];

function greeting(): string {
    const h = new Date().getHours();
    if (h < 5) return 'Working late';
    if (h < 12) return 'Good morning';
    if (h < 17) return 'Good afternoon';
    return 'Good evening';
}

/** Shown while the assistant works and no words have streamed yet. */
function AgentActivity({
    activeTools,
    agentStatus,
}: {
    activeTools: { name: string; status: ToolStatus }[];
    agentStatus: { message: string; steps?: string[] } | null;
}) {
    const hasActive = activeTools.some(t => t.status === 'started');

    return (
        <div className="flex gap-4 py-2 rise-in" aria-live="polite">
            <span className="relative h-7 w-7 shrink-0">
                <span className="absolute -inset-1.5 animate-ping rounded-full bg-primary/25 [animation-duration:1.8s]" />
                <LogoMark className="relative w-7 h-7" />
            </span>
            <div className="min-w-0 flex-1 pt-1 space-y-2.5">
                <div className="inline-flex items-center gap-2 rounded-full bg-primary/10 px-3 py-1 text-sm font-medium text-primary">
                    <span className="typing-dots" aria-hidden="true"><span /><span /><span /></span>
                    <span className="text-gradient">{hasActive ? 'Working on it' : 'Thinking'}</span>
                </div>

                {agentStatus && (
                    <div className="rounded-xl border border-border bg-card px-3.5 py-2.5 text-sm">
                        <p className="text-foreground">{agentStatus.message}</p>
                        {agentStatus.steps && agentStatus.steps.length > 0 && (
                            <ol className="mt-1.5 space-y-0.5 text-[13px] text-muted-foreground list-decimal pl-4">
                                {agentStatus.steps.slice(0, 4).map((step) => <li key={step}>{step}</li>)}
                            </ol>
                        )}
                    </div>
                )}

                {activeTools.length > 0 && (
                    <div className="space-y-1">
                        {activeTools.map((tool, idx) => (
                            <ToolLine key={`${tool.name}-${idx}`} tool={tool} />
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}

export default function ChatWindow({ messages, streamingMessage, activeTools, isLoading }: ChatWindowProps) {
    const scrollRef = React.useRef<HTMLDivElement>(null);
    const { hasMoreMessages, isLoadingMore, loadMoreMessages, sendMessage, agentStatus } = useChatStore();
    const { user } = useAuth();
    const { me } = useOrgStore();
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
        const firstName = (user?.displayName || me?.user.full_name || '').trim().split(/\s+/)[0];
        return (
            <div className="relative isolate flex-1 overflow-y-auto bg-background">
                <Aurora intensity={0.7} />
                <div className="dot-grid absolute inset-0 -z-10" aria-hidden="true" />
                <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-5 py-12">
                    <span className="rise-in eyebrow inline-flex w-fit items-center gap-2 rounded-full border border-border bg-card/70 px-3 py-1 backdrop-blur">
                        <span className="h-1.5 w-1.5 rounded-full bg-highlight shadow-[0_0_8px_hsl(var(--highlight))]" />
                        {me?.organization.name ?? 'BizAssist'}
                    </span>
                    <h1 className="rise-in font-display mt-5 text-4xl sm:text-6xl leading-[1.02] font-bold text-foreground" style={{ animationDelay: '80ms' }}>
                        {greeting()}{firstName ? `, ${firstName}` : ''}.
                        <span className="block text-gradient pb-1">What can I take off your plate?</span>
                    </h1>
                    <div className="mt-10 grid gap-3 sm:grid-cols-2">
                        {SUGGESTIONS.map((s, i) => (
                            <SpotlightCard
                                key={s.text}
                                className="rise-in rounded-2xl border border-border bg-card/80 backdrop-blur transition-transform duration-300 hover:-translate-y-0.5"
                                style={{ animationDelay: `${160 + i * 70}ms` }}
                            >
                                <button onClick={() => handleSuggestion(s.text)} className="group flex h-full w-full items-start gap-3 p-4 text-left">
                                    <span className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-gradient-to-br ${s.tint} text-white shadow-md transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-6`}>
                                        <s.icon className="h-4 w-4" />
                                    </span>
                                    <span className="min-w-0 flex-1">
                                        <span className="eyebrow block !text-[10px]">{s.hint}</span>
                                        <span className="mt-0.5 block text-[15px] leading-snug text-foreground">{s.text}</span>
                                    </span>
                                    <ArrowUpRight className="h-4 w-4 shrink-0 text-muted-foreground transition-all group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
                                </button>
                            </SpotlightCard>
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div
            ref={scrollRef}
            onScroll={handleScroll}
            className="flex-1 overflow-y-auto px-4 sm:px-6 bg-background"
        >
            <div className="max-w-3xl mx-auto w-full pt-8 pb-12">
                {/* Load-more indicator */}
                {isLoadingMore && (
                    <div className="flex justify-center py-4">
                        <div className="flex items-center gap-2 text-sm text-muted-foreground">
                            <Loader2 className="w-4 h-4 animate-spin" />
                            <span>Loading earlier messages…</span>
                        </div>
                    </div>
                )}

                {messages.map(item => (
                    item.interrupt ? (
                        <InterruptBubble
                            key={item.id}
                            chatId={useChatStore.getState().activeChatId!}
                            interrupt={item.interrupt!}
                        />
                    ) : (
                        <MessageBubble key={item.id} message={item} />
                    )
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
                    />
                )}

                {isLoading && !streamingMessage && (
                    <AgentActivity activeTools={activeTools} agentStatus={agentStatus} />
                )}
            </div>
        </div>
    );
}
