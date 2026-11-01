/** Hostname without "www." for compact source labels; falls back to the input. */
export function hostOf(url: string): string {
    try {
        return new URL(url).hostname.replace(/^www\./, '');
    } catch {
        return url;
    }
}
