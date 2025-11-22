// /mnt/data/page.tsx
/* eslint-disable @typescript-eslint/no-explicit-any */
/* eslint-disable @next/next/no-img-element */
"use client";

import React, { useEffect, useRef, useState } from "react";

// --- FIREBASE IMPORTS ---
import {
  onAuthStateChanged,
  signInWithEmailAndPassword,
  createUserWithEmailAndPassword,
  signOut,
  User,
} from "firebase/auth";
import { auth } from "@/lib/firebase"; // make sure this file exists and exports `auth`

// --- Types ---
interface IWindow extends Window {
  SpeechRecognition: any;
  webkitSpeechRecognition: any;
}

export default function VoiceBotPage() {
  // Config
  const BACKEND = process.env.NEXT_PUBLIC_BACKEND_URL || "http://localhost:8000";
  const recogRef = useRef<any>(null);

  // --- State: Auth ---
  const [user, setUser] = useState<User | null>(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [showLoginForm, setShowLoginForm] = useState(false);
  const [isRegister, setIsRegister] = useState(false);
  const [loginEmail, setLoginEmail] = useState("");
  const [loginPassword, setLoginPassword] = useState("");
  const [loginError, setLoginError] = useState<string | null>(null);
  const [loginSubmitting, setLoginSubmitting] = useState(false);

  // --- State: Bot ---
  const [listening, setListening] = useState(false);
  const [status, setStatus] = useState("idle");
  const [transcript, setTranscript] = useState("");
  const [reply, setReply] = useState("");
  const [sources, setSources] = useState<any[]>([]);
  const [intent, setIntent] = useState<string | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  // --- State: TTS ---
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceIndex, setVoiceIndex] = useState(0);
  const [autoSpeak, setAutoSpeak] = useState(true);

  // --- local guard: avoid repeated /auth/sync for same uid ---
  const markSynced = (uid: string | null) => {
    if (!uid) return;
    try { localStorage.setItem(`synced_${uid}`, "1"); } catch (e) { }
  };
  const isAlreadySynced = (uid: string | null) => {
    if (!uid) return false;
    try { return localStorage.getItem(`synced_${uid}`) === "1"; } catch (e) { return false; }
  };

  // --- Effect: Firebase Auth Listener ---
  useEffect(() => {
    if (!auth) {
      setErrorMsg("Firebase not initialized. Check src/lib/firebase.ts");
      setAuthLoading(false);
      return;
    }
    const unsubscribe = onAuthStateChanged(auth, async (currentUser) => {
      setUser(currentUser);
      setAuthLoading(false);
      if (currentUser) {
        // Ensure backend sync on sign-in, but avoid repeat syncs for same user
        try {
          if (!isAlreadySynced(currentUser.uid)) {
            const ok = await syncUserWithBackend(currentUser);
            if (ok) markSynced(currentUser.uid);
          } else {
            // still attempt a silent token-backed /query later; nothing else needed
            console.debug("user already synced (local cache)");
          }
        } catch (e) {
          console.warn("syncUserWithBackend failed", e);
        }
      }
    });
    return () => unsubscribe();
  }, []);

  // --- Effect: Load Voices ---
  useEffect(() => {
    function loadVoices() {
      const v = window.speechSynthesis.getVoices() || [];
      setVoices(v);
      const defaultVoiceIndex = v.findIndex(voice => voice.name.includes("Google US English") || voice.name.includes("Samantha"));
      if (defaultVoiceIndex !== -1) setVoiceIndex(defaultVoiceIndex);
    }
    loadVoices();
    window.speechSynthesis.onvoiceschanged = loadVoices;
  }, []);

  // --- Helper: Text to Speech ---
  const speak = React.useCallback((text: string) => {
    try {
      if (!text) return;
      window.speechSynthesis.cancel();

      const utter = new SpeechSynthesisUtterance(text);
      if (voices.length > 0) utter.voice = voices[voiceIndex];
      utter.rate = 1;
      utter.pitch = 1;
      window.speechSynthesis.speak(utter);
    } catch (e) {
      console.warn("TTS error", e);
    }
  }, [voices, voiceIndex]);

  // --- Effect: Speech Recognition Setup ---
  useEffect(() => {
    if (typeof window === "undefined") return;

    const { SpeechRecognition, webkitSpeechRecognition } = window as unknown as IWindow;
    const SpeechRecognitionConstructor = SpeechRecognition || webkitSpeechRecognition;

    if (!SpeechRecognitionConstructor) {
      setErrorMsg("Browser does not support Web Speech API. Please use Chrome or Edge.");
      return;
    }

    const recog = new SpeechRecognitionConstructor();
    recog.lang = "en-US";
    recog.interimResults = false;
    recog.maxAlternatives = 1;

    recog.onstart = () => {
      setStatus("listening");
      setListening(true);
      setErrorMsg(null);
    };

    recog.onerror = (e: any) => {
      if (e.error === "no-speech") {
        setStatus("idle");
        setListening(false);
        return;
      }
      setStatus("error");
      setErrorMsg(e.error || "Recognition error");
      setListening(false);
    };

    recog.onend = () => {
      setListening(false);
      setStatus((prev) => (prev === "listening" ? "idle" : prev));
    };

    recog.onresult = async (e: any) => {
      const text = Array.from(e.results).map((r: any) => r[0].transcript).join(" ");
      setTranscript(text);
      setStatus("processing");

      // Require a signed-in user (backend expects a Firebase ID token)
      if (!user) {
        setStatus("idle");
        setErrorMsg("Please sign in with email & password to use the assistant.");
        return;
      }

      try {
        const idToken = await user.getIdToken();

        const res = await debugFetch(`${BACKEND}/query`, {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Authorization": `Bearer ${idToken}`,
          },
          body: JSON.stringify({
            transcript: text,
            session_id: `web-${user?.uid || 'anon'}-${new Date().toISOString().split('T')[0]}`,
            username: user?.email || "user",
          }),
        });

        if (res.status === 401) {
          // token invalid/expired — ask user to re-login
          setStatus("idle");
          setErrorMsg("Authentication failed (token invalid). Please sign in again.");
          // clear sync mark so next login attempts will resync
          try { localStorage.removeItem(`synced_${user?.uid}`); } catch (e) { }
          return;
        }

        if (!res.ok) {
          // try to parse error detail
          let detail = "";
          try {
            const errJson = await res.json();
            detail = errJson?.error || errJson?.detail || JSON.stringify(errJson);
          } catch { /* ignore */ }
          throw new Error(`Server error: ${res.status} ${detail}`);
        }

        const data = await res.json();
        setReply(data.reply || "(no reply)");
        setIntent(data.intent || null);
        setSources(data.sources || []);

        if (autoSpeak && data.reply) speak(data.reply);

        setStatus("idle");
      } catch (err: any) {
        console.error(err);
        setStatus("error");
        setErrorMsg(err?.message || "Failed to connect to backend. Is Flask running?");
      }
    };

    recogRef.current = recog;
    return () => {
      try { recog.abort(); } catch (e) { }
    };
  }, [BACKEND, autoSpeak, speak, user]);

  // --- Handlers: Email/password auth ---
  const openLoginForm = () => {
    setLoginError(null);
    setShowLoginForm(true);
  };

  const handleLogout = async () => {
    if (auth) {
      await signOut(auth);
      setSources([]);
      setTranscript("");
      setReply("");
      // clear local synced cache on logout
      try { if (user?.uid) localStorage.removeItem(`synced_${user.uid}`); } catch (e) { }
    }
  };

  // wrapper fetch for debug + replacement (use debugFetch everywhere native fetch was used)
  async function debugFetch(url: string, opts: any) {
    console.log("[DEBUG FETCH] ->", url, opts);
    const start = performance.now();
    // clone headers to display
    try {
      if (opts && opts.headers) {
        console.log("[DEBUG FETCH] headers", opts.headers);
      }
    } catch (e) { }
    const res = await fetch(url, opts);
    const end = performance.now();
    let txt = "<no-body>";
    try { txt = await res.clone().text(); } catch (e) { }
    console.log(`[DEBUG FETCH] <- ${res.status} ${res.statusText} (${(end - start).toFixed(1)}ms)`, txt);
    return res;
  }

  const handleSubmitLogin = async (e?: React.FormEvent) => {
    if (e) e.preventDefault();
    setLoginError(null);
    setLoginSubmitting(true);

    try {
      let credential: any;
      if (isRegister) {
        credential = await createUserWithEmailAndPassword(auth, loginEmail, loginPassword);
      } else {
        credential = await signInWithEmailAndPassword(auth, loginEmail, loginPassword);
      }

      // Sync to backend (attempt once per uid only)
      try {
        if (!isAlreadySynced(credential.user.uid)) {
          const ok = await syncUserWithBackend(credential.user);
          if (ok) markSynced(credential.user.uid);
        } else {
          console.debug("sync skipped; already synced");
        }
      } catch (syncErr) {
        console.warn("Failed to sync user with backend:", syncErr);
        // don't block login; the /query call will still create the user if needed
      }

      setShowLoginForm(false);
      setLoginEmail("");
      setLoginPassword("");
    } catch (err: any) {
      console.error("Auth error", err);
      setLoginError(err?.message || "Authentication failed");
    } finally {
      setLoginSubmitting(false);
    }
  };

  /**
   * syncUserWithBackend
   * Returns true if sync succeeded (2xx), false otherwise.
   */
  const syncUserWithBackend = async (userObj: User): Promise<boolean> => {
    try {
      const idToken = await userObj.getIdToken();
      const body = {
        uid: userObj.uid,
        email: userObj.email,
        displayName: userObj.displayName || null,
        photo_url: userObj.photoURL || null,
      };
      const res = await debugFetch(`${BACKEND}/auth/sync`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Authorization": `Bearer ${idToken}`
        },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        console.warn("sync failed status", res.status);
        // if 401, allow caller to re-login
        return false;
      } else {
        console.log("synced user with backend");
        return true;
      }
    } catch (err) {
      console.warn("syncUserWithBackend error", err);
      return false;
    }
  };

  const startListening = () => {
    if (!recogRef.current) return;
    setTranscript("");
    setReply("");
    setSources([]);
    setIntent(null);
    try {
      recogRef.current.start();
    } catch (e) {
      console.warn("Mic already active");
    }
  };

  const stopListening = () => {
    try { recogRef.current.stop(); } catch (e) { }
  };

  const copyReply = () => navigator.clipboard?.writeText(reply || "");

  // --- Render ---
  return (
    <div className="min-h-screen bg-gradient-to-b from-gray-900 via-black to-gray-900 text-gray-100 p-4 md:p-8 font-sans">
      <div className="max-w-5xl mx-auto">

        {/* Header */}
        <header className="flex flex-col md:flex-row justify-between items-center gap-4 mb-8 border-b border-gray-800 pb-6">
          <div className="flex items-center gap-4">
            <div className="w-12 h-12 bg-gradient-to-tr from-blue-500 to-purple-600 rounded-lg flex items-center justify-center shadow-lg shadow-blue-900/20">
              <span className="text-2xl">🎙️</span>
            </div>
            <div>
              <h1 className="text-2xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-purple-400">
                Voice Assistant
              </h1>
              <p className="text-xs text-gray-400 font-medium tracking-wide">FIREBASE + FLASK + GEMINI</p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            {authLoading ? (
              <span className="text-gray-500 text-sm">Loading...</span>
            ) : user ? (
              <div className="flex items-center gap-3 bg-gray-800/50 px-4 py-2 rounded-full border border-gray-700">
                <img
                  src={user.photoURL || "https://via.placeholder.com/40"}
                  alt="Profile"
                  className="w-8 h-8 rounded-full border border-gray-600"
                />
                <div className="flex flex-col">
                  <span className="text-xs text-gray-400">Logged in as</span>
                  <span className="text-sm font-bold text-white leading-none">{user.displayName || user.email}</span>
                </div>
                <button
                  onClick={handleLogout}
                  className="ml-2 text-xs bg-red-500/10 hover:bg-red-500/20 text-red-400 px-3 py-1.5 rounded-full transition"
                >
                  Sign Out
                </button>
              </div>
            ) : (
              <div>
                <button
                  onClick={openLoginForm}
                  className="flex items-center gap-2 bg-white text-black px-5 py-2 rounded-full font-bold hover:bg-gray-200 transition shadow-lg"
                >
                  <img src="https://www.svgrepo.com/show/475656/google-color.svg" className="w-4 h-4" alt="G" />
                  Sign In
                </button>

                {/* Minimal inline login popup */}
                {showLoginForm && (
                  <div className="absolute right-6 top-24 z-50 w-[320px] bg-gray-900/95 border border-gray-700 rounded-xl p-4 shadow-xl">
                    <form onSubmit={handleSubmitLogin} className="space-y-3">
                      <div className="flex items-center justify-between">
                        <h3 className="text-sm font-bold">{isRegister ? "Create account" : "Sign in"}</h3>
                        <div className="flex items-center gap-2">
                          <button type="button" onClick={() => setIsRegister(!isRegister)} className="text-xs text-gray-400 hover:text-white">
                            {isRegister ? "Have an account?" : "Create"}
                          </button>
                          <button type="button" onClick={() => setShowLoginForm(false)} className="text-xs text-gray-400 hover:text-white">Close</button>
                        </div>
                      </div>

                      <div>
                        <input
                          value={loginEmail}
                          onChange={(e) => setLoginEmail(e.target.value)}
                          placeholder="Email"
                          type="email"
                          required
                          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm outline-none"
                        />
                      </div>
                      <div>
                        <input
                          value={loginPassword}
                          onChange={(e) => setLoginPassword(e.target.value)}
                          placeholder="Password (min 6 chars)"
                          type="password"
                          required
                          className="w-full bg-gray-800 border border-gray-700 rounded px-3 py-2 text-sm outline-none"
                        />
                      </div>

                      {loginError && <div className="text-xs text-red-400">{loginError}</div>}

                      <div className="flex justify-end">
                        <button type="submit" disabled={loginSubmitting} className="px-4 py-2 bg-blue-600 rounded text-sm font-bold">
                          {loginSubmitting ? "Please wait..." : isRegister ? "Create" : "Sign in"}
                        </button>
                      </div>
                    </form>
                  </div>
                )}
              </div>
            )}
            <div className="hidden md:block">
              <StatusBadge status={status} />
            </div>
          </div>
        </header>

        {/* Main Grid */}
        <main className="grid grid-cols-1 lg:grid-cols-12 gap-6">

          {/* Left Column: Controls (4 cols) */}
          <section className="lg:col-span-4 space-y-4">
            {/* Mic Control Card */}
            <div className="bg-gray-800/40 backdrop-blur-md rounded-2xl p-6 border border-gray-700/50 shadow-xl">
              <h2 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-4">Interaction</h2>

              <div className="grid grid-cols-2 gap-3 mb-4">
                <button
                  onClick={startListening}
                  disabled={listening}
                  className={`flex flex-col items-center justify-center gap-2 p-4 rounded-xl transition-all duration-200 border border-transparent ${listening ? 'bg-gray-700 opacity-50 cursor-not-allowed' : 'bg-blue-600 hover:bg-blue-500 hover:scale-[1.02] shadow-lg shadow-blue-900/30'}`}
                >
                  <span className="text-2xl">🎤</span>
                  <span className="font-bold text-sm">Tap to Speak</span>
                </button>

                <button
                  onClick={stopListening}
                  disabled={!listening}
                  className="flex flex-col items-center justify-center gap-2 p-4 rounded-xl bg-gray-700 hover:bg-gray-600 transition border border-gray-600 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                  <span className="text-2xl">⏹️</span>
                  <span className="font-bold text-sm text-gray-300">Stop</span>
                </button>
              </div>

              {/* Animation */}
              <div className={`h-12 flex items-center justify-center gap-1 transition-opacity duration-300 ${status === 'listening' ? 'opacity-100' : 'opacity-0'}`}>
                {[...Array(5)].map((_, i) => (
                  <div key={i} className="w-1.5 bg-green-400 rounded-full animate-sound-wave" style={{ height: '100%', animationDelay: `${i * 0.1}s` }}></div>
                ))}
              </div>
            </div>

            {/* Config Card */}
            <div className="bg-gray-800/40 backdrop-blur-md rounded-2xl p-6 border border-gray-700/50 shadow-xl">
              <h2 className="text-xs font-bold text-gray-500 uppercase tracking-widest mb-4">Configuration</h2>

              <div className="space-y-4">
                <div>
                  <label className="text-xs text-gray-400 mb-1.5 block">Assistant Voice</label>
                  <select
                    value={voiceIndex}
                    onChange={(e) => setVoiceIndex(Number(e.target.value))}
                    className="w-full bg-gray-900/80 text-sm px-3 py-2.5 rounded-lg border border-gray-700 focus:border-blue-500 focus:ring-1 focus:ring-blue-500 outline-none transition"
                  >
                    {voices.map((v, i) => (
                      <option key={i} value={i}>{v.name.slice(0, 30)}...</option>
                    ))}
                  </select>
                </div>

                <div className="flex items-center justify-between bg-gray-900/50 p-3 rounded-lg border border-gray-700/50">
                  <label className="text-sm text-gray-300">Auto-Read Replies</label>
                  <div
                    onClick={() => setAutoSpeak(!autoSpeak)}
                    className={`w-10 h-5 rounded-full relative cursor-pointer transition-colors ${autoSpeak ? 'bg-blue-600' : 'bg-gray-600'}`}
                  >
                    <div className={`absolute top-1 left-1 w-3 h-3 bg-white rounded-full transition-transform ${autoSpeak ? 'translate-x-5' : 'translate-x-0'}`} />
                  </div>
                </div>
              </div>
            </div>
          </section>

          {/* Right Column: Chat & Data (8 cols) */}
          <section className="lg:col-span-8 flex flex-col gap-4">
            {/* User Input Area */}
            <div className="bg-gray-800 rounded-2xl p-1 border border-gray-700 overflow-hidden shadow-lg">
              <div className="bg-gray-900/80 px-4 py-2 border-b border-gray-700 flex justify-between items-center">
                <span className="text-[10px] font-bold text-gray-500 uppercase tracking-widest">Your Query</span>
              </div>
              <div className="p-6 min-h-[100px] flex items-center">
                {transcript ? (
                  <p className="text-xl text-white font-light leading-relaxed">"{transcript}"</p>
                ) : (
                  <p className="text-gray-600 italic">Tap microphone and start speaking...</p>
                )}
              </div>
            </div>

            {/* AI Response Area */}
            <div className="flex-1 bg-gradient-to-br from-gray-800 to-gray-900 rounded-2xl p-1 border border-gray-700 relative shadow-2xl flex flex-col">
              <div className="bg-indigo-900/20 px-4 py-2 border-b border-gray-700/50 flex justify-between items-center">
                <span className="text-[10px] font-bold text-indigo-300 uppercase tracking-widest">Gemini Response</span>
                <div className="flex gap-2">
                  <button onClick={() => speak(reply)} className="p-1.5 hover:bg-white/10 rounded transition" title="Replay Audio">🔊</button>
                  <button onClick={copyReply} className="p-1.5 hover:bg-white/10 rounded transition" title="Copy Text">📋</button>
                </div>
              </div>

              <div className="p-6 flex-1">
                {reply ? (
                  <div className="prose prose-invert max-w-none prose-p:text-gray-200 prose-headings:text-white">
                    <p>{reply}</p>
                  </div>
                ) : (
                  <div className="h-full flex flex-col items-center justify-center text-gray-600 gap-2 opacity-50">
                    <div className="w-8 h-8 border-2 border-gray-600 border-t-transparent rounded-full animate-spin" style={{ display: status === 'processing' ? 'block' : 'none' }}></div>
                    <span>{status === 'processing' ? 'Thinking...' : 'Waiting for input'}</span>
                  </div>
                )}
              </div>

              {/* Metadata Footer */}
              {(intent || sources.length > 0) && (
                <div className="bg-black/20 p-4 border-t border-white/5">
                  {intent && (
                    <div className="mb-3 flex items-center gap-2">
                      <span className="text-xs text-gray-500">INTENT:</span>
                      <span className="text-xs bg-indigo-500/20 text-indigo-300 px-2 py-0.5 rounded border border-indigo-500/30 font-mono">{intent}</span>
                    </div>
                  )}

                  {sources.length > 0 && (
                    <div className="space-y-2">
                      <span className="text-[10px] text-gray-500 uppercase tracking-widest">RAG Sources</span>
                      <div className="grid gap-2">
                        {sources.map((s, idx) => (
                          <div key={idx} className="text-xs bg-gray-900/80 border border-gray-700 p-2 rounded flex justify-between items-center hover:border-gray-500 transition">
                            <div className="flex items-center gap-2 truncate">
                              <span className="bg-gray-700 text-gray-300 px-1.5 py-0.5 rounded text-[10px]">{idx + 1}</span>
                              <span className="text-gray-300 truncate">{s.source}</span>
                            </div>
                            <span className="text-green-500/80 font-mono text-[10px]">{(s.score * 100).toFixed(0)}% match</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>

            {errorMsg && (
              <div className="bg-red-500/10 border border-red-500/50 text-red-200 px-4 py-3 rounded-xl flex items-center gap-3 animate-pulse">
                <span>⚠️</span>
                <span className="text-sm font-medium">{errorMsg}</span>
              </div>
            )}

          </section>
        </main>
      </div>

      {/* Simple CSS for wave animation */}
      <style jsx>{`
        @keyframes sound-wave {
          0%, 100% { height: 20%; }
          50% { height: 100%; }
        }
        .animate-sound-wave {
          animation: sound-wave 1s infinite ease-in-out;
        }
      `}</style>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const styles: any = {
    idle: "bg-gray-800 text-gray-400 border-gray-700",
    listening: "bg-green-900/30 text-green-400 border-green-800 animate-pulse",
    processing: "bg-blue-900/30 text-blue-400 border-blue-800",
    error: "bg-red-900/30 text-red-400 border-red-800"
  };

  return (
    <span className={`px-3 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border ${styles[status] || styles.idle}`}>
      {status}
    </span>
  );
}
