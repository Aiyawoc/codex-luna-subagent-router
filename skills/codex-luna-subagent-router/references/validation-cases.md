# v2.5.1 验收

## 采集与存储

begin 后 pending 增加；finalize 后 outcome 增加且 pending 清除；重复结算不增加行，冲突被拒绝。并发写不重复计数，坏行/符号链接/忙锁应给明确错误。未知身份、路由不匹配、取消、early stop、环境阻塞和 Lead 实质返工记录 partial，不冒充 verified_pass。

## 兼容与隔离

旧三条 global JSONL 可查询但不猜项目归属。Git 根与子目录同 scope；非 Git 显式根；finalize 不受 cwd 改变影响。项目配置优先，全局安装不等于全局数据。缺失/off 不自动采集；旧 record 兼容，新流程用 begin/finalize。

## 历史与统计

A 保留 exact 2/3 门槛；B 需要 5 个唯一回执和 2 个 family，只同模型下降一档，不跨项目/模型/高风险。失败否决，partial 不训练，旧无 ID 行不贡献 B。stats 与 recommend 共用判断；显示可用建议不是实际覆盖，不估算不存在的账单数据。

## 多任务

Astra high 下两个独立同类 bounded 任务可同时派两个 Luna；三独立有价值任务可三个。共享上下文同 family/六轴/路由可 batch；独立复核不合并。依赖或读写冲突串行，Lead 未完成前置任务不虚构完成。已有打开 Worker 和 Codex 较低上限缩减可创建候选。复杂因果 debug 仍考虑 Sol；micro 不为配额派遣；luna_only 不漏出 Sol。

## 原有回归

RoutePlan 2.1、Luna→Sol capability gap、max 跨层 medium 下限、Sol 精确 ID、Terra 退役、单任务 2 attempt、权限/写入隔离、fresh/TASK_ACK/简洁回传/early stop、引导五项和 instruction budget 均保留。

新增 Python 测试只证明脚本规则，不替代 Codex App 的自然派遣、scope、登记与实际身份验收。
