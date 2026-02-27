import React from 'react';
import { CheckCircle2, XCircle, Loader2, Link2, ExternalLink } from 'lucide-react';
import apiClient from '../../api/client';

interface ConnectionStatus {
    connected: boolean;
    auth_url?: string;
}

export default function SettingsView() {
    const [sheetsStatus, setSheetsStatus] = React.useState<ConnectionStatus | null>(null);
    const [isConnecting, setIsConnecting] = React.useState(false);

    React.useEffect(() => {
        const checkStatus = async () => {
            try {
                const res = await apiClient.get('/integrations/google-sheets/status');
                setSheetsStatus(res.data);
            } catch {
                setSheetsStatus({ connected: false });
            }
        };
        checkStatus();
    }, []);

    const handleConnectGoogleSheets = async () => {
        setIsConnecting(true);
        try {
            const res = await apiClient.post('/integrations/google-sheets/connect', {});
            if (res.data.auth_url) {
                const popup = window.open(res.data.auth_url, 'google-sheets-oauth', 'width=600,height=700,left=200,top=100');

                // Listen for the popup to signal completion
                const handleMessage = async (event: MessageEvent) => {
                    if (event.origin !== window.location.origin) return;
                    if (event.data?.type === 'OAUTH_COMPLETE' && event.data?.provider === 'google_sheets') {
                        window.removeEventListener('message', handleMessage);

                        const code = event.data?.code || '';
                        const state = event.data?.state || '';
                        const error = event.data?.error || '';
                        const errorDescription = event.data?.error_description || '';

                        try {
                            if (error) {
                                console.error('Google OAuth error', { error, errorDescription });
                            } else if (code && state) {
                                await apiClient.post('/integrations/google-sheets/callback', { code, state });
                            } else {
                                console.error('OAuth callback missing code/state');
                            }
                        } catch (e) {
                            console.error('OAuth callback exchange failed', e);
                        }

                        apiClient.get('/integrations/google-sheets/status')
                            .then(r => setSheetsStatus(r.data))
                            .catch(() => setSheetsStatus({ connected: false }));
                    }
                };
                window.addEventListener('message', handleMessage);

                // Fallback: poll every 2s while popup is open
                const poll = setInterval(() => {
                    if (!popup || popup.closed) {
                        clearInterval(poll);
                        window.removeEventListener('message', handleMessage);
                        apiClient.get('/integrations/google-sheets/status')
                            .then(r => setSheetsStatus(r.data))
                            .catch(() => setSheetsStatus({ connected: false }));
                    }
                }, 2000);
            }
        } catch (e) {
            console.error('Failed to initiate Google Sheets connection', e);
        } finally {
            setIsConnecting(false);
        }
    };

    // No longer needed — we use postMessage instead of URL params

    return (
        <div className="flex-1 overflow-y-auto bg-background p-6 lg:p-8">
            <div className="max-w-4xl mx-auto space-y-8">
                {/* Header */}
                <div>
                    <h2 className="text-3xl font-bold text-foreground tracking-tight">Settings & Integrations</h2>
                    <p className="text-muted-foreground mt-1 text-lg">Configure your BizAssist integrations and preferences.</p>
                </div>

                {/* Google Sheets Integration - flagship card */}
                <div className="bg-card border border-border rounded-2xl p-7 shadow-sm relative overflow-hidden">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-green-500/5 rounded-full -mr-16 -mt-16" />
                    <div className="flex flex-col sm:flex-row sm:items-start gap-6 relative z-10">
                        {/* Sheets Icon */}
                        <div className="w-14 h-14 rounded-2xl border border-border bg-muted flex items-center justify-center shrink-0">
                            <svg viewBox="0 0 24 24" className="w-8 h-8" fill="none">
                                <rect x="3" y="3" width="18" height="18" rx="2" fill="#0F9D58" />
                                <rect x="3" y="3" width="18" height="6" rx="2" fill="#188038" />
                                <rect x="8" y="1" width="8" height="22" rx="1" fill="white" opacity="0.08" />
                                <line x1="8" y1="3" x2="8" y2="21" stroke="white" strokeWidth="0.5" opacity="0.4" />
                                <line x1="3" y1="9" x2="21" y2="9" stroke="white" strokeWidth="0.5" opacity="0.4" />
                                <line x1="3" y1="15" x2="21" y2="15" stroke="white" strokeWidth="0.5" opacity="0.4" />
                            </svg>
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-3 flex-wrap">
                                <h3 className="text-xl font-bold text-foreground">Google Sheets</h3>
                                {sheetsStatus === null ? (
                                    <span className="px-2.5 py-1 bg-muted border border-border rounded-full text-[11px] font-bold text-muted-foreground">Checking...</span>
                                ) : sheetsStatus.connected ? (
                                    <span className="flex items-center gap-1.5 px-2.5 py-1 bg-green-500/10 text-green-600 dark:text-green-400 border border-green-500/20 rounded-full text-[11px] font-bold uppercase">
                                        <CheckCircle2 className="w-3.5 h-3.5" /> Connected
                                    </span>
                                ) : (
                                    <span className="flex items-center gap-1.5 px-2.5 py-1 bg-amber-500/10 text-amber-600 dark:text-amber-400 border border-amber-500/20 rounded-full text-[11px] font-bold uppercase">
                                        <XCircle className="w-3.5 h-3.5" /> Not Connected
                                    </span>
                                )}
                            </div>
                            <p className="text-muted-foreground mt-2 text-sm leading-relaxed max-w-xl">
                                Connect your Google account to let BizAssist read and write to your spreadsheets — log invoices, read expense data, and generate reports automatically.
                            </p>

                            {!sheetsStatus?.connected && (
                                <div className="mt-5 space-y-3">
                                    <button
                                        onClick={handleConnectGoogleSheets}
                                        disabled={isConnecting}
                                        className="flex items-center gap-2.5 px-5 py-2.5 bg-primary hover:bg-primary/90 text-primary-foreground rounded-xl font-bold text-sm shadow-lg shadow-primary/20 active:scale-[0.98] transition-all disabled:opacity-60"
                                    >
                                        {isConnecting ? (
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                        ) : (
                                            <Link2 className="w-4 h-4" />
                                        )}
                                        {isConnecting ? 'Opening authorization...' : 'Connect Google Sheets'}
                                    </button>
                                    <p className="text-xs text-muted-foreground flex items-start gap-1.5">
                                        <span className="mt-0.5 shrink-0">ℹ️</span>
                                        A Google sign-in window will open. Sign in and grant access — then return here. Your data is never stored by us.
                                    </p>
                                </div>
                            )}

                            {sheetsStatus?.connected && (
                                <div className="mt-5 space-y-3">
                                    <p className="text-sm text-muted-foreground bg-muted/50 rounded-xl px-4 py-3 border border-border">
                                        💬 <strong className="text-foreground">In the chat</strong>, you can ask BizAssist to read or write your expense data. A default BizAssist spreadsheet will be created after you connect and used automatically.
                                    </p>
                                    <button
                                        onClick={handleConnectGoogleSheets}
                                        className="flex items-center gap-2 text-xs text-muted-foreground hover:text-foreground transition-colors"
                                    >
                                        <ExternalLink className="w-3.5 h-3.5" />
                                        Reconnect or switch account
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                {/* AI Model Info */}
                <div className="bg-card border border-border rounded-2xl overflow-hidden shadow-sm">
                    <div className="px-6 py-4 border-b border-border">
                        <h3 className="text-lg font-bold text-foreground">AI Configuration</h3>
                    </div>
                    <div className="divide-y divide-border">
                        {[
                            { label: 'Primary Model', desc: 'Chat, analysis, invoice processing', badge: 'gpt-4.1' },
                            { label: 'Fast Model', desc: 'Guardrails, summarization, classification', badge: 'gpt-4.1-mini' },
                            { label: 'Embeddings', desc: 'Document indexing and RAG retrieval', badge: 'text-embedding-3-small' },
                        ].map(item => (
                            <div key={item.label} className="flex items-center justify-between px-6 py-4">
                                <div>
                                    <p className="font-semibold text-foreground text-sm">{item.label}</p>
                                    <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                                </div>
                                <span className="px-3 py-1 bg-muted border border-border rounded-lg text-xs font-bold text-muted-foreground whitespace-nowrap ml-4">{item.badge}</span>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Guardrails */}
                <div className="bg-card border border-border rounded-2xl p-6 shadow-sm">
                    <h3 className="text-lg font-bold text-foreground mb-3">Safety Guardrails</h3>
                    <p className="text-sm text-muted-foreground mb-4">BizAssist is built for business operations. It automatically blocks out-of-scope requests:</p>
                    <div className="flex gap-5">
                        {['Code generation', 'SQL queries'].map(item => (
                            <div key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
                                <XCircle className="w-4 h-4 text-destructive shrink-0" />
                                <span>{item}</span>
                            </div>
                        ))}
                    </div>
                </div>
            </div>
        </div>
    );
}
