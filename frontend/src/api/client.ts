import axios, { type InternalAxiosRequestConfig } from 'axios';

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

/** Ensure we get a fresh token from Clerk for manual fetch/SSE calls */
export const getAuthHeader = async (): Promise<string> => {
    if (!getTokenFunc) return '';
    const token = await getTokenFunc();
    return token ? `Bearer ${token}` : '';
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
        }
        return Promise.reject(error);
    }
);

export default apiClient;
