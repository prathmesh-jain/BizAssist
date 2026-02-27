import React, { useEffect } from 'react';
import { Link } from 'react-router-dom';
import { ArrowRight, FileText, ShieldCheck, Sparkles, Table2, Zap } from 'lucide-react';
import { useAuth } from '../context/AuthContext';

export default function Landing() {
  const { user, loading } = useAuth();

  useEffect(() => {
    const normalizeBase = (raw?: string) => {
      const base = (raw || 'http://localhost:8000').replace(/\/+$/, '');
      return base.endsWith('/api') ? base.slice(0, -4) : base;
    };

    const baseUrl = normalizeBase(import.meta.env.VITE_API_URL);
    fetch(`${baseUrl}/health`).catch(() => undefined);
  }, []);

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="sticky top-0 z-50 border-b border-border bg-background/70 backdrop-blur supports-backdrop-filter:bg-background/60">
        <div className="mx-auto max-w-6xl px-4 sm:px-6">
          <div className="flex h-16 items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="h-9 w-9 rounded-xl bg-primary flex items-center justify-center text-primary-foreground font-bold shadow-sm">
                B
              </div>
              <div className="leading-tight">
                <div className="text-sm font-bold">BizAssist</div>
                <div className="text-xs text-muted-foreground">AI Business Finance Assistant</div>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {loading ? null : user ? (
                <Link
                  to="/app"
                  className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
                >
                  Dashboard
                </Link>
              ) : (
                <>
                  <Link
                    to="/login"
                    className="rounded-xl border border-border bg-card px-4 py-2 text-sm font-semibold text-foreground hover:bg-muted transition-colors"
                  >
                    Sign in
                  </Link>
                  <Link
                    to="/signup"
                    className="rounded-xl bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground hover:bg-primary/90 transition-colors"
                  >
                    Get started
                  </Link>
                </>
              )}
            </div>
          </div>
        </div>
      </header>

      <main>
        <section className="relative overflow-hidden">
          <div className="absolute inset-0 bg-grid-slate-200/[0.06] mask-[radial-gradient(ellipse_at_top,white,transparent_60%)]" />
          <div className="mx-auto max-w-6xl px-4 sm:px-6 pt-14 pb-14 relative">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-10 items-center">
              <div>
                <div className="inline-flex items-center gap-2 rounded-full border border-border bg-card px-3 py-1 text-xs font-semibold text-muted-foreground">
                  <Sparkles className="h-4 w-4 text-primary" />
                  Built for invoices, expenses & Google Sheets
                </div>

                <h1 className="mt-5 text-4xl sm:text-5xl font-extrabold tracking-tight">
                  Your AI assistant for business finance operations.
                </h1>

                <p className="mt-4 text-lg text-muted-foreground leading-relaxed">
                  BizAssist helps you extract data from invoices and documents, keep expenses organized, and work faster
                  with Google Sheets—so you can focus on running the business.
                </p>

                <div className="mt-7 flex flex-col sm:flex-row gap-3">
                  {loading ? null : user ? (
                    <Link
                      to="/app"
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-bold text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
                    >
                      Go to dashboard
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  ) : (
                    <Link
                      to="/signup"
                      className="inline-flex items-center justify-center gap-2 rounded-xl bg-primary px-5 py-3 text-sm font-bold text-primary-foreground shadow-sm hover:bg-primary/90 transition-colors"
                    >
                      Try now
                      <ArrowRight className="h-4 w-4" />
                    </Link>
                  )}
                  <a
                    href="#features"
                    className="inline-flex items-center justify-center gap-2 rounded-xl border border-border bg-card px-5 py-3 text-sm font-semibold text-foreground hover:bg-muted transition-colors"
                  >
                    Explore features
                  </a>
                </div>

                <div className="mt-6 text-xs text-muted-foreground">
                  By continuing, you agree to our{' '}
                  <a className="text-primary hover:underline" href="https://bizassist.prathmeshjain.online/terms-conditions.html">Terms</a>
                  {' '}and{' '}
                  <a className="text-primary hover:underline" href="https://bizassist.prathmeshjain.online/privacy-policy.html">Privacy Policy</a>.
                </div>
              </div>

              <div className="relative">
                <div className="rounded-3xl border border-border bg-card p-6 shadow-xl">
                  <div className="flex items-center justify-between">
                    <div className="text-sm font-bold">What you can do</div>
                    <div className="text-xs text-muted-foreground">In minutes</div>
                  </div>

                  <div className="mt-4 grid grid-cols-1 gap-3">
                    <DemoRow title="Upload invoices" subtitle="Extract totals, vendor, taxes, and dates" icon={<FileText className="h-5 w-5 text-primary" />} />
                    <DemoRow title="Ask questions" subtitle="Get summaries, comparisons, and trends" icon={<Zap className="h-5 w-5 text-primary" />} />
                    <DemoRow title="Work with Sheets" subtitle="Read sheets, analyze data, and generate insights" icon={<Table2 className="h-5 w-5 text-primary" />} />
                    <DemoRow title="Stay safe" subtitle="Guardrails block out-of-scope requests" icon={<ShieldCheck className="h-5 w-5 text-primary" />} />
                  </div>
                </div>

                <div className="absolute -bottom-10 -right-10 h-40 w-40 rounded-full bg-primary/20 blur-3xl" />
                <div className="absolute -top-10 -left-10 h-40 w-40 rounded-full bg-blue-500/15 blur-3xl" />
              </div>
            </div>
          </div>
        </section>

        <section id="features" className="mx-auto max-w-6xl px-4 sm:px-6 py-14">
          <div className="max-w-2xl">
            <h2 className="text-3xl font-extrabold tracking-tight">Capabilities built for finance workflows</h2>
            <p className="mt-3 text-muted-foreground">
              Everything is designed around real business operations—documents, spreadsheets, and actionable answers.
            </p>
          </div>

          <div className="mt-10 grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-5">
            <FeatureCard title="Invoice & document extraction" description="Pull structured data from PDFs and receipts to reduce manual work." icon={<FileText className="h-5 w-5" />} />
            <FeatureCard title="AI chat assistant" description="Ask for summaries, insights, and next steps based on your uploaded data." icon={<Sparkles className="h-5 w-5" />} />
            <FeatureCard title="Google Sheets analysis" description="Connect Sheets and analyze tabs, totals, and performance instantly." icon={<Table2 className="h-5 w-5" />} />
            <FeatureCard title="Fast workflows" description="Turn repetitive finance operations into guided, repeatable processes." icon={<Zap className="h-5 w-5" />} />
            <FeatureCard title="Guardrails" description="Blocks unsafe/out-of-scope requests to keep usage focused and secure." icon={<ShieldCheck className="h-5 w-5" />} />
            <FeatureCard title="Knowledge ingestion" description="Upload docs once and query them naturally later in the chat." icon={<FileText className="h-5 w-5" />} />
          </div>
        </section>

        <section id="how-it-works" className="border-t border-border bg-card/40">
          <div className="mx-auto max-w-6xl px-4 sm:px-6 py-14">
            <h2 className="text-3xl font-extrabold tracking-tight">How it works</h2>
            <div className="mt-8 grid grid-cols-1 md:grid-cols-3 gap-5">
              <StepCard step="1" title="Sign in" description="Create an account and open your workspace." />
              <StepCard step="2" title="Connect data" description="Upload documents and optionally connect Google Sheets." />
              <StepCard step="3" title="Ask & act" description="Get answers, summaries, and insights to drive decisions." />
            </div>
          </div>
        </section>

        <footer className="border-t border-border">
          <div className="mx-auto max-w-6xl px-4 sm:px-6 py-10 text-sm text-muted-foreground flex flex-col md:flex-row md:items-center md:justify-between gap-4">
            <div>© {new Date().getFullYear()} BizAssist</div>
            <div className="flex items-center gap-4">
              <a className="hover:text-foreground transition-colors" href="https://bizassist.prathmeshjain.online/privacy-policy.html">Privacy Policy</a>
              <a className="hover:text-foreground transition-colors" href="https://bizassist.prathmeshjain.online/terms-conditions.html">Terms &amp; Conditions</a>
            </div>
          </div>
        </footer>
      </main>
    </div>
  );
}

