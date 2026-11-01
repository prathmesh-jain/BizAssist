import { FileText, Paperclip } from 'lucide-react';
import DOMPurify from 'dompurify';
import { Marked } from 'marked';
import type { Message } from '../../types';
import { LogoMark } from '../ui/Logo';
import ToolLine from './ToolLine';

interface MessageBubbleProps {
    message: Message;
    isStreaming?: boolean;
}

const markdownParser = new Marked({
    gfm: true,
    breaks: true,
});

type MessageAttachment = NonNullable<Message['attachments']>[number];

export default function MessageBubble({ message }: MessageBubbleProps) {
    const isAi = message.role === 'assistant';
    const attachments = message.attachments ?? [];
    const toolCalls = message.tool_calls ?? [];

    const sources = toolCalls
        .filter((t) => Boolean(t?.citations?.length))
        .map((t) => ({ name: String(t?.name ?? ''), citations: (t.citations ?? []).map(String) }));

    const sanitizedHtml = isAi && message.content
        ? DOMPurify.sanitize(markdownParser.parse(message.content) as string, { USE_PROFILES: { html: true } })
        : '';

    if (!isAi) {
        return (
            <div className="flex justify-end mb-8 rise-in">
                <div className="flex max-w-[85%] flex-col items-end gap-2">
                    {attachments.length > 0 && (
                        <div className="flex flex-wrap justify-end gap-2">
                            {attachments.map((a) => <AttachmentPreview key={a.id} attachment={a} />)}
                        </div>
                    )}
                    {message.content && (
                        <div className="rounded-2xl rounded-br-md bg-foreground px-4 py-2.5 text-[15px] leading-relaxed text-background whitespace-pre-wrap break-words">
                            {message.content}
                        </div>
                    )}
                </div>
            </div>
        );
    }

    return (
        <div className="flex gap-4 mb-8">
            <LogoMark className="w-7 h-7 shrink-0 mt-0.5" />
            <div className="min-w-0 flex-1 space-y-3">
                {toolCalls.length > 0 && (
                    <div className="space-y-1">
                        {toolCalls.map((tool, idx) => <ToolLine key={`${tool.name}-${idx}`} tool={tool} />)}
                    </div>
                )}

                {attachments.length > 0 && (
                    <div className="flex flex-wrap gap-2">
                        {attachments.map((a) => <AttachmentPreview key={a.id} attachment={a} />)}
                    </div>
                )}

                {message.content && (
                    <div className="md pt-0.5" dangerouslySetInnerHTML={{ __html: sanitizedHtml }} />
                )}

                {sources.length > 0 && (
                    <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1 border-t border-dashed border-border pt-2.5 text-xs text-muted-foreground">
                        <span className="eyebrow">Sources</span>
                        {sources.flatMap((s) =>
                            (s.citations.length ? s.citations.slice(0, 4) : [s.name]).map((c) => (
                                <span key={`${s.name}-${c}`} className="inline-flex items-center gap-1">
                                    <FileText className="w-3 h-3" /> {c}
                                </span>
                            )),
                        )}
                    </div>
                )}
            </div>
        </div>
    );
}

function AttachmentPreview({ attachment: a }: { attachment: MessageAttachment }) {
    const url = a.local_url || a.url || '';
    const isImage = (a.content_type || '').toLowerCase().startsWith('image/');

    if (isImage && url) {
        return (
            <figure className="max-w-[280px]">
                <img src={url} alt={a.filename} className="rounded-lg border border-border max-h-[240px] object-contain bg-card" />
                <figcaption className="mt-1 text-xs text-muted-foreground truncate">{a.filename}</figcaption>
            </figure>
        );
    }

    return (
        <div className="flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2 max-w-[300px]">
            <Paperclip className="w-4 h-4 shrink-0 text-muted-foreground" />
            <span className="text-sm text-foreground truncate">{a.filename}</span>
        </div>
    );
}
