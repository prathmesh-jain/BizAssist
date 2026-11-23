export function timeAgo(iso: string | null | undefined): string {
    if (!iso) return 'never';
    const seconds = Math.floor((Date.now() - new Date(iso).getTime()) / 1000);
    if (seconds < 60) return 'just now';
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    const days = Math.floor(seconds / 86400);
    if (days < 7) return `${days} d ago`;
    return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short' });
}

export function clock(iso: string): string {
    return new Date(iso).toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}
