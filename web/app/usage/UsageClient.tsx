"use client";

import { useEffect, useState } from "react";
import { useAuth } from "@clerk/nextjs";
import {
  getMyUsage,
  getMyUsageHistory,
  type UsagePeriod,
  type UsageSummary,
  type UsageHistoryPoint,
} from "@/lib/api";
import { CoinsIcon, Loader2Icon, ZapIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import {
  ResponsiveContainer,
  LineChart,
  Line,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from "recharts";

const PERIODS: { key: UsagePeriod; label: string }[] = [
  { key: "1h",  label: "Hourly"    },
  { key: "24h", label: "Daily"     },
  { key: "7d",  label: "Weekly"    },
  { key: "30d", label: "Monthly"   },
  { key: "all", label: "All Time"  },
];

function formatBucket(iso: string, period: UsagePeriod): string {
  const d = new Date(iso);
  if (period === "1h") {
    return d.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  if (period === "24h") {
    return d.toLocaleTimeString("en-AU", { hour: "2-digit", minute: "2-digit", hour12: false });
  }
  return d.toLocaleDateString("en-AU", { month: "short", day: "numeric" });
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function ChartTooltip({ active, payload, label, period }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-lg border border-border bg-popover px-3 py-2 text-xs shadow-md">
      <p className="font-medium mb-1">{formatBucket(label, period)}</p>
      {payload.map((p: { name: string; value: number; color: string }) => {
        let display = "";
        if (p.name === "requests") display = `Requests: ${p.value}`;
        else if (p.name === "tokens") display = `Tokens: ${p.value.toLocaleString()}`;
        else if (p.name === "cost_usd") display = `Cost: $${p.value.toFixed(4)}`;
        return <p key={p.name} style={{ color: p.color }}>{display}</p>;
      })}
    </div>
  );
}

export default function UsageClient() {
  const { getToken, isLoaded, isSignedIn } = useAuth();
  const [period, setPeriod] = useState<UsagePeriod>("all");
  const [usage, setUsage] = useState<UsageSummary | null>(null);
  const [points, setPoints] = useState<UsageHistoryPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!isLoaded || !isSignedIn) return;
    setLoading(true);
    setError(null);
    getToken().then((t) =>
      Promise.all([
        getMyUsage(t ?? undefined, period),
        getMyUsageHistory(t ?? undefined, period),
      ])
        .then(([summary, history]) => {
          setUsage(summary);
          setPoints(history.points);
        })
        .catch(() => setError("Failed to load usage data."))
        .finally(() => setLoading(false))
    );
  }, [isLoaded, isSignedIn, period]);

  const periodLabel = PERIODS.find((p) => p.key === period)?.label ?? "Period";

  const chartData = points.map((p) => ({
    bucket: p.bucket,
    requests: p.requests,
    tokens: p.tokens,
    cost_usd: Math.round(p.cost_usd * 100000) / 100000,
  }));

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Usage</h1>
        <p className="text-sm text-muted-foreground mt-1">Your API spend by time period.</p>
      </div>

      {/* Period selector */}
      <div className="inline-flex rounded-lg border border-border p-1 gap-1">
        {PERIODS.map((p) => (
          <button
            key={p.key}
            onClick={() => setPeriod(p.key)}
            className={cn(
              "px-4 py-1.5 rounded-md text-sm font-medium transition-colors",
              period === p.key
                ? "bg-primary text-primary-foreground"
                : "text-muted-foreground hover:text-foreground hover:bg-muted"
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      {loading ? (
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Loader2Icon className="size-4 animate-spin" /> Loading…
        </div>
      ) : error ? (
        <p className="text-destructive text-sm">{error}</p>
      ) : (
        <>
          {/* Summary cards */}
          <div className="grid grid-cols-2 gap-4">
            <div className="rounded-xl border border-border bg-card p-6 flex flex-col gap-2">
              <span className="text-xs text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                <CoinsIcon className="size-3" /> {periodLabel} cost
              </span>
              <span className="text-3xl font-bold tabular-nums">
                ${(Math.round((usage?.total_cost_usd ?? 0) * 10000) / 10000).toFixed(4)}
              </span>
              <span className="text-xs text-muted-foreground">USD</span>
            </div>

            <div className="rounded-xl border border-border bg-card p-6 flex flex-col gap-2">
              <span className="text-xs text-muted-foreground uppercase tracking-wider flex items-center gap-1.5">
                <ZapIcon className="size-3" /> {periodLabel} tokens
              </span>
              <span className="text-3xl font-bold tabular-nums">
                {(usage?.total_tokens ?? 0).toLocaleString()}
              </span>
              <span className="text-xs text-muted-foreground">input + output</span>
            </div>
          </div>

          {/* Charts */}
          {chartData.length === 0 ? (
            <div className="rounded-xl border border-border bg-card p-8 text-center text-sm text-muted-foreground">
              No activity in this period yet.
            </div>
          ) : (
            <div className="flex flex-col gap-6">
              {/* Requests chart */}
              <div className="rounded-xl border border-border bg-card p-5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-4">
                  Requests
                </p>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={chartData} margin={{ top: 4, right: 4, left: -20, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="oklch(1 0 0 / 0.06)" />
                    <XAxis
                      dataKey="bucket"
                      tickFormatter={(v) => formatBucket(v, period)}
                      tick={{ fontSize: 10, fill: "oklch(0.7 0 0)" }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "oklch(0.7 0 0)" }}
                      axisLine={false}
                      tickLine={false}
                      allowDecimals={false}
                    />
                    <Tooltip content={<ChartTooltip period={period} />} />
                    <Line
                      type="monotone"
                      dataKey="requests"
                      stroke="oklch(0.62 0.22 264)"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Cost chart */}
              <div className="rounded-xl border border-border bg-card p-5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-4">
                  Cost (USD)
                </p>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={chartData} margin={{ top: 4, right: 4, left: 4, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="oklch(1 0 0 / 0.06)" />
                    <XAxis
                      dataKey="bucket"
                      tickFormatter={(v) => formatBucket(v, period)}
                      tick={{ fontSize: 10, fill: "oklch(0.7 0 0)" }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "oklch(0.7 0 0)" }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v: number) => `$${v.toFixed(4)}`}
                      width={58}
                    />
                    <Tooltip content={<ChartTooltip period={period} />} />
                    <Line
                      type="monotone"
                      dataKey="cost_usd"
                      stroke="oklch(0.75 0.18 55)"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>

              {/* Tokens chart */}
              <div className="rounded-xl border border-border bg-card p-5">
                <p className="text-xs font-medium text-muted-foreground uppercase tracking-wider mb-4">
                  Tokens used
                </p>
                <ResponsiveContainer width="100%" height={180}>
                  <LineChart data={chartData} margin={{ top: 4, right: 4, left: -10, bottom: 0 }}>
                    <CartesianGrid strokeDasharray="3 3" stroke="oklch(1 0 0 / 0.06)" />
                    <XAxis
                      dataKey="bucket"
                      tickFormatter={(v) => formatBucket(v, period)}
                      tick={{ fontSize: 10, fill: "oklch(0.7 0 0)" }}
                      axisLine={false}
                      tickLine={false}
                      interval="preserveStartEnd"
                    />
                    <YAxis
                      tick={{ fontSize: 10, fill: "oklch(0.7 0 0)" }}
                      axisLine={false}
                      tickLine={false}
                      tickFormatter={(v: number) => v >= 1000 ? `${(v / 1000).toFixed(0)}k` : String(v)}
                    />
                    <Tooltip content={<ChartTooltip period={period} />} />
                    <Line
                      type="monotone"
                      dataKey="tokens"
                      stroke="oklch(0.72 0.18 142)"
                      strokeWidth={2}
                      dot={false}
                      activeDot={{ r: 4 }}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </div>
          )}
        </>
      )}

      <p className="text-xs text-muted-foreground">
        Costs are estimates computed from the per-token rates configured on the server.
      </p>
    </div>
  );
}
