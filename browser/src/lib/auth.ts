// import firebase auth helpers
import { auth } from "@/lib/firebase";
import { createUserWithEmailAndPassword, signInWithEmailAndPassword, sendEmailVerification } from "firebase/auth";

/** Sign up new user (email/password) */
export async function signUpWithEmail(email: string, password: string) {
    const userCred = await createUserWithEmailAndPassword(auth, email, password);
    // optionally send verification email
    if (userCred.user) {
        await sendEmailVerification(userCred.user);
    }
    return userCred.user;
}

/** Sign in existing user */
export async function signInWithEmail(email: string, password: string) {
    const userCred = await signInWithEmailAndPassword(auth, email, password);
    return userCred.user;
}

/** Get current ID token to send to backend */
export async function getIdToken() {
    const user = auth.currentUser;
    if (!user) return null;
    return await user.getIdToken(/* forceRefresh= */ false);
}
