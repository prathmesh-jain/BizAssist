import { create } from 'zustand';
import apiClient, { getAuthHeader } from '../api/client';
import { triggerUnauthorized } from '../api/client';
import type { Chat, Message, ToolStatus, ToolCall } from '../types';

interface ChatState {
    chats: Chat[];
    activeChatId: string | null;
    messages: Message[];
    isLoading: boolean;
    streamingMessage: string;
    activeTools: ToolCall[];
    agentStatus: { message: string; steps?: string[] } | null;
    hasMoreMessages: boolean;
    isLoadingMore: boolean;

    fetchChats: () => Promise<void>;
    setActiveChat: (id: string) => void;
    createChat: (title?: string) => Promise<string>;
    sendMessage: (content: string, attachments?: { file: File; preview?: string }[]) => Promise<void>;
    loadMoreMessages: () => Promise<void>;
    deleteChat: (id: string) => Promise<void>;
    renameChat: (id: string, title: string) => Promise<void>;
    clearStreaming: () => void;
    resolveInterrupt: (chatId: string, action: 'accept' | 'reject', data?: any) => Promise<void>;
    resolveInterruptWithFiles: (chatId: string, files: File[], content?: string) => Promise<void>;
}

/**
 * Get the API base URL, ensuring it ends with /api.
 */
const getApiBase = () => {
    const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
    return base.endsWith('/api') ? base : `${base}/api`;
};

interface ChatStreamEvent {
    type: 'token' | 'interrupt' | 'tool_start' | 'tool_end' | 'source' | 'title_update' | 'status' | 'error' | 'done';
    content?: string | { 
        question: string; 
        interrupt_type?: 'file_upload' | 'text_input' | 'yes_no_confirmation' | 'accept_decline';
        action_required?: string; 
        data?: any; 
        message?: string;
        steps?: string[];
    };
    interrupt_id?: string;
    name?: string;
    tool?: string;
    citations?: string[];
    chat_id?: string;
    title?: string;
}

/** 
 * Shared SSE stream handler 
 */
