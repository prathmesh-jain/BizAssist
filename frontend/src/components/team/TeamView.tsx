import React from 'react';
import { Check, Copy, Loader2, LogOut, Mail, Pencil, Trash2, UserPlus, X } from 'lucide-react';
import apiClient, { apiErrorDetail } from '../../api/client';
import useOrgStore, { hasPermission } from '../../store/orgStore';
import { setActiveOrganizationId } from '../../lib/session';
import type { OrgInvitation, OrgMember, OrgRole } from '../../types';

const ROLES: OrgRole[] = ['viewer', 'member', 'admin', 'owner'];
const ROLE_RANK: Record<OrgRole, number> = { viewer: 0, member: 1, admin: 2, owner: 3 };
const ROLE_HINT: Record<OrgRole, string> = {
    viewer: 'Chat and read shared data',
    member: 'Also upload documents and update spreadsheets',
    admin: 'Also manage members, invitations, and integrations',
    owner: 'Full control, including other owners',
};

// Mirrors backend app.authz.can_assign_role: owners grant anything, others only lower roles.
const assignableRoles = (actor: OrgRole | undefined): OrgRole[] =>
    !actor ? [] : actor === 'owner' ? ROLES : ROLES.filter((r) => ROLE_RANK[r] < ROLE_RANK[actor]);

const errorDetail = apiErrorDetail;

const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });

