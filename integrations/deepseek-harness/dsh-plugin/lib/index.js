import { readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';

/**
 * AgentBell notification bridge for DeepSeek Harness.
 *
 * The plugin listens to `session/event` and sends one fire-and-forget HTTP
 * request to the local AgentBell app when a turn ends. It never blocks the
 * harness event loop and never prints the token.
 */

export const name = 'agentbell-notify';

export const inject = [];

const DEFAULTS = {
  endpoint: 'http://127.0.0.1:8765/notify',
  source: 'DeepSeek Harness',
  token: '',
  tokenEnv: 'AGENTBELL_TOKEN',
  tokenFile: '',
  includeSummary: false,
};

const LOOPBACK_HOSTS = new Set(['127.0.0.1', 'localhost', '::1']);
const REQUEST_TIMEOUT_MS = 4000;
const CHUNK_BUFFER_LIMIT = 500;

function normalizeConfig(config) {
  const input = config && typeof config === 'object' ? config : {};
  return {
    endpoint:
      typeof input.endpoint === 'string' && input.endpoint.trim()
        ? input.endpoint.trim()
        : DEFAULTS.endpoint,
    source:
      typeof input.source === 'string' && input.source.trim()
        ? input.source.trim().slice(0, 100)
        : DEFAULTS.source,
    token: typeof input.token === 'string' ? input.token : '',
    tokenEnv:
      typeof input.tokenEnv === 'string' ? input.tokenEnv.trim() : DEFAULTS.tokenEnv,
    tokenFile: typeof input.tokenFile === 'string' ? input.tokenFile.trim() : '',
    includeSummary: Boolean(input.includeSummary),
  };
}

function clip(value, limit) {
  const text = String(value ?? '').replace(/\s+/g, ' ').trim();
  return text.length > limit ? text.slice(0, limit) : text;
}

function projectName(cwd) {
  if (typeof cwd !== 'string' || !cwd.trim()) return '';
  const parts = cwd.trim().split(/[\\/]+/).filter(Boolean);
  return parts.length > 0 ? parts[parts.length - 1] : '';
}

function sessionTitle(session, id) {
  const cwd = session?.header?.cwd;
  const project = projectName(cwd);
  if (project) return clip(project, 200);
  return clip(`DeepSeek Harness ${String(id).slice(0, 8)}`, 200);
}

function formatDuration(ms) {
  if (!Number.isFinite(ms) || ms < 0) return '';
  if (ms < 1000) return `${Math.max(0, Math.round(ms))}ms`;
  const totalSeconds = Math.round(ms / 1000);
  if (totalSeconds < 60) return `${totalSeconds}s`;
  const totalMinutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (totalMinutes < 60) return `${totalMinutes}m${seconds}s`;
  const hours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  return `${hours}h${minutes}m`;
}

function readableError(value) {
  if (value == null) return '';
  if (typeof value === 'string') return clip(value, 1000);
  if (value instanceof Error) return clip(value.message, 1000);
  if (typeof value === 'object' && typeof value.message === 'string') {
    return clip(value.message, 1000);
  }
  try {
    return clip(JSON.stringify(value), 1000);
  } catch {
    return clip(String(value), 1000);
  }
}

function chunkText(data) {
  if (typeof data === 'string') return data;
  if (!data || typeof data !== 'object') return '';
  for (const key of ['text', 'delta', 'content', 'chunk']) {
    const value = data[key];
    if (typeof value === 'string' && value) return value;
    if (value && typeof value === 'object') {
      const nested = chunkText(value);
      if (nested) return nested;
    }
  }
  return '';
}

function loopbackUrl(endpoint) {
  try {
    const url = new URL(endpoint);
    if (url.protocol !== 'http:' && url.protocol !== 'https:') return null;
    const host = url.hostname.replace(/^\[|\]$/g, '').toLowerCase();
    if (!LOOPBACK_HOSTS.has(host)) return null;
    return url;
  } catch {
    return null;
  }
}

function expandHome(path) {
  if (!path.startsWith('~')) return path;
  if (path === '~') return homedir();
  if (path.startsWith('~/') || path.startsWith('~\\')) {
    return join(homedir(), path.slice(2));
  }
  return path;
}

function resolveToken(options) {
  if (options.token) return options.token;
  if (options.tokenEnv) {
    const fromEnv = process.env[options.tokenEnv];
    if (typeof fromEnv === 'string' && fromEnv) return fromEnv;
  }
  if (options.tokenFile) {
    try {
      const raw = readFileSync(expandHome(options.tokenFile), 'utf8');
      const data = JSON.parse(raw);
      if (data && typeof data.token === 'string') return data.token;
    } catch {
      // Missing or unreadable token file: send without a token.
    }
  }
  return '';
}

function reasonOf(data) {
  const reason = data?.reason;
  if (reason && typeof reason === 'object') {
    return {
      kind: typeof reason.kind === 'string' ? reason.kind : 'completed',
      error: reason.error,
    };
  }
  return { kind: 'completed', error: undefined };
}

function statusOf(kind) {
  if (kind === 'error') return 'failed';
  if (kind === 'aborted' || kind === 'interrupted') return 'canceled';
  return 'succeeded';
}

async function send(options, payload) {
  const url = loopbackUrl(options.endpoint);
  if (!url) {
    console.warn('[agentbell-notify] endpoint is not a loopback http(s) URL; skipped');
    return;
  }
  const token = resolveToken(options);
  const headers = { 'Content-Type': 'application/json; charset=utf-8' };
  if (token) headers['X-Token'] = token;

  try {
    const response = await fetch(url, {
      method: 'POST',
      headers,
      body: JSON.stringify(payload),
      signal: AbortSignal.timeout(REQUEST_TIMEOUT_MS),
    });
    if (!response.ok) {
      console.warn(`[agentbell-notify] AgentBell returned HTTP ${response.status}`);
    }
  } catch (error) {
    const message = readableError(error) || 'request failed';
    console.warn(`[agentbell-notify] notify failed: ${message.slice(0, 200)}`);
  }
}

export function apply(ctx, config = {}) {
  const options = normalizeConfig(config);
  /** @type {Map<string, {startedAt: number, turn: unknown}>} */
  const turns = new Map();
  /** @type {Map<string, string>} */
  const chunks = new Map();

  const keyOf = (session) => String(session?.id ?? '');

  ctx.on('session/event', (session, event) => {
    if (!session || !event) return;
    const id = keyOf(session);
    if (!id) return;
    const data = event.data && typeof event.data === 'object' ? event.data : {};

    if (event.type === 'turn/start') {
      // A new turn supersedes any stale timer or summary buffer for this session.
      turns.set(id, { startedAt: Date.now(), turn: data.turn });
      chunks.delete(id);
      return;
    }

    if (event.type === 'assistant/chunk') {
      if (!options.includeSummary) return;
      const text = chunkText(data);
      if (!text) return;
      const merged = `${chunks.get(id) ?? ''}${text}`;
      chunks.set(id, merged.slice(-CHUNK_BUFFER_LIMIT));
      return;
    }

    if (event.type !== 'turn/end') return;

    const started = turns.get(id);
    turns.delete(id);
    const turn = data.turn ?? started?.turn ?? '?';
    const elapsedMs = started ? Date.now() - started.startedAt : null;
    const duration = elapsedMs == null ? '' : formatDuration(elapsedMs);
    const { kind, error } = reasonOf(data);
    const status = statusOf(kind);

    let summary = `第 ${turn} 轮结束`;
    if (duration) summary += `（${duration}）`;
    if (kind !== 'completed') summary += ` · ${kind}`;
    const errorText = readableError(error);
    if (status === 'failed' && errorText) summary += `：${errorText}`;
    if (options.includeSummary) {
      const tail = chunks.get(id);
      if (tail) summary += ` · ${clip(tail, CHUNK_BUFFER_LIMIT)}`;
    }
    chunks.delete(id);

    const payload = {
      title: sessionTitle(session, id),
      status,
      summary: clip(summary, 4000),
      duration: clip(duration, 64),
      source: options.source,
      session_id: clip(id, 120),
      run_id: clip(`dsh:${id}`, 120),
      dedupe_key: clip(`dsh:${id}:${turn}`, 200),
      origin: {
        pid: process.pid,
        working_dir: clip(session?.header?.cwd ?? '', 1024),
      },
    };
    if (status === 'failed' && errorText) payload.error = errorText;

    // Fire and forget: the harness must never wait on AgentBell.
    void send(options, payload).catch((failure) => {
      console.warn(
        `[agentbell-notify] notify failed: ${(readableError(failure) || 'unknown').slice(0, 200)}`,
      );
    });
  });
}
