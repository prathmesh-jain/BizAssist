import React from 'react';
import { ChevronsUpDown } from 'lucide-react';
import useOrgStore from '../../store/orgStore';
import { switchOrganization } from '../../lib/session';

/** Current organization and role; a selector appears once the user belongs to several. */
export default function OrgSwitcher() {
    const { me, fetchMe } = useOrgStore();

    React.useEffect(() => {
        if (!me) fetchMe();
    }, [me, fetchMe]);

    if (!me) return <div className="h-11 mx-3 rounded-md bg-muted/60 animate-pulse" />;

    const switchable = me.memberships.filter((m) => m.status === 'active' && m.organization_active);
    const initial = me.organization.name.trim()[0]?.toUpperCase() || '·';

    return (
        <div className="px-3">
            <div className={`relative flex items-center gap-2.5 rounded-md px-2 py-1.5 ${switchable.length > 1 ? 'hover:bg-muted' : ''}`}>
                <span className="font-display w-7 h-7 rounded-lg bg-gradient-to-br from-orange-400 to-rose-500 text-white flex items-center justify-center text-sm font-bold shrink-0">
                    {initial}
                </span>
                <div className="min-w-0 flex-1 leading-tight">
                    <p className="text-sm font-medium text-foreground truncate">{me.organization.name}</p>
                    <p className="text-xs text-muted-foreground capitalize">{me.role}</p>
                </div>
                {switchable.length > 1 && (
                    <>
                        <ChevronsUpDown className="w-4 h-4 text-muted-foreground shrink-0" />
                        {/* Native select laid over the row: accessible and works on touch devices. */}
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
