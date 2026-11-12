import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';

import * as plugin from '../lib/index.js';
import { apply, inject, name } from '../lib/index.js';

const TOKEN = 'test-secret-token';

function createContext() {
  const handlers = new Map();
  return {
    handlers,
    on(event, handler) {
      handlers.set(event, handler);
    },
    emit(session, event) {
      const handler = handlers.get('session/event');
      assert.ok(handler, 'plugin must subscribe to session/event');
      handler(session, event);
    },
  };
}

function sleep(ms) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function waitFor(predicate, message = 'timed out waiting for condition') {
  const deadline = Date.now() + 2000;
  while (Date.now() < deadline) {
    if (predicate()) return;
    await sleep(10);
  }
  throw new Error(message);
}

async function startServer(status = 202) {
  const requests = [];
  const server = http.createServer((request, response) => {
    const chunks = [];
    request.on('data', (chunk) => chunks.push(chunk));
    request.on('end', () => {
      const raw = Buffer.concat(chunks).toString('utf8');
      requests.push({
        method: request.method,
        url: request.url,
        headers: request.headers,
        body: raw ? JSON.parse(raw) : {},
      });
      response.writeHead(status, { 'Content-Type': 'application/json' });
      response.end(JSON.stringify({ ok: status < 400, id: 'notif-1' }));
    });
  });
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const { port } = server.address();
  return {
    requests,
    endpoint: `http://127.0.0.1:${port}/notify`,
    async close() {
      server.closeAllConnections?.();
      await new Promise((resolve) => server.close(resolve));
    },
  };
}

function session(id = 'session-abcdef123456', cwd = 'C:\\work\\demo-project') {
  return { id, header: { cwd } };
}

test('exports the required named ESM API without a default export', () => {
  assert.equal(name, 'agentbell-notify');
  assert.ok(Array.isArray(inject));
  assert.deepEqual(inject, []);
  assert.equal(typeof apply, 'function');
  assert.equal('default' in plugin, false);
});

test('turn/start + completed turn/end sends the expected payload and token', async (t) => {
  const server = await startServer();
  t.after(() => server.close());

  const ctx = createContext();
  apply(ctx, { endpoint: server.endpoint, token: TOKEN });

  const active = session();
  ctx.emit(active, { type: 'turn/start', data: { turn: 1 } });
  await sleep(25);
  ctx.emit(active, { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } });

  await waitFor(() => server.requests.length === 1);
  const request = server.requests[0];
  assert.equal(request.method, 'POST');
  assert.equal(request.url, '/notify');
  assert.equal(request.headers['x-token'], TOKEN);

  const body = request.body;
  assert.equal(body.title, 'demo-project');
  assert.equal(body.status, 'succeeded');
  assert.equal(body.source, 'DeepSeek Harness');
  assert.equal(body.session_id, 'session-abcdef123456');
  assert.equal(body.run_id, 'dsh:session-abcdef123456');
  assert.equal(body.dedupe_key, 'dsh:session-abcdef123456:1');
  assert.deepEqual(body.origin, {
    pid: process.pid,
    working_dir: 'C:\\work\\demo-project',
  });
  assert.match(body.summary, /^第 1 轮结束/);
  assert.ok(body.duration, 'duration text must be present');
  assert.equal(body.error, undefined);
});

test('reason.kind=error maps to failed with a readable error', async (t) => {
  const server = await startServer();
  t.after(() => server.close());

  const ctx = createContext();
  apply(ctx, { endpoint: server.endpoint, token: TOKEN });
  const active = session('session-error', '/home/user/project');

  ctx.emit(active, { type: 'turn/start', data: { turn: 2 } });
  ctx.emit(active, {
    type: 'turn/end',
    data: { turn: 2, reason: { kind: 'error', error: new Error('build exploded') } },
  });

  await waitFor(() => server.requests.length === 1);
  const body = server.requests[0].body;
  assert.equal(body.title, 'project');
  assert.equal(body.status, 'failed');
  assert.equal(body.error, 'build exploded');
  assert.match(body.summary, /^第 2 轮结束/);
  assert.match(body.summary, /error/);
  assert.ok(body.summary.includes('build exploded'));
});

