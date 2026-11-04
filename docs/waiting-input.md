# 等待输入提醒接入示例

AgentBell 用 `running` 通知上的 `needs_input` 表示「Agent 正在等你」。显式上报是主路径：不依赖会话文件格式，也能准确说明在等什么。

```json
{
  "title": "Claude Code 等待权限确认",
  "status": "running",
  "needs_input": true,
  "wait_reason": "permission",
  "wait_source": "explicit",
  "session_id": "abc123",
  "run_id": "run-20261103-001",
  "summary": "需要允许执行 npm test",
  "source": "Claude Code",
  "origin": { "pid": 12345, "window_title": "Claude Code" }
}
```

约束：

- `needs_input=true` 只能与 `status="running"` 一起使用，其他组合返回 422。
- `wait_reason` 取 `permission` / `question` / `rate_limit` / `context_limit` / `other`，缺省 `other`。
- `wait_source` 取 `explicit` / `inferred`，人工或 Hook 上报用 `explicit`。
- 同一 `session_id` 的新通知会结束上一次等待；也可以显式发送 `needs_input=false`。
- 未填写 `priority` 时，等待通知默认 `high`。

## Claude Code Hook

Claude Code 的 `Notification` 事件在需要权限或等待输入时触发，`UserPromptSubmit` 在用户提交新输入时触发。把下面的脚本保存为 `agentbell_wait_hook.py`，再把 Hook 写进项目或用户级 `.claude/settings.json`。

```python
import json
import os
import sys
import urllib.request

PORT = os.environ.get("AGENTBELL_PORT", "8765")
TOKEN = os.environ.get("AGENTBELL_TOKEN", "")
EVENT = sys.argv[1] if len(sys.argv) > 1 else "wait"

payload = json.load(sys.stdin)
session_id = payload.get("session_id", "")
message = (payload.get("message") or "Claude Code 正在等待输入")[:200]

if EVENT == "resume":
    body = {
        "title": "Claude Code 继续执行",
        "status": "running",
        "needs_input": False,
        "session_id": session_id,
        "summary": "已收到输入，继续执行",
        "source": "Claude Code",
    }
else:
    body = {
        "title": "Claude Code 等待输入",
        "status": "running",
        "needs_input": True,
        "wait_reason": "permission",
        "wait_source": "explicit",
        "session_id": session_id,
        "summary": message,
        "source": "Claude Code",
        "origin": {"pid": os.getppid()},
    }

request = urllib.request.Request(
    f"http://127.0.0.1:{PORT}/notify",
    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
    headers={"Content-Type": "application/json; charset=utf-8", "X-Token": TOKEN},
    method="POST",
)
try:
    urllib.request.urlopen(request, timeout=3).read()
except Exception as exc:
    print(f"agentbell notify failed: {exc}", file=sys.stderr)
```

`.claude/settings.json`：

```json
{
  "hooks": {
    "Notification": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python C:\\Tools\\agentbell_wait_hook.py wait"
          }
        ]
      }
    ],
    "UserPromptSubmit": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python C:\\Tools\\agentbell_wait_hook.py resume"
          }
        ]
      }
    ]
  }
}
```

把 `AGENTBELL_PORT` / `AGENTBELL_TOKEN` 设为启动 Agent 时的环境变量。Hook 是同步执行的，脚本在 3 秒后超时且只写 stderr，不会阻塞 Claude Code。

## 通用脚本

任何能发 HTTP 的脚本都可以上报等待。Bash：

```bash
curl -sS -X POST "http://127.0.0.1:${AGENTBELL_PORT:-8765}/notify" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Token: ${AGENTBELL_TOKEN}" \
  --data-binary @- <<'JSON'
{"title":"构建等待确认","status":"running","needs_input":true,"wait_reason":"permission","source":"build.sh","session_id":"build-001","summary":"需要确认是否覆盖 dist/"}
JSON
```

恢复或取消等待时发送同 `session_id` 的普通进行中通知，或带 `"needs_input": false`：

```bash
curl -sS -X POST "http://127.0.0.1:${AGENTBELL_PORT:-8765}/notify" \
  -H "Content-Type: application/json; charset=utf-8" \
  -H "X-Token: ${AGENTBELL_TOKEN}" \
  --data-binary '{"title":"构建继续","status":"running","needs_input":false,"session_id":"build-001","source":"build.sh"}'
```

## 本地推断

不接 Hook 时，可在「偏好设置 → Agent → 等待输入提醒」开启本地推断。它只读取最近 10 分钟内 Claude Code / Qoder 会话文件的尾部，连续两次扫描命中且闲置达到阈值才上报；推断结果带「推断」标记，提问类默认只进通知中心。推断不修改会话文件，也不会把会话正文写入日志或数据库。

显式上报与推断可以同时开启：同一会话已有显式等待时，推断不会重复创建卡片。

## 运行时间线

等待与恢复会自动进入运行时间线。每次上报只需带稳定的 `session_id` 或 `run_id`：

- 某个 `run_id` 的第一条 `running` 记为「开始」，等待上报记为「等待输入」。
- 同一次运行里等待之后的第一条非等待事件记为「已继续」。
- 终态（成功 / 失败 / 取消）记为「完成」。
- 同一运行同一阶段 5 秒内只保留一条，重复上报不会堆叠。

也可以显式传 `phase`（`started` / `progress` / `waiting_input` / `resumed` / `finished` / `note`）精确控制某一条事件的归属。通知卡片的「时间线」按钮、会话详情的「本次运行」和统计页的运行指标都读取同一份 `run_events`。
