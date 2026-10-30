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
  status    必填，"succeeded" 成功 / "failed" 失败 / "canceled" 取消 / "running" 进行中
  summary   本轮结论，一句话即可，最多 4000 字
  duration  可选，本轮耗时，例如 "8m30s"
  link      可选，仅支持 http/https 链接
  error     仅失败时填写，简短错误原因
  priority  可选，"low" / "normal" / "high" / "critical"；失败默认 high，critical 会一直保留直到用户确认
  source    可选，来源标识（Agent 名或任务类型），便于规则匹配和统计
  dedupe_key 可选，同一任务的多轮更新使用相同的去重键，AgentBell 会原地更新卡片而不是重复弹出
  require_ack 可选，true 表示需要用户点击“知道了”才算完成，适合等你决策或失败需处理的场景
  progress  可选，0-100，配合 status="running" 和 dedupe_key 展示任务进度
  actions   可选，最多 4 个按钮，每项为 {{"kind":"open|copy|retry|path|center","label":"按钮文字","value":"参数"}}
            open/link 用 http(s) 链接；copy 用要复制的文本；path 用本地绝对路径；retry 只能用本机 http 回调地址
  bypass_quiet_hours 可选，true 表示忽略免打扰时段（谨慎使用）
  silent    可选，true 表示只记录到通知中心，不弹窗
  popup_mode 可选，"corner" 右侧卡片 / "center" 居中确认 / "overlay" 全屏遮挡
  popup_skin 可选，"midnight" 午夜蓝 / "light" 晨光白 / "ocean" 深海青 / "amber" 琥珀暖
  expires_in 可选，秒数，过期后不再弹出
  channel_types 可选，限制本条只走指定外部渠道，如 ["wecom","ntfy"]

示例：
  长任务每轮用同一个 dedupe_key 推送 status="running" + progress，结束后推送 status="succeeded"。
  需要用户确认时设置 require_ack=true；重要但不需要确认时设置 priority="high"。
  不要把普通成功都设成 critical，也不要在每一轮都使用 require_ack。

curl 示例：
{curl_example}

注意：
1. 推送失败不要中断主任务，也不要反复重试，只需在回复末尾提醒我“AgentBell 通知未送达”。
2. summary 只写结论，不要粘贴过程日志。
3. 通知只用于桌面提醒；只有 require_ack=true 时才需要等待我确认。

完成后，AgentBell 会在桌面右上角弹出提醒，并在“通知中心”保留记录；你可以在通知中心搜索、统计成功率和耗时。"""
