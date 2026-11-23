import React from 'react';
import { ArrowLeft, ArrowRight, CheckCircle2, ExternalLink, Loader2, Store, Users } from 'lucide-react';
import { apiErrorDetail } from '../../api/client';
import { botsApi, PLATFORM_LABEL, type BotAudience, type BotItem, type BotPlatform, type SetupInfo } from '../../lib/botsApi';
import { CopyField, Field, inputClass, PlatformBadge, primaryButton, secondaryButton } from './botUi';

type Step = 'platform' | 'audience' | 'credentials' | 'done';

const TELEGRAM_STEPS = [
    <>Open <a className="font-medium text-primary underline underline-offset-4" href="https://t.me/BotFather" target="_blank" rel="noreferrer">@BotFather</a> in Telegram and send <code>/newbot</code>.</>,
    <>Choose a display name (e.g. “Sharma Packaging”) and a username ending in <code>bot</code>.</>,
    <>BotFather replies with a token like <code>123456789:AAH…</code>. Copy it and paste it below.</>,
];

const WHATSAPP_STEPS = [
    <>Go to <a className="font-medium text-primary underline underline-offset-4" href="https://developers.facebook.com/apps" target="_blank" rel="noreferrer">Meta for Developers</a>, create an app of type <b>Business</b>, and add the <b>WhatsApp</b> product.</>,
    <>In <b>WhatsApp › API Setup</b>, add your business phone number. Copy the <b>Phone number ID</b> and the <b>WhatsApp Business Account ID</b>.</>,
    <>In <a className="font-medium text-primary underline underline-offset-4" href="https://business.facebook.com/settings/system-users" target="_blank" rel="noreferrer">Business Settings › System users</a>, add a system user (Admin), assign it your app and WhatsApp account, and generate a token that <b>never expires</b> with <code>whatsapp_business_messaging</code> and <code>whatsapp_business_management</code>.</>,
    <>In the app’s <b>App settings › Basic</b>, copy the <b>App secret</b>.</>,
];

