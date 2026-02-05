"use client";

import Link from "next/link";
import { useAuth } from "@/hooks/use-auth";

import "./marketing.css";

export default function MarketingLayout({
    children,
}: {
    children: React.ReactNode;
}) {
    const { user } = useAuth();

    return (
        <div className="landing-page">
            {/* Navigation */}
            <nav className="nav">
                <div className="nav-container">
                    <div className="nav-logo">AVENGE AI</div>
                    <ul className="nav-links">
                        <li>
                            <a href="#features" className="nav-link">
                                Features
                            </a>
                        </li>
                        <li>
                            <a href="#pricing" className="nav-link">
                                Pricing
                            </a>
                        </li>
                        <li>
                            <a href="#integrations" className="nav-link">
                                Integrations
                            </a>
                        </li>
                        <li>
                            {user ? (
                                <Link href="/dashboard" className="btn btn-primary">
                                    Dashboard
                                </Link>
                            ) : (
                                <Link href="/login" className="btn btn-primary">
                                    Sign In
                                </Link>
                            )}
                        </li>
                    </ul>
                </div>
            </nav>

            {children}

            {/* Footer */}
            <footer className="footer">
                <div className="container">
                    <div className="footer-content">
                        <div className="footer-brand">
                            <div className="footer-logo">AVENGE AI</div>
                            <p className="footer-tagline">© 2026 Avenge AI. Enterprise AI Platform.</p>
                        </div>

                    </div>
                </div>
            </footer>
        </div>
    );
}
