import { spawn } from "node:child_process";
import { Type } from "@sinclair/typebox";
// @ts-ignore - resolved by the OpenClaw plugin runtime
import { definePluginEntry } from "openclaw/plugin-sdk/plugin-entry";
// @ts-ignore - resolved by the OpenClaw plugin runtime
import type { OpenClawPluginApi } from "openclaw/plugin-sdk";

type GcbPluginConfig = {
  command: string;
  commandArgs: string[];
  state: string;
  databaseUrl?: string;
  config?: string;
  rawStore: string;
  timeoutMs: number;
};

type GcbToolResult = {
  content: { type: "text"; text: string }[];
  details: Record<string, unknown>;
};

const DEFAULT_CONFIG: GcbPluginConfig = {
  command: "gcb",
  commandArgs: [],
  state: ".local/context.sqlite",
  rawStore: ".local/raw",
  timeoutMs: 15000,
};

function resolveConfig(api: OpenClawPluginApi): GcbPluginConfig {
  const raw = api.pluginConfig ?? {};
  return {
    command: stringValue(raw.command, DEFAULT_CONFIG.command),
    commandArgs: stringArray(raw.commandArgs),
    state: stringValue(raw.state, DEFAULT_CONFIG.state),
    databaseUrl: optionalString(raw.databaseUrl),
    config: optionalString(raw.config),
    rawStore: stringValue(raw.rawStore, DEFAULT_CONFIG.rawStore),
    timeoutMs: positiveInteger(raw.timeoutMs, DEFAULT_CONFIG.timeoutMs),
  };
}

function stringValue(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value : fallback;
}

function optionalString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value : undefined;
}

function stringArray(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((item): item is string => typeof item === "string") : [];
}

function positiveInteger(value: unknown, fallback: number): number {
  return Number.isInteger(value) && Number(value) > 0 ? Number(value) : fallback;
}

async function runGcbJson(config: GcbPluginConfig, args: string[]): Promise<Record<string, unknown>> {
  const stdout = await runGcb(config, args);
  const parsed = JSON.parse(stdout) as unknown;
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error("GCB CLI returned non-object JSON");
  }
  return parsed as Record<string, unknown>;
}

function runGcb(config: GcbPluginConfig, args: string[]): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(config.command, [...config.commandArgs, ...args], {
      env: { ...process.env, ...(config.databaseUrl ? { GCB_DATABASE_URL: config.databaseUrl } : {}) },
      stdio: ["ignore", "pipe", "pipe"],
    });
    let stdout = "";
    let stderr = "";
    const timer = setTimeout(() => {
      child.kill("SIGTERM");
      reject(new Error(`GCB CLI timed out after ${config.timeoutMs}ms`));
    }, config.timeoutMs);

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk) => {
      stdout += chunk;
    });
    child.stderr.on("data", (chunk) => {
      stderr += chunk;
    });
    child.on("error", (error) => {
      clearTimeout(timer);
      reject(error);
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      if (code === 0) {
        resolve(stdout);
        return;
      }
      reject(new Error(`GCB CLI exited with ${code}: ${stderr.trim()}`));
    });
  });
}

function searchArgs(config: GcbPluginConfig, query: string, limit: number): string[] {
  const args = ["search-state", query, "--limit", String(limit), "--state", config.state];
  if (config.databaseUrl) args.push("--database-url", config.databaseUrl);
  return args;
}

function healthArgs(config: GcbPluginConfig): string[] {
  const args = ["health", "--state", config.state, "--raw-store", config.rawStore];
  if (config.databaseUrl) args.push("--database-url", config.databaseUrl);
  if (config.config) args.push("--config", config.config);
  return args;
}

function toolResult(text: string, details: Record<string, unknown>): GcbToolResult {
  return {
    content: [{ type: "text", text }],
    details,
  };
}

function summarizeSearch(report: Record<string, unknown>): string {
  const summary = typeof report.summary === "string" ? report.summary : "";
  const auditRef = typeof report.audit_ref === "string" ? report.audit_ref : "none";
  return [
    "## 4ok Search",
    summary || "No summary returned.",
    "",
    `Audit ref: ${auditRef}`,
    "",
    "Full evidence pack is available in tool details.",
  ].join("\n");
}

function registerSearchTool(api: OpenClawPluginApi, config: GcbPluginConfig): void {
  api.registerTool(
    {
      name: "gcb_search_context",
      label: "Search 4ok",
      description:
        "Search local governed company context and return permission-filtered evidence with source refs.",
      parameters: Type.Object(
        {
          query: Type.String({
            minLength: 1,
            description: "Search query for governed company context evidence.",
          }),
          limit: Type.Optional(
            Type.Integer({
              minimum: 1,
              maximum: 20,
              default: 5,
              description: "Maximum number of primary evidence candidates.",
            })
          ),
        },
        { additionalProperties: false }
      ),
      async execute(_toolCallId, params) {
        const query = String((params as { query: string }).query).trim();
        const rawLimit = (params as { limit?: number }).limit ?? 5;
        const limit = Math.min(Math.max(Number(rawLimit), 1), 20);
        const report = await runGcbJson(config, searchArgs(config, query, limit));
        return toolResult(summarizeSearch(report), report);
      },
    },
    { name: "gcb_search_context" }
  );
}

function registerHealthTool(api: OpenClawPluginApi, config: GcbPluginConfig): void {
  api.registerTool(
    {
      name: "gcb_health",
      label: "Check 4ok health",
      description: "Check the local GCB runtime database schema and raw-store boundary.",
      parameters: Type.Object({}, { additionalProperties: false }),
      async execute() {
        const report = await runGcbJson(config, healthArgs(config));
        const status = typeof report.status === "string" ? report.status : "unknown";
        return toolResult(`GCB health status: ${status}`, report);
      },
    },
    { name: "gcb_health" }
  );
}

export default definePluginEntry({
  id: "gcb-local",
  name: "4ok",
  description: "Local governed company context tools for OpenClaw agents.",
  register(api: OpenClawPluginApi) {
    const config = resolveConfig(api);
    registerSearchTool(api, config);
    registerHealthTool(api, config);
    api.logger.info("4ok local plugin loaded");
  },
});