test('aborted and interrupted turns map to canceled', async (t) => {
  const server = await startServer();
  t.after(() => server.close());

  const ctx = createContext();
  apply(ctx, { endpoint: server.endpoint, token: TOKEN });

  for (const [index, kind] of ['aborted', 'interrupted'].entries()) {
    const active = session(`session-cancel-${index}`, '/srv/demo');
    ctx.emit(active, { type: 'turn/start', data: { turn: index + 1 } });
    ctx.emit(active, {
      type: 'turn/end',
      data: { turn: index + 1, reason: { kind } },
    });
  }

  await waitFor(() => server.requests.length === 2);
  assert.deepEqual(
    server.requests.map((item) => item.body.status),
    ['canceled', 'canceled'],
  );
});

test('non turn/end events do not send a notification', async (t) => {
  const server = await startServer();
  t.after(() => server.close());

  const ctx = createContext();
  apply(ctx, { endpoint: server.endpoint, token: TOKEN });
  const active = session();

  ctx.emit(active, { type: 'turn/start', data: { turn: 1 } });
  ctx.emit(active, { type: 'assistant/chunk', data: { text: 'still working' } });
  await sleep(150);

  assert.equal(server.requests.length, 0);
});

test('non-loopback endpoints are rejected before any request', async () => {
  const ctx = createContext();
  apply(ctx, { endpoint: 'http://192.0.2.10:8765/notify', token: TOKEN });
  const active = session();

  const originalFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => {
    calls += 1;
    throw new Error('fetch must not be called for non-loopback endpoints');
  };
  const warnings = [];
  const originalWarn = console.warn;
  console.warn = (...args) => warnings.push(args.join(' '));

  try {
    ctx.emit(active, { type: 'turn/start', data: { turn: 1 } });
    ctx.emit(active, { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } });
    await sleep(100);
  } finally {
    globalThis.fetch = originalFetch;
    console.warn = originalWarn;
  }

  assert.equal(calls, 0);
  assert.ok(warnings.some((line) => line.includes('loopback')));
});

test('multiple sessions keep independent timers and dedupe keys', async (t) => {
  const server = await startServer();
  t.after(() => server.close());

  const ctx = createContext();
  apply(ctx, { endpoint: server.endpoint, token: TOKEN });
  const first = session('session-one', '/work/alpha');
  const second = session('session-two', '/work/beta');

  ctx.emit(first, { type: 'turn/start', data: { turn: 1 } });
  ctx.emit(second, { type: 'turn/start', data: { turn: 3 } });
  ctx.emit(second, { type: 'turn/end', data: { turn: 3, reason: { kind: 'completed' } } });
  ctx.emit(first, { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } });

  await waitFor(() => server.requests.length === 2);
  const bySession = new Map(
    server.requests.map((item) => [item.body.session_id, item.body]),
  );
  assert.equal(bySession.get('session-one').dedupe_key, 'dsh:session-one:1');
  assert.equal(bySession.get('session-two').dedupe_key, 'dsh:session-two:3');
  assert.equal(bySession.get('session-one').title, 'alpha');
  assert.equal(bySession.get('session-two').title, 'beta');
});

test('token is resolved from tokenEnv and omitted when no token exists', async (t) => {
  const server = await startServer();
  t.after(() => server.close());

  process.env.AGENTBELL_TEST_TOKEN = 'env-token';
  t.after(() => {
    delete process.env.AGENTBELL_TEST_TOKEN;
  });

  const ctx = createContext();
  apply(ctx, { endpoint: server.endpoint, tokenEnv: 'AGENTBELL_TEST_TOKEN' });
  const active = session();
  ctx.emit(active, { type: 'turn/start', data: { turn: 1 } });
  ctx.emit(active, { type: 'turn/end', data: { turn: 1, reason: { kind: 'completed' } } });

  await waitFor(() => server.requests.length === 1);
  assert.equal(server.requests[0].headers['x-token'], 'env-token');

  const noTokenCtx = createContext();
  apply(noTokenCtx, { endpoint: server.endpoint, tokenEnv: 'AGENTBELL_MISSING_TOKEN' });
  noTokenCtx.emit(active, { type: 'turn/start', data: { turn: 2 } });
  noTokenCtx.emit(active, { type: 'turn/end', data: { turn: 2, reason: { kind: 'completed' } } });

  await waitFor(() => server.requests.length === 2);
  assert.equal(server.requests[1].headers['x-token'], undefined);
});
