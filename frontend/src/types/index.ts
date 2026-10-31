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

export type OrgRole = 'viewer' | 'member' | 'admin' | 'owner';

export interface Membership {
    organization_id: string;
    organization_name: string;
    role: OrgRole;
    status: 'active' | 'suspended' | 'invited';
    organization_active: boolean;
}

export interface Me {
    user: { id: string; email: string; full_name: string | null };
    organization: { id: string; name: string; slug: string };
    role: OrgRole;
    permissions: string[];
    memberships: Membership[];
}

export interface OrgMember {
    user_id: string;
    email: string;
    full_name: string | null;
    role: OrgRole;
    status: 'active' | 'suspended';
    joined_at: string;
    is_you: boolean;
    can_manage: boolean;
}

export interface OrgInvitation {
    id: string;
    email: string;
    role: OrgRole;
    status: string;
    expires_at: string;
    created_at: string;
}

export interface InvitationPreview {
    organization_id: string;
    organization_name: string;
    role: OrgRole;
    email: string;
    email_matches: boolean;
    expires_at: string;
}
