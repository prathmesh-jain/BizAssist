import React from 'react';
import { useLocation, useNavigate, useParams, Routes, Route, Navigate } from 'react-router-dom';
import ChatInput from '../components/chat/ChatInput';
import useChatStore from '../store/chatStore';
import useBusinessStore from '../store/businessStore';
import useOrgStore, { hasPermission } from '../store/orgStore';
import type { Message, ToolStatus } from '../types';
import { Menu } from 'lucide-react';
import Logo from '../components/ui/Logo';
import { usePageMeta } from '../lib/seo';

const Sidebar = React.lazy(() => import('../components/layout/Sidebar'));
const ChatWindow = React.lazy(() => import('../components/chat/ChatWindow'));
const DocumentView = React.lazy(() => import('../components/documents/DocumentView'));
const CalendarView = React.lazy(() => import('../components/calendar/CalendarView'));
const SettingsView = React.lazy(() => import('../components/settings/SettingsView'));
const TeamView = React.lazy(() => import('../components/team/TeamView'));
const OnboardingFlow = React.lazy(() => import('../components/business/OnboardingFlow'));
const BusinessProfileView = React.lazy(() => import('../components/business/BusinessProfileView'));

/** Send admins of an organization without a confirmed profile to onboarding, once per visit. */
function useOnboardingRedirect() {
    const navigate = useNavigate();
    const location = useLocation();
    const { me } = useOrgStore();
    const { profile, loaded, load } = useBusinessStore();
    const checked = React.useRef(false);
    const manager = hasPermission(me, 'business.manage');

    React.useEffect(() => {
        if (me && manager) load();
    }, [me, manager, load]);

    React.useEffect(() => {
        if (checked.current || !me || !loaded) return;
        checked.current = true;
        const needsOnboarding = manager && (!profile || (profile.status !== 'confirmed' && !profile.onboarding_dismissed));
        if (needsOnboarding && location.pathname.startsWith('/app/chat')) navigate('/app/onboarding', { replace: true });
    }, [me, loaded, manager, profile, location.pathname, navigate]);
}

export default function Dashboard() {
    usePageMeta({ title: 'Workspace', noindex: true });
    const [isSidebarOpen, setIsSidebarOpen] = React.useState(false);
    const navigate = useNavigate();
    const location = useLocation();
    const { messages, streamingMessage, activeTools, isLoading, sendMessage } = useChatStore();
    useOnboardingRedirect();

    const currentView = React.useMemo(() => {
        if (location.pathname.startsWith('/app/settings')) return 'settings';
        if (location.pathname.startsWith('/app/team')) return 'team';
        if (location.pathname.startsWith('/app/business') || location.pathname.startsWith('/app/onboarding')) return 'business';
        if (location.pathname.startsWith('/app/documents')) return 'documents';
        if (location.pathname.startsWith('/app/calendar')) return 'calendar';
        return 'chat';
    }, [location.pathname]);

    const setCurrentViewHandler = (view: string) => {
        if (view === 'chat') {
            navigate('/app/chat');
        } else {
            navigate(`/app/${view}`);
        }
    };

    return (
        <div className="flex h-dvh app-wash overflow-hidden">
            <React.Suspense fallback={null}>
                <Sidebar
                    isOpen={isSidebarOpen}
                    setIsOpen={setIsSidebarOpen}
                    currentView={currentView}
                    setCurrentView={setCurrentViewHandler}
                />
            </React.Suspense>
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

                    <Route path="calendar" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><CalendarView /></FeatureView>} />
                    <Route path="documents" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><DocumentView /></FeatureView>} />
                    <Route path="settings" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><SettingsView /></FeatureView>} />
                    <Route path="team" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><TeamView /></FeatureView>} />
                    <Route path="business" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><BusinessProfileView /></FeatureView>} />
                    <Route path="onboarding" element={<FeatureView onMenuClick={() => setIsSidebarOpen(true)}><OnboardingFlow /></FeatureView>} />

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
        <div className="flex-1 flex flex-col h-dvh overflow-hidden">
            <MobileHeader onMenuClick={onMenuClick} />
            <React.Suspense fallback={<div className="flex-1 bg-background" />}>
                <ChatWindow
                    messages={messages}
                    streamingMessage={streamingMessage}
                    activeTools={activeTools}
                    isLoading={isLoading}
                />
            </React.Suspense>
            <ChatInput onSend={sendMessage} isLoading={isLoading} />
        </div>
    );
}

function FeatureView({ children, onMenuClick }: { children: React.ReactNode; onMenuClick: () => void }) {
    return (
        <div className="flex-1 h-full overflow-auto">
            <MobileHeader onMenuClick={onMenuClick} />
            <React.Suspense fallback={<div className="p-8 text-sm text-muted-foreground">Loading…</div>}>
                {children}
            </React.Suspense>
        </div>
    );
}

function MobileHeader({ onMenuClick }: { onMenuClick: () => void }) {
    return (
        <header className="h-14 border-b border-border flex items-center gap-2 px-3 bg-sidebar lg:hidden shrink-0 sticky top-0 z-30">
            <button
                onClick={onMenuClick}
                aria-label="Open menu"
                className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
            >
                <Menu className="w-5 h-5" />
            </button>
            <Logo size="sm" />
        </header>
    );
}
