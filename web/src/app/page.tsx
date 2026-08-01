import Image from "next/image";
import Link from "next/link";
import {
  IconArrow,
  IconBolt,
  IconBox,
  IconExternal,
  IconFlow,
  IconGithub,
  IconLayers,
  IconPulse,
  IconShield,
  IconSliders,
} from "@/components/icons";
import { LiveRoutingNote, LiveStats } from "@/components/live-stats";
import { Mark } from "@/components/shell";

const PIPELINE = [
  {
    n: "01",
    title: "Guard",
    body: "Size caps, output ceilings, and redaction of emails, phone numbers, card-like digits and API-key patterns before anything leaves the process.",
  },
  {
    n: "02",
    title: "Admit",
    body: "Token-bucket rate limits per key, a monthly budget check, and a concurrency semaphore that records how long a call waited for a slot.",
  },
  {
    n: "03",
    title: "Route",
    body: "A rule-based classifier scores the prompt, then the policy picks the cheapest — or fastest — model at or above the required tier. The reason is stored with the request.",
  },
  {
    n: "04",
    title: "Cache",
    body: "Exact-match lookup on a canonical hash of messages and parameters. Only deterministic calls qualify unless the caller opts in. A hit costs nothing and is credited as avoided spend.",
  },
  {
    n: "05",
    title: "Call",
    body: "Bounded retries with jittered backoff, ordered failover across providers, and a circuit breaker that stops hammering an upstream that is already down.",
  },
  {
    n: "06",
    title: "Account",
    body: "Tokens from the provider when reported, estimated when not. Cost from an editable price book, plus the counterfactual cost of the premium model.",
  },
  {
    n: "07",
    title: "Observe",
    body: "W3C spans for every hop, Prometheus counters and histograms, and a live event stream — all emitted whether or not a collector is attached.",
  },
];

const CAPABILITIES = [
  {
    Icon: IconFlow,
    title: "Routing you can interrogate",
    body: "Cheapest-capable, latency-first, weighted A/B, ordered failover and shadow traffic. Every decision keeps its candidate set, estimated costs and the sentence explaining the pick.",
  },
  {
    Icon: IconBolt,
    title: "Cost accounting per request",
    body: "Tokens and dollars against a price book you edit in the console, including prompt-cache-hit rates. The premium-baseline counterfactual turns 'we optimised spend' into a percentage.",
  },
  {
    Icon: IconPulse,
    title: "Tracing with a measured price tag",
    body: "Spans persisted locally for the built-in waterfall, mirrored to OTLP when configured. The load test reports what recording them actually costs instead of asserting it is free.",
  },
  {
    Icon: IconShield,
    title: "Resilience that is visible",
    body: "Per-provider circuit breakers, retry budgets, upstream timeouts and failover chains — with the attempt sequence stored on the request so a failure is explainable after the fact.",
  },
  {
    Icon: IconLayers,
    title: "Multi-tenant metering",
    body: "Hashed keys with their own RPM/TPM limits and monthly budgets. Spend is attributed at request time, so a key that exhausts its budget stops rather than surprises you.",
  },
  {
    Icon: IconBox,
    title: "OpenAI-compatible surface",
    body: "Drop-in /v1/chat/completions with streaming. Existing SDKs point at it unchanged; the extra routing fields and the response's sentinel block are purely additive.",
  },
  {
    Icon: IconSliders,
    title: "Policy at runtime",
    body: "Cache, tracing, retries, breaker thresholds, limits and service objectives are rows the hot path reads — changed from the console, effective on the next request.",
  },
  {
    Icon: IconArrow,
    title: "Load testing built in",
    body: "Ramp concurrency against a deterministic local engine and get sustained throughput, TTFT percentiles and the queueing point that an autoscaling threshold should be set from.",
  },
];

const STACK = [
  ["Gateway", "FastAPI · async SQLAlchemy · httpx · Pydantic v2"],
  ["Store", "Postgres or SQLite · no broker, no Redis required"],
  ["Upstreams", "DeepSeek · any OpenAI-compatible endpoint · deterministic local engine"],
  ["Console", "Next.js 16 App Router · TypeScript · Tailwind v4 · Recharts"],
  ["Observability", "Prometheus · W3C spans · optional OTLP/HTTP export · SSE"],
  ["Delivery", "Docker · compose · Kustomize + KEDA · GitHub Actions"],
];

