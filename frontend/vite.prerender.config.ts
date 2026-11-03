import { defineConfig, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { fileURLToPath } from 'node:url';

const authStub = fileURLToPath(new URL('./src/prerender/authStub.tsx', import.meta.url));

/** Replace the Firebase-backed auth context with a signed-out stub for build-time rendering. */
function stubAuth(): Plugin {
    return {
        name: 'bizassist-prerender-auth-stub',
        enforce: 'pre',
        resolveId(source) {
            if (/\/context\/AuthContext(\.tsx)?$/.test(source)) return authStub;
            return null;
        },
    };
}

// SSR build used only by scripts/prerender.mjs; the app itself is built by vite.config.ts.
export default defineConfig({
    plugins: [stubAuth(), react()],
    build: {
        ssr: 'src/prerender/entry.tsx',
        outDir: 'dist-ssr',
        emptyOutDir: true,
        rollupOptions: { output: { entryFileNames: 'entry.js' } },
    },
    ssr: { noExternal: ['lucide-react'] },
    logLevel: 'warn',
});
