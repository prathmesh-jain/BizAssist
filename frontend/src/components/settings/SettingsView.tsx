import React from 'react';
import { XCircle, Loader2, Link2, RefreshCw } from 'lucide-react';
import PageHeader from '../ui/PageHeader';
import StatusChip from '../ui/StatusChip';
import apiClient from '../../api/client';
import useSettingsStore from '../../store/settingsStore';
import GoogleCalendarCard from './GoogleCalendarCard';

interface ConnectionStatus {
    connected: boolean;
    auth_url?: string;
}

// gpt-4.1-nano was retired by OpenAI (requests now fail with model_not_found).
const MODEL_OPTIONS = ['gpt-4.1', 'gpt-4.1-mini', 'gpt-5-nano'];

export default function SettingsView() {
    const [sheetsStatus, setSheetsStatus] = React.useState<ConnectionStatus | null>(null);
    const [apiKeyInput, setApiKeyInput] = React.useState('');
    const [guardrailEnabled, setGuardrailEnabled] = React.useState(true);
    const [primaryModel, setPrimaryModel] = React.useState('gpt-4.1');
    const [fastModel, setFastModel] = React.useState('gpt-4.1-mini');
    const [nanoModel, setNanoModel] = React.useState('gpt-4.1-mini');
    const [saveMessage, setSaveMessage] = React.useState('');
    const { aiSettings, isLoading, error, fetchAISettings, updateAISettings } = useSettingsStore();
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
        fetchAISettings();
    }, [fetchAISettings]);

    React.useEffect(() => {
        if (!aiSettings) return;
        setGuardrailEnabled(aiSettings.guardrail_enabled);
        setPrimaryModel(aiSettings.primary_model);
        setFastModel(aiSettings.fast_model);
        setNanoModel(aiSettings.nano_model);
    }, [aiSettings]);

    const handleConnectGoogleSheets = async () => {
        setIsConnecting(true);
        try {
            const res = await apiClient.post('/integrations/google-sheets/connect', {});
            if (res.data.auth_url) {
                const popup = window.open(res.data.auth_url, 'google-sheets-oauth', 'width=600,height=700,left=200,top=100');

                // Listen for the popup to signal completion
                const handleMessage = async (event: MessageEvent) => {
                    if (event.origin !== window.location.origin) return;
                    if (event.data?.type === 'OAUTH_COMPLETE' && ['google', 'google_sheets'].includes(event.data?.provider)) {
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

    const handleSaveAISettings = async () => {
        setSaveMessage('');
        try {
            await updateAISettings({
                ...(apiKeyInput.trim() ? { openai_api_key: apiKeyInput.trim() } : {}),
                guardrail_enabled: guardrailEnabled,
                primary_model: primaryModel,
                fast_model: fastModel,
                nano_model: nanoModel,
            });
            setApiKeyInput('');
            setSaveMessage('AI settings updated.');
        } catch {
            setSaveMessage('');
        }
    };

    const handleClearApiKey = async () => {
        setSaveMessage('');
        try {
            await updateAISettings({ clear_api_key: true });
            setApiKeyInput('');
            setSaveMessage('OpenAI API key removed.');
        } catch {
            setSaveMessage('');
        }
    };

    return (
        <div className="flex-1 overflow-y-auto bg-background px-4 py-8 sm:px-8 lg:py-12">
            <div className="max-w-3xl mx-auto space-y-6">
                <PageHeader
                    eyebrow="Settings"
                    title="Connections and preferences"
                    description="Choose what BizAssist can reach and which models it runs on."
                />

                <p className="eyebrow pt-4">Connected apps</p>
                <GoogleCalendarCard />

                {/* Google Sheets Integration - flagship card */}
                <div className="bg-card border border-border rounded-2xl p-5 sm:p-6">
                    <div className="flex flex-col sm:flex-row sm:items-start gap-5">
                        {/* Sheets Icon */}
                        <div className="w-11 h-11 rounded-xl border border-border bg-background flex items-center justify-center shrink-0">
                            <svg viewBox="0 0 24 24" className="w-6 h-6" fill="none">
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
                                <h3 className="text-lg font-semibold text-foreground">Google Sheets</h3>
                                {sheetsStatus === null ? (
                                    <StatusChip tone="neutral">Checking…</StatusChip>
                                ) : sheetsStatus.connected ? (
                                    <StatusChip tone="success">Connected</StatusChip>
                                ) : (
                                    <StatusChip tone="warning">Not connected</StatusChip>
                                )}
                            </div>
                            <p className="text-muted-foreground mt-2 text-sm leading-relaxed max-w-xl">
                                Lets BizAssist read and update your spreadsheets: log an expense, pull last month’s totals, or add rows to a tracker.
                            </p>

                            {!sheetsStatus?.connected && (
                                <div className="mt-5 space-y-3">
                                    <button
                                        onClick={handleConnectGoogleSheets}
                                        disabled={isConnecting}
                                        className="flex items-center gap-2 px-4 py-2 btn-glow rounded-xl font-semibold text-sm disabled:opacity-60"
                                    >
                                        {isConnecting ? (
                                            <Loader2 className="w-4 h-4 animate-spin" />
                                        ) : (
                                            <Link2 className="w-4 h-4" />
                                        )}
                                        {isConnecting ? 'Opening Google…' : 'Connect Google Sheets'}
                                    </button>
                                    <p className="text-xs text-muted-foreground">
                                        A Google window opens. Sign in, allow access, and you’ll come straight back here.
                                    </p>
                                </div>
                            )}

                            {sheetsStatus?.connected && (
                                <div className="mt-5 space-y-3">
                                    <p className="text-sm text-muted-foreground border-l-2 border-primary/40 pl-3">
                                        Ask about your spreadsheets in the chat. BizAssist created a default spreadsheet when you connected and uses it unless you name another one.
                                    </p>
                                    <button
                                        onClick={handleConnectGoogleSheets}
                                        className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
                                    >
                                        <RefreshCw className="w-3.5 h-3.5" />
                                        Reconnect or switch account
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>
                </div>

                <p className="eyebrow pt-6">AI</p>
                <div className="bg-card border border-border rounded-2xl overflow-hidden">
                    <div className="space-y-5 p-5 sm:p-6">
                        <div>
                            <div className="flex items-center justify-between gap-4 flex-wrap">
                                <div>
                                    <h3 className="text-lg font-semibold text-foreground">OpenAI API key</h3>
                                    <p className="text-sm text-muted-foreground mt-0.5">
                                        BizAssist runs on your own key, so usage is billed to your OpenAI account. Chat stays off until one is added.
                                    </p>
                                </div>
                                {aiSettings?.has_api_key ? (
                                    <StatusChip tone="success">Key saved</StatusChip>
                                ) : (
                                    <StatusChip tone="warning">Needed</StatusChip>
                                )}
                            </div>
                            <input
                                type="password"
                                value={apiKeyInput}
                                onChange={(e) => setApiKeyInput(e.target.value)}
                                placeholder={aiSettings?.has_api_key ? 'Paste a new key to replace the saved one' : 'sk-…'}
                                className="mt-4 w-full rounded-xl border border-input bg-background px-3 py-2.5 font-mono text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                            />
                            <div className="mt-3 flex flex-wrap gap-3">
                                <button
                                    onClick={handleSaveAISettings}
                                    disabled={isLoading}
                                    className="px-4 py-2 rounded-xl btn-glow text-sm font-medium hover:bg-primary/90 disabled:opacity-60"
                                >
                                    {isLoading ? 'Saving…' : 'Save AI settings'}
                                </button>
                                {aiSettings?.has_api_key && (
                                    <button
                                        onClick={handleClearApiKey}
                                        disabled={isLoading}
                                        className="px-4 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-60"
                                    >
                                        Remove key
                                    </button>
                                )}
                            </div>
                        </div>

                        <div className="border-t border-border" />
                        {[
                            {
                                label: 'Main model',
                                desc: 'Conversations, analysis, and reading documents.',
                                value: primaryModel,
                                onChange: setPrimaryModel,
                            },
                            {
                                label: 'Fast model',
                                desc: 'Planning steps, summaries, and chat titles.',
                                value: fastModel,
                                onChange: setFastModel,
                            },
                            {
                                label: 'Small model',
                                desc: 'Quick safety checks.',
                                value: nanoModel,
                                onChange: setNanoModel,
                            },
                        ].map(item => (
                            <div key={item.label} className="flex items-center justify-between gap-4 flex-wrap">
                                <div>
                                    <p className="font-medium text-foreground text-sm">{item.label}</p>
                                    <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                                </div>
                                <select
                                    value={item.value}
                                    onChange={(e) => item.onChange(e.target.value)}
                                    className="min-w-[170px] rounded-xl border border-input bg-background px-3 py-2 font-mono text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/15"
                                >
                                    {MODEL_OPTIONS.map(model => (
                                        <option key={model} value={model}>{model}</option>
                                    ))}
                                </select>
                            </div>
                        ))}

                        <div className="flex items-center justify-between gap-4 flex-wrap">
                            <div>
                                <p className="font-medium text-foreground text-sm">Document search</p>
                                <p className="text-xs text-muted-foreground mt-0.5">Used to index and search your documents. Not changeable yet.</p>
                            </div>
                            <span className="font-mono text-xs text-muted-foreground">text-embedding-3-small</span>
                        </div>
                        {(saveMessage || error) && (
                            <div className={`rounded-xl px-4 py-3 text-sm font-medium ${error ? 'bg-destructive/10 text-destructive border border-destructive/20' : 'bg-success/10 text-success border border-success/25'}`}>
                                {error || saveMessage}
                            </div>
                        )}
                    </div>
                </div>

                <p className="eyebrow pt-6">Safety</p>
                <div className="bg-card border border-border rounded-2xl p-5 sm:p-6">
                    <div className="flex items-start justify-between gap-4 flex-wrap">
                        <div>
                            <h3 className="text-lg font-semibold text-foreground">Keep it on topic</h3>
                            <p className="text-sm text-muted-foreground mt-0.5 max-w-lg">
                                When on, BizAssist turns down requests that aren’t about running your business.
                            </p>
                        </div>
                        <button
                            type="button"
                            onClick={() => setGuardrailEnabled(prev => !prev)}
                            className={`relative inline-flex h-6 w-11 shrink-0 items-center rounded-full transition-colors ${guardrailEnabled ? 'bg-primary' : 'bg-input'}`}
                            role="switch"
                            aria-checked={guardrailEnabled}
                            aria-label="Keep it on topic"
                        >
                            <span
                                className={`inline-block h-4.5 w-4.5 transform rounded-full bg-card shadow transition-transform ${guardrailEnabled ? 'translate-x-[22px]' : 'translate-x-[3px]'}`}
                            />
                        </button>
                    </div>
                    <div className="mt-4 flex flex-wrap gap-5">
                        {['Writing code', 'Database queries', 'Anything unrelated to your business'].map(item => (
                            <div key={item} className="flex items-center gap-2 text-sm text-muted-foreground">
                                <XCircle className="w-4 h-4 text-muted-foreground shrink-0" />
                                <span>{item}</span>
                            </div>
                        ))}
                    </div>
                    <p className="mt-4 text-xs text-muted-foreground">
                        Currently <span className="font-medium text-foreground">{guardrailEnabled ? 'on' : 'off'}</span>. Press “Save AI settings” above to keep this change.
                    </p>
                </div>
            </div>
        </div>
    );
}