export default function LandingPage() {
  return (
    <div className="relative overflow-x-hidden">
      <Nav />
      <Hero />

      <Section
        id="problem"
        eyebrow="the problem"
        title="Calling a model is easy. Operating the call is not."
        lead="One HTTP request to a provider is an afternoon's work. Knowing what it cost, why that model was chosen, where the three seconds went, and what happens when the provider returns 503 for four minutes — that is the part teams keep rebuilding badly."
      >
        <div className="grid gap-4 md:grid-cols-3">
          {[
            {
              k: "Cost is invisible until the invoice",
              v: "Spend is aggregated per month, per provider, with no line back to the request or the team that made it. Nobody can answer 'what would this have cost on the cheaper model?'",
            },
            {
              k: "Latency is a single number",
              v: "Without time-to-first-token separated from generation time and gateway overhead, a slow endpoint has no diagnosis — only a complaint.",
            },
            {
              k: "Failure is all-or-nothing",
              v: "No retry budget, no breaker, no failover. One upstream incident becomes your incident, and the retry storm makes it worse.",
            },
          ].map((item) => (
            <div key={item.k} className="panel p-5">
              <p className="text-[13px] font-semibold text-ink">{item.k}</p>
              <p className="mt-2 text-[13px] leading-relaxed text-muted">{item.v}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section
        id="pipeline"
        eyebrow="the pipeline"
        title="Seven stages, every one traced."
        lead="A single code path handles every call. Each stage emits a span, so the waterfall for any request shows exactly where its milliseconds went and which decision produced its cost."
      >
        <ol className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {PIPELINE.map((stage, index) => (
            <li
              key={stage.n}
              className={`panel relative p-5 ${index === PIPELINE.length - 1 ? "md:col-span-2 xl:col-span-1" : ""}`}
            >
              <span className="num text-[11px] tracking-widest text-signal">{stage.n}</span>
              <p className="mt-2 text-[13.5px] font-semibold text-ink">{stage.title}</p>
              <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{stage.body}</p>
            </li>
          ))}
        </ol>
        <div className="mt-4 rounded-xl border border-signal/25 bg-signal/[0.04] p-4">
          <p className="text-[13px] leading-relaxed text-muted">
            <span className="font-semibold text-signal">The measurable claims:</span> share of spend
            avoided versus routing everything to the premium model, sustained requests/second before
            time-to-first-token breaches its objective, and the added gateway overhead of recording
            spans. All three are computed by the gateway from its own traffic, not estimated in a
            slide.
          </p>
        </div>
      </Section>

      <Section
        id="architecture"
        eyebrow="architecture"
        title="One container, or a fleet."
        lead="No broker, no Redis, no sidecar required. It starts on SQLite with a deterministic local engine and grows into Postgres, real upstreams and an OTLP collector without touching application code."
      >
        <div className="grid gap-4 lg:grid-cols-5">
          <div className="panel overflow-hidden lg:col-span-2">
            <div className="relative h-52">
              <Image
                src="/media/infra-switch.jpg"
                alt="Network cables in a server rack"
                fill
                sizes="(max-width: 1024px) 100vw, 40vw"
                className="object-cover opacity-70"
              />
              <div className="absolute inset-0 bg-gradient-to-t from-panel via-panel/30 to-transparent" />
            </div>
            <div className="p-5">
              <p className="text-[13px] font-semibold text-ink">Degrades honestly</p>
              <p className="mt-2 text-[12.5px] leading-relaxed text-muted">
                No provider keys? The local engine serves four priced tiers with configurable
                time-to-first-token, throughput and failure rate — which is what makes the load test
                and CI reproducible. Add a key and that provider joins the routing pool immediately.
              </p>
            </div>
          </div>

          <div className="panel p-5 lg:col-span-3">
            <ArchitectureDiagram />
          </div>
        </div>
      </Section>

      <Section id="capabilities" eyebrow="capabilities" title="What is actually built.">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {CAPABILITIES.map(({ Icon, title, body }) => (
            <div key={title} className="panel p-5">
              <Icon className="size-4 text-signal" />
              <p className="mt-3 text-[13px] font-semibold text-ink">{title}</p>
              <p className="mt-2 text-[12.5px] leading-relaxed text-muted">{body}</p>
            </div>
          ))}
        </div>
      </Section>

      <Section id="stack" eyebrow="stack" title="Boring dependencies, deliberately.">
        <dl className="grid gap-x-8 gap-y-0 divide-y divide-line md:grid-cols-2 md:divide-y-0">
          {STACK.map(([key, value]) => (
            <div
              key={key}
              className="flex flex-wrap items-baseline gap-3 border-line py-3 md:border-b"
            >
              <dt className="label-xs w-32 shrink-0">{key}</dt>
              <dd className="num text-[12.5px] text-muted">{value}</dd>
            </div>
          ))}
        </dl>
      </Section>

      <section className="border-t border-line px-6 py-20 lg:px-10">
        <div className="mx-auto max-w-3xl text-center">
          <h2 className="text-2xl font-semibold tracking-tight sm:text-3xl">
            Send a prompt and watch the decision.
          </h2>
          <p className="mt-3 text-[14px] leading-relaxed text-muted">
            The playground calls the same public endpoint your services would. Every answer carries
            the model that served it, why it was chosen, what it cost against the premium baseline,
            and a trace id you can open into a waterfall.
          </p>
          <div className="mt-7 flex flex-wrap items-center justify-center gap-3">
            <Link
              href="/console/playground"
              className="inline-flex items-center gap-2 rounded-lg bg-signal px-4 py-2.5 text-[13px] font-semibold text-[#04161b] transition-colors hover:bg-signal/90"
            >
              Open the playground
              <IconArrow className="size-4" />
            </Link>
            <Link
              href="/console"
              className="inline-flex items-center gap-2 rounded-lg border border-line-strong bg-raised px-4 py-2.5 text-[13px] text-ink transition-colors hover:bg-overlay"
            >
              Gateway dashboard
            </Link>
          </div>
        </div>
      </section>

      <footer className="border-t border-line px-6 py-8 lg:px-10">
        <div className="mx-auto flex max-w-6xl flex-col gap-4 text-[11px] text-faint sm:flex-row sm:items-center sm:justify-between">
          <div className="flex items-center gap-2.5">
            <Mark />
            <span>Sentinel — model-serving gateway. MIT licensed.</span>
          </div>
          <p className="leading-relaxed">
            Photography via{" "}
            <a
              href="https://www.pexels.com"
              target="_blank"
              rel="noreferrer"
              className="underline transition-colors hover:text-muted"
            >
              Pexels
            </a>{" "}
            (Suki Lee, Brett Sayles).
          </p>
        </div>
      </footer>
    </div>
  );
}

function Nav() {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-base/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-6xl items-center gap-6 px-6 lg:px-10">
        <Link href="/" className="flex items-center gap-2.5">
          <Mark />
          <span className="text-[15px] font-semibold tracking-tight">Sentinel</span>
        </Link>
        <nav className="ml-auto hidden items-center gap-6 text-[12.5px] text-muted md:flex">
          <a href="#pipeline" className="transition-colors hover:text-ink">
            Pipeline
          </a>
          <a href="#architecture" className="transition-colors hover:text-ink">
            Architecture
          </a>
          <a href="#capabilities" className="transition-colors hover:text-ink">
            Capabilities
          </a>
          <a
            href="https://github.com/shahriar-ahmed-seam/sentinel"
            target="_blank"
            rel="noreferrer"
            className="flex items-center gap-1.5 transition-colors hover:text-ink"
          >
            <IconGithub className="size-3.5" />
            Source
          </a>
        </nav>
        <Link
          href="/console"
          className="ml-auto inline-flex items-center gap-1.5 rounded-lg border border-signal/35 bg-signal/10 px-3 py-1.5 text-[12.5px] font-medium text-signal transition-colors hover:bg-signal/16 md:ml-0"
        >
          Console
          <IconExternal className="size-3.5" />
        </Link>
      </div>
    </header>
  );
}

function Hero() {
  return (
    <section className="relative overflow-hidden border-b border-line">
      <div className="absolute inset-0">
        <Image
          src="/media/hero-fiber.jpg"
          alt=""
          fill
          priority
          sizes="100vw"
          className="object-cover opacity-[0.16]"
        />
        <div className="absolute inset-0 bg-gradient-to-b from-base/40 via-base/85 to-base" />
      </div>
      <div className="grid-bg radial-fade absolute inset-0 opacity-70" aria-hidden />
      <div className="grain absolute inset-0" aria-hidden />

      <div className="relative mx-auto max-w-6xl px-6 pb-16 pt-20 lg:px-10 lg:pb-24 lg:pt-28">
        <div className="inline-flex items-center gap-2 rounded-full border border-line-strong bg-panel/70 px-3 py-1 text-[11px] text-muted backdrop-blur">
          <i className="size-1.5 rounded-full bg-signal pulse-dot" />
          model serving + observability · OpenAI-compatible · self-hosted
        </div>

        <h1 className="mt-6 max-w-3xl text-[34px] font-semibold leading-[1.08] tracking-[-0.02em] sm:text-[46px] lg:text-[56px]">
          Every model call,
          <br />
          <span className="text-signal">priced, routed and traced.</span>
        </h1>

        <p className="mt-6 max-w-2xl text-[15px] leading-relaxed text-muted lg:text-[16px]">
          Sentinel sits in front of your model providers and does the operational work: classify the
          prompt, route it to the cheapest capable model, cache what is safe to cache, retry and fail
          over when an upstream breaks, then account for every token and trace every hop.
        </p>

        <div className="mt-8 flex flex-wrap items-center gap-3">
          <Link
            href="/console"
            className="inline-flex items-center gap-2 rounded-lg bg-signal px-4 py-2.5 text-[13px] font-semibold text-[#04161b] transition-colors hover:bg-signal/90"
          >
            Open the live console
            <IconArrow className="size-4" />
          </Link>
          <a
            href="#pipeline"
            className="inline-flex items-center gap-2 rounded-lg border border-line-strong bg-raised/70 px-4 py-2.5 text-[13px] text-ink backdrop-blur transition-colors hover:bg-overlay"
          >
            How a request flows
          </a>
          <LiveRoutingNote />
        </div>

        <div className="mt-12">
          <LiveStats />
        </div>
      </div>
    </section>
  );
}

function Section({
  id,
  eyebrow,
  title,
  lead,
  children,
}: {
  id: string;
  eyebrow: string;
  title: string;
  lead?: string;
  children?: React.ReactNode;
}) {
  return (
    <section id={id} className="border-b border-line px-6 py-16 lg:px-10 lg:py-20">
      <div className="mx-auto max-w-6xl">
        <p className="label-xs">{eyebrow}</p>
        <h2 className="mt-3 max-w-3xl text-2xl font-semibold tracking-tight sm:text-[30px]">
          {title}
        </h2>
        {lead ? (
          <p className="mt-4 max-w-3xl text-[14px] leading-relaxed text-muted">{lead}</p>
        ) : null}
        {children ? <div className="mt-8">{children}</div> : null}
      </div>
    </section>
  );
}

function ArchitectureDiagram() {
  const groups = [
    {
      label: "data plane · /v1",
      tone: "border-signal/30 bg-signal/[0.05]",
      items: ["chat/completions", "streaming SSE", "models", "sentinel meta block"],
    },
    {
      label: "pipeline",
      tone: "border-violet/30 bg-violet/[0.05]",
      items: [
        "guard",
        "rate limit",
        "budget",
        "classifier",
        "router",
        "cache",
        "retry",
        "breaker",
        "accounting",
      ],
    },
    {
      label: "control plane · /api",
      tone: "border-info/30 bg-info/[0.05]",
      items: ["requests", "traces", "policies", "catalogue", "keys", "runtime", "load tests"],
    },
    {
      label: "state & egress",
      tone: "border-line-strong bg-raised",
      items: [
        "postgres / sqlite",
        "prometheus registry",
        "span store",
        "optional OTLP",
        "SSE bus",
      ],
    },
  ];
  return (
    <div className="space-y-3">
      {groups.map((group) => (
        <div key={group.label} className={`rounded-xl border p-3.5 ${group.tone}`}>
          <p className="label-xs">{group.label}</p>
          <div className="mt-2.5 flex flex-wrap gap-1.5">
            {group.items.map((item) => (
              <span
                key={item}
                className="num rounded-md border border-line bg-base/70 px-2 py-1 text-[11px] text-muted"
              >
                {item}
              </span>
            ))}
          </div>
        </div>
      ))}
      <p className="text-[11.5px] leading-relaxed text-faint">
        The span buffer and the rate-limit buckets are per process. That is a deliberate trade for a
        single-container deployment and a documented limitation for a fleet: a shared bus and a Redis
        counter are the fix, and neither is pretended away.
      </p>
    </div>
  );
}
