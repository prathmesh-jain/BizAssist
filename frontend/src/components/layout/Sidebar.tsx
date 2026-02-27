import { PlusCircle, MessageSquare, LogOut, Settings, FileText, X, Sun, Moon, Pencil, Trash2 } from 'lucide-react';
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
        if (confirm('Are you sure you want to delete this chat?')) {
            await deleteChat(chatId);
        }
        navigate('/app/chat');
    };

    const menuItems = [
        { id: 'chat', label: 'Chat Assistant', icon: MessageSquare },
        { id: 'documents', label: 'Documents', icon: FileText },
        { id: 'settings', label: 'Settings', icon: Settings },
    ];

    return (
        <>
            {/* Mobile Backdrop */}
            {isOpen && (
                <div
                    className="fixed inset-0 bg-background/80 backdrop-blur-sm z-40 lg:hidden"
                    onClick={() => setIsOpen(false)}
                />
            )}

            {/* Sidebar */}
            <aside className={`
        fixed lg:static top-0 left-0 bottom-0 z-50 w-64 bg-card border-r border-border transition-all duration-300 ease-in-out lg:translate-x-0
        ${isOpen ? 'translate-x-0 shadow-2xl' : '-translate-x-full lg:translate-x-0'}
        flex flex-col h-full
      `}>
                <div className="flex flex-col h-full">
                    {/* Logo / Header */}
                    <div className="p-3 border-b border-border flex items-center justify-between">
                        <div className="flex items-center space-x-2">
                            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-primary-foreground font-bold">
                                B
                            </div>
                            <h1 className="text-xl font-bold bg-linear-to-r from-primary to-blue-400 bg-clip-text text-transparent">
                                BizAssist
                            </h1>
                        </div>
                        <button
                            onClick={toggleTheme}
                            className="flex items-center justify-center px-2 py-2 rounded-xl text-foreground transition-all"
                        >
                            <span className="flex items-center">
                                {theme === 'dark' ? <Moon className="w-5 h-5" /> : <Sun className="w-5 h-5" />}
                            </span>
                        </button>
                        <button className="lg:hidden text-muted-foreground hover:text-foreground p-1" onClick={() => setIsOpen(false)}>
                            <X className="w-5 h-5" />
                        </button>
                    </div>

                    {/* New Chat Button */}
                    <div className="p-2">
                        <button
                            onClick={handleCreateChat}
                            className="w-full flex items-center justify-center space-x-2 bg-primary hover:bg-primary/90 text-primary-foreground py-2.5 px-4 rounded-xl transition-all font-medium shadow-sm hover:shadow-md active:scale-[0.98]"
                        >
                            <PlusCircle className="w-5 h-5" />
                            <span>New Interaction</span>
                        </button>
                    </div>

                    {/* Navigation */}
                    <nav className="flex-1 overflow-y-auto px-3 py-1 space-y-1">
                        {menuItems.map((item) => (
                            <button
                                key={item.id}
                                onClick={() => {
                                    setCurrentView(item.id);
                                    if (window.innerWidth < 1024) setIsOpen(false);
                                }}
                                className={`
                  w-full flex items-center space-x-3 px-3 py-2.5 rounded-xl transition-all group
                  ${currentView === item.id
                                        ? 'bg-primary/10 text-primary border border-primary/20'
                                        : 'text-muted-foreground hover:bg-muted hover:text-foreground'}
                `}
                            >
                                <item.icon className={`w-5 h-5 transition-transform group-hover:scale-110 ${currentView === item.id ? 'text-primary' : ''}`} />
                                <span className="font-medium">{item.label}</span>
                            </button>
                        ))}
                    </nav>

                    {/* Chat History */}
                    <div className="flex-[1.4] overflow-y-auto px-3 py-2 border-t border-border">
                        <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider px-3 py-2">
                            Recent Chats
                        </h3>
                        <div className="space-y-1">
                            {chats.length === 0 ? (
                                <p className="text-sm text-muted-foreground px-3 py-2">No chats yet</p>
                            ) : (
                                chats.slice(0, 10).map((chat) => (
                                    <div
                                        key={chat.id}
                                        onClick={() => handleChatSelect(chat.id)}
                                        className={`
                                            w-full flex items-center space-x-2 px-3 py-2 rounded-xl transition-all group cursor-pointer
                                            ${activeChatId === chat.id
                                                ? 'bg-primary/10 text-primary border border-primary/20'
                                                : 'text-muted-foreground hover:bg-muted hover:text-foreground'}
                                        `}
                                    >
                                        <MessageSquare className="w-4 h-4 shrink-0" />
                                        {editingChatId === chat.id ? (
                                            <input
                                                type="text"
                                                value={editingTitle}
                                                onChange={(e) => setEditingTitle(e.target.value)}
                                                onBlur={handleSaveRename}
                                                onKeyDown={(e) => e.key === 'Enter' && handleSaveRename()}
                                                onClick={(e) => e.stopPropagation()}
                                                className="flex-1 bg-transparent border-b border-primary focus:outline-none text-sm"
                                                autoFocus
                                            />
                                        ) : (
                                            <>
                                                <span className="text-sm font-medium truncate flex-1">{chat.title}</span>
                                                <div className="hidden group-hover:flex items-center space-x-1">
                                                    <button
                                                        onClick={(e) => { e.stopPropagation(); handleRename(chat.id); }}
                                                        className="p-1 hover:bg-primary/20 rounded"
                                                    >
                                                        <Pencil className="w-3 h-3" />
                                                    </button>
                                                    <button
                                                        onClick={(e) => handleDelete(chat.id, e)}
                                                        className="p-1 hover:bg-destructive/20 rounded text-destructive"
                                                    >
                                                        <Trash2 className="w-3 h-3" />
                                                    </button>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                ))
                            )}
                        </div>
                    </div>

                    {/* Theme Toggle & User Profile */}
                    <div className="p-4 border-t border-border space-y-4">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center space-x-3 truncate">
                                <div className="w-9 h-9 rounded-xl bg-primary/20 border border-primary/10 flex items-center justify-center text-primary font-bold shrink-0 overflow-hidden shadow-inner">
                                    {user?.photoURL ? (
                                        <img src={user.photoURL} alt="profile" />
                                    ) : (
                                        user?.email?.[0]?.toUpperCase() || 'U'
                                    )}
                                </div>
                                <div className="text-sm truncate">
                                    <p className="font-semibold text-foreground truncate">{user?.displayName || 'User'}</p>
                                    <p className="text-muted-foreground text-xs truncate">{user?.email || ''}</p>
                                </div>
                            </div>
                            <button onClick={handleLogout} className="p-2 text-muted-foreground hover:text-destructive transition-colors rounded-lg hover:bg-destructive/10" title="Log out">
                                <LogOut className="w-5 h-5" />
                            </button>
                        </div>
                    </div>
                </div>
            </aside>
        </>
    );
}
