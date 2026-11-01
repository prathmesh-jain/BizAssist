import { Plus, MessageSquare, LogOut, Settings, FileText, X, Sun, Moon, Pencil, Trash2, Users, Briefcase } from 'lucide-react';
import Logo from '../ui/Logo';
import type { Chat } from '../../types';
import OrgSwitcher from './OrgSwitcher';
import useChatStore from '../../store/chatStore';
import useThemeStore from '../../store/themeStore';
import React from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';

interface SidebarProps {
    isOpen: boolean;
    setIsOpen: (open: boolean) => void;
    currentView: string;
    setCurrentView: (view: string) => void;
}

export default function Sidebar({ isOpen, setIsOpen, currentView, setCurrentView }: SidebarProps) {
    const { user, logout } = useAuth();
    const navigate = useNavigate();
    const { fetchChats, createChat, chats, activeChatId, setActiveChat, deleteChat, renameChat } = useChatStore();
    const { theme, toggleTheme } = useThemeStore();
    const [editingChatId, setEditingChatId] = React.useState<string | null>(null);
    const [editingTitle, setEditingTitle] = React.useState('');
    const [deleteTarget, setDeleteTarget] = React.useState<{ id: string; title: string } | null>(null);
    const [isDeletingChat, setIsDeletingChat] = React.useState(false);

    React.useEffect(() => {
        fetchChats();
    }, [fetchChats]);

    const handleLogout = () => {
        logout();
    };

    const handleChatSelect = (chatId: string) => {
        setActiveChat(chatId);
        setCurrentView('chat');
        navigate(`/app/chat/${chatId}`);
        if (window.innerWidth < 1024) setIsOpen(false);
    };

    const handleCreateChat = async () => {
        const newChatId = await createChat();
        navigate(`/app/chat/${newChatId}`);
        setActiveChat(newChatId);
        if (window.innerWidth < 1024) setIsOpen(false);
    };

    const handleRename = (chatId: string) => {
        const chat = chats.find(c => c.id === chatId);
        if (chat) {
            setEditingChatId(chatId);
            setEditingTitle(chat.title);
        }
    };

    const handleSaveRename = async () => {
        if (editingChatId && editingTitle.trim()) {
            await renameChat(editingChatId, editingTitle.trim());
        }
        setEditingChatId(null);
        setEditingTitle('');
    };

    const handleDelete = async (chatId: string, e: React.MouseEvent) => {
        e.stopPropagation();
        const chat = chats.find(c => c.id === chatId);
        if (!chat) return;
        setDeleteTarget({ id: chatId, title: chat.title });
    };

    const handleConfirmDelete = async () => {
        if (!deleteTarget || isDeletingChat) return;
        setIsDeletingChat(true);
        try {
            await deleteChat(deleteTarget.id);
            if (activeChatId === deleteTarget.id) {
                navigate('/app/chat');
            }
            setDeleteTarget(null);
        } finally {
            setIsDeletingChat(false);
        }
    };

    const menuItems = [
        { id: 'chat', label: 'Assistant', icon: MessageSquare },
        { id: 'business', label: 'Your business', icon: Briefcase },
        { id: 'documents', label: 'Documents', icon: FileText },
        { id: 'team', label: 'Team', icon: Users },
        { id: 'settings', label: 'Settings', icon: Settings },
    ];

    const groups = groupChatsByDate(chats.slice(0, 30));
    const displayName = user?.displayName || user?.email?.split('@')[0] || 'You';

    return (
        <>
            {deleteTarget && (
                <div className="fixed inset-0 z-[70] flex items-center justify-center bg-background/60 backdrop-blur-sm p-4">
                    <div role="alertdialog" aria-modal="true" className="rise-in w-full max-w-sm rounded-2xl border border-border bg-card shadow-2xl p-6">
                        <h3 className="font-display text-xl font-bold text-foreground">Delete this conversation?</h3>
                        <p className="mt-2 text-sm text-muted-foreground leading-relaxed">
                            <span className="font-medium text-foreground">{deleteTarget.title}</span> and all its messages will be gone for good.
                        </p>
                        <div className="mt-6 flex items-center justify-end gap-2">
                            <button
                                onClick={() => setDeleteTarget(null)}
                                disabled={isDeletingChat}
                                className="px-4 py-2 rounded-md border border-border text-sm text-foreground hover:bg-muted disabled:opacity-50"
                            >
                                Keep it
                            </button>
                            <button
                                onClick={handleConfirmDelete}
                                disabled={isDeletingChat}
                                className="px-4 py-2 rounded-md bg-destructive text-sm font-medium text-destructive-foreground hover:bg-destructive/90 disabled:opacity-50"
                            >
                                {isDeletingChat ? 'Deleting…' : 'Delete'}
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Mobile backdrop */}
            {isOpen && (
                <div
                    className="fixed inset-0 bg-foreground/25 z-40 lg:hidden"
                    onClick={() => setIsOpen(false)}
                />
            )}

            <aside className={`
                fixed lg:static top-0 left-0 bottom-0 z-50 w-[272px] shrink-0 bg-sidebar border-r border-border
                transition-transform duration-200 ease-out lg:translate-x-0
                ${isOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full lg:translate-x-0'}
                flex flex-col h-full
            `}>
                <div className="flex items-center justify-between px-4 h-16 shrink-0">
                    <Logo size="sm" />
                    <button className="lg:hidden p-1.5 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted" onClick={() => setIsOpen(false)} aria-label="Close menu">
                        <X className="w-5 h-5" />
                    </button>
                </div>

                <OrgSwitcher />

                <div className="px-3 pt-3">
                    <button
                        onClick={handleCreateChat}
                        className="btn-glow group w-full flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-sm font-semibold"
                    >
                        <Plus className="w-4 h-4 transition-transform duration-300 group-hover:rotate-90" />
                        New conversation
                    </button>
                </div>

                <nav className="px-3 pt-4 space-y-0.5" aria-label="Main">
                    {menuItems.map((item) => {
                        const active = currentView === item.id;
                        return (
                            <button
                                key={item.id}
                                onClick={() => {
                                    setCurrentView(item.id);
                                    if (window.innerWidth < 1024) setIsOpen(false);
                                }}
                                aria-current={active ? 'page' : undefined}
                                className={`group relative w-full flex items-center gap-3 rounded-xl px-3 py-2 text-sm transition-all ${active
                                    ? 'bg-primary/10 text-foreground font-medium'
                                    : 'text-muted-foreground hover:bg-muted hover:text-foreground hover:translate-x-0.5'}`}
                            >
                                {active && <span className="absolute -left-3 top-1.5 bottom-1.5 w-1 rounded-r-full bg-brand-gradient" />}
                                <span className={`flex h-7 w-7 items-center justify-center rounded-lg transition-colors ${active ? 'bg-brand-gradient text-white shadow-[0_4px_14px_-4px_hsl(var(--glow-1)/0.7)]' : 'bg-transparent group-hover:bg-card'}`}>
                                    <item.icon className="w-4 h-4" strokeWidth={active ? 2.25 : 2} />
                                </span>
                                {item.label}
                            </button>
                        );
                    })}
                </nav>

                <div className="mt-5 flex-1 min-h-0 overflow-y-auto px-3 pb-3">
                    {chats.length === 0 ? (
                        <p className="px-3 text-sm text-muted-foreground leading-relaxed">
                            Your conversations will be listed here.
                        </p>
                    ) : (
                        groups.map((group) => (
                            <div key={group.label} className="mb-4">
                                <p className="eyebrow px-3 pb-1.5">{group.label}</p>
                                <ul className="space-y-px">
                                    {group.chats.map((chat) => {
                                        const active = activeChatId === chat.id && currentView === 'chat';
                                        return (
                                            <li
                                                key={chat.id}
                                                onClick={() => handleChatSelect(chat.id)}
                                                className={`group relative flex items-center gap-1 rounded-lg pl-3 pr-1 py-1.5 cursor-pointer text-sm transition-colors ${active
                                                    ? 'bg-card text-foreground shadow-[0_0_0_1px_hsl(var(--border)),0_4px_14px_-8px_hsl(var(--glow-1)/0.5)]'
                                                    : 'text-muted-foreground hover:bg-muted hover:text-foreground'}`}
                                            >
                                                {active && <span className="absolute left-0 top-2 bottom-2 w-0.5 rounded-full bg-brand-gradient" />}
                                                {editingChatId === chat.id ? (
                                                    <input
                                                        type="text"
                                                        value={editingTitle}
                                                        onChange={(e) => setEditingTitle(e.target.value)}
                                                        onBlur={handleSaveRename}
                                                        onKeyDown={(e) => {
                                                            if (e.key === 'Enter') handleSaveRename();
                                                            if (e.key === 'Escape') { setEditingChatId(null); setEditingTitle(''); }
                                                        }}
                                                        onClick={(e) => e.stopPropagation()}
                                                        aria-label="Conversation title"
                                                        className="flex-1 min-w-0 bg-transparent border-b border-primary focus:outline-none"
                                                        autoFocus
                                                    />
                                                ) : (
                                                    <>
                                                        <span className="truncate flex-1">{chat.title}</span>
                                                        <span className="hidden group-hover:flex group-focus-within:flex items-center">
                                                            <button
                                                                onClick={(e) => { e.stopPropagation(); handleRename(chat.id); }}
                                                                className="p-1 rounded text-muted-foreground hover:text-foreground"
                                                                aria-label={`Rename ${chat.title}`}
                                                            >
                                                                <Pencil className="w-3.5 h-3.5" />
                                                            </button>
                                                            <button
                                                                onClick={(e) => handleDelete(chat.id, e)}
                                                                className="p-1 rounded text-muted-foreground hover:text-destructive"
                                                                aria-label={`Delete ${chat.title}`}
                                                            >
                                                                <Trash2 className="w-3.5 h-3.5" />
                                                            </button>
                                                        </span>
                                                    </>
                                                )}
                                            </li>
                                        );
                                    })}
                                </ul>
                            </div>
                        ))
                    )}
                </div>

                <div className="shrink-0 border-t border-border p-3">
                    <div className="flex items-center gap-2.5">
                        <Avatar name={displayName} photoURL={user?.photoURL} />
                        <div className="min-w-0 flex-1 text-sm leading-tight">
                            <p className="font-medium text-foreground truncate">{displayName}</p>
                            <p className="text-muted-foreground text-xs truncate">{user?.email || ''}</p>
                        </div>
                        <button
                            onClick={toggleTheme}
                            className="p-2 rounded-md text-muted-foreground hover:text-foreground hover:bg-muted"
                            aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
                            title={theme === 'dark' ? 'Light theme' : 'Dark theme'}
                        >
                            {theme === 'dark' ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
                        </button>
                        <button onClick={handleLogout} className="p-2 rounded-md text-muted-foreground hover:text-destructive hover:bg-destructive/10" title="Sign out" aria-label="Sign out">
                            <LogOut className="w-4 h-4" />
                        </button>
                    </div>
                </div>
            </aside>
        </>
    );
}

function Avatar({ name, photoURL }: { name: string; photoURL?: string | null }) {
    if (photoURL) {
        return <img src={photoURL} alt="" className="w-8 h-8 rounded-full object-cover shrink-0" referrerPolicy="no-referrer" />;
    }
    const initials = name.split(/[\s._-]+/).filter(Boolean).slice(0, 2).map((p) => p[0]?.toUpperCase()).join('') || 'U';
    return (
        <span className="w-8 h-8 rounded-full bg-brand-gradient text-white text-xs font-bold flex items-center justify-center shrink-0 ring-2 ring-card shadow-[0_0_0_3px_hsl(var(--primary)/0.25)]">
            {initials}
        </span>
    );
}

/** Bucket conversations the way people remember them: today, this week, earlier. */
function groupChatsByDate(chats: Chat[]): { label: string; chats: Chat[] }[] {
    const now = new Date();
    const startOfToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    const day = 24 * 60 * 60 * 1000;
    const buckets: { label: string; test: (t: number) => boolean; chats: Chat[] }[] = [
        { label: 'Today', test: (t) => t >= startOfToday, chats: [] },
        { label: 'Yesterday', test: (t) => t >= startOfToday - day, chats: [] },
        { label: 'Past week', test: (t) => t >= startOfToday - 7 * day, chats: [] },
        { label: 'Earlier', test: () => true, chats: [] },
    ];
    for (const chat of chats) {
        const t = new Date(chat.updated_at || chat.created_at).getTime() || 0;
        buckets.find((b) => b.test(t))!.chats.push(chat);
    }
    return buckets.filter((b) => b.chats.length);
}
