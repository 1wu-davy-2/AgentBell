# @agentbell/dsh-notify

dsh（DeepSeek Harness）bundle 插件：在每个 turn 结束时向本机 AgentBell 桌面应用
发送一条通知。插件入口为 ESM，导出命名 `name`、`inject`、`apply`，没有 default export。

## 要求

- dsh `>= 0.2.2-rc.1 < 0.3.0`
- Node 18+（使用全局 `fetch` 与 `AbortSignal.timeout`，推荐 Node 24）
- AgentBell 正在运行，且插件使用的 token 与 AgentBell 配置一致

## 配置

`cordis.patch.yml` 的默认配置：

| 字段 | 默认值 | 说明 |
| --- | --- | --- |
| `endpoint` | `http://127.0.0.1:8765/notify` | 必须是环回地址 |
| `source` | `DeepSeek Harness` | 通知来源，最多 100 字符 |
| `token` | 空 | 直接给 token（优先级最高） |
| `tokenEnv` | `AGENTBELL_TOKEN` | 从该环境变量读取 token |
| `tokenFile` | 空 | JSON 文件，读取其 `token` 字段 |
| `includeSummary` | `false` | 为 true 时把 assistant 文本尾部附到 summary |

token 解析顺序：`token` → `tokenEnv` → `tokenFile`。token 只写入 `X-Token`
请求头，不会打印。`tokenFile` 支持 `~/` 前缀。

## 行为

- 订阅 `ctx.on('session/event', (session, event) => ...)`。
- `turn/start`：按 `session.id` 记录开始时间；新 turn 覆盖旧计时，支持多会话并发。
- `turn/end`：发送 POST 后清理该会话状态；请求为 fire-and-forget，内部捕获所有错误。
- 其他事件（如 `assistant/chunk`）只在 `includeSummary=true` 时缓存文本，不发送请求。
- 标题：`session.header.cwd` 末级目录名，缺失时回退
  `DeepSeek Harness <session.id 前 8 位>`。
- 状态：`reason.kind=error` → `failed`；`aborted`/`interrupted` → `canceled`；
  其余 → `succeeded`。
- payload：`title`、`status`、`summary`（`第 N 轮结束` + 耗时 + 可选 reason/error）、
  `duration`、`source`、`session_id`、`run_id: dsh:<session.id>`、
  `dedupe_key: dsh:<session.id>:<turn>`、
  `origin: {pid: process.pid, working_dir: cwd}`；失败时附 `error`。
- 超时 4 秒；非环回或非 http(s) 端点直接拒绝并 `console.warn`；其他失败只输出
  一行精简 `console.warn`。

## 安装

```bash
dsh plugin --profile web add /absolute/path/to/dsh-plugin
```

再把 `@agentbell/dsh-notify` 加入 `$DSH_HOME/profiles/web/package.json`：

```json
{
  "dsh": {
    "profile": {
      "bundles": ["@agentbell/dsh-notify"]
    }
  }
}
```

重启 dsh。

## 测试

```bash
node --test test/plugin.test.mjs
```

测试使用 mock ctx、本地 `http.createServer` 和假事件，不依赖已安装的 dsh。
