import React from 'react';
import { Building2, ChevronsUpDown } from 'lucide-react';
import useOrgStore from '../../store/orgStore';
import { switchOrganization } from '../../lib/session';

/** Current organization and role; a selector appears once the user belongs to several. */
export default function OrgSwitcher() {
    const { me, fetchMe } = useOrgStore();

    React.useEffect(() => {
        if (!me) fetchMe();
    }, [me, fetchMe]);

    if (!me) return <div className="h-12 mx-2 my-2 rounded-xl bg-muted/50 animate-pulse" />;

    const switchable = me.memberships.filter((m) => m.status === 'active' && m.organization_active);

    return (
        <div className="px-2 pt-2">
            <div className="relative flex items-center gap-2.5 rounded-xl border border-border bg-muted/40 px-3 py-2">
                <Building2 className="w-4 h-4 text-primary shrink-0" />
                <div className="min-w-0 flex-1">
                    <p className="text-sm font-semibold text-foreground truncate">{me.organization.name}</p>
                    <p className="text-[11px] text-muted-foreground capitalize">{me.role}</p>
                </div>
                {switchable.length > 1 && (
                    <>
                        <ChevronsUpDown className="w-4 h-4 text-muted-foreground shrink-0" />
                        {/* Native select laid over the card: accessible and works on touch devices. */}
                        <select
                            aria-label="Switch organization"
                            value={me.organization.id}
                            onChange={(e) => switchOrganization(e.target.value)}
                            className="absolute inset-0 w-full opacity-0 cursor-pointer"
                        >
                            {switchable.map((m) => (
                                <option key={m.organization_id} value={m.organization_id}>
                                    {m.organization_name} ({m.role})
                                </option>
                            ))}
                        </select>
                    </>
                )}
            </div>
        </div>
    );
}