export default function ConnectBot({ onCancel, onDone }: { onCancel: () => void; onDone: (botId: string) => void }) {
    const [step, setStep] = React.useState<Step>('platform');
    const [platform, setPlatform] = React.useState<BotPlatform>('whatsapp');
    const [audience, setAudience] = React.useState<BotAudience>('customer');
    const [name, setName] = React.useState('');
    const [creds, setCreds] = React.useState<Record<string, string>>({});
    const [busy, setBusy] = React.useState(false);
    const [error, setError] = React.useState('');
    const [result, setResult] = React.useState<{ bot: BotItem; setup: SetupInfo } | null>(null);
    const [publicUrlSet, setPublicUrlSet] = React.useState(true);

    React.useEffect(() => {
        botsApi.options().then((o) => setPublicUrlSet(o.public_api_url_set)).catch(() => undefined);
    }, []);

    const set = (key: string) => (e: React.ChangeEvent<HTMLInputElement>) => setCreds((c) => ({ ...c, [key]: e.target.value }));
    const ready = platform === 'telegram'
        ? !!creds.token?.trim()
        : ['access_token', 'phone_number_id', 'app_secret', 'waba_id'].every((k) => creds[k]?.trim());

    const connect = async (e: React.FormEvent) => {
        e.preventDefault();
        setBusy(true);
        setError('');
        try {
            setResult(await botsApi.create({ platform, audience, name, credentials: creds }));
            setStep('done');
        } catch (err) {
            setError(apiErrorDetail(err, 'Couldn’t connect. Check the details and try again.'));
        } finally {
            setBusy(false);
        }
    };

    return (
        <div className="rise-in space-y-6">
            <button onClick={step === 'platform' || step === 'done' ? onCancel : () => setStep(step === 'credentials' ? 'audience' : 'platform')}
                className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground">
                <ArrowLeft className="h-4 w-4" /> {step === 'platform' || step === 'done' ? 'Back to bots' : 'Back'}
            </button>
            <Progress step={step} />

            {!publicUrlSet && step !== 'done' && (
                <p className="rounded-xl border border-warning/30 bg-warning/10 px-4 py-3 text-sm text-foreground">
                    The server’s public address (<code>PUBLIC_API_URL</code>) isn’t set, so WhatsApp and Telegram can’t deliver
                    messages yet. You can still connect and test the bot here.
                </p>
            )}

            {step === 'platform' && (
                <section className="space-y-4">
                    <h2 className="font-display text-2xl font-semibold text-foreground">Where will people message you?</h2>
                    <div className="grid gap-3 sm:grid-cols-2">
                        {(['whatsapp', 'telegram'] as BotPlatform[]).map((p) => (
                            <Choice key={p} selected={platform === p} onClick={() => setPlatform(p)}
                                icon={<PlatformBadge platform={p} />} title={PLATFORM_LABEL[p]}
                                text={p === 'whatsapp'
                                    ? 'Where most customers already are. Needs a Meta business app (about 15 minutes, we’ll guide you).'
                                    : 'Quickest to set up: create a bot in Telegram and paste one token (about 2 minutes).'} />
                        ))}
                    </div>
                    <div className="flex justify-end"><button className={primaryButton} onClick={() => setStep('audience')}>Continue <ArrowRight className="h-4 w-4" /></button></div>
                </section>
            )}

            {step === 'audience' && (
                <section className="space-y-4">
                    <h2 className="font-display text-2xl font-semibold text-foreground">Who is this bot for?</h2>
                    <p className="text-sm text-muted-foreground">A bot serves one group, so what it can do stays clear. You can connect another bot for the other group.</p>
                    <div className="grid gap-3 sm:grid-cols-2">
                        <Choice selected={audience === 'customer'} onClick={() => setAudience('customer')}
                            icon={<span className="chip-amber inline-flex h-10 w-10 items-center justify-center rounded-xl"><Store className="h-5 w-5" /></span>}
                            title="Your customers"
                            text="Anyone can message it. It answers about your business, can book times and save enquiries, and politely refuses anything else." />
                        <Choice selected={audience === 'team'} onClick={() => setAudience('team')}
                            icon={<span className="chip-violet inline-flex h-10 w-10 items-center justify-center rounded-xl"><Users className="h-5 w-5" /></span>}
                            title="Your team"
                            text="Only people in your workspace, after linking their account. They use BizAssist from chat with the tools you allow." />
                    </div>
                    <div className="flex justify-end"><button className={primaryButton} onClick={() => setStep('credentials')}>Continue <ArrowRight className="h-4 w-4" /></button></div>
                </section>
            )}

            {step === 'credentials' && (
                <form onSubmit={connect} className="space-y-5">
                    <h2 className="font-display text-2xl font-semibold text-foreground">Connect {PLATFORM_LABEL[platform]}</h2>
                    <ol className="space-y-3 rounded-2xl border border-border bg-card p-5">
                        {(platform === 'telegram' ? TELEGRAM_STEPS : WHATSAPP_STEPS).map((text, i) => (
                            <li key={i} className="flex gap-3 text-sm text-foreground leading-relaxed">
                                <span className="chip-green inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold">{i + 1}</span>
                                <span>{text}</span>
                            </li>
                        ))}
                    </ol>
                    <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
                        <Field label="Name in BizAssist" hint="Only you and your team see this.">
                            <input className={inputClass} value={name} onChange={(e) => setName(e.target.value)} maxLength={80}
                                placeholder={audience === 'customer' ? 'e.g. Customer chat' : 'e.g. Team assistant'} />
                        </Field>
                        {platform === 'telegram' ? (
                            <Field label="Bot token">
                                <input className={inputClass} value={creds.token || ''} onChange={set('token')} autoComplete="off" spellCheck={false} placeholder="123456789:AAH…" />
                            </Field>
                        ) : (
                            <>
                                <Field label="Permanent access token" hint="From the system user. Temporary tokens from API Setup stop working after a day.">
                                    <input className={inputClass} value={creds.access_token || ''} onChange={set('access_token')} autoComplete="off" spellCheck={false} placeholder="EAAG…" />
                                </Field>
                                <div className="grid gap-4 sm:grid-cols-2">
                                    <Field label="Phone number ID">
                                        <input className={inputClass} value={creds.phone_number_id || ''} onChange={set('phone_number_id')} inputMode="numeric" placeholder="1098…" />
                                    </Field>
                                    <Field label="WhatsApp Business Account ID">
                                        <input className={inputClass} value={creds.waba_id || ''} onChange={set('waba_id')} inputMode="numeric" placeholder="2034…" />
                                    </Field>
                                </div>
                                <Field label="App secret" hint="Lets BizAssist check that messages really come from Meta.">
                                    <input className={inputClass} type="password" value={creds.app_secret || ''} onChange={set('app_secret')} autoComplete="off" />
                                </Field>
                            </>
                        )}
                        <p className="text-xs text-muted-foreground">Credentials are encrypted and never shown again.</p>
                    </div>
                    {error && <p role="alert" className="rounded-xl border border-destructive/30 bg-destructive/10 px-4 py-3 text-sm text-destructive">{error}</p>}
                    <div className="flex justify-end">
                        <button type="submit" disabled={!ready || busy} className={primaryButton}>
                            {busy ? <Loader2 className="h-4 w-4 animate-spin" /> : null} {busy ? 'Checking with ' + PLATFORM_LABEL[platform] + '…' : 'Connect'}
                        </button>
                    </div>
                </form>
            )}

            {step === 'done' && result && <Done result={result} onOpen={() => onDone(result.bot.id)} />}
        </div>
    );
}

