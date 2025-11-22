// firebase.ts
import { initializeApp, getApps, getApp } from "firebase/app";
import { getAuth, GoogleAuthProvider, onAuthStateChanged, User } from "firebase/auth";

// TODO: Replace the following with your app's Firebase project configuration
// See: https://firebase.google.com/docs/web/setup#config-object
const firebaseConfig = {
    apiKey: process.env.NEXT_PUBLIC_FIREBASE_API_KEY,
    authDomain: process.env.NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN,
    projectId: process.env.NEXT_PUBLIC_FIREBASE_PROJECT_ID,
    storageBucket: process.env.NEXT_PUBLIC_FIREBASE_STORAGE_BUCKET,
    messagingSenderId: process.env.NEXT_PUBLIC_FIREBASE_MESSAGING_SENDER_ID,
    appId: process.env.NEXT_PUBLIC_FIREBASE_APP_ID,
    measurementId: process.env.NEXT_PUBLIC_FIREBASE_MEASUREMENT_ID,
};

// Initialize Firebase
const app = !getApps().length ? initializeApp(firebaseConfig) : getApp();

// Initialize Firebase Auth
const auth = getAuth(app);
const provider = new GoogleAuthProvider();

/*
  Debug helpers:
  - Expose `auth` on window for console access (dev only)
  - Maintain window.__CURRENT_USER and window.__CURRENT_ID_TOKEN to inspect easily
  - Provide window.getIdTokenForDebug() to fetch the current ID token on demand
*/
if (typeof window !== "undefined") {
    // attach objects for console debugging (remove in production if you want)
    (window as any).auth = auth;

    // helper to fetch and cache the current id token (useful from console)
    (window as any).getIdTokenForDebug = async function getIdTokenForDebug(forceRefresh = false) {
        const user = auth.currentUser as User | null;
        if (!user) {
            console.log("No user logged in");
            return null;
        }
        try {
            const token = await user.getIdToken(forceRefresh);
            // store (and keep truncated log to avoid leaking token into casual logs)
            (window as any).__CURRENT_ID_TOKEN = token;
            console.log("🔐 ID token (start):", token.slice(0, 40) + "...");
            return token;
        } catch (err) {
            console.error("Failed to fetch ID token:", err);
            throw err;
        }
    };
}

// Listen for auth state changes and print helpful debug info
onAuthStateChanged(auth, async (user) => {
    if (!user) {
        // clear debug state
        if (typeof window !== "undefined") {
            (window as any).__CURRENT_USER = null;
            (window as any).__CURRENT_ID_TOKEN = null;
        }
        console.log("No user logged in");
        return;
    }

    // Save minimal user info for console inspection
    const u = {
        uid: user.uid,
        email: user.email,
        displayName: user.displayName,
        photoURL: user.photoURL,
    };

    if (typeof window !== "undefined") {
        (window as any).__CURRENT_USER = u;
    }

    // Try to fetch a token (no force refresh) and log only a short prefix
    try {
        const token = await user.getIdToken(/* forceRefresh */ false);
        if (typeof window !== "undefined") {
            (window as any).__CURRENT_ID_TOKEN = token;
        }
        console.log("✅ user signed in:", u);
        console.log("🔐 ID token (start):", token);
    } catch (err) {
        console.warn("Signed in but failed to fetch ID token immediately:", err);
        console.log("✅ user signed in:", u);
    }
});

export { auth, provider };
export default app;
