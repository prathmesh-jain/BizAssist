import apiClient from '../api/client';
import type { MemoryItem, MemoryKind, MemoryScope } from '../types';

export interface MemoryListResponse {
    memories: MemoryItem[];
    total: number;
    enabled: boolean;
    can_write_shared: boolean;
}

export const memoryApi = {
    list: (params: { scope?: MemoryScope; kind?: MemoryKind; q?: string; limit?: number; offset?: number }) =>
        apiClient.get<MemoryListResponse>('/memory', { params }).then((r) => r.data),
    create: (body: { content: string; kind: Exclude<MemoryKind, 'activity'>; scope: MemoryScope }) =>
        apiClient.post<{ memory: MemoryItem; action: 'added' | 'updated' | 'unchanged' }>('/memory', body).then((r) => r.data),
    update: (id: string, body: { content?: string; kind?: Exclude<MemoryKind, 'activity'>; pinned?: boolean }) =>
        apiClient.patch<{ memory: MemoryItem }>(`/memory/${id}`, body).then((r) => r.data.memory),
    remove: (id: string) => apiClient.delete(`/memory/${id}`),
    undo: (id: string) => apiClient.post<{ ok: boolean; restored: MemoryItem | null }>(`/memory/${id}/undo`).then((r) => r.data),
    setEnabled: (enabled: boolean) =>
        apiClient.patch<{ enabled: boolean }>('/memory/settings', { enabled }).then((r) => r.data.enabled),
};
