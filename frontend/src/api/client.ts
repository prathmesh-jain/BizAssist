import axios, { type InternalAxiosRequestConfig } from 'axios';
import { getActiveOrganizationId, setActiveOrganizationId } from '../lib/session';

const normalizeApiBaseUrl = (raw?: string) => {
    const base = (raw || 'http://localhost:8000').replace(/\/+$/, '');
    return base.endsWith('/api') ? base : `${base}/api`;
};

const apiClient = axios.create({
    baseURL: normalizeApiBaseUrl(import.meta.env.VITE_API_URL),
    headers: {
        'Content-Type': 'application/json',
    },
});

type UnauthorizedHandler = () => void;
let unauthorizedHandler: UnauthorizedHandler | null = null;

export const setUnauthorizedHandler = (fn: UnauthorizedHandler) => {
    unauthorizedHandler = fn;
};

export const triggerUnauthorized = () => {
    unauthorizedHandler?.();
};

type TokenGetter = () => Promise<string | null>;
let getTokenFunc: TokenGetter | null = null;

export const setTokenGetter = (fn: TokenGetter) => {
    getTokenFunc = fn;
};

/** Ensure we get a fresh token from Firebase for manual fetch/SSE calls */
export const getAuthHeader = async (): Promise<string> => {
    if (!getTokenFunc) return '';
    const token = await getTokenFunc();
    return token ? `Bearer ${token}` : '';
};

/** Headers for manual fetch/SSE calls: auth plus the selected organization. */
export const getRequestHeaders = async (): Promise<Record<string, string>> => {
    const headers: Record<string, string> = { Authorization: await getAuthHeader() };
    const organizationId = getActiveOrganizationId();
    if (organizationId) headers['X-Organization-Id'] = organizationId;
    return headers;
};

/** Human-readable message from an API error (FastAPI `detail`), or the fallback. */
export const apiErrorDetail = (error: unknown, fallback: string): string => {
    if (!axios.isAxiosError(error)) return fallback;
    const detail = (error.response?.data as { detail?: unknown } | undefined)?.detail;
    if (typeof detail === 'string') return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === 'string') return detail[0].msg;
    return fallback;
};

/** If the remembered organization is no longer usable, forget it and reload into the default one. */
export const handleOrganizationAccessError = (status: number, detail: unknown): boolean => {
    if (status !== 403 || !getActiveOrganizationId()) return false;
    if (typeof detail !== 'string' || !detail.includes('member of this organization')) return false;
    setActiveOrganizationId(null);
    window.location.assign('/app/chat');
    return true;
};

apiClient.interceptors.request.use(
    async (config: InternalAxiosRequestConfig) => {
        if (getTokenFunc) {
            const token = await getTokenFunc();
            if (token) {
                const authHeader = `Bearer ${token}`;
                config.headers.Authorization = authHeader;
                // Also update the common headers so other fetch calls can use it
                apiClient.defaults.headers.common['Authorization'] = authHeader;
            }
        }
        const organizationId = getActiveOrganizationId();
        if (organizationId) config.headers['X-Organization-Id'] = organizationId;
        return config;
    },
    (error) => Promise.reject(error)
);

apiClient.interceptors.response.use(
    (response) => response,
    (error) => {
        if (error.response && error.response.status === 401) {
            console.error("Unauthorized request. Token might be expired.");
            triggerUnauthorized();
        } else if (error.response) {
            handleOrganizationAccessError(error.response.status, error.response.data?.detail);
        }
        return Promise.reject(error);
    }
);

export default apiClient;
