import React from 'react';
import { CheckCircle2, ExternalLink, Loader2, RefreshCw, XCircle } from 'lucide-react';
import StatusChip from '../ui/StatusChip';
import apiClient, { apiErrorDetail } from '../../api/client';
import useSettingsStore from '../../store/settingsStore';

interface ProviderInfo {
    id: string;
    label: string;
    key_url: string | null;
    key_placeholder: string;
    needs_base_url: boolean;
    key_optional: boolean;
}

const INPUT_CLASS = 'w-full rounded-xl border border-input bg-background px-3 py-2.5 text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/15';
const SIDE_INPUT_CLASS = 'w-full sm:w-72 rounded-xl border border-input bg-background px-3 py-2 font-mono text-sm text-foreground outline-none focus:border-primary focus:ring-2 focus:ring-primary/15';
const MODEL_LIST_ID = 'provider-model-options';

/** Pick a provider, its key and models. Model names come live from the provider, or can be typed. */
export default function AIProviderCard({ guardrailEnabled }: { guardrailEnabled: boolean }) {
    const { aiSettings, isLoading, error, updateAISettings } = useSettingsStore();
    const [providers, setProviders] = React.useState<ProviderInfo[]>([]);
    const [providerId, setProviderId] = React.useState('openai');
    const [baseUrl, setBaseUrl] = React.useState('');
    const [apiKey, setApiKey] = React.useState('');
    const [documentsKey, setDocumentsKey] = React.useState('');
    const [primaryModel, setPrimaryModel] = React.useState('');
    const [fastModel, setFastModel] = React.useState('');
    const [nanoModel, setNanoModel] = React.useState('');
    const [models, setModels] = React.useState<string[]>([]);
    const [modelsBusy, setModelsBusy] = React.useState(false);
    const [modelsNote, setModelsNote] = React.useState('');
    const [testing, setTesting] = React.useState(false);
    const [testResult, setTestResult] = React.useState<{ ok: boolean; message: string } | null>(null);
    const [saveMessage, setSaveMessage] = React.useState('');
    const [formError, setFormError] = React.useState('');
    const latestModelsRequest = React.useRef(0);

    const provider = providers.find(p => p.id === providerId);
    const keySaved = !!aiSettings?.saved_key_providers?.includes(providerId);
    const isSavedProvider = aiSettings?.provider === providerId;

    const loadModels = React.useCallback(async (id: string, url: string, key: string) => {
        const request = ++latestModelsRequest.current;
        setModelsBusy(true);
        setModelsNote('');
        try {
            const { data } = await apiClient.post<{ models: string[] }>('/settings/ai/models', {
                provider: id,
                base_url: url.trim() || null,
                api_key: key.trim() || null,
            });
            if (request !== latestModelsRequest.current) return;
            setModels(data.models);
            if (!data.models.length) setModelsNote('This provider didn’t list any models. Type the model name below.');
        } catch (e) {
            if (request !== latestModelsRequest.current) return;
            setModels([]);
            setModelsNote(`${apiErrorDetail(e, 'Could not list models.')} You can still type a model name.`);
        } finally {
            if (request === latestModelsRequest.current) setModelsBusy(false);
        }
    }, []);

    React.useEffect(() => {
        apiClient.get<{ providers: ProviderInfo[] }>('/settings/ai/providers')
            .then(res => setProviders(res.data.providers))
            .catch(() => setFormError('Could not load the provider list. Refresh to try again.'));
    }, []);

    React.useEffect(() => {
        if (!aiSettings) return;
        setProviderId(aiSettings.provider);
        setBaseUrl(aiSettings.base_url ?? '');
        setPrimaryModel(aiSettings.primary_model);
        setFastModel(aiSettings.fast_model);
        setNanoModel(aiSettings.nano_model);
        if (aiSettings.chat_enabled) loadModels(aiSettings.provider, aiSettings.base_url ?? '', '');
    }, [aiSettings, loadModels]);

    const selectProvider = (id: string) => {
        const next = providers.find(p => p.id === id);
        const backToSaved = aiSettings?.provider === id;
        const url = backToSaved ? aiSettings?.base_url ?? '' : '';
        setProviderId(id);
        setBaseUrl(url);
        setApiKey('');
        setModels([]);
        setModelsNote('');
        setTestResult(null);
        setSaveMessage('');
        setFormError('');
        // Model names don't carry across providers.
        setPrimaryModel(backToSaved ? aiSettings?.primary_model ?? '' : '');
        setFastModel(backToSaved ? aiSettings?.fast_model ?? '' : '');
        setNanoModel(backToSaved ? aiSettings?.nano_model ?? '' : '');
        latestModelsRequest.current++;
        setModelsBusy(false);
        if (aiSettings?.saved_key_providers?.includes(id) && (!next?.needs_base_url || url)) loadModels(id, url, '');
    };

    const canListModels = provider?.needs_base_url ? !!baseUrl.trim() : !!apiKey.trim() || keySaved;

    const testConnection = async () => {
        if (!primaryModel.trim()) {
            setTestResult({ ok: false, message: 'Choose a main model to test.' });
            return;
        }
        setTesting(true);
        setTestResult(null);
        try {
            await apiClient.post('/settings/ai/test', {
                provider: providerId,
                base_url: baseUrl.trim() || null,
                api_key: apiKey.trim() || null,
                model: primaryModel.trim(),
            });
            setTestResult({ ok: true, message: `${primaryModel.trim()} answered. This setup works.` });
        } catch (e) {
            setTestResult({ ok: false, message: apiErrorDetail(e, 'The connection test failed.') });
        } finally {
            setTesting(false);
        }
    };

    const save = async () => {
        setSaveMessage('');
        setFormError('');
        if (!primaryModel.trim() || !fastModel.trim() || !nanoModel.trim()) {
            setFormError('Choose a main, fast and small model.');
            return;
        }
        try {
            await updateAISettings({
                provider: providerId,
                ...(provider?.needs_base_url ? { base_url: baseUrl.trim() } : {}),
                ...(apiKey.trim() ? { api_key: apiKey.trim() } : {}),
                ...(documentsKey.trim() && providerId !== 'openai' ? { openai_api_key: documentsKey.trim() } : {}),
                guardrail_enabled: guardrailEnabled,
                primary_model: primaryModel.trim(),
                fast_model: fastModel.trim(),
                nano_model: nanoModel.trim(),
            });
            setApiKey('');
            setDocumentsKey('');
            setSaveMessage('AI settings updated.');
        } catch {
            setSaveMessage('');
        }
    };

    const removeKey = async () => {
        setSaveMessage('');
        setFormError('');
        try {
            await updateAISettings({ clear_api_key: true });
            setApiKey('');
            setModels([]);
            setSaveMessage('API key removed.');
        } catch {
            setSaveMessage('');
        }
    };

    const modelRows = [
        { label: 'Main model', desc: 'Conversations, analysis, and reading documents.', value: primaryModel, onChange: setPrimaryModel },
        { label: 'Fast model', desc: 'Planning steps, summaries, and chat titles.', value: fastModel, onChange: setFastModel },
        { label: 'Small model', desc: 'Quick safety checks.', value: nanoModel, onChange: setNanoModel },
    ];
    const message = formError || error;

    return (
        <div className="bg-card border border-border rounded-2xl overflow-hidden">
            <div className="space-y-5 p-5 sm:p-6">
                <div>
                    <div className="flex items-center justify-between gap-4 flex-wrap">
                        <div>
                            <h3 className="text-lg font-semibold text-foreground">AI provider</h3>
                            <p className="text-sm text-muted-foreground mt-0.5">
                                BizAssist runs on your own account, so usage is billed by the provider you choose. Chat stays off until one is set up.
                            </p>
                        </div>
                        {isSavedProvider && aiSettings?.chat_enabled ? (
                            <StatusChip tone="success">Ready</StatusChip>
                        ) : (
                            <StatusChip tone="warning">Not set up</StatusChip>
                        )}
                    </div>
                    <label htmlFor="ai-provider" className="mt-4 block text-sm font-medium text-foreground">Provider</label>
                    <select
                        id="ai-provider"
                        value={providerId}
                        onChange={(e) => selectProvider(e.target.value)}
                        className={`${INPUT_CLASS} mt-1.5`}
                    >
                        {providers.map(p => <option key={p.id} value={p.id}>{p.label}</option>)}
                    </select>
                </div>

                {provider?.needs_base_url && (
                    <div>
                        <label htmlFor="ai-base-url" className="block text-sm font-medium text-foreground">Base URL</label>
                        <input
                            id="ai-base-url"
                            type="url"
                            value={baseUrl}
                            onChange={(e) => setBaseUrl(e.target.value)}
                            onBlur={() => { if (baseUrl.trim()) loadModels(providerId, baseUrl, apiKey); }}
                            placeholder="https://your-server.example.com/v1"
                            className={`${INPUT_CLASS} mt-1.5 font-mono`}
                        />
                        <p className="mt-1.5 text-xs text-muted-foreground">Any server that speaks the OpenAI chat API, over https.</p>
                    </div>
                )}

                <div>
                    <div className="flex items-center justify-between gap-3 flex-wrap">
                        <label htmlFor="ai-api-key" className="text-sm font-medium text-foreground">
                            API key{provider?.key_optional ? ' (optional)' : ''}
                        </label>
                        {provider?.key_url && (
                            <a href={provider.key_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline">
                                Get a key <ExternalLink className="w-3 h-3" />
                            </a>
                        )}
                    </div>
                    <input
                        id="ai-api-key"
                        type="password"
                        autoComplete="off"
                        value={apiKey}
                        onChange={(e) => setApiKey(e.target.value)}
                        onBlur={() => { if (apiKey.trim() && canListModels) loadModels(providerId, baseUrl, apiKey); }}
                        placeholder={keySaved ? 'Saved. Paste a new key to replace it' : provider?.key_placeholder}
                        className={`${INPUT_CLASS} mt-1.5 font-mono`}
                    />
                </div>

                <div className="border-t border-border" />

                <div className="flex items-center justify-between gap-3 flex-wrap">
                    <p className="text-sm text-muted-foreground">
                        {modelsBusy ? 'Loading models…' : models.length ? `${models.length} models available. Pick one or type a name.` : 'Add your key to list models, or type a name.'}
                    </p>
                    <button
                        type="button"
                        onClick={() => loadModels(providerId, baseUrl, apiKey)}
                        disabled={modelsBusy || !canListModels}
                        className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground disabled:opacity-50"
                    >
                        <RefreshCw className={`w-3.5 h-3.5 ${modelsBusy ? 'animate-spin' : ''}`} />
                        Refresh list
                    </button>
                </div>
                {modelsNote && <p className="text-sm text-foreground rounded-xl border border-warning/30 bg-warning/10 px-3 py-2">{modelsNote}</p>}

                <datalist id={MODEL_LIST_ID}>
                    {models.map(model => <option key={model} value={model} />)}
                </datalist>
                {modelRows.map((item, index) => (
                    <div key={item.label} className="flex items-center justify-between gap-4 flex-wrap">
                        <div>
                            <p className="font-medium text-foreground text-sm">{item.label}</p>
                            <p className="text-xs text-muted-foreground mt-0.5">{item.desc}</p>
                        </div>
                        <input
                            list={MODEL_LIST_ID}
                            aria-label={item.label}
                            value={item.value}
                            onChange={(e) => item.onChange(e.target.value)}
                            onBlur={() => {
                                // Most people start with one model throughout; each stays editable.
                                if (index === 0 && primaryModel.trim()) {
                                    if (!fastModel.trim()) setFastModel(primaryModel.trim());
                                    if (!nanoModel.trim()) setNanoModel(primaryModel.trim());
                                }
                            }}
                            placeholder="Model name"
                            className={SIDE_INPUT_CLASS}
                        />
                    </div>
                ))}

                <div className="flex items-start justify-between gap-4 flex-wrap">
                    <div className="min-w-0">
                        <p className="font-medium text-foreground text-sm">Document search</p>
                        <p className="text-xs text-muted-foreground mt-0.5 max-w-sm">
                            {providerId === 'openai'
                                ? 'Indexes and searches your documents with your OpenAI key.'
                                : 'Always runs on OpenAI, whichever provider you chat with. Add an OpenAI key to use documents; everything else works without one.'}
                        </p>
                    </div>
                    {providerId === 'openai' ? (
                        <span className="font-mono text-xs text-muted-foreground">text-embedding-3-small</span>
                    ) : (
                        <input
                            type="password"
                            autoComplete="off"
                            aria-label="OpenAI key for document search"
                            value={documentsKey}
                            onChange={(e) => setDocumentsKey(e.target.value)}
                            placeholder={aiSettings?.has_embedding_key ? 'Saved. Paste to replace' : 'sk-… (optional)'}
                            className={SIDE_INPUT_CLASS}
                        />
                    )}
                </div>

                <div className="flex flex-wrap gap-3">
                    <button
                        onClick={save}
                        disabled={isLoading}
                        className="px-4 py-2 rounded-xl btn-glow text-sm font-medium hover:bg-primary/90 disabled:opacity-60"
                    >
                        {isLoading ? 'Saving…' : 'Save AI settings'}
                    </button>
                    <button
                        onClick={testConnection}
                        disabled={testing}
                        className="inline-flex items-center gap-2 px-4 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-60"
                    >
                        {testing && <Loader2 className="w-4 h-4 animate-spin" />}
                        {testing ? 'Testing…' : 'Test connection'}
                    </button>
                    {isSavedProvider && keySaved && (
                        <button
                            onClick={removeKey}
                            disabled={isLoading}
                            className="px-4 py-2 rounded-xl border border-border text-sm text-foreground hover:bg-muted disabled:opacity-60"
                        >
                            Remove key
                        </button>
                    )}
                </div>

                {testResult && (
                    <p role="status" className={`flex items-start gap-2 text-sm ${testResult.ok ? 'text-success' : 'text-destructive'}`}>
                        {testResult.ok ? <CheckCircle2 className="w-4 h-4 mt-0.5 shrink-0" /> : <XCircle className="w-4 h-4 mt-0.5 shrink-0" />}
                        {testResult.message}
                    </p>
                )}
                {(saveMessage || message) && (
                    <div className={`rounded-xl px-4 py-3 text-sm font-medium ${message ? 'bg-destructive/10 text-destructive border border-destructive/20' : 'bg-success/10 text-success border border-success/25'}`}>
                        {message || saveMessage}
                    </div>
                )}
            </div>
        </div>
    );
}
