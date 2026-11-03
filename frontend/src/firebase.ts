import { initializeApp } from 'firebase/app';
import { connectAuthEmulator, getAuth, GoogleAuthProvider } from 'firebase/auth';

const firebaseConfig = {
    apiKey: import.meta.env.VITE_FIREBASE_API_KEY,
    authDomain: import.meta.env.VITE_FIREBASE_AUTH_DOMAIN,
    projectId: import.meta.env.VITE_FIREBASE_PROJECT_ID,
};

const app = initializeApp(firebaseConfig);

export const firebaseAuth = getAuth(app);
export const googleProvider = new GoogleAuthProvider();

// Local development/testing only: use the Firebase Auth emulator (e.g. "localhost:9099").
const authEmulatorHost = import.meta.env.VITE_FIREBASE_AUTH_EMULATOR_HOST;
if (import.meta.env.DEV && authEmulatorHost) {
    connectAuthEmulator(firebaseAuth, `http://${authEmulatorHost}`, { disableWarnings: true });
}
