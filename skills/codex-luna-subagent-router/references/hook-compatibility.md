# v2.9.1 Hook 兼容性与诊断

核对日期：2026-10-22。状态：候选实现，真实 Desktop 加载、信任、触发与 UI 尚需现场验收。

## 兼容范围

默认仍为 `UserPromptSubmit / Stop / SubagentStart / SubagentStop` 四个事件。已有四事件安装不会因缺少新增事件而被判定为安装失败。Reader/hook 协议仍为 2.6.1；产品版本从 VERSION 读取。

`Interrupt / SessionEnd` 为单独确认后启用的本地 command hooks，不根据 Host 版本字符串自动启用，不把云端编排或独立 CLI 的成功当作 Desktop 当前会话支持证明。`--hooks-supported` 与 `--lifecycle-hooks-supported` 均是操作者声明，不是能力探测、授权或信任绕过。

官方契约：

- https://learn.chatgpt.com/docs/hooks
- https://learn.chatgpt.com/docs/app-server

Interrupt 包含主线程 session_id 和 turn_id，不覆盖子 Agent。SessionEnd 只有会话身份，没有可靠 turn_id，且离开页面不等于立即结束会话。两类事件使用同步 command handler，显式 timeout=3；输出只用空 JSON 或 systemMessage 警告，不发送继续/阻止/重启指令。官方说明 transcript 不是稳定接口。

## 统计与显示分离

`token_accounting=on/off` 控制统计。`token_accounting_summary` 只控制自动摘要：

| 值 | 行为 |
|---|---|
| silent | 仍统计；正常 Stop/SubagentStop 不输出用量，自动 preview 不扫描日志。错误警告不会被隐藏。 |
| brief | 显示简要已知用量；不承诺覆盖所有线程或账单。 |
| detailed | 显示详细快照与完整度。 |
| 未设置且原统计已开 | 保留 legacy 显示，不静默改变既有行为。 |

新开启的统计默认 silent；已有显式选择保留。手动 `stats/report/preview` 不受静默显示限制，只有自动 preview 使用 `--respect-summary`。不要为展示最终数字触发新的模型回合。

```bash
# 以下命令中的安装路径必须来自实际安装结果。
"$ROUTER" configure_token_accounting --scope user --mode on \
  --install-hooks --hooks-supported --summary silent --dry-run --json
```

去掉 dry-run 前应检查差异并走正常用户信任审查。更改任何 hook 定义都可能需要重新信任。此 helper 不读写信任数据库、不改权限、不自动启用 Host hooks。

## 可选结束事件

只有当前 Host 确认支持时才运行：

```bash
"$ROUTER" configure_token_accounting --scope user --mode on \
  --install-hooks --hooks-supported --summary silent \
  --lifecycle-hooks on --lifecycle-hooks-supported --dry-run --json
```

确认并应用后，通过客户端审查定义。每次重新配置启用中的结束事件，仍需确认当前 Host 的支持；不能复用旧 Host 版本的假定。关闭可选事件而保留四事件统计：

```bash
"$ROUTER" configure_token_accounting --scope user --mode on \
  --install-hooks --hooks-supported --lifecycle-hooks off
```

事件处理只做有界原子记录，不扫描 transcript、usage ledger 或目录，不轮询，不启动后台常驻服务或模型。健康记录失败不阻止正常统计；终止事件记录失败输出固定警告，但仍不阻止用户中断/退出。

Interrupt 按 scope + session + turn 精确关联，并冻结此前已保存的轮次统计；晚到 Stop、子线程回执、下一轮日志和显式 refresh 不会被用于补齐中断后的区间。缺少最终计数保持 partial/unavailable。当前版本没有证明中断时最后一次用量已落盘，因此不能据此声称最终用量完整。

SessionEnd 只记会话结束证据，不猜当前轮次、不证明任务成功、不将所有子 Agent 标记为结束。重新打开同一会话的新轮次不受这个会话级观察阻止。

## 诊断证据

```bash
"$ROUTER" diagnostics --json
"$ROUTER" turn_usage stats --json
```

diagnostics 保持只读，不触发 refresh。现在同时盘点用户/项目层的 hooks.json 与内联 TOML，显示重复来源与本地显式禁用/managed-only 限制。发现另一作用域或内联配置已有 Router handler 时，配置器拒绝叠加安装；应先审核迁移，不自动删除其他来源。

`hooks.handler_receipts.events` 每事件保存最新一次 handler 的阶段：

- not_observed：没有该 scope/安装/版本的记录，不能等同 Host 不支持。
- received：入口已到达，但没读到完成记录；可能仍运行、被终止或最终诊断写入失败，不证明超时。
- handled：处理器已返回；不证明所有 token 完整，也不证明任务验收通过。
- failed：处理器捕获到失败；只存固定分类，不存异常详情。
- stale_runtime / unavailable：其他版本/安装的旧记录，或记录不可读。

本地手动运行也能产生相同 stdin，因此 receipts 永远不把 `host_hook_trust / host_event_execution` 自动升级为已验证。真实 Desktop build、有效信任和能力需要独立现场证据。只看到图标、配置条目或单元测试 PASS 均不够。

轮次 JSON 另有 execution 对象，把 interrupted、session_end_observed 与 usage status 分开。普通 Stop 不是质量通过证明；没有对应终止证据时执行状态保持 unknown。

## 存储与回退

新记录位于 usage 账本旁的 `usage.hook-state/`。健康记录固定为每个 scope/事件的最新小文件；结束证据按身份摘要单独存放，重复事件幂等。只保存受控 metadata、不可逆身份摘要、产品版本、时间和耗时，不保存 prompt、回复、源码、token 明细、transcript 内容、真实项目路径或信任数据。单文件读取上限 16 KiB；不无限增长单个热路径文件。

usage.jsonl、usage.turns.jsonl 和 outcome 账本 schema 不变。升级/停用不删除历史。结束证据不会自动清理，因为删除它可能丢失冻结标记；归档时必须与对应账本一起处理。

回退前先停用当前入口并确认没有活动任务，保存配置、全部账本与 hook-state，再按照原有完整包或插件 rollback 流程恢复。v2.9.0 可以读取原账本，但不认识新增冻结标记：回退后不要对已中断历史轮次做 collect/refresh；以升级前备份/已冻结导出为准。绝不通过删除账本或直接写信任哈希来回退。

## 插件与仍未接通的能力

默认插件包仍声明四事件。六事件包是用于现场验收的显式构建变体：维护者使用 `tools/build_plugin.py --lifecycle-hooks`，文件名带 `plugin-lifecycle`，不替换默认包。四事件插件不允许配置器静默开启未声明的结束事件。两种包共用同一 Core 和账本；不得同时启用。

本版不连接 Desktop 私有 App Server，不自动使用账户用量替换任务账本，不把不同来源的 token 相加，不新增权限审批、线程执行 UI 或账户仪表盘。v2.10 原生事件接入仍以受支持入口和同一执行身份实证为前置条件。