async function handleStream(
    response: Response,
    set: any,
    get: () => ChatState
) {
    const reader = response.body?.getReader();
    if (!reader) {
        set({ isLoading: false });
        return;
    }

    const decoder = new TextDecoder();
    let buffer = '';
    let hasReceivedFirstToken = false;
    const pendingToolMeta: Record<string, { citations?: string[] }> = {};

    while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split('\n');
        buffer = lines.pop() ?? '';

        for (const rawLine of lines) {
            const line = rawLine.trim();
            if (!line.startsWith('data:')) continue;

            const data = line.replace(/^data:\s?/, '');
            if (!data) continue;
            if (data === '[DONE]') {
                buffer = '';
                break;
            }

            try {
                const parsed: ChatStreamEvent = JSON.parse(data);

                if (parsed.type === 'token') {
                    if (!hasReceivedFirstToken) {
                        hasReceivedFirstToken = true;
                        set({ isLoading: false });
                    }
                    set((state: ChatState) => ({ streamingMessage: state.streamingMessage + (parsed.content ?? '') }));

                } else if (parsed.type === 'interrupt') {
                    set({ isLoading: false });
                    const interruptContent = typeof parsed.content === 'object' ? parsed.content : null;
                    const interruptMsg: Message = {
                        id: `interrupt-${Date.now()}`,
                        role: 'assistant',
                        content: '',
                        interrupt: {
                            id: parsed.interrupt_id!,
                            question: typeof parsed.content === 'string' 
                                ? parsed.content 
                                : (interruptContent?.question || 'Approval required'),
                            action_required: interruptContent?.action_required,
                            interrupt_type: interruptContent?.interrupt_type,
                            data: interruptContent?.data
                        },
                        created_at: new Date().toISOString()
                    };
                    set((state: ChatState) => ({ 
                        messages: [...state.messages, interruptMsg],
                        streamingMessage: '', 
                        activeTools: [],
                        agentStatus: null,
                    }));
                    return; 

                } else if (parsed.type === 'status') {
                    const statusContent = typeof parsed.content === 'object' ? parsed.content : null;
                    if (statusContent?.message) {
                        set({
                            agentStatus: {
                                message: String(statusContent.message),
                                steps: Array.isArray(statusContent.steps) ? statusContent.steps.map(String) : undefined,
                            }
                        });
                    }

                } else if (parsed.type === 'tool_start') {
                    const toolName = parsed.name ?? parsed.tool;
                    if (toolName) {
                        const meta = pendingToolMeta[String(toolName)] || {};
                        set((state: ChatState) => ({
                            activeTools: [...state.activeTools, {
                                name: toolName as string,
                                status: 'started' as ToolStatus,
                                ...meta,
                            }]
                        }));
                    }

                } else if (parsed.type === 'tool_end') {
                    const toolName = parsed.name ?? parsed.tool;
                    if (toolName) {
                        set((state: ChatState) => ({
                            activeTools: state.activeTools.map((t: ToolCall) =>
                                t.name === toolName ? { ...t, status: 'completed' as ToolStatus } : t
                            )
                        }));
                    }

                } else if (parsed.type === 'source') {
                    const toolName = parsed.name ?? parsed.tool ?? 'Source';
                    pendingToolMeta[String(toolName)] = {
                        citations: Array.isArray(parsed.citations) ? parsed.citations.map(String) : undefined,
                    };
                    set((state: ChatState) => ({
                        activeTools: state.activeTools.map((t: ToolCall) =>
                            t.name === toolName ? { ...t, ...pendingToolMeta[String(toolName)] } : t
                        )
                    }));

                } else if (parsed.type === 'title_update') {
                    const chatId = parsed.chat_id;
                    const newTitle = parsed.title;
                    if (chatId && newTitle) {
                        set((state: ChatState) => ({
                            chats: state.chats.map((c: Chat) =>
                                c.id === chatId ? { ...c, title: newTitle } : c
                            )
                        }));
                    }

                } else if (parsed.type === 'error') {
                    if (!hasReceivedFirstToken) {
                        set({ isLoading: false });
                    }
                    const errorText = parsed.content ? String(parsed.content) : 'Something went wrong.';
                    set((state: ChatState) => ({ streamingMessage: state.streamingMessage || errorText }));
                    buffer = '';
                    break;

                } else if (parsed.type === 'done') {
                    buffer = '';
                    break;
                }
            } catch (e) {
                if (!hasReceivedFirstToken) {
                    hasReceivedFirstToken = true;
                    set({ isLoading: false });
                }
                set((state: ChatState) => ({ streamingMessage: state.streamingMessage + data }));
            }
        }
    }

    set({ isLoading: false });

    const { activeChatId: finalChatId, streamingMessage: finalText, activeTools } = get();
    if (finalText) {
        const aiMsg: Message = {
            id: (Date.now() + 1).toString(),
            role: 'assistant',
            content: finalText,
            tool_calls: activeTools.map(t => ({
                name: t.name,
                status: t.status as ToolStatus,
                citations: t.citations
            })),
            created_at: new Date().toISOString()
        };
        set((state: ChatState) => ({
            messages: [...state.messages, aiMsg],
            streamingMessage: '',
            activeTools: [],
            agentStatus: null,
        }));
    }
    set({ streamingMessage: '', activeTools: [], agentStatus: null });

    if (finalChatId) {
        try {
            const authHeader = await getAuthHeader();
            const r = await fetch(`${getApiBase()}/chat/${finalChatId}/messages?limit=10`, {
                headers: { 'Authorization': authHeader }
            });
            if (r.ok) {
                const d = await r.json();
                const fresh: Message[] = d.messages ?? d;
                const seen = new Set<string>();
                const unique = fresh
                    .filter((m: Message) => { if (seen.has(m.id)) return false; seen.add(m.id); return true; })
                    .map((m: Message) => ({
                        ...m,
                        tool_calls: (m.tool_calls || []).map((tc: ToolCall) => ({
                            name: String(tc?.name ?? ''),
                            status: (tc?.status as ToolStatus) || 'completed',
                            citations: Array.isArray(tc?.citations) ? tc.citations.map(String) : undefined,
                        } as ToolCall))
                    }));
                set({ messages: unique });
            }
        } catch (_) {}
    }
}

