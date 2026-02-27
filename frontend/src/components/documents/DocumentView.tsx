import React from 'react';
import { FileText, Trash2, Loader2, Building2 } from 'lucide-react';
import apiClient from '../../api/client';
import type { DocumentMetadata } from '../../types';

export default function DocumentView() {
    const [file, setFile] = React.useState<File | null>(null);
    const [isUploading, setIsUploading] = React.useState(false);
    const [documents, setDocuments] = React.useState<DocumentMetadata[]>([]);
    const [isLoading, setIsLoading] = React.useState(true);

    const fetchDocuments = React.useCallback(async () => {
        try {
            const response = await apiClient.get('/documents');
            setDocuments(response.data);
        } catch (error) {
            console.error('Failed to fetch documents:', error);
        } finally {
            setIsLoading(false);
        }
    }, []);

    React.useEffect(() => {
        fetchDocuments();
    }, [fetchDocuments]);

    const handleUpload = async () => {
        if (!file) return;

        setIsUploading(true);
        const formData = new FormData();
        formData.append('file', file);

        try {
            await apiClient.post('/documents/upload', formData, {
                headers: { 'Content-Type': 'multipart/form-data' },
            });
            setFile(null);
            fetchDocuments();
        } catch (error) {
            console.error('Upload failed:', error);
        } finally {
            setIsUploading(false);
        }
    };

    const handleDelete = async (id: string) => {
        if (!confirm('Are you sure you want to delete this document? It will be removed from the AI knowledge base.')) return;

        try {
            await apiClient.delete(`/documents/${id}`);
            fetchDocuments();
        } catch (error) {
            console.error('Delete failed:', error);
        }
    };

    return (
        <div className="flex-1 overflow-y-auto bg-background p-6 lg:p-8">
            <div className="max-w-6xl mx-auto space-y-10">
                {/* Header */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                    <div>
                        <h2 className="text-3xl font-bold text-foreground tracking-tight">Knowledge Base</h2>
                        <p className="text-muted-foreground mt-1">Power your AI with custom business documents.</p>
                    </div>
                </div>

                {/* Upload Card */}
                <div className="bg-card border border-border rounded-3xl p-8 shadow-sm hover:shadow-md transition-shadow relative overflow-hidden group">
                    <div className="absolute top-0 right-0 w-32 h-32 bg-primary/5 rounded-full -mr-16 -mt-16 transition-transform group-hover:scale-110" />

                    <div className="flex flex-col lg:flex-row lg:items-center gap-10 relative z-10">
                        <div className="flex-1">
                            <div className="flex items-center space-x-4 mb-6">
                                <div className="w-10 h-10 rounded-xl bg-primary flex items-center justify-center text-primary-foreground shadow-lg shadow-primary/20">
                                    <Building2 className="w-5 h-5" />
                                </div>
                                <h3 className="text-2xl font-semibold text-foreground">Ingest Knowledge</h3>
                            </div>
                            <p className="text-muted-foreground leading-relaxed max-w-xl">
                                Upload PDF, DOCX, or Text files. BizAssist will automatically index the content so you can query it naturally in the chat.
                            </p>
                        </div>

                        <div className="lg:w-[400px] flex flex-col space-y-4">
                            <div className="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
                                <input
                                    type="file"
                                    id="doc-upload"
                                    className="hidden"
                                    onChange={(e) => e.target.files && setFile(e.target.files[0])}
                                    accept=".pdf,.docx,.txt"
                                />
                                <label
                                    htmlFor="doc-upload"
                                    className="flex-1 flex items-center justify-between px-5 py-3.5 bg-muted/50 border border-border rounded-2xl text-sm text-foreground cursor-pointer hover:border-primary/50 hover:bg-muted transition-all shadow-inner"
                                >
                                    <span className="truncate font-medium">{file ? file.name : 'Choose a file...'}</span>
                                    <FileText className="w-5 h-5 text-muted-foreground ml-2 shrink-0" />
                                </label>
                                <button
                                    onClick={handleUpload}
                                    disabled={!file || isUploading}
                                    className="bg-primary hover:bg-primary/90 text-primary-foreground py-3.5 px-6 rounded-2xl transition-all font-bold disabled:opacity-50 disabled:cursor-not-allowed shadow-lg shadow-primary/20 flex items-center justify-center min-w-[120px] active:scale-[0.98]"
                                >
                                    {isUploading ? <Loader2 className="w-5 h-5 animate-spin" /> : <span>Upload</span>}
                                </button>
                            </div>
                            <div className="flex items-center justify-center space-x-4 text-[11px] text-muted-foreground font-bold uppercase tracking-wider">
                                <span>PDF</span>
                                <div className="w-1 h-1 rounded-full bg-border" />
                                <span>DOCX</span>
                                <div className="w-1 h-1 rounded-full bg-border" />
                                <span>TXT</span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Document Grid */}
                <div className="space-y-5">
                    <div className="flex items-center justify-between">
                        <h3 className="text-xl font-bold text-foreground">Knowledge Library</h3>
                        <div className="px-3 py-1 bg-muted rounded-full text-xs font-bold text-muted-foreground uppercase tracking-tight">
                            {documents.length} Files
                        </div>
                    </div>

                    {isLoading ? (
                        <div className="flex items-center justify-center p-20">
                            <Loader2 className="w-10 h-10 text-primary animate-spin" />
                        </div>
                    ) : documents.length > 0 ? (
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
                            {documents.map((doc) => (
                                <div key={doc.id} className="bg-card border border-border rounded-2xl p-6 hover:border-primary/50 hover:shadow-md transition-all group relative overflow-hidden">
                                    <div className="absolute top-0 right-0 w-24 h-24 bg-primary/5 rounded-full -mr-12 -mt-12 transition-transform group-hover:scale-110" />

                                    <div className="flex items-start justify-between relative z-10">
                                        <div className="w-12 h-12 rounded-xl bg-muted flex items-center justify-center text-primary border border-border group-hover:bg-primary/10 group-hover:border-primary/20 transition-colors">
                                            <FileText className="w-6 h-6" />
                                        </div>
                                        <button
                                            onClick={() => handleDelete(doc.id)}
                                            className="text-muted-foreground hover:text-destructive p-2 opacity-0 group-hover:opacity-100 transition-all rounded-lg hover:bg-destructive/10"
                                            title="Delete Knowledge"
                                        >
                                            <Trash2 className="w-5 h-5" />
                                        </button>
                                    </div>
                                    <div className="mt-6 relative z-10">
                                        <h4 className="text-foreground font-bold text-lg truncate leading-tight mb-1" title={doc.filename}>{doc.filename}</h4>
                                        <div className="flex items-center space-x-3 text-xs font-bold text-muted-foreground uppercase tracking-tight">
                                            <span className="px-2 py-0.5 bg-muted rounded">{doc.file_type.split('/')[1] || 'DOC'}</span>
                                            <div className="w-1 h-1 rounded-full bg-border" />
                                            <span>{doc.chunk_count} Data Chunks</span>
                                        </div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    ) : (
                        <div className="p-24 text-center bg-muted/20 border border-border rounded-3xl text-muted-foreground">
                            <div className="p-4 bg-muted w-fit mx-auto rounded-full mb-6">
                                <FileText className="w-10 h-10 opacity-30" />
                            </div>
                            <h4 className="text-foreground font-semibold text-lg mb-2">No documents found</h4>
                            <p className="max-w-xs mx-auto">Upload business documents above to start building your AI's private knowledge base.</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
