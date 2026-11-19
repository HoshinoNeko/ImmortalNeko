# ImmortalNeko

项目仓库：[HoshinoNeko/ImmortalNeko](https://github.com/HoshinoNeko/ImmortalNeko)，
SSH：`git@HoshinoNeko.github:HoshinoNeko/ImmortalNeko.git`。
独立配置仓库，不 Fork 或提交完整 ImmortalWrt 源码。源码使用官方稳定分支
`openwrt-25.12` 的发布版 **v25.12.2**，固定 Commit
`4fc16f2985a358bd43bb522e43f05395fcbd6ed5`；5 个官方 Feed 同样固定完整 Commit。
Vantage 主题通过额外 Feed 固定在 `faade36bb629f84b1e233edcad9e37abc500ae52`。
25.12 使用 apk，旧 LEDE 18.06 的 opkg 软件包与 UCI 配置必须经过迁移。

当前交付包括源码构建流水线、四个 Profile、配置验证、缓存、产物与发布、
旧配置清单分析工具、只读设备采集器和本地 keepalived 控制包。**完整固件编译及实机切换仍待验证**。
已对现役 x86 完成只读采集：680个已安装包、80个配置文件。当前66个 LuCI 应用/协议/主题条目中，
已有方案的56项均已显式加入 x86-ha（包含原有主题及可用中文翻译），仍有10项待确定迁移方案，见 [迁移清单](migration/current-plugin-plan.json)。
代理已识别为 SSR Plus 及其后端；两种 HA Profile 选择官方 HomeProxy/Sing-box 作为基础代理候选，
旧节点、订阅、分流与服务端功能的完整迁移仍待验证。现有 Profile 不能视为全部旧插件迁移版。
没有更改默认主题或指定 LAN/WAN 地址。当前四个 Profile 均已通过真实 `make defconfig`，包含新增二层 VPN 依赖；新功能的固件编译与实机互通仍待验证。

四个 Profile 也均包含 **Vantage 可选主题与中文网络首页**：按内网 VLAN 查看速率、采样累计流量及图表，
并从集客 AC 展示 SSID、AP 和终端，替代首页的本机无线展示。AC 默认地址为用户指定的 `172.16.10.89`，
凭据仅在设备本地配置。主题切换、统计口径和配置方法见 [首页与 AC 采集](docs/dashboard.md)。

## 目录

```text
.github/workflows/   静态检查、手动完整构建与草稿 Release
config/             源码/Feed 锁、通用/目标/内核 Kconfig 片段
profiles/           目标、包清单、覆盖层、必需产物声明
packages/           基础、HA、二层 VPN 与现有插件/驱动清单
local-packages/     本仓库维护的软件包；firmware-ha 含 HA 控制逻辑
files/              common 与各 Profile 的根文件系统覆盖层
patches/            common 与各 Profile 的 series 补丁序列
themes/             主题软件包与 LuCI 覆盖扩展入口；保留上游默认外观
migration/          旧软件包替代规则
scripts/            分离的源码、配置、产物、清单迁移模块
templates/          部署前填写的拓扑、内核和网络配置示例
tests/              对实际脚本的回归测试和 Linux 集成验证
private/            被 Git 忽略的原始配置与设备凭据；不得用作固件覆盖层
.work/              被 Git 忽略的源码、下载和编译缓存
artifacts/          被 Git 忽略的固件与构建记录
```

## 构建方案

| Profile | 硬件与镜像 | 预装范围 |
| --- | --- | --- |
| `x86-basic` | x86/64；Legacy/UEFI × ext4/SquashFS 四种镜像 | 上游默认 + LuCI 中文、CA、Vantage、网络首页、HomeProxy/Sing-box、ddns-go |
| `x86-ha` | 同上 | 基础 + HA 服务 + 已核对的部分现有 x86 组件 |
| `r619ac-basic` | ipq40xx/generic，`p2w_r619ac-128m`，NAND SquashFS | 上游默认 + LuCI 中文 + 二层 VPN / Xray + Vantage、网络首页、HomeProxy/Sing-box、ddns-go |
| `r619ac-ha` | ipq40xx/generic，`p2w_r619ac-128m`，NAND SquashFS | 同 HA 服务集，保留上游目标驱动默认值 |

HA 服务集：DHCP/DNS（上游 dnsmasq/odhcpd）、OpenVPN、WireGuard、ddns-go、
ZeroTier、FRP 客户端、HomeProxy/Sing-box、keepalived。WireGuard 由 netifd 管理；在设备本地用 HA 的 managed_interface
列表指定需要随角色启停的 WireGuard 接口，默认不选择接口，不停止整个 network 服务。
本维护分支的四个 Profile 都通过 `packages/proxy-ddns.list` 安装 HomeProxy/Sing-box 与 ddns-go
（含中文界面和 dnsmasq nftset 支持）；basic 版只安装这两个服务，不包含 HA 控制器。
该分支尚未重新执行完整编译和实机验证。软件包选择不等同于具备可工作的 VPN/DDNS/代理配置；
凭据须刷机后在设备本地填写。
`x86-ha` 另通过 `packages/x86-retained.list` 显式选择已有方案的旧插件与翻译，包括 Socat/PPTP 页面、
文件管理器、下载/存储/打印服务、多 WAN 管理、原有主题、bonding、系统 NTP 和 Tailscale。
根分区设为2048MiB，x86-basic 仍为512MiB；R619AC 保持基本服务范围。
`r619ac-basic`、`r619ac-ha` 和 `x86-ha` 共用二层 VPN 功能：L2TPv3 Ethernet / VXLAN → WireGuard，
可选经独立 Xray/VLESS＋TLS/REALITY 转发。LuCI“网络 → 接口”可配置隧道，“网络 → 二层 VPN”配置 VLESS。
默认不创建隧道或桥接现有 LAN，VLESS 转发关闭；两端模板、DHCP/RA、MTU 与 HA 接入见 [二层 VPN 部署](docs/l2-vpn.md)。
宿舍 basic 版包含基础、网络首页和二层 VPN 软件包，保留自己的 WAN 与管理网络；用户已确认宿舍 R619AC 也是128MiB NAND／512MiB RAM，使用 `p2w_r619ac-128m` 目标。
首次安装会关闭额外服务的自动启动，配置完成后再在设备本地启用；已初始化的保留配置升级不重复关闭。
Argon/Material 只注册可选主题，不切换当前外观；OpenVPN/IPsec 页面不自动改写网络、防火墙或生成 PKI。
SyncDial 保留页面，但单会话策略下阻止其多拨脚本和重拨按钮，HA 启动前也会拒绝已启用的 SyncDial。
Socat/PPTP 页面复用官方后端包，不争用其配置/init文件的所有权。Socat 保留旧字符串与逐项参数；
PPTP 默认关闭、不预设账号/地址，后端补丁保留旧 DNS 字段并保护生成的 PPP 凭据。
旧流量监视器使用本地只读页面和官方 nlbwmon 后端，显示按 MAC 汇总的 IPv4/IPv6 流量及采样速率。
访问时间控制改用官方防火墙的 Traffic Rules；规则迁移、时区、已建立连接和卸载路径仍待验收。
V2Ray Server 使用本地页面及独立适配层，协议实现来自锁定的官方 V2Ray 5.53.0；
生成配置权限600，交由核心校验后才通过 procd 启动，不自动放行端口或变更网络。
Turbo ACC 使用本地中文页面管理实际防火墙卸载、BBR 与官方 DNSProxy；旧 FullCone 模式须明确选择新策略。
BBR 关闭时按记录恢复原算法，DNSProxy 默认关闭且无公共上游预设；详见 [加速配置迁移](docs/migration.md#turbo-acc-加速配置迁移)。
Server酱由固定 Feed 中的 WeChatPush 及中文界面替代，默认关闭；通知规则及凭据须在设备本地重新配置。
`packages/x86-drivers.list` 选择当前 x86 已安装的27项网卡/USB/存储模块名，按新内核重新编译；
源码定义存在不代表当前硬件绑定或启动已经验证。

`p2w_r619ac-128m` 的 128M 是 **128 MiB NAND 闪存**；用户已确认 **512 MiB RAM**。
设备目前不可访问，仍待实机 board/内存与启动验证，不能混刷64M NAND版本。
配置解析不代表完整编译或并发负载可用，仍需测量内存、吞吐与 OOM。
详见 [硬件与服务验证](docs/validation.md)。

## GitHub Actions

将这个配置仓库推送到自己的 GitHub 仓库，进入 Actions → Build firmware → Run workflow：
选择 Profile；默认只构建 `x86-basic`。`all` 根据 `profiles/*.json` 自动生成矩阵。
默认只上传 Actions Artifacts；勾选 `publish` 才生成一个包含所选 Profile 的**草稿 Release**。
发布任务仅在全部构建成功后运行，自动校验 SHA256，再打包每个 Profile，避免同名产物覆盖。
首次全量构建可能需要数小时；日志在失败后也会上传。修改配置或扩展包无需改主工作流。
更新修复后，选择 `main` 重新发起 Run workflow；旧任务的 Re-run jobs 仍使用原来的提交。

HA 集成测试会验证临时目录是否允许执行。若 runner 的 `/run` 禁止执行，改用
`/usr/local/lib` 下 root 所有的临时目录；CI 在私有 mount namespace 中强制 `/run` 为 `noexec` 验证此路径。

流水线使用 Ubuntu 24.04，先安装构建依赖，再拉取锁定源码、安装锁定 Feed、应用补丁、
安装本地包、叠加系统文件、执行 `make defconfig`。任何请求的包或 Kconfig 选项被静默移除，
都会直接失败并输出差异。随后 `make download`、完整 `make`、验证镜像与 Manifest，最后打包。
失败不会降级为成功；没有使用 `make ... || true` 掩盖错误。
本地 LuCI 包须保留 `# call BuildPackage - OpenWrt buildroot signature` 扫描标记；
`validate` 会在下载源码前检查，防止应用及翻译包被扫描器一起跳过。

缓存分为下载、C/C++ 和 Go 三层，支持失败编译后保存已完成的缓存；普通页面改动不再清掉整组缓存。
`compile_jobs=auto` 按 CPU 和内存选择并发；`use_cache` 可关闭缓存做对照。统计写入构建 Summary 和日志。
不整体共享 build_dir/staging_dir；实际源码和 Feed Commit 总在使用前核对。隔离规则与容量说明见 [构建提速](docs/build-acceleration.md)。
GitHub Actions 自身同样固定完整 Commit；更新时需核对上游发布记录。
只读任务仅有 contents:read；草稿发布任务才获得 contents:write。
CI 不执行来自 PR 的固件发布；工作流不接收设备密码或其他固件凭据。

## 本地构建与检查

完整源码编译使用 x86_64 Linux（建议 Ubuntu 24.04）、足够磁盘（建议 80 GiB 以上）和内存。
本地控制脚本仅依赖 Python 3.10+ 标准库；无需 pip。macOS 可运行静态检查和模拟测试。

```sh
python3 scripts/build.py validate
python3 -m unittest discover -s tests -v
python3 scripts/build.py prepare --profile x86-basic
python3 scripts/build.py download --profile x86-basic --jobs 4
python3 scripts/build.py compile --profile x86-basic --jobs 2
python3 scripts/build.py collect --profile x86-basic --out artifacts/x86-basic
```

`prepare` 要求新的源码目录；重新构建可用 `--work .work-next`，每个阶段均需指定同一目录。
不自动删除已有源码。应先提交配置到 Git 再正式构建，以便产物准确记录配置仓库版本。
若只需调整源码 Commit，编辑 `config/source.lock.json`，并同步审核所选版本的 Feed 锁和配置兼容性。
不允许使用浮动分支作为依赖版本；额外 Feed 初始为空。

## 扩展方法

* 软件包：独立维护 `.list`，在 Profile 的 `packages` 中引用；每行一个包名，`-包名` 禁用。
  清单不应列入跨架构旧 kmod；驱动由对应 Profile 核实。
* 额外 Feed：编辑 `config/feeds.extra.lock.json`，每条包含 name、HTTPS url 和 40 位 commit。
  构建会验证最终 HEAD，初始不添加未经确认的第三方源。
* 系统文件：按根目录结构放入 `files/common/` 或 Profile 覆盖层。
  带密码、私钥、Wi-Fi key、VPN 文件、shadow 等内容会被输入扫描拒绝。
  扫描是防误放辅助措施，提交时仍需检查变更；原始配置只能存入 `private/`。
* 补丁：写入 `patches/common/` 或 `patches/<profile>/`，在该目录 `series` 中按顺序列相对文件名。
  每个补丁先 `git apply --check`，失败即停止。主树补丁相对主源码树；
  Feed 补丁放在 `patches/feeds/<feed>/series`，相对已经核对 Commit 的 Feed 根目录，
  Profile 专用补丁可放 `patches/feeds/<feed>/<profile>/series`。当前含 DHCP/代理 HA 角色保护补丁。
* 自定义内核：编辑 `config/kernel.config` 添加 `CONFIG_KERNEL_*`；启动参数可在 x86 片段添加
  `CONFIG_GRUB_BOOTOPTS="..."`。新增目标特有设置应独立片段并在 Profile 引用。
* 网络默认值：参照 `templates/network.uci.example`，得到用户确认后才放入对应覆盖层或首次启动脚本。
* 主题：新包放入 `themes/packages/<package>/`，在包清单显式选择；修改已有主题推荐锁定主题源码，
  用可审阅补丁维护。`themes/luci-overrides` 只有显式列为覆盖层才会进入固件，不默认应用。
  禁止靠同名目录无提示覆盖既有本地包。
* LuCI 页面：作为独立包维护在 local-packages/ 或 themes/packages/，或用目标补丁；不把 UI 改动塞入构建工作流。

## 旧 LEDE 迁移

参见 [迁移文档](docs/migration.md)。提供了只读 SSH 采集脚本，所有原始配置留在 Git 忽略的
`private/`。导入器仅输出配置结构，不输出密码值；遇到无法映射的旧插件显式标记 review。
只有全部条目确认并移入目标包清单后，才能验收“保留所有插件”。
历史备份已由用户确认过期，当前以实时 SSH 快照为准；Tailscale 作为现有独立服务也已列入待保留范围。
`ddns-scripts` → `ddns-go` 的规则已准备，但域名、API 提供商、认证方式需重新配置。

## 双机与 PPPoE

参见 [HA 部署和故障行为](docs/ha.md)。控制包默认关闭；你尚未确认的端口与地址均留空。
两个节点都以 BACKUP 状态启动，x86 优先级 200、R619AC 100，允许延迟抢占。
支持显式配置多个 VLAN 的网关 VIP；FIFO 按序处理角色切换，停止时使用已生效配置快照执行清理。
用户已确认只支持一个 PPPoE 会话，使用 `cold-pppoe`。默认双路径模式同时监测
WAN DHCP（192.168.1.0/24）与专用心跳口，通过同一个 VRRP 实例选主，拨号前查询对端释放状态。
`warm` 只允许显式声明 multiple 会话的独立上联环境。双路径同时隔离仍需外部仲裁才能保证不双主。

现网交付仍需解决旧插件兼容、确认端口/VLAN/地址、完成编译与双机演练。R619AC 当前无法访问。
此前 CI 的启动参数和本地 LuCI 包扫描问题已修复。新增宿舍 basic 版及二层 VPN 后，
四个 Profile 的真实配置解析均通过，Xray 原生配置解析及回环 UDP 转发已验证；
Linux 中两种二层隧道经 WireGuard 直连/VLESS 的完整链路、WAN断线及受管接口重建已通过 CI；
R619AC 实机与两地网络仍需验收。

## 安装、升级与产物

首次安装 x86：核对 UEFI/Legacy 和磁盘，用相应 `*-combined[-efi].img.gz` 写入目标盘。
写盘会覆盖数据，本文不自动选择磁盘或执行刷写。ext4 易修改；SquashFS 提供只读基础系统和 overlay。
日后同架构升级先备份并用 `sysupgrade -T <image>` 验证，明确是否保留配置。
从 LEDE 18.06 跨大版本升级不应直接恢复整个 `/etc/config`，尤其是 swconfig → DSA 网络与 firewall3 → firewall4。
R619AC 首刷使用确切硬件对应的安装/恢复方法；`sysupgrade.bin` 只供已支持该目标的系统升级。
不要对未知型号执行强制升级，也不自动写 U-Boot、ART 或设备校准分区。

每次产物包含实际 `*.manifest`、resolved/requested.config、feeds.conf.lock、BUILD_VERSION、build-info.json、
各镜像和 SHA256SUMS。build-info 记录配置仓库 Commit、源码实际 Commit、Feed 实际 Commit、
Profile、构建时间和全部自定义输入的 SHA256。下载后先在该目录运行 `sha256sum -c SHA256SUMS`。
签名私钥、原始配置、构建缓存不会作为固件发布附件。

测试记录与剩余工作见 [验证记录](docs/validation.md)。
