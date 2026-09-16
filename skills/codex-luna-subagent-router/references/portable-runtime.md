# 便携 Python 运行环境与完整包安装（v2.6.0）

## 交付边界

Windows x64/ARM64：CPython 3.13.15 官方 embeddable；macOS x64/ARM64：python-build-standalone 3.13.15+20260901 install_only_stripped。固定来源和 SHA256 在仓库 `tools/runtime-lock.json`。每个完整包真正包含解释器、标准库、动态库、许可证、启动器和全部 Skill 文件；运行/安装阶段不再下载 Python，不依赖 uv、pip、系统 Python 或修改 PATH。

源码 Git 不存大型二进制。GitHub 自动生成的 Source code.zip/tar.gz **不是**完整运行包。只有 `router-<版本>-<平台>.zip` 或 `.tar.gz` 才是完整包。版本 2.6.0 在 PR 验证期间尚未正式发布；此时只能选择明确标记的 PR 构建产物，不能把它称作稳定 Release。

## 推荐：交给 Agent 安装

1. 识别宿主系统与 CPU，选择完整平台包。不把 WSL Linux 当作原生 Windows；不提供 Linux 便携包。
2. 从指定正式 Release（或用户明确选择的 PR 产物）取完整包和对应 SHA256。用 macOS `shasum -a 256` 或 PowerShell `Get-FileHash -Algorithm SHA256` 对照摘要后再解压。摘要证明下载一致性，不代替可信发布源或代码签名。
3. 解压到已安装 Skill 目录之外。运行 `bin/router doctor --verify`；Windows 用 `bin/router.cmd doctor --verify` 或 `bin/router.ps1`。没有 Python 的机器也可启动。
4. macOS：`bash ./install.sh --global`；Windows：`./install.ps1 --global`。项目安装改为 `--project <项目>`。不自动绕过 PowerShell 执行策略；受组织策略限制时使用 `bin/router.cmd install --global` 或向管理员确认。
5. 安装器输出实际 `installed` 路径。按该路径运行盘点并继续六项引导，不把文件复制成功当作配置/信任完成。

现有 `$CODEX_SKILLS_DIR` 与 `$CODEX_AGENTS_DIR` 覆盖保留。默认全局新装用 `~/.agents/skills`；只有旧 `$CODEX_HOME/skills` 存在时复用旧路径。两处同时安装时拒绝猜测，要求明确指定路径。项目包仍使用 `<项目>/.agents/skills`。

## 统一调用

从工作项目目录调用，不为了运行脚本改变项目 scope。以下用 POSIX 入口举例，Windows 替换为完整路径的 `bin/router.cmd` 或 `bin/router.ps1`：

```bash
ROUTER="/实际安装目录/codex-luna-subagent-router/bin/router"
"$ROUTER" doctor --verify
"$ROUTER" inspect_guided_install --json
"$ROUTER" route_advisor stats
"$ROUTER" token_usage stats --json
"$ROUTER" turn_usage preview
```

`bin/router <脚本名>` 支持省略或保留 `.py` 后缀。调用参数原样传给原辅助脚本，工作目录和 stdin 保留。不要再用 Xcode 的 Python 3.9 或裸 `python3`。未知并发配置仍是未知，不因为环境错误自动允许并发 3。

## hooks 与升级

所有自动 hooks 指向安装目录内的私有解释器，并经统一 `runtime_dispatch.py token_usage` 入口执行。启用 `-I -S -B -X utf8`，隔离 PYTHONHOME、PYTHONPATH 和用户 site-packages，避免旧解释器/同名模块污染；保留 CODEX_HOME 等显式用户配置。

更新包不会自动写 hooks.json 或信任库。旧 hook 版本/路径在第 6 项重新盘点；用户同意后重新生成四项定义，并由客户端正常审查信任。明确 off 保留，不因为升级自动开启；手动采集继续可用。

安装前校验全包，暂存后复核，随后更换 Skill 目录和托管 profiles。失败回滚；Windows 文件正在使用导致更换失败时应报告，不杀掉 Agent。保留旧包于同级 `.codex-luna-subagent-router.previous-*`，确认升级后由用户自行删除。旧包回滚也需检查 hook 命令/版本并重新审查，不恢复或删除统计账本。

config.toml、routing.json、非托管 AGENTS.md、其它 profiles 和 outcome/usage 账本均不因复制包而改写。运行时损坏或平台错误时明确失败，不静默使用系统 Python、不临时联网修复。Stop 入口能运行但辅助脚本出错时仍保持非阻塞；解释器本身无法启动时由宿主 hook 超时/错误机制处理，不能承诺这种情况也返回 JSON。

## 构建与支持状态

构建机需要 Python 3.12+ 和联网；这是维护者要求，不是用户运行要求。固定上游下载后先核对 SHA256，再安全解压；拒绝目录穿越、特殊文件、越界链接和异常膨胀。保留上游完整 stripped/embeddable 结构，不激进删除标准库。`runtime/licenses/SOURCES.md` 和 `runtime.json` 保留来源及许可证索引。

```bash
python tools/build_portable.py --target macos-arm64
python tools/smoke_portable.py --target macos-arm64
```

四个平台分别在原生 runner 用随包解释器验证：模块导入、没有 Python 的 PATH、中文/空格目录、环境变量污染、全局安装与重复升级、配置/账本不变、hook 命令与完整单元测试。CI 不等于用户 Codex Desktop 自动派遣/信任/真实日志验收。macOS 上游最低系统版本及系统下载隔离/Gatekeeper 行为仍须在目标用户环境验收；本项目不提供 Apple Developer ID 公证，不自动清除 quarantine。

源码开发仍允许显式 `CODEX_ROUTER_PYTHON=/绝对路径/python3`，要求 Python >=3.11；完整包存在 runtime.json 时禁止此覆盖。源码模式不冒充便携运行验收。

本轮只解决运行环境与交付。日志边界、重复 session_meta、历史快照刷新等问题独立跟踪，不改变 token 口径来掩盖缺失。

来源：
- https://docs.python.org/3/using/windows.html#the-embeddable-package
- https://www.python.org/ftp/python/3.13.15/windows-3.13.15.json
- https://github.com/astral-sh/python-build-standalone/releases/tag/20260901
- https://gregoryszorc.com/docs/python-build-standalone/main/distributions.html