export default function TeamView() {
    const { me, fetchMe } = useOrgStore();
    const [members, setMembers] = React.useState<OrgMember[]>([]);
    const [invitations, setInvitations] = React.useState<OrgInvitation[]>([]);
    const [loading, setLoading] = React.useState(true);
    const [error, setError] = React.useState('');
    const [busyId, setBusyId] = React.useState<string | null>(null);
    const [removeTarget, setRemoveTarget] = React.useState<OrgMember | null>(null);
    const [confirmLeave, setConfirmLeave] = React.useState(false);

    const canManage = hasPermission(me, 'member.manage');
    const canRename = hasPermission(me, 'organization.manage');
    const roleChoices = assignableRoles(me?.role);

    const load = React.useCallback(async () => {
        setError('');
        try {
            const [membersRes, invitesRes] = await Promise.all([
                apiClient.get<{ members: OrgMember[] }>('/organization/members'),
                canManage
                    ? apiClient.get<{ invitations: OrgInvitation[] }>('/organization/invitations')
                    : Promise.resolve({ data: { invitations: [] as OrgInvitation[] } }),
            ]);
            setMembers(membersRes.data.members);
            setInvitations(invitesRes.data.invitations);
        } catch (e) {
            setError(errorDetail(e, 'Could not load your team.'));
        } finally {
            setLoading(false);
        }
    }, [canManage]);

    React.useEffect(() => {
        if (!me) fetchMe();
    }, [me, fetchMe]);

    React.useEffect(() => {
        if (me) load();
    }, [me, load]);

    const run = async (id: string, action: () => Promise<unknown>) => {
        setBusyId(id);
        setError('');
        try {
            await action();
            await load();
        } catch (e) {
            setError(errorDetail(e, 'That change could not be saved.'));
        } finally {
            setBusyId(null);
        }
    };

    const updateMember = (m: OrgMember, body: { role?: OrgRole; status?: 'active' | 'suspended' }) =>
        run(m.user_id, () => apiClient.patch(`/organization/members/${m.user_id}`, body));

    const handleLeave = async () => {
        setBusyId('leave');
        setError('');
        try {
            await apiClient.post('/organization/leave');
            setActiveOrganizationId(null);
            window.location.assign('/app/chat');
        } catch (e) {
            setError(errorDetail(e, 'Could not leave this organization.'));
            setConfirmLeave(false);
        } finally {
            setBusyId(null);
        }
    };

    if (!me) {
        return <div className="p-8 text-sm text-muted-foreground">Loading…</div>;
    }

    return (
        <div className="flex-1 overflow-y-auto px-4 py-8 sm:px-8 lg:py-12">
            <div className="max-w-3xl mx-auto space-y-6">
                <div className="rise-in border-b border-border pb-6">
                    <p className="eyebrow mb-3 inline-flex items-center gap-2 rounded-full border border-border bg-card px-2.5 py-1"><span className="h-1.5 w-1.5 rounded-full bg-brand-gradient" />Team</p>
                    <OrganizationName name={me.organization.name} editable={canRename} onSaved={fetchMe} />
                    <p className="text-muted-foreground mt-2 text-[15px]">
                        You are {me.role === 'admin' || me.role === 'owner' ? 'an' : 'a'}{' '}
                        <span className="font-semibold text-foreground">{me.role}</span> of this organization.
                    </p>
                </div>

                {error && (
                    <div className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                        {error}
                    </div>
                )}

                {canManage && <InviteCard roles={roleChoices} onInvited={load} />}

                <section className="bg-card border border-border rounded-2xl">
                    <div className="px-5 sm:px-6 py-4 border-b border-border">
                        <h3 className="font-display text-xl font-semibold text-foreground">People <span className="font-sans text-sm text-muted-foreground tabular-nums">{members.length || ''}</span></h3>
                    </div>
                    {loading ? (
                        <div className="p-6 text-sm text-muted-foreground flex items-center gap-2">
                            <Loader2 className="w-4 h-4 animate-spin" /> Loading members…
                        </div>
                    ) : (
                        <ul className="divide-y divide-border">
                            {members.map((m, idx) => (
                                <li key={m.user_id} className="px-5 sm:px-6 py-4 flex flex-wrap items-center gap-3">
                                    <div className={`${['chip-green', 'chip-blue', 'chip-violet', 'chip-amber', 'chip-teal', 'chip-rose'][idx % 6]} w-9 h-9 rounded-full text-sm font-semibold flex items-center justify-center shrink-0`}>
                                        {(m.full_name || m.email)[0]?.toUpperCase()}
                                    </div>
                                    <div className="min-w-0 flex-1 basis-48">
                                        <p className="font-semibold text-foreground truncate">
                                            {m.full_name || m.email}
                                            {m.is_you && <span className="ml-2 text-xs font-medium text-muted-foreground">(you)</span>}
                                        </p>
                                        <p className="text-sm text-muted-foreground truncate">{m.email}</p>
                                    </div>

                                    {m.status === 'suspended' && (
                                        <span className="px-2.5 py-1 rounded-full text-[11px] font-semibold uppercase bg-warning/10 text-warning border border-warning/25">
                                            Suspended
                                        </span>
                                    )}

                                    {m.can_manage ? (
                                        <select
                                            aria-label={`Role for ${m.email}`}
                                            value={m.role}
                                            disabled={busyId === m.user_id}
                                            onChange={(e) => updateMember(m, { role: e.target.value as OrgRole })}
                                            className="rounded-xl border border-border bg-background px-3 py-2 text-sm text-foreground"
                                        >
                                            {Array.from(new Set([m.role, ...roleChoices])).map((r) => (
                                                <option key={r} value={r} disabled={!roleChoices.includes(r)}>
                                                    {r}
                                                </option>
                                            ))}
                                        </select>
                                    ) : (
                                        <span className="px-3 py-1.5 rounded-xl bg-muted text-sm font-medium text-foreground capitalize">
                                            {m.role}
                                        </span>
                                    )}

                                    {m.can_manage && (
                                        <div className="flex items-center gap-1">
                                            <button
                                                onClick={() => updateMember(m, { status: m.status === 'active' ? 'suspended' : 'active' })}
                                                disabled={busyId === m.user_id}
                                                className="px-3 py-2 rounded-xl text-sm border border-border text-foreground hover:bg-muted transition-colors disabled:opacity-50"
                                            >
                                                {m.status === 'active' ? 'Suspend' : 'Reactivate'}
                                            </button>
                                            <button
                                                onClick={() => setRemoveTarget(m)}
                                                disabled={busyId === m.user_id}
                                                title="Remove from organization"
                                                aria-label={`Remove ${m.email}`}
                                                className="p-2 rounded-xl text-destructive hover:bg-destructive/10 transition-colors disabled:opacity-50"
                                            >
                                                <Trash2 className="w-4 h-4" />
                                            </button>
                                        </div>
                                    )}
                                </li>
                            ))}
                        </ul>
                    )}
                </section>

                {canManage && invitations.length > 0 && (
                    <section className="bg-card border border-border rounded-2xl">
                        <div className="px-5 sm:px-6 py-4 border-b border-border">
                            <h3 className="font-display text-xl font-semibold text-foreground">Waiting to join</h3>
                        </div>
                        <ul className="divide-y divide-border">
                            {invitations.map((inv) => {
                                const expired = new Date(inv.expires_at) <= new Date();
                                return (
                                    <li key={inv.id} className="px-5 sm:px-6 py-4 flex flex-wrap items-center gap-3">
                                        <Mail className="w-4 h-4 text-muted-foreground shrink-0" />
                                        <div className="min-w-0 flex-1 basis-48">
                                            <p className="font-medium text-foreground truncate">{inv.email}</p>
                                            <p className="text-xs text-muted-foreground">
                                                <span className="capitalize">{inv.role}</span> ·{' '}
                                                {expired ? 'expired' : `expires ${formatDate(inv.expires_at)}`}
                                            </p>
                                        </div>
                                        <button
                                            onClick={() => run(inv.id, () => apiClient.delete(`/organization/invitations/${inv.id}`))}
                                            disabled={busyId === inv.id}
                                            className="px-3 py-2 rounded-xl text-sm border border-border text-foreground hover:bg-muted transition-colors disabled:opacity-50"
                                        >
                                            Revoke
                                        </button>
                                    </li>
                                );
                            })}
                        </ul>
                    </section>
                )}

                <section className="bg-card border border-destructive/20 rounded-lg p-5 sm:p-6 flex flex-wrap items-center gap-4 justify-between">
                    <div>
                        <h3 className="font-semibold text-foreground">Leave this organization</h3>
                        <p className="text-sm text-muted-foreground">
                            You will lose access to its documents and integrations. Your chats here stay private to you.
                        </p>
                    </div>
                    <button
                        onClick={() => setConfirmLeave(true)}
                        className="flex items-center gap-2 px-4 py-2 rounded-xl border border-destructive/40 text-destructive hover:bg-destructive/10 transition-colors text-sm font-semibold"
                    >
                        <LogOut className="w-4 h-4" /> Leave
                    </button>
                </section>
            </div>

            {removeTarget && (
                <ConfirmDialog
                    title="Remove member?"
                    body={<><span className="font-semibold text-foreground">{removeTarget.email}</span> will lose access to this organization. You can invite them again later.</>}
                    confirmLabel="Remove"
                    busy={busyId === removeTarget.user_id}
                    onCancel={() => setRemoveTarget(null)}
                    onConfirm={async () => {
                        const target = removeTarget;
                        await run(target.user_id, () => apiClient.delete(`/organization/members/${target.user_id}`));
                        setRemoveTarget(null);
                    }}
                />
            )}

            {confirmLeave && (
                <ConfirmDialog
                    title={`Leave ${me.organization.name}?`}
                    body="You'll need a new invitation to rejoin."
                    confirmLabel="Leave"
                    busy={busyId === 'leave'}
                    onCancel={() => setConfirmLeave(false)}
                    onConfirm={handleLeave}
                />
            )}
        </div>
    );
}

