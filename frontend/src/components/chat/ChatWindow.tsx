import React from 'react';
import type { Message, ToolStatus } from '../../types';
import MessageBubble from './MessageBubble';
import InterruptBubble from './InterruptBubble';
import CalendarChangeCard from './CalendarChangeCard';
import useChatStore from '../../store/chatStore';
import { ArrowUpRight, CalendarDays, FileSpreadsheet, FileText, Loader2, TrendingUp } from 'lucide-react';
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
    { text: 'What’s on my calendar this week?', hint: 'Calendar', icon: CalendarDays, chip: 'chip-blue' },
    { text: 'Which documents have I uploaded, and what’s in them?', hint: 'Documents', icon: FileText, chip: 'chip-violet' },
    { text: 'Who are our closest competitors, and what do they do better?', hint: 'Business', icon: TrendingUp, chip: 'chip-amber' },
    { text: 'Summarise last month’s biggest expenses from my sheet', hint: 'Sheets', icon: FileSpreadsheet, chip: 'chip-green' },
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
            <LogoMark className="w-7 h-7 shrink-0" />
            <div className="min-w-0 flex-1 pt-1 space-y-2.5">
                <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <span className="typing-dots text-primary" aria-hidden="true"><span /><span /><span /></span>
                    {hasActive ? 'Working on it' : 'Thinking'}
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
    const { hasMoreMessages, isLoadingMore, loadMoreMessages, sendMessage, agentStatus, calendarChanges } = useChatStore();
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
            <div className="relative isolate flex-1 overflow-y-auto">
                                <div className="mx-auto flex min-h-full w-full max-w-3xl flex-col justify-center px-5 py-12">
                    <span className="rise-in eyebrow inline-flex w-fit items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1">
                        <span className="h-1.5 w-1.5 rounded-full bg-success" />
                        {me?.organization.name ?? 'BizAssist'}
                    </span>
                    <h1 className="rise-in font-display mt-5 text-3xl sm:text-[2.75rem] leading-[1.1] font-semibold text-foreground" style={{ animationDelay: '60ms' }}>
                        {greeting()}{firstName ? `, ${firstName}` : ''}.
                        <span className="block text-muted-foreground">What can I take off your plate?</span>
                    </h1>
                    <div className="mt-10 grid gap-3 sm:grid-cols-2">
                        {SUGGESTIONS.map((s, i) => (
                            <SpotlightCard
                                key={s.text}
                                className="rise-in shadow-soft rounded-2xl border border-border/70 bg-card hover:-translate-y-px"
                                style={{ animationDelay: `${120 + i * 50}ms` }}
                            >
                                <button onClick={() => handleSuggestion(s.text)} className="group flex h-full w-full items-start gap-3 p-4 text-left">
                                    <span className={`${s.chip} flex h-9 w-9 shrink-0 items-center justify-center rounded-xl transition-transform duration-200 group-hover:scale-105`}>
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

                {calendarChanges.map((change, index) => (
                    <CalendarChangeCard key={`${change.title}-${index}`} change={change} />
                ))}

                {isLoading && !streamingMessage && (
                    <AgentActivity activeTools={activeTools} agentStatus={agentStatus} />
                )}
            </div>
        </div>
    );
}
