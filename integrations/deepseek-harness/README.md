# DeepSeek Harness 接入（AgentBell）

本目录提供两种接入方式，二者可以同时使用：

| 目录 | 形式 | 适用场景 |
| --- | --- | --- |
| `agentbell-notify/` | Agent Skill + 单文件 CLI | 任意 dsh / Claude 会话按需上报 |
| `dsh-plugin/` | dsh bundle 插件 | dsh 自动在每轮结束时上报 |

所有请求只发往本机 AgentBell HTTP API（默认 `http://127.0.0.1:8765/notify`），
不读取会话正文，不执行命令，也不能批准权限或继续任务。

## 1. 安装技能

把整个 `agentbell-notify` 目录复制到技能目录：

```bash
# dsh 与 Claude 共用的技能目录
cp -r agentbell-notify ~/.agents/skills/agentbell-notify

# 或只给 dsh 使用
mkdir -p ~/.dsh/skills
cp -r agentbell-notify ~/.dsh/skills/agentbell-notify
```

（Windows 下把 `~/.agents/skills/` 换成 `%USERPROFILE%\.agents\skills\`。）

脚本只用 Python 标准库，可直接试运行：

```bash
python ~/.agents/skills/agentbell-notify/agentbell_notify.py \
  --title "示例任务" --status succeeded --summary "技能已连通" --json
```

退出码 0 表示 AgentBell 已接收，2 表示配置、网络或 HTTP 错误（原因写到 stderr，
不会输出 token）。

## 2. 安装 dsh 插件

要求 dsh `>= 0.2.2-rc.1 < 0.3.0`，且 Node 支持全局 `fetch` 与 `AbortSignal.timeout`
（Node 18+，推荐 Node 24）。

```bash
# 使用本目录的绝对路径注册 bundle
dsh plugin --profile web add /absolute/path/to/integrations/deepseek-harness/dsh-plugin
```

然后把 bundle 名称加入 `$DSH_HOME/profiles/web/package.json` 的
`dsh.profile.bundles`（保留已有条目）：

```json
{
  "dsh": {
    "profile": {
      "bundles": ["@agentbell/dsh-notify"]
    }
  }
}
```

重启 dsh 使插件生效。插件通过 `cordis.patch.yml` 插入：

```yaml
- insert:
    - id: agentbell-notify
      name: '@agentbell/dsh-notify'
      config:
        endpoint: 'http://127.0.0.1:8765/notify'
        source: 'DeepSeek Harness'
        tokenEnv: 'AGENTBELL_TOKEN'
        tokenFile: ''
        includeSummary: false
```

每轮 `turn/end` 会自动发送一条通知：标题取 `session.header.cwd` 的末级目录名，
`session_id` 为 dsh 会话 ID，`run_id` 为 `dsh:<id>`，`dedupe_key` 为
`dsh:<id>:<turn>`。`error` 映射为 `failed`，`aborted`/`interrupted` 映射为
`canceled`。请求为 fire-and-forget，失败只写一行 `console.warn`，不会阻塞事件循环。

## 3. Token 与安全边界

AgentBell 开启 token 校验时，按以下顺序取 token：

1. bundle config 的 `token`；
2. 环境变量 `AGENTBELL_TOKEN`（即 `tokenEnv`，可在 patch 中改名）；
3. `tokenFile` 指向的 JSON 文件中的 `token` 字段（例如 AgentBell 的 `config.json`）。

技能 CLI 则按 `--token` → `--config` → `AGENTBELL_CONFIG` → `AGENTBELL_HOME/config.json`
→ `%LOCALAPPDATA%\AgentBell\config.json` / `%APPDATA%\AgentBell\config.json` →
`~/.agentbell/config.json` → `~/AgentBell/config.json` 查找 `port` 与 `token`。

安全边界：

- 端点必须是 `http(s)` 且主机为 `127.0.0.1`、`localhost` 或 `::1`，否则插件直接拒绝；
- token 只放在 `X-Token` 请求头，不打印、不写入日志、不出现在 URL 中；
- 不读取会话消息、文件内容或 shell 历史；
- 不提供批准权限、回答提问、继续/取消 turn 的能力。

## 4. 验证

```bash
# 技能：单元测试（本地假 HTTP 服务）
python -m pytest tests/test_deepseek_skill.py -q

# 插件：mock ctx + 本地 HTTP 服务
node --test integrations/deepseek-harness/dsh-plugin/test/plugin.test.mjs

# 端到端（需 AgentBell 已启动）
curl -s http://127.0.0.1:8765/health
python integrations/deepseek-harness/agentbell-notify/agentbell_notify.py \
  --title "E2E" --summary "hello" --json
```

本机未安装 dsh，因此插件按 dsh 0.2.2-rc.1 的官方 bundle 格式（命名导出、
`session/event`、`cordis.patch.yml`）实现，并用 mock ctx 与本地 HTTP 服务验证；
实际加载需要在装有 dsh >= 0.2.2-rc.1 的环境中完成上述注册步骤。

## 5. 发布与生态收录

DeepSeek Harness 目前没有集中式「官方插件库」，官方发现入口是 GitHub 的
[`dsh-plugin` topic](https://github.com/topics/dsh-plugin)，分发方式为 npm、tarball
或 Git（见 [DeepSeek Harness 官网](https://www.deepseek.com/harness/)）。社区目录
（如 [awesome-deepseek-harness-plugins](https://github.com/imsai-sh/awesome-deepseek-harness-plugins)、
[dsh-plugin.org](https://dsh-plugin.org/)）按 topic 自动发现或接受 PR 收录。

本目录的 bundle 已符合官方格式，但**尚未对外发布**，因此暂不会被社区索引。
要进入生态，需要依次完成：

1. 在 `1wu-davy-2/AgentBell` 仓库添加 `dsh-plugin` topic（需仓库权限）；
2. 可选：把 `@agentbell/dsh-notify` 发布到 npm；若没有该 scope，改用未占用的包名，并同步 `cordis.patch.yml` 与文档；
3. 可选：向 awesome 列表提交 PR。

以上均为对外发布操作，需明确授权后执行；未发布前，用户仍可通过本目录的
绝对路径 `dsh plugin --profile web add ...` 直接安装。
