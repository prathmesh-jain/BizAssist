import React from 'react';
import type { Message, ToolStatus } from '../../types';
import MessageBubble from './MessageBubble';
import InterruptBubble from './InterruptBubble';
import useChatStore from '../../store/chatStore';
import { ArrowUpRight, Loader2 } from 'lucide-react';
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
    { text: 'What’s on my calendar this week?', hint: 'Calendar' },
    { text: 'Which documents have I uploaded, and what’s in them?', hint: 'Documents' },
    { text: 'Who are our closest competitors, and what do they do better?', hint: 'Business profile' },
    { text: 'Read last month’s expenses from my sheet and summarise the big items', hint: 'Sheets' },
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
                    <div className="border-l-2 border-accent/60 pl-3 text-sm">
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
            <div className="flex-1 overflow-y-auto bg-background">
                <div className="mx-auto flex min-h-full w-full max-w-2xl flex-col justify-center px-5 py-12 rise-in">
                    <p className="eyebrow">{me?.organization.name ?? 'BizAssist'}</p>
                    <h1 className="font-display mt-3 text-4xl sm:text-[2.75rem] leading-tight font-medium text-foreground">
                        {greeting()}{firstName ? `, ${firstName}` : ''}.
                        <span className="block text-muted-foreground">What can I take off your plate?</span>
                    </h1>
                    <ul className="mt-10 border-t border-border">
                        {SUGGESTIONS.map(s => (
                            <li key={s.text} className="border-b border-border">
                                <button
                                    onClick={() => handleSuggestion(s.text)}
                                    className="group flex w-full items-center gap-4 py-3.5 text-left"
                                >
                                    <span className="flex-1 text-[15px] text-foreground group-hover:text-primary">{s.text}</span>
                                    <span className="hidden sm:inline eyebrow">{s.hint}</span>
                                    <ArrowUpRight className="w-4 h-4 shrink-0 text-muted-foreground transition-transform group-hover:-translate-y-0.5 group-hover:translate-x-0.5 group-hover:text-primary" />
                                </button>
                            </li>
                        ))}
                    </ul>
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
