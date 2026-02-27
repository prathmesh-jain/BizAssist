import React, { useState } from 'react';
import { useNavigate, useParams, Routes, Route, Navigate } from 'react-router-dom';
import Sidebar from '../components/layout/Sidebar';
import ChatWindow from '../components/chat/ChatWindow';
import ChatInput from '../components/chat/ChatInput';
import DocumentView from '../components/documents/DocumentView';
import SettingsView from '../components/settings/SettingsView';
import useChatStore from '../store/chatStore';
import type { Message, ToolStatus } from '../types';

export default function Dashboard() {
    const [isSidebarOpen, setIsSidebarOpen] = React.useState(false);
    const navigate = useNavigate();
    const { messages, streamingMessage, activeTools, isLoading, sendMessage } = useChatStore();
    const [currentView, setCurrentView] = useState('chat');

    const setCurrentViewHandler = (view: string) => {
        setCurrentView(view);
        if (view === 'chat') {
            navigate('/app/chat');
        } else {
            navigate(`/app/${view}`);
        }
    };

    return (
        <div className="flex h-screen bg-background overflow-hidden font-sans">
            <Sidebar
                isOpen={isSidebarOpen}
                setIsOpen={setIsSidebarOpen}
                currentView={currentView}        // sidebar highlights based on URL now
                setCurrentView={setCurrentViewHandler}
            />
            <main className="flex-1 flex flex-col min-w-0 relative">
                <Routes>
                    {/* Default: redirect / to /chat */}
                    <Route index element={<Navigate to="chat" replace />} />

                    {/* Chat view with optional chat ID */}
                    <Route
                        path="chat"
                        element={
                            <ChatViewWrapper
                                messages={messages}
                                streamingMessage={streamingMessage}
                                activeTools={activeTools}
                                isLoading={isLoading}
                                sendMessage={sendMessage}
                                onMenuClick={() => setIsSidebarOpen(true)}
                            />
                        }
                    />
                    <Route
                        path="chat/:chatId"
                        element={
                            <ChatViewWrapper
                                messages={messages}
                                streamingMessage={streamingMessage}
                                activeTools={activeTools}
                                isLoading={isLoading}
                                sendMessage={sendMessage}
                                onMenuClick={() => setIsSidebarOpen(true)}
                            />
                        }
                    />

                    <Route path="documents" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><DocumentView /></FeatureView>} />
                    <Route path="settings" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><SettingsView /></FeatureView>} />

                    <Route path="*" element={<Navigate to="chat" replace />} />
                </Routes>
            </main>
        </div>
    );
}

/** Chat view — syncs chatId from URL into the store on mount */
function ChatViewWrapper({
    messages, streamingMessage, activeTools, isLoading, sendMessage, onMenuClick
}: {
    messages: Message[];
    streamingMessage: string;
    activeTools: { name: string; status: ToolStatus }[];
    isLoading: boolean;
    sendMessage: (content: string, attachments?: { file: File; preview?: string }[]) => Promise<void>;
    onMenuClick: () => void;
}) {
    const { chatId } = useParams<{ chatId?: string }>();
    const { setActiveChat, activeChatId } = useChatStore();
    const navigate = useNavigate();

    // When the URL has a chatId, load it into the store
    React.useEffect(() => {
        if (chatId && chatId !== activeChatId) {
            setActiveChat(chatId);
        }
    }, [chatId]);

    // When a new chat is created without an ID in URL, redirect to /chat/:id
    React.useEffect(() => {
        if (activeChatId && !chatId) {
            navigate(`/app/chat/${activeChatId}`, { replace: true });
        }
    }, [activeChatId, chatId]);

    return (
        <div className="flex-1 flex flex-col h-screen overflow-hidden bg-background">
            <MobileHeader onMenuClick={onMenuClick} />
            <ChatWindow
                messages={messages}
                streamingMessage={streamingMessage}
                activeTools={activeTools}
                isLoading={isLoading}
            />
            <ChatInput onSend={sendMessage} isLoading={isLoading} />
        </div>
    );
}

function FeatureView({ children, onMenuClick }: { children: React.ReactNode; onMenuClick: () => void }) {
    return (
        <div className="flex-1 h-full overflow-auto bg-background">
            <MobileHeader onMenuClick={onMenuClick} />
            {children}
        </div>
    );
}

function MobileHeader({ onMenuClick }: { onMenuClick: () => void }) {
    return (
        <header className="h-16 border-b border-border flex items-center px-6 bg-card lg:hidden shrink-0">
            <button
                onClick={onMenuClick}
                className="p-2 text-muted-foreground hover:text-foreground transition-colors"
            >
                <svg className="w-6 h-6" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
            </button>
            <h1 className="ml-4 font-bold text-foreground">BizAssist</h1>
        </header>
    );
}