function OrganizationName({ name, editable, onSaved }: { name: string; editable: boolean; onSaved: () => Promise<void> }) {
    const [editing, setEditing] = React.useState(false);
    const [value, setValue] = React.useState(name);
    const [saving, setSaving] = React.useState(false);
    const [error, setError] = React.useState('');

    React.useEffect(() => setValue(name), [name]);

    const save = async () => {
        setSaving(true);
        setError('');
        try {
            await apiClient.patch('/organization', { name: value });
            await onSaved();
            setEditing(false);
        } catch (e) {
            setError(errorDetail(e, 'Could not rename the organization.'));
        } finally {
            setSaving(false);
        }
    };

    if (!editing) {
        return (
            <div className="flex items-center gap-2">
                <h1 className="font-display text-3xl sm:text-[2.25rem] leading-[1.1] font-semibold text-foreground break-words">{name}</h1>
                {editable && (
                    <button
                        onClick={() => setEditing(true)}
                        title="Rename organization"
                        aria-label="Rename organization"
                        className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-muted transition-colors"
                    >
                        <Pencil className="w-4 h-4" />
                    </button>
                )}
            </div>
        );
    }

    return (
        <div>
            <div className="flex flex-wrap items-center gap-2">
                <input
                    value={value}
                    onChange={(e) => setValue(e.target.value)}
                    onKeyDown={(e) => e.key === 'Enter' && save()}
                    maxLength={120}
                    autoFocus
                    aria-label="Organization name"
                    className="flex-1 min-w-0 basis-56 rounded-xl border border-border bg-background px-3 py-2 text-xl font-semibold text-foreground"
                />
                <button onClick={save} disabled={saving} aria-label="Save name" className="p-2 rounded-xl btn-glow disabled:opacity-50">
                    {saving ? <Loader2 className="w-5 h-5 animate-spin" /> : <Check className="w-5 h-5" />}
                </button>
                <button onClick={() => { setEditing(false); setValue(name); }} aria-label="Cancel rename" className="p-2 rounded-xl border border-border text-foreground hover:bg-muted">
                    <X className="w-5 h-5" />
                </button>
            </div>
            {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
        </div>
    );
}

function InviteCard({ roles, onInvited }: { roles: OrgRole[]; onInvited: () => Promise<void> }) {
    const [email, setEmail] = React.useState('');
    const [role, setRole] = React.useState<OrgRole>('member');
    const [sending, setSending] = React.useState(false);
    const [error, setError] = React.useState('');
    const [link, setLink] = React.useState<{ url: string; email: string } | null>(null);
    const [copied, setCopied] = React.useState(false);

    const submit = async (e: React.FormEvent) => {
        e.preventDefault();
        setSending(true);
        setError('');
        setCopied(false);
        try {
            const res = await apiClient.post('/organization/invitations', { email: email.trim(), role });
            setLink({ url: res.data.invite_url, email: res.data.invitation.email });
            setEmail('');
            await onInvited();
        } catch (err) {
            setError(errorDetail(err, 'Could not create the invitation.'));
        } finally {
            setSending(false);
        }
    };

    const copy = async () => {
        if (!link) return;
        try {
            await navigator.clipboard.writeText(link.url);
            setCopied(true);
        } catch {
            setCopied(false);
        }
    };

    return (
        <section className="bg-card border border-border rounded-2xl p-5 sm:p-6">
            <div className="flex items-center gap-2">
                <UserPlus className="w-5 h-5 text-primary" />
                <h3 className="font-display text-xl font-semibold text-foreground">Invite someone</h3>
            </div>
            <form onSubmit={submit} className="mt-4 flex flex-wrap gap-3">
                <input
                    type="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="name@company.com"
                    aria-label="Email to invite"
                    className="flex-1 min-w-0 basis-60 rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground"
                />
                <select
                    value={role}
                    onChange={(e) => setRole(e.target.value as OrgRole)}
                    aria-label="Role for invitee"
                    className="rounded-xl border border-border bg-background px-3 py-2.5 text-sm text-foreground"
                >
                    {roles.map((r) => (
                        <option key={r} value={r}>{r}</option>
                    ))}
                </select>
                <button
                    type="submit"
                    disabled={sending}
                    className="flex items-center gap-2 px-5 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground rounded-xl font-semibold text-sm disabled:opacity-60"
                >
                    {sending && <Loader2 className="w-4 h-4 animate-spin" />}
                    Create invite link
                </button>
            </form>
            <p className="mt-2 text-xs text-muted-foreground">{ROLE_HINT[role]}.</p>
            {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

            {link && (
                <div className="mt-4 rounded-xl border border-primary/20 bg-primary/5 p-4">
                    <p className="text-sm text-foreground">
                        Invites aren’t emailed yet, so send this link to <span className="font-semibold">{link.email}</span> yourself. It works once, only for that email, and expires in 7 days.
                        Copy it now; it won’t be shown again.
                    </p>
                    <div className="mt-3 flex flex-wrap gap-2">
                        <input
                            readOnly
                            value={link.url}
                            onFocus={(e) => e.target.select()}
                            aria-label="Invitation link"
                            className="flex-1 min-w-0 basis-60 rounded-lg border border-border bg-background px-3 py-2 text-xs font-mono text-foreground"
                        />
                        <button
                            onClick={copy}
                            className="flex items-center gap-1.5 px-3 py-2 rounded-2xl border border-border bg-card text-sm text-foreground hover:bg-muted"
                        >
                            {copied ? <Check className="w-4 h-4" /> : <Copy className="w-4 h-4" />}
                            {copied ? 'Copied' : 'Copy'}
                        </button>
                    </div>
                </div>
            )}
        </section>
    );
}

function ConfirmDialog({ title, body, confirmLabel, busy, onCancel, onConfirm }: {
    title: string;
    body: React.ReactNode;
    confirmLabel: string;
    busy: boolean;
    onCancel: () => void;
    onConfirm: () => void;
}) {
    return (
        <div className="fixed inset-0 z-[70] flex items-center justify-center bg-foreground/30 p-4">
            <div role="dialog" aria-modal="true" className="w-full max-w-md rounded-2xl border border-border bg-card shadow-xl p-6">
                <h3 className="font-display text-xl font-semibold text-foreground">{title}</h3>
                <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{body}</p>
                <div className="mt-6 flex items-center justify-end gap-3">
                    <button onClick={onCancel} disabled={busy} className="px-4 py-2 rounded-xl border border-border text-foreground hover:bg-muted transition-colors disabled:opacity-50">
                        Cancel
                    </button>
                    <button onClick={onConfirm} disabled={busy} className="px-4 py-2 rounded-xl bg-destructive text-destructive-foreground hover:bg-destructive/90 transition-colors disabled:opacity-50">
                        {busy ? 'Working…' : confirmLabel}
                    </button>
                </div>
            </div>
        </div>
    );
}
