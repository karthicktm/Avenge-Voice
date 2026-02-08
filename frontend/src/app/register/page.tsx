"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Loader2, Check, Sparkles, ArrowLeft, ArrowRight } from "lucide-react";
import { EmailVerificationDialog } from "@/components/auth/email-verification-dialog";
import { cn } from "@/lib/utils";

// Plan configuration
const PLANS = [
  {
    id: "free",
    name: "Free",
    price: 0,
    description: "Perfect for trying out",
    features: ["1 Agent", "1 Workspace", "10 Voice Minutes/mo", "Basic Support"],
    popular: false,
  },
  {
    id: "starter",
    name: "Starter",
    price: 49,
    description: "For small teams",
    features: [
      "5 Agents",
      "3 Workspaces",
      "500 Voice Minutes/mo",
      "10K LLM Requests/mo",
      "Email Support",
    ],
    popular: false,
  },
  {
    id: "professional",
    name: "Professional",
    price: 199,
    description: "For growing businesses",
    features: [
      "20 Agents",
      "10 Workspaces",
      "2,000 Voice Minutes/mo",
      "50K LLM Requests/mo",
      "Priority Support",
      "Advanced Analytics",
    ],
    popular: true,
  },
  {
    id: "enterprise",
    name: "Enterprise",
    price: -1,
    description: "For large organizations",
    features: [
      "Unlimited Agents",
      "Unlimited Workspaces",
      "Unlimited Voice Minutes",
      "Unlimited LLM Requests",
      "24/7 Dedicated Support",
      "Custom Integrations",
      "SLA Guarantee",
    ],
    popular: false,
  },
];

