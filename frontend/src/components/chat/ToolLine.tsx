import React from 'react';
import { Check, Loader2, X, FileSpreadsheet, Search, FileText, Brain, CalendarDays } from 'lucide-react';
import type { ToolStatus } from '../../types';

/** Pretty display name + icon for known tool names */
function resolveToolDisplay(rawName: string): { label: string; icon: React.ReactNode; verb: string } {
    const n = rawName.toLowerCase();

    if (n.includes('planning'))
        return { label: 'Planning', icon: <Brain className="w-3.5 h-3.5" />, verb: 'Planning the steps…' };
    if (n.includes('execution'))
        return { label: 'Execution', icon: <Brain className="w-3.5 h-3.5" />, verb: 'Working through the steps…' };
    if (n.includes('calendar') || n.includes('meet') || n.includes('event'))
        return { label: 'Calendar', icon: <CalendarDays className="w-3.5 h-3.5" />, verb: 'Checking the calendar…' };
    if (n.includes('sheet') || n.includes('spreadsheet') || n.includes('google')) {
        if (n.includes('add') || n.includes('write') || n.includes('update') || n.includes('row'))
            return { label: 'Google Sheets', icon: <FileSpreadsheet className="w-3.5 h-3.5" />, verb: 'Editing spreadsheet…' };
        if (n.includes('read') || n.includes('get') || n.includes('values') || n.includes('range'))
            return { label: 'Google Sheets', icon: <FileSpreadsheet className="w-3.5 h-3.5" />, verb: 'Reading spreadsheet…' };
        return { label: 'Google Sheets', icon: <FileSpreadsheet className="w-3.5 h-3.5" />, verb: 'Accessing spreadsheet…' };
    }
    if (n.includes('search_available_tools'))
        return { label: 'Tool Search', icon: <Search className="w-3.5 h-3.5" />, verb: 'Picking the right tools…' };
    if (n.includes('search') || n.includes('web'))
        return { label: 'Web Search', icon: <Search className="w-3.5 h-3.5" />, verb: 'Searching the web…' };
    if (n.includes('retriev') || n.includes('rag') || n.includes('document') || n.includes('chunk'))
        return { label: 'Knowledge Base', icon: <FileText className="w-3.5 h-3.5" />, verb: 'Searching documents…' };
    if (n.includes('analys') || n.includes('invoice'))
        return { label: 'Analysing data', icon: <Brain className="w-3.5 h-3.5" />, verb: 'Analysing data…' };

    // Fallback: humanize the raw name
    const label = rawName.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase());
    return { label, icon: <Brain className="w-3.5 h-3.5" />, verb: `Using ${label}…` };
}

/** One line of activity: what the assistant is doing or has done. */
export default function ToolLine({ tool }: { tool: { name: string; status: ToolStatus } }) {
    const { label, icon, verb } = resolveToolDisplay(tool.name);
    const tone = {
        started: 'text-foreground',
        completed: 'text-muted-foreground',
        failed: 'text-destructive',
    }[tool.status];

    return (
        <div className={`flex items-center gap-2 text-[13px] ${tone}`}>
            <span className="flex h-4 w-4 items-center justify-center">
                {tool.status === 'started' && <Loader2 className="w-3.5 h-3.5 animate-spin text-primary" />}
                {tool.status === 'completed' && <Check className="w-3.5 h-3.5 text-success" strokeWidth={2.5} />}
                {tool.status === 'failed' && <X className="w-3.5 h-3.5" strokeWidth={2.5} />}
            </span>
            <span className="opacity-70">{icon}</span>
            <span>{tool.status === 'started' ? verb : tool.status === 'failed' ? `${label} didn’t work` : label}</span>
        </div>
    );
}