const useChatStore = create<ChatState>((set, get) => ({
    chats: [],
    activeChatId: null,
    messages: [],
    isLoading: false,
    streamingMessage: '',
    activeTools: [],
    agentStatus: null,
    hasMoreMessages: true,
    isLoadingMore: false,

    fetchChats: async () => {
        try {
            const response = await apiClient.get('/chat');
            set({ chats: response.data });
        } catch (error) {
            console.error('Failed to fetch chats:', error);
        }
    },

    setActiveChat: async (id: string) => {
        set({ activeChatId: id, messages: [], streamingMessage: '', activeTools: [], agentStatus: null, hasMoreMessages: true });
        try {
            const authHeader = await getAuthHeader();
            const response = await fetch(`${getApiBase()}/chat/${id}/messages?limit=10`, {
                headers: { 'Authorization': authHeader }
            });
            if (response.ok) {
                const data = await response.json();
                const msgs: Message[] = data.messages ?? data;
                const hasMore: boolean = data.has_more ?? msgs.length >= 10;
                set({ messages: msgs, hasMoreMessages: hasMore });
            }
        } catch (error) {
            console.error('Failed to load messages:', error);
        }
    },

    createChat: async (title = 'New Chat') => {
        try {
            const response = await apiClient.post('/chat', { title });
            const newChat = response.data;
            set((state) => ({ chats: [newChat, ...state.chats], activeChatId: newChat.id }));
            return newChat.id;
        } catch (error) {
            console.error('Failed to create chat:', error);
            throw error;
        }
    },

    sendMessage: async (content: string, attachments: { file: File; preview?: string }[] = []) => {
        let { activeChatId } = get();
        if (!activeChatId) activeChatId = await get().createChat('New Chat');

        set({ isLoading: true, streamingMessage: '', activeTools: [], agentStatus: null });

        const userMsg: Message = {
            id: Date.now().toString(),
            role: 'user',
            content,
            created_at: new Date().toISOString()
        };
        set((state) => ({ messages: [...state.messages, userMsg] }));

        try {
            const authHeader = await getAuthHeader();
            const hasFiles = (attachments || []).length > 0;
            const url = hasFiles
                ? `${getApiBase()}/chat/${activeChatId}/message_with_files`
                : `${getApiBase()}/chat/${activeChatId}/message`;

            const fetchInit: RequestInit = {
                method: 'POST',
                headers: { 'Authorization': authHeader }
            };

            if (hasFiles) {
                const form = new FormData();
                form.append('content', content || '');
                for (const a of attachments) form.append('files', a.file);
                fetchInit.body = form;
            } else {
                (fetchInit.headers as any)['Content-Type'] = 'application/json';
                fetchInit.body = JSON.stringify({ content });
            }

            const response = await fetch(url, fetchInit);
            if (response.status === 401) triggerUnauthorized();
            if (!response.ok) {
                let detail = 'Request failed';
                try {
                    const payload = await response.json();
                    detail = payload?.detail || detail;
                } catch (_) {}
                throw new Error(detail);
            }

            await handleStream(response, set, get);
        } catch (error) {
            console.error('Streaming error:', error);
            set({
                isLoading: false,
                streamingMessage: error instanceof Error ? error.message : 'Request failed.',
            });
        }
    },

    loadMoreMessages: async () => {
        const { activeChatId, messages, hasMoreMessages, isLoadingMore } = get();
        if (!activeChatId || !hasMoreMessages || isLoadingMore) return;
        set({ isLoadingMore: true });
        try {
            const oldestMsg = messages[0];
            const query = oldestMsg?.id ? `?before=${encodeURIComponent(oldestMsg.id)}&limit=10` : `?limit=10`;
            const authHeader = await getAuthHeader();
            const response = await fetch(`${getApiBase()}/chat/${activeChatId}/messages${query}`, {
                headers: { 'Authorization': authHeader }
            });
            if (response.ok) {
                const data = await response.json();
                const older: Message[] = data.messages ?? data;
                const hasMore: boolean = data.has_more ?? older.length >= 10;
                set((state) => ({
                    messages: [...older, ...state.messages],
                    hasMoreMessages: hasMore,
                    isLoadingMore: false
                }));
            }
        } catch (error) {
            console.error('Failed to load more messages:', error);
            set({ isLoadingMore: false });
        }
    },

    deleteChat: async (id: string) => {
        try {
            await apiClient.delete(`/chat/${id}`);
            set((state) => ({
                chats: state.chats.filter(c => c.id !== id),
                activeChatId: state.activeChatId === id ? null : state.activeChatId,
                messages: state.activeChatId === id ? [] : state.messages,
            }));
        } catch (error) {}
    },

    renameChat: async (id: string, title: string) => {
        try {
            const response = await apiClient.patch(`/chat/${id}`, { title });
            set((state) => ({ chats: state.chats.map(c => c.id === id ? response.data : c) }));
        } catch (error) {}
    },

    clearStreaming: () => set({ streamingMessage: '', activeTools: [], agentStatus: null }),

    resolveInterrupt: async (chatId: string, action: 'accept' | 'reject', data?: any) => {
        set((state: ChatState) => ({ 
            isLoading: true, 
            activeTools: [],
            agentStatus: null,
            messages: state.messages.filter(m => !m.interrupt)
        }));
        try {
            const authHeader = await getAuthHeader();
            const response = await fetch(`${getApiBase()}/chat/${chatId}/interrupt-resolve`, {
                method: 'POST',
                headers: {
                    'Authorization': authHeader,
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ action, data })
            });
            if (!response.ok) {
                let detail = 'Resolution failed';
                try {
                    const payload = await response.json();
                    detail = payload?.detail || detail;
                } catch (_) {}
                throw new Error(detail);
            }
            await handleStream(response, set, get);
        } catch (error) {
            console.error('Resolution error:', error);
            set({
                isLoading: false,
                streamingMessage: error instanceof Error ? error.message : 'Resolution failed.',
            });
        }
    },

    resolveInterruptWithFiles: async (chatId: string, files: File[], content = '') => {
        set((state: ChatState) => ({
            isLoading: true,
            activeTools: [],
            agentStatus: null,
            messages: state.messages.filter(m => !m.interrupt),
            streamingMessage: '',
        }));
        try {
            const authHeader = await getAuthHeader();
            const form = new FormData();
            form.append('content', content);
            for (const file of files) form.append('files', file);

            const response = await fetch(`${getApiBase()}/chat/${chatId}/interrupt-resolve-with-files`, {
                method: 'POST',
                headers: { 'Authorization': authHeader },
                body: form,
            });
            if (!response.ok) {
                let detail = 'File upload resolution failed';
                try {
                    const payload = await response.json();
                    detail = payload?.detail || detail;
                } catch (_) {}
                throw new Error(detail);
            }
            await handleStream(response, set, get);
        } catch (error) {
            console.error('File resolution error:', error);
            set({
                isLoading: false,
                streamingMessage: error instanceof Error ? error.message : 'File upload resolution failed.',
            });
        }
    },
}));

export default useChatStore;
