"use client";

import { useState, useRef, useEffect } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Loader2, Mail, RefreshCw, CheckCircle2 } from "lucide-react";
import { emailVerificationApi } from "@/lib/api";
import { toast } from "sonner";

interface EmailVerificationDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  email: string;
  onVerified: (accessToken: string) => void;
}

export function EmailVerificationDialog({
  open,
  onOpenChange,
  email,
  onVerified,
}: EmailVerificationDialogProps) {
  const [code, setCode] = useState(["", "", "", "", "", ""]);
  const [error, setError] = useState("");
  const [isVerifying, setIsVerifying] = useState(false);
  const [isResending, setIsResending] = useState(false);
  const [resendCountdown, setResendCountdown] = useState(0);
  const [isSuccess, setIsSuccess] = useState(false);
  const inputRefs = useRef<(HTMLInputElement | null)[]>([]);

  // Start countdown when dialog opens
  useEffect(() => {
    if (open) {
      setResendCountdown(60); // 60 second cooldown
    }
  }, [open]);

  // Countdown timer
  useEffect(() => {
    if (resendCountdown > 0) {
      const timer = setTimeout(() => setResendCountdown(resendCountdown - 1), 1000);
      return () => clearTimeout(timer);
    }
    return undefined;
  }, [resendCountdown]);

  // Auto-focus first input when dialog opens
  useEffect(() => {
    if (open && inputRefs.current[0]) {
      inputRefs.current[0].focus();
    }
  }, [open]);

  const handleCodeChange = (index: number, value: string) => {
    // Only allow digits
    if (value && !/^\d$/.test(value)) return;

    const newCode = [...code];
    newCode[index] = value;
    setCode(newCode);
    setError("");

    // Auto-focus next input
    if (value && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }

    // Auto-submit when all 6 digits are entered
    if (index === 5 && value) {
      const fullCode = newCode.join("");
      if (fullCode.length === 6) {
        void handleVerify(fullCode);
      }
    }
  };

  const handleKeyDown = (index: number, e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "Backspace" && !code[index] && index > 0) {
      // Move to previous input on backspace if current is empty
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowLeft" && index > 0) {
      inputRefs.current[index - 1]?.focus();
    } else if (e.key === "ArrowRight" && index < 5) {
      inputRefs.current[index + 1]?.focus();
    }
  };

  const handlePaste = (e: React.ClipboardEvent) => {
    e.preventDefault();
    const pastedData = e.clipboardData.getData("text").replace(/\D/g, "").slice(0, 6);

    if (pastedData.length === 6) {
      const newCode = pastedData.split("");
      setCode(newCode);
      setError("");
      inputRefs.current[5]?.focus();

      // Auto-submit
      void handleVerify(pastedData);
    }
  };

  const handleVerify = async (codeToVerify?: string) => {
    const verificationCode = codeToVerify ?? code.join("");

    if (verificationCode.length !== 6) {
      setError("Please enter all 6 digits");
      return;
    }

    setIsVerifying(true);
    setError("");

    try {
      const response = await emailVerificationApi.verifyCode(email, verificationCode);
      setIsSuccess(true);
      toast.success("Email verified successfully!");
      // Wait a moment to show success state before redirecting
      setTimeout(() => {
        onVerified(response.access_token);
        onOpenChange(false);
      }, 1500);
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosError = err as { response?: { data?: { detail?: string } } };
        setError(axiosError.response?.data?.detail ?? "Invalid verification code");
      } else {
        setError("Failed to verify code. Please try again.");
      }
      // Clear code on error
      setCode(["", "", "", "", "", ""]);
      inputRefs.current[0]?.focus();
    } finally {
      setIsVerifying(false);
    }
  };

  const handleResend = async () => {
    setIsResending(true);
    setError("");

    try {
      await emailVerificationApi.sendCode(email);
      setResendCountdown(60);
      setCode(["", "", "", "", "", ""]);
      inputRefs.current[0]?.focus();
    } catch (err: unknown) {
      if (err && typeof err === "object" && "response" in err) {
        const axiosError = err as { response?: { data?: { detail?: string } } };
        setError(axiosError.response?.data?.detail ?? "Failed to resend code");
      } else {
        setError("Failed to resend code. Please try again.");
      }
    } finally {
      setIsResending(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-md">
        {isSuccess ? (
          // Success state
          <div className="py-8 text-center">
            <div className="mx-auto mb-4 flex h-16 w-16 items-center justify-center rounded-full bg-green-100 dark:bg-green-900/30">
              <CheckCircle2 className="h-10 w-10 text-green-600 dark:text-green-400" />
            </div>
            <h3 className="mb-2 text-xl font-semibold">Email Verified!</h3>
            <p className="text-muted-foreground">
              Your account has been verified successfully.
              <br />
              Redirecting to dashboard...
            </p>
          </div>
        ) : (
          // Verification form
          <>
            <DialogHeader>
              <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-full bg-primary/10">
                <Mail className="h-6 w-6 text-primary" />
              </div>
              <DialogTitle className="text-center">Verify your email</DialogTitle>
              <DialogDescription className="text-center">
                We&apos;ve sent a 6-digit code to <strong>{email}</strong>
                <br />
                Enter the code below to verify your account.
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-4 py-4">
              {/* 6-digit code input */}
              <div className="flex justify-center gap-2">
                {code.map((digit, index) => (
                  <Input
                    key={index}
                    ref={(el) => {
                      inputRefs.current[index] = el;
                    }}
                    type="text"
                    inputMode="numeric"
                    maxLength={1}
                    value={digit}
                    onChange={(e) => handleCodeChange(index, e.target.value)}
                    onKeyDown={(e) => handleKeyDown(index, e)}
                    onPaste={index === 0 ? handlePaste : undefined}
                    disabled={isVerifying}
                    className="h-14 w-12 text-center text-lg font-semibold"
                    aria-label={`Digit ${index + 1}`}
                  />
                ))}
              </div>

              {/* Error message */}
              {error && (
                <div className="rounded-md bg-destructive/15 p-3 text-center text-sm text-destructive">
                  {error}
                </div>
              )}

              {/* Resend button */}
              <div className="text-center">
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => void handleResend()}
                  disabled={isResending || resendCountdown > 0}
                  className="text-sm text-muted-foreground hover:text-foreground"
                >
                  {isResending ? (
                    <>
                      <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                      Sending...
                    </>
                  ) : resendCountdown > 0 ? (
                    `Resend code in ${resendCountdown}s`
                  ) : (
                    <>
                      <RefreshCw className="mr-2 h-4 w-4" />
                      Resend code
                    </>
                  )}
                </Button>
              </div>
            </div>

            <DialogFooter>
              <Button
                onClick={() => void handleVerify()}
                disabled={isVerifying || code.join("").length !== 6}
                className="w-full"
              >
                {isVerifying && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Verify Email
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
