# 验证记录与验收范围

2026-11-05，执行环境：macOS arm64，Python 3.14.5，工作目录 /Users/hoshino/immortalwrt。
本机没有 Docker/Podman、没有 Linux 网络命名空间；数据卷剩余约14 GiB。

## 已执行

* 锁定源码：核对官方 v25.12.2 annotated tag 指向 Commit 4fc16f2985a358bd43bb522e43f05395fcbd6ed5。
* 核对发布版 feeds.conf.default 的5个固定 Commit。
* 核对目标 image/generic.mk：p2w_r619ac-128m 为128M NAND规格。
* 核对锁定版本 ddns-go/frpc/keepalived 包与启动逻辑、FRP LuCI 包名、Kconfig 缓存/日志/签名定义。
* python3 scripts/build.py validate：配置结构、锁定格式、包名与固件输入扫描。
* Python AST 语法检查：scripts 与 tests 中所有 .py。
* sh -n：本地包与 scripts 中所有 .sh 和 .init。
* actionlint v1.7.12：两份 Actions 工作流；二进制经固定 SHA256 校验，未运行 shellcheck。
* unittest：实际执行了构建校验、旧清单迁移及实际 HA Shell 脚本的模拟测试。
  最终结果：35项全部通过，耗时13.890秒。初轮30项中的3项失败已修复（macOS测试时钟）。
  最终 Python AST检查11个文件通过，Shell语法检查8个脚本通过，actionlint退出码0。

模拟测试覆盖：默认关闭、配置注入拒绝、主备优先级/延迟抢占、备机不拨号、
主机启动服务、WAN失败/拨号等待窗口、冷却与封顶退避、恢复试探、warm模式健康门禁、
绑定自身WAN探测、物理链路故障、服务失败退出与抑制、WireGuard接口随角色启停、未知旧插件不静默丢弃。
这不等同于设备功能测试、真实 PPPoE 测试或完整固件构建成功。

## 已提供但未执行

Linux 集成测试：sudo python3 tests/integration/keepalived_netns.py。
它在临时 namespace/veth/bridge 中运行两个真实 keepalived，验证单VIP主机、WAN断开接管、
x86恢复抢占和主进程停止接管；UCI/netifd及应用服务是模拟接口，不模拟运营商PPPoE。
它不连接现网，退出时清理测试资源。已接入 CI；固件构建先等待 CI 检查完成。
本机只做了该测试脚本的语法检查，不能标记该集成测试通过。

以下尚无执行结果：make defconfig（真实源码与Feed）、make download、完整 make、
实际固件的 Manifest/SHA256 输出、GitHub Actions 运行、草稿 Release、启动/刷机。
GitHub 目标仓库尚未指定；当前未推送、未触发构建、未发布固件。

## 完整交付的待验收项目

| 需求 | 当前证据 | 仍需的证据 |
| --- | --- | --- |
| 独立模块化仓库、配置/Feed/补丁/主题入口 | 工程文件与本地 Git | 后续维护迭代验证 |
| x86 四类镜像 | 明确 Kconfig、产物硬门禁 | 实际编译生成并启动验证 |
| R619AC 128M 支持 | 官方目标候选、包清单 | 用户 board 信息、对应镜像编译与硬件启动 |
| 保留所有旧插件 | 导入/映射工具、ddns替代规则 | 真实 opkg 安装清单与逐项确认映射、功能检查 |
| 旧系统配置迁移 | 不含值的结构分析、私有采集入口 | 真实 etc/config、目标配置与防火墙验证 |
| PPPoE 接管/回落、x86恢复主机 | 实际控制脚本及模拟测试 | 会话策略、拓扑、Linux集成结果、运营商实测 |
| 独立1G心跳 | 可选 election_device | 链路故障/断电演练及仲裁设计确认 |
| DHCP/OpenVPN/代理/DDNS/ZeroTier/FRP/WG | 用户确认服务的包清单、受管服务/接口机制 | 代理具体实现、运行配置、实际连通与恢复测试 |
| 128 MiB RAM基本服务 | 未减配承诺服务 | 真实RAM、空闲/峰值内存、并发压力、OOM与吞吐记录 |
| 缓存、元数据、Manifest/SHA256与Release | 工作流与输出校验模块 | Actions运行产物、缓存命中、校验与下载验证 |
| 禁止凭据入固件、升级区别 | 私有目录隔离、输入扫描、运行期配置、升级初始化标记 | 最终自定义输入审查、实际 rootfs审查、保留配置升级演练 |

实机演练至少覆盖：主机掉电、WAN断开、PPPoE认证失败、主机服务停止、备机WAN故障、
交换机故障、仅心跳断开、仅LAN断开、两机同时重启、主机恢复、反复抖动、ISP会话释放延迟。
每次记录VIP唯一性、拨号归属、DHCP租约冲突、DNS与公网、各VPN/FRP/DDNS恢复时间、CPU/内存。
IPv6另测RA/DHCPv6/PD与路由行为；连接状态同步和DHCP租约同步目前未实现。

缺少上述证据时保持项目目标 active，不应将“架构存在”描述成“开箱即用现网固件已完成”。

## 当前外部输入

已核对现有“规划ImmortalWrt固件”与“恢复 OpenWrt 防火墙配置”任务：均未包含实际旧机
安装清单、完整 UCI 配置、硬件输出或可用设备地址，未从其他任务导入任何凭据。
用户待补充：旧机资料位置、R619AC board/内存信息、端口/地址/宽带会话策略、目标 GitHub 仓库。
本轮完成了工程代码与可执行检查，属于实质进展；完整目标保持 active。