function Done({ result, onOpen }: { result: { bot: BotItem; setup: SetupInfo }; onOpen: () => void }) {
    const { bot, setup } = result;
    return (
        <section className="space-y-5">
            <div className="flex items-start gap-3">
                <CheckCircle2 className="mt-1 h-6 w-6 shrink-0 text-success" />
                <div>
                    <h2 className="font-display text-2xl font-semibold text-foreground">{bot.name} is connected</h2>
                    <p className="text-sm text-muted-foreground">{bot.handle}{bot.verified_name ? ` · ${bot.verified_name}` : ''}</p>
                </div>
            </div>

            {bot.platform === 'whatsapp' ? (
                <div className="space-y-4 rounded-2xl border border-border bg-card p-5">
                    <p className="text-sm font-semibold text-foreground">Last step: tell Meta where to send messages</p>
                    <ol className="list-decimal space-y-1.5 pl-5 text-sm text-foreground">
                        <li>In your Meta app, open <b>WhatsApp › Configuration</b> and press <b>Edit</b> next to Webhook.</li>
                        <li>Paste the callback URL and verify token below, then press <b>Verify and save</b>.</li>
                        <li>Under webhook fields, <b>Subscribe</b> to <code>messages</code>.</li>
                    </ol>
                    <CopyField label="Callback URL" value={setup.webhook_url} />
                    <CopyField label="Verify token" value={setup.verify_token || ''} />
                    {setup.subscribed === 'failed' && (
                        <p className="text-xs text-warning">We couldn’t subscribe the app to your WhatsApp account automatically ({setup.error}). Check the Business Account ID; the Health tab re-checks this.</p>
                    )}
                </div>
            ) : (
                <div className="space-y-3 rounded-2xl border border-border bg-card p-5 text-sm">
                    {setup.webhook === 'registered' ? (
                        <p className="text-foreground">Telegram will now send messages to BizAssist. Send your bot a message to try it.</p>
                    ) : (
                        <p className="text-warning">Telegram couldn’t be told where to send messages yet{setup.error ? ` (${setup.error})` : ''}. Open the bot’s Health tab to fix it.</p>
                    )}
                    {bot.chat_link && <a href={bot.chat_link} target="_blank" rel="noreferrer" className={secondaryButton}>Open {bot.handle} <ExternalLink className="h-4 w-4" /></a>}
                </div>
            )}

            <div className="flex justify-end"><button onClick={onOpen} className={primaryButton}>Set up what it can do <ArrowRight className="h-4 w-4" /></button></div>
        </section>
    );
}

function Choice({ selected, onClick, icon, title, text }: { selected: boolean; onClick: () => void; icon: React.ReactNode; title: string; text: string }) {
    return (
        <button type="button" onClick={onClick} aria-pressed={selected}
            className={`flex flex-col items-start gap-3 rounded-2xl border bg-card p-5 text-left transition-colors ${selected ? 'border-primary ring-4 ring-primary/10' : 'border-border hover:border-primary/40'}`}>
            {icon}
            <span className="font-semibold text-foreground">{title}</span>
            <span className="text-sm text-muted-foreground leading-relaxed">{text}</span>
        </button>
    );
}

function Progress({ step }: { step: Step }) {
    const steps: Step[] = ['platform', 'audience', 'credentials', 'done'];
    const index = steps.indexOf(step);
    return (
        <div className="flex gap-1.5" aria-label={`Step ${index + 1} of 4`}>
            {steps.map((s, i) => <span key={s} className={`h-1 flex-1 rounded-full ${i <= index ? 'bg-primary' : 'bg-border'}`} />)}
        </div>
    );
}
