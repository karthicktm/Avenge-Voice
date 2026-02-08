"use client";

import { useEffect } from "react";
import Link from "next/link";
import Script from "next/script";

// Type declaration for the WaveformAnimation class loaded from external script
declare global {
  interface Window {
    WaveformAnimation?: new (canvasId: string) => void;
  }
}

export default function LandingPage() {
  useEffect(() => {
    // Initialize Intersection Observer for scroll animations
    const observerOptions = {
      threshold: 0.1,
      rootMargin: "0px 0px -50px 0px",
    };

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry: IntersectionObserverEntry, index: number) => {
        if (entry.isIntersecting) {
          setTimeout(() => {
            entry.target.classList.add("visible");
          }, index * 100);
        }
      });
    }, observerOptions);

    // Observe all animatable elements
    const featureCards = document.querySelectorAll(".feature-card");
    featureCards.forEach((card) => observer.observe(card));

    const pricingCards = document.querySelectorAll(".pricing-card");
    pricingCards.forEach((card) => observer.observe(card));

    const integrationItems = document.querySelectorAll(".integration-item");
    integrationItems.forEach((item: Element) => observer.observe(item));

    // Initialize hero waveform animation with retry logic
    let attempts = 0;
    const maxAttempts = 20;
    const initWaveform = () => {
      attempts++;
      if (typeof window.WaveformAnimation !== "undefined") {
        new window.WaveformAnimation("waveform");
      } else if (attempts < maxAttempts) {
        setTimeout(initWaveform, 200);
      }
    };
    initWaveform();

    // Cleanup
    return () => {
      observer.disconnect();
    };
  }, []);

  return (
    <>
      {/* Hero Section */}
      <section className="hero section">
        <div className="hero-badge">MULTI-AGENT AI PLATFORM</div>

        <h1 className="hero-title">AVENGE AI</h1>

        <canvas id="waveform" className="hero-animation"></canvas>

        <p className="hero-subtitle">
          Build AI agents for <span className="text-bold">voice, chat, and automation</span>.
        </p>

        <div className="hero-cta">
          <Link href="/register" className="btn btn-primary">
            Get Started
          </Link>
          <Link href="#pricing" className="btn btn-secondary">
            View Demo
          </Link>
        </div>
      </section>

      {/* Features Section */}
      <section id="features" className="features section">
        <div className="container">
          <div className="text-label">CAPABILITIES</div>
          <h2>Everything You Need to Build AI Agents</h2>

          <div className="features-grid">
            <div className="feature-card">
              <div className="feature-icon">01</div>
              <h3 className="feature-title">Real-Time Voice AI</h3>
              <p className="feature-description">
                Sub-320ms latency with OpenAI GPT-4 Realtime. Natural conversations that feel human.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">02</div>
              <h3 className="feature-title">Multi-LLM Support</h3>
              <p className="feature-description">
                Choose from OpenAI, Google Gemini, or Cerebras. Pick your price-to-quality tradeoff.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">03</div>
              <h3 className="feature-title">30+ Integrations</h3>
              <p className="feature-description">
                Connect to HubSpot, Salesforce, Google Calendar, Shopify, Slack, and more out of the
                box.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">04</div>
              <h3 className="feature-title">Built-in CRM</h3>
              <p className="feature-description">
                Contact management, call history, and analytics included. No external CRM required.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">05</div>
              <h3 className="feature-title">Embeddable Widget</h3>
              <p className="feature-description">
                Add voice AI to any website with one line of code. Domain allowlisting for security.
              </p>
            </div>

            <div className="feature-card">
              <div className="feature-icon">06</div>
              <h3 className="feature-title">Flexible Pricing</h3>
              <p className="feature-description">
                Start free with 100K tokens. Scale to millions as you grow. No hidden fees.
              </p>
            </div>
          </div>
        </div>
      </section>

      {/* Pricing Section */}
      <section id="pricing" className="pricing section">
        <div className="container">
          <div className="text-label">PRICING PLANS</div>
          <h2>Start Free, Scale as You Grow</h2>

          <div className="pricing-grid">
            <div className="pricing-card">
              <div className="pricing-tier">Free</div>
              <div className="pricing-cost">$0</div>
              <div className="pricing-unit">forever</div>
              <ul className="pricing-features">
                <li>1 AI Workspace</li>
                <li>100K tokens/month</li>
                <li>Community support</li>
                <li>Basic integrations</li>
              </ul>
              <Link href="/register" className="btn btn-secondary">
                Start Free
              </Link>
            </div>

            <div className="pricing-card">
              <div className="pricing-tier">Starter</div>
              <div className="pricing-cost">$29</div>
              <div className="pricing-unit">per month</div>
              <ul className="pricing-features">
                <li>Up to 5 AI Workspaces</li>
                <li>1M tokens/month</li>
                <li>Email support</li>
                <li>All integrations</li>
              </ul>
              <Link href="/register" className="btn btn-secondary">
                Choose Starter
              </Link>
            </div>

            <div className="pricing-card popular">
              <div className="pricing-tier">Growth</div>
              <div className="pricing-cost">$99</div>
              <div className="pricing-unit">per month</div>
              <ul className="pricing-features">
                <li>Up to 20 AI Workspaces</li>
                <li>10M tokens/month</li>
                <li>Priority support</li>
                <li>Advanced analytics</li>
                <li>Custom integrations</li>
              </ul>
              <Link href="/register" className="btn btn-primary">
                Choose Growth
              </Link>
            </div>

            <div className="pricing-card">
              <div className="pricing-tier">Enterprise</div>
              <div className="pricing-cost">Custom</div>
              <div className="pricing-unit">contact sales</div>
              <ul className="pricing-features">
                <li>Unlimited AI Workspaces</li>
                <li>Unlimited tokens</li>
                <li>Dedicated support</li>
                <li>Custom integrations</li>
              </ul>
              <Link href="/register" className="btn btn-secondary">
                Contact Sales
              </Link>
            </div>
          </div>
        </div>
      </section>

      {/* Integrations Section */}
      <section id="integrations" className="integrations section">
        <div className="container">
          <div className="text-label">INTEGRATIONS</div>
          <h2>Connect to Your Favorite Tools</h2>

          <div className="integrations-grid">
            <div className="integration-item">HubSpot</div>
            <div className="integration-item">Salesforce</div>
            <div className="integration-item">Pipedrive</div>
            <div className="integration-item">Zoho CRM</div>
            <div className="integration-item">Google Calendar</div>
            <div className="integration-item">Calendly</div>
            <div className="integration-item">Cal.com</div>
            <div className="integration-item">Shopify</div>
            <div className="integration-item">Slack</div>
            <div className="integration-item">Outlook</div>
            <div className="integration-item">Gmail</div>
            <div className="integration-item">SendGrid</div>
            <div className="integration-item">Airtable</div>
            <div className="integration-item">Notion</div>
            <div className="integration-item">Google Sheets</div>
            <div className="integration-item">Stripe</div>
          </div>
        </div>
      </section>

      {/* CTA Section */}
      <section className="cta-section">
        <div className="container">
          <h2>Ready to Build Your AI Agents?</h2>
          <p style={{ fontSize: "20px", marginBottom: "32px", opacity: 0.9 }}>
            <span className="text-bold">Voice, chat, automation.</span> All in one platform.
          </p>
          <div style={{ display: "flex", gap: "16px", justifyContent: "center", flexWrap: "wrap" }}>
            <Link href="/register" className="btn btn-primary">
              Get Started Free
            </Link>
            <Link href="/login" className="btn btn-secondary btn-secondary-dark">
              Book a Demo
            </Link>
          </div>
        </div>
      </section>

      {/* Load animation scripts */}
      <Script src="/landing/animations.js" strategy="lazyOnload" />
      <Script
        src="/landing/hero-animation.js"
        strategy="afterInteractive"
        onReady={() => {
          // Initialize waveform animation after script loads
          if (typeof window.WaveformAnimation !== "undefined") {
            new window.WaveformAnimation("waveform");
          }
        }}
      />
    </>
  );
}
