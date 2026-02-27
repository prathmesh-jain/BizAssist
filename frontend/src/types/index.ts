export interface User {
    id: string;
    email: string;
    fullName?: string;
    clerkId: string;
    imageUrl?: string;
}

export interface Chat {
    id: string;
    title: string;
    created_at: string;
    updated_at: string;
}

export interface Attachment {
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

export interface Message {
    id: string;
    role: 'user' | 'assistant';
    content: string;
    tool_calls?: ToolCall[];
    attachments?: Attachment[];
    created_at: string;
}

export interface DocumentMetadata {
    id: string;
    filename: string;
    file_type: string;
    chunk_count: number;
    created_at: string;
}
