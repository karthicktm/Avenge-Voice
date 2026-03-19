"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { api } from "@/lib/api";
import { Loader2 } from "lucide-react";

export default function AuthCallbackPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const errorParam = searchParams.get("error");

    if (errorParam) {
      const messages: Record<string, string> = {
        google_oauth_cancelled: "Google sign-in was cancelled.",
        invalid_oauth_state: "Invalid OAuth state. Please try again.",
        invalid_oauth_response: "Invalid response from Google. Please try again.",
        google_token_exchange_failed: "Failed to sign in with Google. Please try again.",
        google_missing_user_info: "Could not retrieve your Google account info.",
        oauth_not_configured: "Google sign-in is not configured.",
      };
      setError(messages[errorParam] ?? "Sign-in failed. Please try again.");
      setTimeout(() => router.replace("/login"), 3000);
      return;
    }

    // Read token from URL fragment (#token=...) — fragments are never sent to
    // servers or written to access logs, keeping the JWT out of log files.
    const hash = window.location.hash.slice(1);
    const params = new URLSearchParams(hash);
    const token = params.get("token");

    // Remove the fragment from the URL immediately so the token doesn't linger
    // in the browser's session history.
    window.history.replaceState(null, "", window.location.pathname);

    if (!token) {
      setError("No authentication token received.");
      setTimeout(() => router.replace("/login"), 3000);
      return;
    }

    // Store token and verify it
    localStorage.setItem("access_token", token);

    api
      .get("/api/v1/auth/me")
      .then(() => {
        router.replace("/dashboard");
      })
      .catch(() => {
        localStorage.removeItem("access_token");
        setError("Authentication failed. Please try again.");
        setTimeout(() => router.replace("/login"), 3000);
      });
  }, [router, searchParams]);

  if (error) {
    return (
      <div className="flex min-h-screen flex-col items-center justify-center bg-black p-4">
        <div className="max-w-md rounded-md bg-destructive/15 p-4 text-center text-sm text-destructive">
          {error}
          <p className="mt-2 text-xs text-muted-foreground">Redirecting to login...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-black p-4">
      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      <p className="mt-4 text-sm text-muted-foreground">Signing you in...</p>
    </div>
  );
}
