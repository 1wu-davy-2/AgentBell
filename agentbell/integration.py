from __future__ import annotations


def build_agent_instructions(port: int, token: str = "") -> str:
    """Text copied to the clipboard and handed to an AI agent."""
    auth_lines = ["  Content-Type: application/json"]
    if token:
        auth_lines.append(f"  X-Token: {token}")
    auth_note = "请求头：\n" + "\n".join(auth_lines)
    if not token:
        auth_note += "\n（当前未开启 X-Token，无需鉴权请求头）"

    curl_headers = ['  -H "Content-Type: application/json"']
    if token:
        curl_headers.append(f'  -H "X-Token: {token}"')
    curl_example = (
        'curl -s -X POST "http://127.0.0.1:%d/notify" \\\n' % port
        + " \\\n".join(curl_headers)
        + " \\\n  -d '{\"title\":\"生成竞品分析报告\",\"status\":\"succeeded\","
        "\"summary\":\"已完成 12 页报告\",\"duration\":\"8m30s\"}'"
    )

    return f"""你正在接入 AgentBell，这是一个运行在本机的桌面通知工具。请把下面的规则加入你的工作方式。

【必须执行】每一轮对话或任务结束时，都要向 AgentBell 推送一条通知，然后再给出最终回复。无论成功、失败还是取消都要推送；不要只在用户明确要求时推送，也不要在同一轮内重复推送。

接口：POST http://127.0.0.1:{port}/notify
{auth_note}

请求体字段（JSON）：
  title     必填，本轮需求的简短名称，最多 200 字（不要包含“上一轮”）
  status    必填，"succeeded" 成功 / "failed" 失败 / "canceled" 取消
  summary   本轮结论，一句话即可，最多 4000 字
  duration  可选，本轮耗时，例如 "8m30s"
  link      可选，仅支持 http/https 链接
  error     仅失败时填写，简短错误原因

curl 示例：
{curl_example}

注意：
1. 推送失败不要中断主任务，也不要反复重试，只需在回复末尾提醒我“AgentBell 通知未送达”。
2. summary 只写结论，不要粘贴过程日志。
3. 通知只用于桌面提醒，不需要等待我确认。

完成后，AgentBell 会在桌面右上角弹出提醒，并在“通知中心”保留记录。"""
