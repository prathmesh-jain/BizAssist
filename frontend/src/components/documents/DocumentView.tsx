import React from 'react';
import { Link } from 'react-router-dom';
import { FileText, Trash2, Loader2, UploadCloud } from 'lucide-react';
import apiClient, { apiErrorDetail } from '../../api/client';
import type { DocumentMetadata } from '../../types';
import useSettingsStore from '../../store/settingsStore';
import PageHeader from '../ui/PageHeader';

const ACCEPT = '.pdf,.docx,.txt';
const ACCEPTED_EXTENSIONS = ['pdf', 'docx', 'txt'];

const formatDate = (iso: string) =>
    new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' });

const extensionOf = (doc: DocumentMetadata) =>
    (doc.filename.split('.').pop() || doc.file_type.split('/')[1] || 'doc').toLowerCase();

export default function DocumentView() {
    const [file, setFile] = React.useState<File | null>(null);
    const [isUploading, setIsUploading] = React.useState(false);
    const [documents, setDocuments] = React.useState<DocumentMetadata[]>([]);
    const [isLoading, setIsLoading] = React.useState(true);
    const [dragging, setDragging] = React.useState(false);
    const [error, setError] = React.useState('');
    const [deleting, setDeleting] = React.useState<string | null>(null);
    const inputRef = React.useRef<HTMLInputElement>(null);
    const { aiSettings, isLoaded, fetchAISettings } = useSettingsStore();

    const fetchDocuments = React.useCallback(async () => {
        try {
            const response = await apiClient.get('/documents');
            setDocuments(response.data);
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t load your documents.'));
        } finally {
            setIsLoading(false);
        }
    }, []);

    React.useEffect(() => {
        fetchDocuments();
        if (!aiSettings) fetchAISettings();
    }, [fetchDocuments, aiSettings, fetchAISettings]);

    const hasApiKey = !!aiSettings?.has_api_key;
    const settingsPending = !isLoaded && !aiSettings;
    const blocked = !settingsPending && !hasApiKey;

    const choose = (candidate: File | undefined) => {
        if (!candidate) return;
        const ext = candidate.name.split('.').pop()?.toLowerCase() ?? '';
        if (!ACCEPTED_EXTENSIONS.includes(ext)) {
            setError(`${candidate.name} isn’t a PDF, Word, or text file.`);
            return;
        }
        setError('');
        setFile(candidate);
    };

    const handleUpload = async () => {
        if (!file) return;
        setIsUploading(true);
        setError('');
        const formData = new FormData();
        formData.append('file', file);
        try {
            await apiClient.post('/documents/upload', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            setFile(null);
            await fetchDocuments();
        } catch (e) {
            setError(apiErrorDetail(e, `Couldn’t add ${file.name}. Try again in a moment.`));
        } finally {
            setIsUploading(false);
        }
    };

    const handleDelete = async (doc: DocumentMetadata) => {
        if (!confirm(`Remove “${doc.filename}”? BizAssist will stop using it to answer questions.`)) return;
        setDeleting(doc.id);
        try {
            await apiClient.delete(`/documents/${doc.id}`);
            await fetchDocuments();
        } catch (e) {
            setError(apiErrorDetail(e, 'Couldn’t remove that document.'));
        } finally {
            setDeleting(null);
        }
    };

    return (
        <div className="flex-1 overflow-y-auto bg-background px-4 py-8 sm:px-8 lg:py-12">
            <div className="max-w-3xl mx-auto space-y-8">
                <PageHeader
                    eyebrow="Documents"
                    title="What BizAssist has read"
                    description="Price lists, contracts, policies, handbooks. Add them once and ask about them in plain words any time after."
                />

                {blocked && (
                    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-warning/30 bg-warning/10 px-4 py-3 text-sm">
                        <span>Reading documents uses your OpenAI key, and none is saved yet.</span>
                        <Link to="/app/settings" className="font-medium text-primary underline underline-offset-4">Add it in Settings</Link>
                    </div>
                )}

                <div
                    onDragOver={(e) => { e.preventDefault(); if (!blocked) setDragging(true); }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                        e.preventDefault();
                        setDragging(false);
                        if (!blocked) choose(e.dataTransfer.files?.[0]);
                    }}
                    className={`rounded-lg border-2 border-dashed px-6 py-8 text-center transition-colors ${dragging ? 'border-primary bg-primary/5' : 'border-input bg-card'} ${blocked ? 'opacity-60' : ''}`}
                >
                    <input
                        ref={inputRef}
                        type="file"
                        className="hidden"
                        accept={ACCEPT}
                        onChange={(e) => { choose(e.target.files?.[0]); e.target.value = ''; }}
                    />
                    {file ? (
                        <div className="flex flex-col items-center gap-3 sm:flex-row sm:justify-center">
                            <span className="flex items-center gap-2 text-sm text-foreground">
                                <FileText className="w-4 h-4 text-muted-foreground" />
                                <span className="max-w-[16rem] truncate font-medium">{file.name}</span>
                            </span>
                            <div className="flex gap-2">
                                <button
                                    onClick={handleUpload}
                                    disabled={isUploading || blocked}
                                    className="flex items-center gap-2 btn-glow rounded-xl px-4 py-2 text-sm font-semibold disabled:opacity-50"
                                >
                                    {isUploading && <Loader2 className="w-4 h-4 animate-spin" />}
                                    {isUploading ? 'Reading…' : 'Add document'}
                                </button>
                                <button
                                    onClick={() => setFile(null)}
                                    disabled={isUploading}
                                    className="rounded-xl border border-border px-3 py-2 text-sm text-foreground hover:bg-muted disabled:opacity-50"
                                >
                                    Cancel
                                </button>
                            </div>
                        </div>
                    ) : (
                        <>
                            <UploadCloud className="mx-auto w-6 h-6 text-muted-foreground" />
                            <p className="mt-3 text-[15px] text-foreground">
                                Drop a file here, or{' '}
                                <button
                                    type="button"
                                    disabled={blocked}
                                    onClick={() => inputRef.current?.click()}
                                    className="font-medium text-primary underline underline-offset-4 disabled:no-underline"
                                >
                                    choose one
                                </button>
                            </p>
                            <p className="mt-1 text-xs text-muted-foreground">PDF, Word (.docx), or plain text</p>
                        </>
                    )}
                </div>

                {error && (
                    <div role="alert" className="rounded-lg border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">
                        {error}
                    </div>
                )}

                <section>
                    <div className="flex items-baseline justify-between border-b border-foreground/70 pb-2">
                        <h2 className="font-display text-xl font-semibold">On file</h2>
                        <span className="text-sm text-muted-foreground tabular-nums">
                            {documents.length} {documents.length === 1 ? 'document' : 'documents'}
                        </span>
                    </div>

                    {isLoading ? (
                        <div className="flex items-center gap-2 py-10 text-sm text-muted-foreground">
                            <Loader2 className="w-4 h-4 animate-spin" /> Loading…
                        </div>
                    ) : documents.length > 0 ? (
                        <ul className="divide-y divide-border">
                            {documents.map((doc) => (
                                <li key={doc.id} className="group flex items-center gap-4 py-3.5">
                                    <span className="w-12 shrink-0 rounded border border-border bg-card py-1 text-center font-mono text-[10px] uppercase text-muted-foreground">
                                        {extensionOf(doc)}
                                    </span>
                                    <div className="min-w-0 flex-1">
                                        <p className="truncate text-[15px] text-foreground" title={doc.filename}>{doc.filename}</p>
                                        <p className="text-xs text-muted-foreground">
                                            Added {formatDate(doc.created_at)} · {doc.chunk_count} {doc.chunk_count === 1 ? 'section' : 'sections'} indexed
                                        </p>
                                    </div>
                                    <button
                                        onClick={() => handleDelete(doc)}
                                        disabled={deleting === doc.id}
                                        className="rounded-xl p-2 text-muted-foreground opacity-100 hover:bg-destructive/10 hover:text-destructive sm:opacity-0 sm:group-hover:opacity-100 focus:opacity-100 disabled:opacity-50"
                                        aria-label={`Remove ${doc.filename}`}
                                        title="Remove"
                                    >
                                        {deleting === doc.id ? <Loader2 className="w-4 h-4 animate-spin" /> : <Trash2 className="w-4 h-4" />}
                                    </button>
                                </li>
                            ))}
                        </ul>
                    ) : (
                        <p className="py-10 text-[15px] text-muted-foreground">
                            Nothing here yet. A good first document is the one you keep looking things up in: a rate card,
                            a supplier contract, or your returns policy.
                        </p>
                    )}
                </section>
            </div>
        </div>
    );
}
