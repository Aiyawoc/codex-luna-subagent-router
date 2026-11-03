# Adaptive工作所有权：30% / 50%观察目标

`adaptive` 本身吸收主动委派改进，面向可拆分的中大型任务，观察目标约30%的子线程用量；新增 `adaptive_aggressive` 面向约50%。不另设balanced/proactive开关，不把百分比当运行时配额。`luna_only` 保留原有模型与执行形态边界。

## 两档差异

| 规则 | adaptive | adaptive_aggressive |
| --- | --- | --- |
| 同层同档独立包 | 有中/深推理或高上下文时可委派，即使只有一个包 | 进一步允许简单但完整、可移交的实施/分析包 |
| 多个只读任务 | 机械查询用本地并行工具；分析不能因只读被收回Lead | 同样区分机械与分析，边界充分时更早移交 |
| Worker职责 | 声明范围内完成实现、测试与局部修正 | 更优先移交完整工作包，不把中间小步骤逐个交回Lead |
| Lead职责 | 目标、跨模块决策、整合、风险验收 | 更偏协调与验收，不重复Worker拥有的工作 |

简单但完整不包含micro修改、读取一个符号、运行一条固定命令。激进档也允许0 Worker，不为目标增加测试轮次或更贵模型。

## 工作包

通常根据六轴及read/write路径推断，无新增必填字段。可选 `work_package` 用于澄清所有权：

```json
{
  "work_package": {
    "kind": "delivery",
    "handoff_ready": true,
    "stages": ["investigate", "implement", "test", "repair"]
  }
}
```

kind为 `mechanical / analysis / delivery`。stages仅描述同一目标和权限范围内适用的阶段，不强迫执行无必要阶段；没有write_paths不能声明implement/repair。不能把深度推理或写入任务标成mechanical。`handoff_ready=false`先补足最小交接边界，不允许Lead借机完成全部实现。

新规则只提升已有bounded任务，不凭空生成任务或Reviewer。workflow应拆成少量可独立验收的bounded包，不切成大量命令碎片。独立复核仍有独立上下文，不与实现者合并。

模型基准仍由原Advisor与历史校准确定。完整执行形态必须通过正常 `route_advisor plan`；单独recommend没有所有权和依赖信息，不替代规划。

## 不放宽的边界

- 模型白名单、能力下限、Luna-only、Sol档位、已验证失败、授权与Host身份验证不变。
- 最大并发仍为3，并取实际Host/配置上限的最小值；健康探针、degraded暂停、依赖与写入冲突不变。
- 全部既有retain_reason仍是显式保留要求，激进档不能覆盖。仅在关键路径不应自动填critical_path保留理由，优先级由依赖顺序表达；确需Lead权限/判断才保留。
- 叶子Worker可以负责多阶段闭环，但不递归、不升模型、不扩路径、不做最终不可逆动作；每子任务最多2 attempt不变。
- 同模块小幅修正可条件复用，新的独立复核保持独立。Lead等待时不重复实现，不倾倒Worker原始日志。
- Decisions仍Shadow；雷达仍独立opt-in且只在ready Worker之后运行。切换策略不启用外部API或改动密钥。

## 百分比验收

30%/50%是可拆分中大型工作流的观察目标，不是任务数量或强制控制变量。简单任务不纳入该目标组。按同一父会话/工作流和同一时间区间核对主子净增量；去除继承基线、重复快照，失败和重试用量也保留。缓存是输入子项，推理是输出子项；不完整采集保留未知，不补零。

分别报告含缓存tokens、非缓存输入、输出；只有可靠费用/配额证据才报告成本占比，不用API价格猜订阅消耗。不能用50%的任务数或规划Worker数宣称50%的消耗达标。

还需同时检查单位交付Lead消耗下降、总消耗未因重复工作增加、质量和耗时不恶化。比例低时排查首次委派时机、包大小、执行缺口和Lead接管，不在收尾时凑Worker。

planner的target_subagent_usage_share只是目标；measured_subagent_usage_share=null表示尚未观测。planning账本记录策略版本和ownership_promotions；历史旧adaptive行仍可读，不反推旧行为或用量。

## 切换（仅安装支持此功能的版本后）

```bash
bin/router configure_guided_install --delegation none --routing-scope user \
  --routing-mode adaptive --json
bin/router configure_guided_install --delegation none --routing-scope user \
  --routing-mode adaptive_aggressive --json
```

切换不重装、不重录Key，保留Decision/Radar与Token设置。升级保留模式名称，不自动开启激进档；应明确告知adaptive行为增强。源码开发候选不等于生产安装。