function DemoRow({ title, subtitle, icon }: { title: string; subtitle: string; icon: React.ReactNode }) {
  return (
    <div className="flex items-start gap-3 rounded-2xl border border-border bg-background/40 p-4">
      <div className="h-10 w-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center shrink-0">
        {icon}
      </div>
      <div>
        <div className="text-sm font-bold">{title}</div>
        <div className="mt-0.5 text-xs text-muted-foreground">{subtitle}</div>
      </div>
    </div>
  );
}

function FeatureCard({
  title,
  description,
  icon,
}: {
  title: string;
  description: string;
  icon: React.ReactNode;
}) {
  return (
    <div className="rounded-3xl border border-border bg-card p-6 shadow-sm">
      <div className="h-10 w-10 rounded-xl bg-primary/10 border border-primary/20 flex items-center justify-center text-primary">
        {icon}
      </div>
      <div className="mt-4 text-base font-extrabold">{title}</div>
      <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{description}</p>
    </div>
  );
}

function StepCard({ step, title, description }: { step: string; title: string; description: string }) {
  return (
    <div className="rounded-3xl border border-border bg-background p-6">
      <div className="h-10 w-10 rounded-xl bg-primary text-primary-foreground flex items-center justify-center font-extrabold">
        {step}
      </div>
      <div className="mt-4 text-lg font-extrabold">{title}</div>
      <p className="mt-2 text-sm text-muted-foreground leading-relaxed">{description}</p>
    </div>
  );
}
