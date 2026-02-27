import { create } from 'zustand';
import apiClient, { getAuthHeader } from '../api/client';
import { triggerUnauthorized } from '../api/client';
import type { Chat, Message, ToolStatus, Attachment, ToolCall } from '../types';

interface ChatState {
    chats: Chat[];
    activeChatId: string | null;
    messages: Message[];
    isLoading: boolean;
    streamingMessage: string;
    activeTools: { name: string; status: ToolStatus }[];
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
}

/**
 * Get the API base URL, ensuring it ends with /api.
 * Uses the raw env var (without the apiClient abstraction) because SSE
 * streaming requires raw fetch, not axios.
 */
const getApiBase = () => {
    const base = (import.meta.env.VITE_API_URL || 'http://localhost:8000').replace(/\/+$/, '');
    return base.endsWith('/api') ? base : `${base}/api`;
};

const useChatStore = create<ChatState>((set, get) => ({
    chats: [],
    activeChatId: null,
    messages: [],
    isLoading: false,
    streamingMessage: '',
    activeTools: [],
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

    setActiveChat: async (id) => {
        set({ activeChatId: id, messages: [], streamingMessage: '', activeTools: [], hasMoreMessages: true });

        try {
            const authHeader = await getAuthHeader();
            const response = await fetch(`${getApiBase()}/chat/${id}/messages?limit=10`, {
                headers: { 'Authorization': authHeader }
            });

            if (response.ok) {
                const data = await response.json();
                const msgs: Message[] = data.messages ?? data;
                const hasMore: boolean = data.has_more ?? msgs.length >= 10;
                // Dedup by id just in case
                const seen = new Set<string>();
                const unique = msgs
                    .filter(m => { if (seen.has(m.id)) return false; seen.add(m.id); return true; })
                    .map((m) => ({
                        ...m,
                        tool_calls: (m.tool_calls || []).map((tc: any) => ({
                            name: String(tc?.name ?? ''),
                            status: (tc?.status as ToolStatus) || 'completed',
                            citations: Array.isArray(tc?.citations) ? tc.citations.map(String) : undefined,
                        } as ToolCall))
                    }));
                set({ messages: unique, hasMoreMessages: hasMore });
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

    sendMessage: async (content, attachments = []) => {
        let { activeChatId } = get();
        if (!activeChatId) {
            activeChatId = await get().createChat('New Chat');
        }

        set({ isLoading: true, streamingMessage: '', activeTools: [] });

        // Add user message optimistically
        const optimisticAtts: Attachment[] = (attachments || []).map((a, idx) => ({
            id: `local-${Date.now()}-${idx}`,
            filename: a.file.name,
            content_type: a.file.type || 'application/octet-stream',
            size: a.file.size,
            url: '',
            local_url: a.preview,
        }));

        const userMsg: Message = {
            id: Date.now().toString(),
            role: 'user',
            content,
            attachments: optimisticAtts.length > 0 ? optimisticAtts : undefined,
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
                headers: {
                    'Authorization': authHeader
                }
            };

            if (hasFiles) {
                const form = new FormData();
                form.append('content', content || '');
                for (const a of attachments) {
                    form.append('files', a.file);
                }
                fetchInit.body = form;
            } else {
                (fetchInit.headers as any)['Content-Type'] = 'application/json';
                fetchInit.body = JSON.stringify({ content });
            }

            const response = await fetch(url, fetchInit);

            if (response.status === 401) {
                triggerUnauthorized();
                throw new Error('Unauthorized');
            }

            if (!response.ok) {
                let errText = 'Request failed.';
                try {
                    const asJson = await response.json();
                    if (asJson?.detail) errText = String(asJson.detail);
                    else errText = JSON.stringify(asJson);
                } catch (_) {
                    try {
                        errText = await response.text();
                    } catch (_) {
                        // ignore
                    }
                }
                set({ isLoading: false, streamingMessage: errText || 'Request failed.' });
                throw new Error(errText || 'Stream failed');
            }

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
                        const parsed = JSON.parse(data);

                        if (parsed.type === 'token') {
                            if (!hasReceivedFirstToken) {
                                hasReceivedFirstToken = true;
                                set({ isLoading: false });
                            }
                            set((state) => ({ streamingMessage: state.streamingMessage + (parsed.content ?? '') }));

                        } else if (parsed.type === 'tool_start') {
                            const toolName = parsed.name ?? parsed.tool;
                            if (toolName) {
                                const meta = pendingToolMeta[String(toolName)] || {};
                                set((state) => ({
                                    activeTools: [...state.activeTools, {
                                        name: toolName,
                                        status: 'started' as ToolStatus,
                                        ...meta,
                                    }]
                                }));
                            }

                        } else if (parsed.type === 'tool_end') {
                            const toolName = parsed.name ?? parsed.tool;
                            if (toolName) {
                                set((state) => ({
                                    activeTools: state.activeTools.map(t =>
                                        t.name === toolName ? { ...t, status: 'completed' as ToolStatus } : t
                                    )
                                }));
                            }

                        } else if (parsed.type === 'source') {
                            const toolName = parsed.name ?? parsed.tool ?? 'Source';
                            pendingToolMeta[String(toolName)] = {
                                citations: Array.isArray(parsed.citations) ? parsed.citations.map(String) : undefined,
                            };
                            // If the tool pill already exists (rare ordering), patch it.
                            set((state) => ({
                                activeTools: state.activeTools.map(t =>
                                    t.name === toolName ? { ...t, ...pendingToolMeta[String(toolName)] } : t
                                )
                            }));

                        } else if (parsed.type === 'title_update') {
                            // Update chat title in sidebar in real-time
                            const chatId = parsed.chat_id;
                            const newTitle = parsed.title;
                            if (chatId && newTitle) {
                                set((state) => ({
                                    chats: state.chats.map(c =>
                                        c.id === chatId ? { ...c, title: newTitle } : c
                                    )
                                }));
                            }

                        } else if (parsed.type === 'error') {
                            if (!hasReceivedFirstToken) {
                                set({ isLoading: false });
                            }
                            const errorText = parsed.content ? String(parsed.content) : 'Something went wrong.';
                            set((state) => ({ streamingMessage: state.streamingMessage || errorText }));
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
                        set((state) => ({ streamingMessage: state.streamingMessage + data }));
                    }
                }
            }

            set({ isLoading: false });

            // Finish streaming — fetch the real persisted message from server
            // (avoids adding a synthetic local copy that collides with server IDs)
            const { activeChatId: finalChatId, streamingMessage: finalText } = get();
            const aiMsg: Message = {
                id: (Date.now() + 1).toString(), // temporary — replaced on next setActiveChat
                role: 'assistant',
                content: finalText,
                tool_calls: get().activeTools,
                created_at: new Date().toISOString()
            };
            set((state) => ({
                messages: [...state.messages, aiMsg],
                streamingMessage: '',
                activeTools: []
            }));

            // Background-refresh to swap in the real server ID (fixes dup on loadMore)
            if (finalChatId) {
                try {
                    const authHeader = await getAuthHeader();
                    const r = await fetch(`${getApiBase()}/chat/${finalChatId}/messages?limit=10`, {
                        headers: { 'Authorization': authHeader }
                    });
                    if (r.ok) {
                        const d = await r.json();
                        const fresh: Message[] = d.messages ?? d;
                        const hasMore: boolean = d.has_more ?? fresh.length >= 10;
                        const seen = new Set<string>();
                        const unique = fresh
                            .filter((m: Message) => { if (seen.has(m.id)) return false; seen.add(m.id); return true; })
                            .map((m) => ({
                                ...m,
                                tool_calls: (m.tool_calls || []).map((tc: any) => ({
                                    name: String(tc?.name ?? ''),
                                    status: (tc?.status as ToolStatus) || 'completed',
                                    citations: Array.isArray(tc?.citations) ? tc.citations.map(String) : undefined,
                                } as ToolCall))
                            }));
                        set({ messages: unique, hasMoreMessages: hasMore });
                    }
                } catch (_) {
                    // Non-critical — cached local copy is fine
                }
            }

        } catch (error) {
            console.error('Streaming error:', error);
            const msg = error instanceof Error ? error.message : 'Something went wrong.';
            set({ isLoading: false, streamingMessage: get().streamingMessage || msg });
        }
    },

    loadMoreMessages: async () => {
        const { activeChatId, messages, hasMoreMessages, isLoadingMore } = get();
        if (!activeChatId || !hasMoreMessages || isLoadingMore) return;

        set({ isLoadingMore: true });

        try {
            // Get the oldest message ID to fetch older messages
            const oldestMsg = messages[0];
            const query = oldestMsg?.id ? `?before=${encodeURIComponent(oldestMsg.id)}&limit=10` : `?limit=10`;

            const authHeader = await getAuthHeader();
            const response = await fetch(`${getApiBase()}/chat/${activeChatId}/messages${query}`, {
                headers: { 'Authorization': authHeader }
            });

            if (!response.ok) throw new Error('Failed to load more messages');

            const data = await response.json();
            // API now returns {messages: [...], has_more: bool}
            const olderMessages: Message[] = data.messages ?? data;
            const hasMore: boolean = data.has_more ?? olderMessages.length >= 10;

            if (olderMessages.length === 0) {
                set({ hasMoreMessages: false, isLoadingMore: false });
            } else {
                set((state) => {
                    // Dedup: don't prepend messages already in state
                    const existingIds = new Set(state.messages.map(m => m.id));
                    const newOnes = olderMessages.filter(m => !existingIds.has(m.id));
                    return {
                        messages: [...newOnes, ...state.messages],
                        hasMoreMessages: hasMore,
                        isLoadingMore: false
                    };
                });
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
        } catch (error) {
            console.error('Failed to delete chat:', error);
        }
    },

    renameChat: async (id: string, title: string) => {
        try {
            const response = await apiClient.patch(`/chat/${id}`, { title });
            const updatedChat = response.data;
            set((state) => ({
                chats: state.chats.map(c => c.id === id ? updatedChat : c)
            }));
        } catch (error) {
            console.error('Failed to rename chat:', error);
        }
    },

    clearStreaming: () => set({ streamingMessage: '', activeTools: [] })
}));

export default useChatStore;
