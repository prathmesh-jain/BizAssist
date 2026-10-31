// Start the Vite dev server against a local backend and the Firebase Auth emulator.
// Usage (from the repo root or frontend/):  node frontend/scripts/dev-emulator.mjs
//   firebase emulators:start --only auth --project demo-bizassist   (in another terminal)
// Process env overrides frontend/.env, so real Firebase settings are left untouched.
//
// Emulator-only test accounts used for manual testing (they exist only in the local emulator):
//   owner@bizassist.test / Test-Pass-123!     invitee@bizassist.test / Test-Pass-123!
import { spawn } from 'node:child_process';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const frontendDir = resolve(dirname(fileURLToPath(import.meta.url)), '..');

const env = {
    ...process.env,
    VITE_API_URL: process.env.VITE_API_URL || 'http://localhost:8000',
    VITE_FIREBASE_API_KEY: 'demo-api-key',
    VITE_FIREBASE_AUTH_DOMAIN: 'localhost',
    VITE_FIREBASE_PROJECT_ID: 'demo-bizassist',
    VITE_FIREBASE_AUTH_EMULATOR_HOST: process.env.VITE_FIREBASE_AUTH_EMULATOR_HOST || 'localhost:9099',
};

const child = spawn('npm', ['run', 'dev'], { cwd: frontendDir, env, stdio: 'inherit', shell: true });
child.on('exit', (code) => process.exit(code ?? 0));