export default function RegisterPage() {
  const { register } = useAuth();
  const router = useRouter();

  // Multi-step state
  const [step, setStep] = useState<"plan" | "details">("plan");
  const [selectedPlan, setSelectedPlan] = useState<string>("free");

  // Form state
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [showVerificationDialog, setShowVerificationDialog] = useState(false);

  const handlePlanSelect = (planId: string) => {
    if (planId === "enterprise") {
      // Redirect to contact sales
      window.location.href = "mailto:sales@avengeai.com?subject=Enterprise Plan Inquiry";
      return;
    }
    setSelectedPlan(planId);
  };

  const handleContinueToDetails = () => {
    setStep("details");
  };

  const handleBackToPlan = () => {
    setStep("plan");
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");

    if (password !== confirmPassword) {
      setError("Passwords do not match");
      return;
    }

    if (password.length < 8) {
      setError("Password must be at least 8 characters");
      return;
    }

    setIsLoading(true);

    try {
      // Pass the selected plan to the register function
      await register(email, username, password, selectedPlan);
      // Show verification dialog after successful registration
      setShowVerificationDialog(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setIsLoading(false);
    }
  };

  const handleVerified = (accessToken: string) => {
    // Save token and redirect to dashboard
    localStorage.setItem("access_token", accessToken);
    router.push("/dashboard");
  };

  const selectedPlanData = PLANS.find((p) => p.id === selectedPlan);

  return (
    <div className="flex min-h-screen flex-col items-center justify-center bg-black p-4">
      {/* Logo */}
      <div className="mb-8">
        <span
          className="animate-gradient-flow bg-clip-text text-3xl font-bold tracking-tight text-transparent"
          style={{
            backgroundImage: "linear-gradient(90deg, #e2e8f0, #94a3b8, #e2e8f0, #94a3b8, #e2e8f0)",
            backgroundSize: "200% 100%",
          }}
        >
          Avenge AI
        </span>
      </div>

      {step === "plan" ? (
        /* Step 1: Plan Selection */
        <div className="w-full max-w-5xl">
          <div className="mb-8 text-center">
            <h1 className="text-3xl font-bold text-white">Choose your plan</h1>
            <p className="mt-2 text-muted-foreground">
              Select the plan that best fits your needs. You can upgrade anytime.
            </p>
          </div>

          <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
            {PLANS.map((plan) => (
              <Card
                key={plan.id}
                className={cn(
                  "relative flex cursor-pointer flex-col transition-all hover:border-primary/50",
                  plan.popular && "border-primary shadow-lg shadow-primary/20",
                  selectedPlan === plan.id && "border-primary bg-primary/5 ring-2 ring-primary"
                )}
                onClick={() => handlePlanSelect(plan.id)}
              >
                {plan.popular && (
                  <div className="absolute -top-3 left-1/2 -translate-x-1/2">
                    <Badge className="bg-primary">
                      <Sparkles className="mr-1 h-3 w-3" />
                      Most Popular
                    </Badge>
                  </div>
                )}

                {selectedPlan === plan.id && (
                  <div className="absolute right-3 top-3">
                    <div className="flex h-6 w-6 items-center justify-center rounded-full bg-primary">
                      <Check className="h-4 w-4 text-primary-foreground" />
                    </div>
                  </div>
                )}

                <CardHeader className="pb-2">
                  <CardTitle className="text-lg">{plan.name}</CardTitle>
                  <CardDescription className="text-xs">{plan.description}</CardDescription>
                </CardHeader>

                <CardContent className="pb-2">
                  <div className="mb-4">
                    {plan.price === -1 ? (
                      <span className="text-2xl font-bold">Custom</span>
                    ) : (
                      <>
                        <span className="text-3xl font-bold">${plan.price}</span>
                        <span className="text-sm text-muted-foreground">/month</span>
                      </>
                    )}
                  </div>

                  <ul className="space-y-1.5">
                    {plan.features.map((feature, i) => (
                      <li key={i} className="flex items-start gap-2 text-xs">
                        <Check className="mt-0.5 h-3 w-3 shrink-0 text-primary" />
                        <span className="text-muted-foreground">{feature}</span>
                      </li>
                    ))}
                  </ul>
                </CardContent>

                <CardFooter className="mt-auto pt-2">
                  {plan.id === "enterprise" ? (
                    <Button variant="outline" size="sm" className="w-full" asChild>
                      <a href="mailto:sales@avengeai.com">Contact Sales</a>
                    </Button>
                  ) : (
                    <Button
                      variant={selectedPlan === plan.id ? "default" : "outline"}
                      size="sm"
                      className="w-full"
                      onClick={(e) => {
                        e.stopPropagation();
                        handlePlanSelect(plan.id);
                      }}
                    >
                      {selectedPlan === plan.id ? "Selected" : "Select"}
                    </Button>
                  )}
                </CardFooter>
              </Card>
            ))}
          </div>

          <div className="mt-8 flex flex-col items-center gap-4">
            <Button
              size="lg"
              className="min-w-[200px]"
              onClick={handleContinueToDetails}
              disabled={!selectedPlan || selectedPlan === "enterprise"}
            >
              Continue
              <ArrowRight className="ml-2 h-4 w-4" />
            </Button>
            <p className="text-center text-sm text-muted-foreground">
              Already have an account?{" "}
              <Link href="/login" className="text-primary hover:underline">
                Sign in
              </Link>
            </p>
          </div>
        </div>
      ) : (
        /* Step 2: Account Details */
        <Card className="w-full max-w-md">
          <CardHeader className="space-y-1">
            <div className="flex items-center gap-2">
              <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleBackToPlan}>
                <ArrowLeft className="h-4 w-4" />
              </Button>
              <div>
                <CardTitle className="text-2xl font-bold">Create your account</CardTitle>
                <CardDescription>
                  {selectedPlanData && (
                    <span className="flex items-center gap-2">
                      Selected plan:{" "}
                      <Badge variant="outline" className="font-medium">
                        {selectedPlanData.name}
                        {selectedPlanData.price > 0 && ` - $${selectedPlanData.price}/mo`}
                      </Badge>
                    </span>
                  )}
                </CardDescription>
              </div>
            </div>
          </CardHeader>
          <form onSubmit={(e) => void handleSubmit(e)}>
            <CardContent className="space-y-4">
              {error && (
                <div className="rounded-md bg-destructive/15 p-3 text-sm text-destructive">
                  {error}
                </div>
              )}
              <div className="space-y-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="you@example.com"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="username">Full Name</Label>
                <Input
                  id="username"
                  type="text"
                  placeholder="John Doe"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>
              <div className="space-y-2">
                <Label htmlFor="confirmPassword">Confirm Password</Label>
                <Input
                  id="confirmPassword"
                  type="password"
                  value={confirmPassword}
                  onChange={(e) => setConfirmPassword(e.target.value)}
                  required
                  disabled={isLoading}
                />
              </div>
            </CardContent>
            <CardFooter className="flex flex-col space-y-4">
              <Button type="submit" className="w-full" disabled={isLoading}>
                {isLoading && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                Create account
              </Button>
              <p className="text-center text-xs text-muted-foreground">
                By creating an account, you agree to our{" "}
                <Link href="/terms" className="text-primary hover:underline">
                  Terms of Service
                </Link>{" "}
                and{" "}
                <Link href="/privacy" className="text-primary hover:underline">
                  Privacy Policy
                </Link>
              </p>
            </CardFooter>
          </form>
        </Card>
      )}

      {/* Email Verification Dialog */}
      <EmailVerificationDialog
        open={showVerificationDialog}
        onOpenChange={setShowVerificationDialog}
        email={email}
        onVerified={handleVerified}
      />
    </div>
  );
}
