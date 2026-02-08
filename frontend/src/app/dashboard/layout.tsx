"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import { AppSidebar } from "@/components/app-sidebar";
import { TopBar } from "@/components/top-bar";
import { useAuth } from "@/hooks/use-auth";
import { EmailVerificationDialog } from "@/components/auth/email-verification-dialog";
import { Loader2 } from "lucide-react";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const { user, token, isLoading } = useAuth();
  const [showVerificationDialog, setShowVerificationDialog] = useState(false);

  // Redirect to login if not authenticated
  useEffect(() => {
    if (!isLoading && !token) {
      // Save the current path to redirect back after login
      const returnUrl = encodeURIComponent(pathname);
      router.push(`/login?returnUrl=${returnUrl}`);
    }
  }, [isLoading, token, router, pathname]);

  // Show verification dialog if email not verified
  useEffect(() => {
    if (!isLoading && user && !user.email_verified) {
      setShowVerificationDialog(true);
    }
  }, [isLoading, user]);

  // Handle successful email verification
  const handleVerified = (accessToken: string) => {
    // Store the new token (the auth context will automatically refresh user data)
    localStorage.setItem("access_token", accessToken);
    setShowVerificationDialog(false);
    // Reload to refresh user state
    window.location.reload();
  };

  // Show loading state while checking auth
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-primary" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  // Don't render dashboard if not authenticated
  if (!token) {
    return null;
  }

  return (
    <>
      <div className="flex h-screen overflow-hidden bg-sidebar">
        <AppSidebar />
        <div className="relative flex flex-1 flex-col overflow-hidden">
          <TopBar />
          <div className="flex-1 overflow-hidden px-2.5 pb-2.5">
            <main className="flex h-full flex-col overflow-hidden rounded-lg bg-background">
              <div className="flex flex-1 flex-col gap-4 overflow-auto p-4 md:p-6 lg:p-8">
                {children}
              </div>
            </main>
          </div>
        </div>
      </div>

      {/* Email Verification Dialog */}
      {user && !user.email_verified && (
        <EmailVerificationDialog
          open={showVerificationDialog}
          onOpenChange={setShowVerificationDialog}
          email={user.email}
          onVerified={handleVerified}
        />
      )}
    </>
  );
}
