export interface AISettings {
    provider: 'openai';
    has_api_key: boolean;
    chat_enabled: boolean;
    guardrail_enabled: boolean;
    primary_model: string;
    fast_model: string;
    nano_model: string;
}

export interface Chat {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
}

interface Attachment {
    id: string;
    filename: string;
    content_type: string;
    size: number;
    url: string;
    local_url?: string;
}

export type ToolStatus = 'started' | 'completed' | 'failed';

export interface ToolCall {
    name: string;
    status: ToolStatus;
    citations?: string[];
}

type InterruptType = 'file_upload' | 'text_input' | 'yes_no_confirmation' | 'accept_decline';

export interface Interrupt {
    id: string;
    question: string;
    interrupt_type?: InterruptType;
    action_required?: string;
    data?: any;
}

export interface Message {
    id: string;
    role: 'user' | 'assistant' | 'system';
    content: string;
    tool_calls?: ToolCall[];
    attachments?: Attachment[];
    interrupt?: Interrupt;
    created_at: string;
}

export interface DocumentMetadata {
    id: string;
    filename: string;
    file_type: string;
    chunk_count: number;
    created_at: string;
}
