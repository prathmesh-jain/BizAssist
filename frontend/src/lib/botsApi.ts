import apiClient from '../api/client';

export type BotPlatform = 'whatsapp' | 'telegram';
export type BotAudience = 'team' | 'customer';

export interface BookingSettings {
    duration_minutes: number;
    days_ahead: number;
    start: string;
    end: string;
    weekdays_only: boolean;
    add_meet: boolean;
    max_per_contact: number;
}

export interface BotSettings {
    daily_cap: number;
    tools?: string[];
    capabilities?: string[];
    about?: string;
    greeting?: string;
    documents?: string[];
    booking?: BookingSettings;
    leads?: { tab: string; spreadsheet_id?: string | null };
}

export interface Explained { what: string; fix: string }

export interface BotItem {
    id: string;
    name: string;
    platform: BotPlatform;
    audience: BotAudience;
    status: 'active' | 'paused';
    handle: string | null;
    chat_link: string | null;
    linked: boolean | null;
    settings?: BotSettings;
    created_at?: string;
    last_inbound_at?: string | null;
    last_reply_at?: string | null;
    last_error?: string | null;
    last_error_at?: string | null;
    last_error_explained?: Explained | null;
    stats?: { replies_today: number; failed_today: number; conversations: number };
    setup?: SetupInfo;
    verified_name?: string | null;
}

export interface SetupInfo {
    webhook_url: string;
    verify_token?: string;
    webhook_fields?: string[];
    webhook?: 'registered' | 'failed' | 'missing_public_url';
    subscribed?: 'ok' | 'failed' | 'skipped';
    error?: string;
}

export interface BotOptions {
    team_tools: { id: string; label: string }[];
    customer_capabilities: { id: string; label: string }[];
    public_api_url_set: boolean;
}

export interface TraceStep {
    step: string;
    [key: string]: unknown;
}

export interface BotMessageItem {
    id: string;
    direction: 'in' | 'out';
    author: 'contact' | 'bot' | 'staff' | 'system';
    kind: string;
    text: string;
    status: string;
    error: string | null;
    error_code: string | null;
    explained: Explained | null;
    trace: TraceStep[];
    latency_ms: number | null;
    reply_to_id: string | null;
    created_at: string;
}

export interface ConversationItem {
    id: string;
    contact_name: string | null;
    contact_handle: string | null;
    mode: 'bot' | 'human';
    is_test: boolean;
    last_message_at: string | null;
    can_reply: boolean;
    problems: number;
    awaiting_approval: boolean;
    last_message: { text: string; direction: 'in' | 'out'; status: string } | null;
}

export interface ConversationDetail {
    conversation: {
        id: string;
        contact_name: string | null;
        contact_handle: string | null;
        mode: 'bot' | 'human';
        is_test: boolean;
        can_reply: boolean;
        reply_blocked_reason: string | null;
        chat_id: string | null;
    };
    messages: BotMessageItem[];
}

export interface HealthCheck { id: string; label: string; ok: boolean | null; detail: string; fix: string }

export const botsApi = {
    options: () => apiClient.get<BotOptions>('/bots/options').then((r) => r.data),
    list: () => apiClient.get<{ bots: BotItem[]; can_view: boolean; can_manage: boolean }>('/bots').then((r) => r.data),
    get: (id: string) => apiClient.get<BotItem>(`/bots/${id}`).then((r) => r.data),
    create: (body: { platform: BotPlatform; audience: BotAudience; name: string; credentials: Record<string, string>; settings?: Partial<BotSettings> }) =>
        apiClient.post<{ bot: BotItem; setup: SetupInfo }>('/bots', body).then((r) => r.data),
    update: (id: string, body: { name?: string; status?: 'active' | 'paused'; settings?: Partial<BotSettings>; credentials?: Record<string, string> }) =>
        apiClient.patch<{ bot: BotItem; setup: SetupInfo }>(`/bots/${id}`, body).then((r) => r.data),
    reconnect: (id: string) => apiClient.post<{ setup: SetupInfo }>(`/bots/${id}/reconnect`).then((r) => r.data.setup),
    remove: (id: string) => apiClient.delete(`/bots/${id}`),
    health: (id: string) => apiClient.get<{ checks: HealthCheck[] }>(`/bots/${id}/health`).then((r) => r.data.checks),
    test: (id: string, text: string) => apiClient.post<ConversationDetail>(`/bots/${id}/test`, { text }).then((r) => r.data),
    linkCode: (id: string) =>
        apiClient.post<{ code: string; message: string; expires_at: string; chat_link: string | null }>(`/bots/${id}/link-code`).then((r) => r.data),
    unlink: (id: string) => apiClient.delete(`/bots/${id}/link`),
    conversations: (id: string, params: { q?: string; problems?: boolean }) =>
        apiClient.get<{ conversations: ConversationItem[] }>(`/bots/${id}/conversations`, { params }).then((r) => r.data.conversations),
    conversation: (id: string, conversationId: string) =>
        apiClient.get<ConversationDetail>(`/bots/${id}/conversations/${conversationId}`).then((r) => r.data),
    reply: (id: string, conversationId: string, text: string) =>
        apiClient.post<BotMessageItem>(`/bots/${id}/conversations/${conversationId}/reply`, { text }).then((r) => r.data),
    setMode: (id: string, conversationId: string, mode: 'bot' | 'human') =>
        apiClient.patch(`/bots/${id}/conversations/${conversationId}`, { mode }),
    documents: () => apiClient.get<{ id: string; filename: string }[]>('/documents').then((r) => r.data),
};

export const PLATFORM_LABEL: Record<BotPlatform, string> = { whatsapp: 'WhatsApp', telegram: 'Telegram' };
