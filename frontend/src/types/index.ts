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

// ---- Business profile & research ----

export type QuestionType = 'text' | 'url' | 'textarea' | 'number' | 'select' | 'multiselect' | 'tags';

export interface OnboardingQuestion {
    id: string;
    label: string;
    type: QuestionType;
    required?: boolean;
    placeholder?: string;
    help?: string;
    allow_other?: boolean;
    options?: { value: string; label: string }[];
    show_if?: { field: string; in: string[] };
}

export interface OnboardingStep {
    id: string;
    title: string;
    description?: string;
    questions: OnboardingQuestion[];
}

export type AnswerValue = string | number | string[];
export type Answers = Record<string, AnswerValue>;

export type Basis = 'user_provided' | 'verified' | 'estimated' | 'unknown' | 'edited';

export interface ResearchField {
    value: string | string[] | null;
    basis: Basis;
    sources: string[];
    note?: string;
    suggested?: ResearchField;
}

export interface Competitor {
    name: string;
    website?: string | null;
    competition: 'direct' | 'indirect';
    relative_scale: 'similar' | 'smaller' | 'larger' | 'much_larger' | 'unknown';
    rationale: string;
    sources: string[];
    added_by_user?: boolean;
}

export interface Opportunity {
    title: string;
    area: string;
    rationale: string;
    basis: 'evidence' | 'general_practice' | 'user_added';
    sources: string[];
}

export interface ResearchResult {
    profile: Record<string, ResearchField>;
    public_facts: { fact: string; sources: string[] }[];
    competitors: Competitor[];
    industry_trends: { summary: string; sources: string[] }[];
    opportunities: Opportunity[];
    sources: { url: string; title: string; kind: string }[];
    warnings: string[];
    search_provider: string;
}

export interface ResearchRun {
    id: string;
    status: 'queued' | 'running' | 'completed' | 'failed';
    progress: { message: string; at: string }[];
    result: ResearchResult | null;
    error: string | null;
    created_at: string;
    finished_at: string | null;
}

export interface BusinessProfile {
    status: 'draft' | 'confirmed';
    answers: Answers;
    subdomain: string | null;
    competitors: Competitor[];
    opportunities: Opportunity[];
    provenance: Record<string, { basis: Basis; sources: string[] }>;
    confirmed_at: string | null;
    onboarding_dismissed: boolean;
}
