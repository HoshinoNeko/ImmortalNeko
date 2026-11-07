# 验证记录与验收范围

最近更新：2026-11-08。环境：macOS arm64、Python 3.14.5。
详细机器可读结果见 [test-results.json](test-results.json) 和 [config-validation.json](config-validation.json)。

## 已执行并通过

* 完整172项回归测试全部通过，139.054秒，无跳过项；包含4项本地包发现检查、15项加速配置、7项 WeChatPush 及14项 V2Ray Server 配置与启动流程测试。
  覆盖构建配置、产物、旧清单分析、采集器、双路径探测、释放确认、单会话限制与可恢复退避事件。
  首次 Ubuntu Actions 的失败及本地修复见下文；本机通过不等同于远程流水线通过。
* Socat、PPTP、设备流量、V2Ray Server 及 Turbo ACC 五组实际JS表单/视图模拟测试通过。
  流量页覆盖IPv4/IPv6、计数基线、筛选/排序及只读ACL；V2Ray 页面覆盖隐藏字段保留、凭据遮蔽、UUID及协议参数校验。
* 27个Python文件 AST、20个 .sh/.init Shell语法检查通过；6个本地JS语法、5份中文PO的 msgfmt 检查通过，Turbo ACC 的47条及V2Ray的51条消息覆盖通过。
* 固定源插件补丁测试12项、首次安装/保留配置升级测试4项通过；实际LuCI Lua文件通过本机Lua 5.5语法解析，首次Actions的Lua 5.1解析及SyncDial入口检查也通过。
* Shell语法门禁负向验证：临时错误脚本在旧写法中返回0，修正后返回1；实际工程脚本返回0。
* actionlint v1.7.12：工作流通过；二进制经过固定SHA256校验。未运行shellcheck。
* 固件输入扫描及目录边界校验通过；private/ 不能通过 files/../private 误选为覆盖层。
* 实际源码和5个Feed的HEAD逐一匹配 source.lock.json。
* 当前三个真实 make defconfig 均通过，且所有请求的包/选项与解析结果严格相等：
  x86-basic 18项、x86-ha 171项、r619ac-ha 33项。已记录各最终配置及构建输入的SHA256。
  包含新增 SSH/timeout、HomeProxy/Sing-box、x86 插件与中文翻译、本地页面、V2Ray/Python适配层、
  BBR/DNSProxy、WeChatPush及27项驱动；十个此前缺失的应用/翻译包均已在实际元数据中注册，解析结果为 y。
* 用户指定的现役 x86 只读采集完成：680个安装包、80个配置文件，11项采集产物校验和通过。
  未修改现网设置、未启停服务或刷写设备。

真实配置验证首先在原磁盘失败：文件系统不区分大小写、getopt不满足要求，旧Bash也产生解析错误。
之后在缓存目录创建并挂载2GiB容量上限的大小写敏感APFS稀疏映像，复用已下载仓库；
加入已安装的GNU getopt路径并安装Bash 5.3.20，重新生成索引并通过配置解析。
没有使用FORCE=1绕过前置检查。该映像仅用于配置验证，不是Linux固件完整构建环境。
原始及最终日志保留在 .work-config-audit/logs/；不将缓存/完整上游源码提交到Git。

模拟测试新增覆盖：关闭HA后仍清理旧WAN、配置变化后的生效快照、慢启动期间的有序退让、
事件处理器退出、缺失服务仍尝试释放拨号、多个VLAN网关、重复地址/配置注入拒绝、
任一受管网段链路故障、采集超时/失败、私有路径和归档边界。
这些结果不等同于真实设备网络服务测试。
本次还执行了 Socat JS 表单往返、主树/Feed补丁作用域与失败不改写测试，以及服务角色/接管阶段保护。
针对固定源码复制出的3份 init 文件完成真实补丁应用和 sh -n，HomeProxy 的 TUN 缺失/存在/删除失败及
首次日志目录创建用模拟 ip/config helper 执行；未触碰真实网络或服务，记录见 .work/vendor-patch-audit.json。

## 首次 Actions 失败与修复

用户已推送 `4806fc4c511c014491403486c77fee2466905f04`，
[Static checks #1](https://github.com/HoshinoNeko/ImmortalNeko/actions/runs/42173306468) 运行失败。
用户提供的日志确认 Ubuntu 单元测试运行160项，只有 OpenVPN 导出夹具失败；
keepalived 2.3.3 已编译成功，随后 `make install` 尝试写入 `/usr/lib/systemd/system` 而失败。

OpenVPN 测试原先连续替换 PKI 和 `/tmp/` 前缀，第二次替换会改写 Linux 临时目录中已经替换好的路径。
在本机设置 `TMPDIR=/tmp` 后复现了相同失败，现改为单次替换；夹具自身包含 `/tmp/`，确保本机也覆盖此路径布局。
修复未改动固件中的 OpenVPN 导出逻辑。测试用 keepalived 现只复制构建产物到 `.work/tools/.../sbin/keepalived`，
保留可执行权限，不运行安装服务单元和示例配置的完整安装目标。
新增4项离线构建助手测试覆盖工作目录产物、权限、编译失败、缺失可执行文件及源校验失败。
16项相关测试在 `TMPDIR=/tmp` 下通过，随后164项完整测试也在 `/tmp` 和 dash 下通过，127.487秒。
下载/编译命令在助手测试中被模拟，本机未运行真实Linux编译或namespace测试。

## 后续 Actions 配置检查失败与修复

用户提供的后续日志确认，测试用 keepalived 已能启动配置校验；检查因
`Ignoring track_interface lan0 since own interface` 返回5，选主与故障切换尚未开始。
锁定的2.3.3源码把重复跟踪已绑定接口报告为配置错误，同时会隐式跟踪该接口。
生成器现排除已绑定的选举接口，其余网关设备去重后显式跟踪，空列表不输出配置块。
不绑定接口的双路径模式仍显式跟踪所有网关接口；健康脚本继续检查 LAN、WAN 底层与额外网关。
`firmware-ha` release 升至6，原生 `--config-test` 的零退出码要求保持不变。
6项相关回归已通过，覆盖空块、不同绑定接口、额外网关去重、双路径及额外网关断链。
完整166项测试在 `/tmp` 和 dash 下通过，130.295秒，无失败或跳过项。
后续日志已走到两端启动后的选主等待，说明这轮单路径配置检查已通过；启动阶段的新错误见下文。
源码依据见 [HA说明](ha.md#多-vlan-与有序事件)。

## 后续 Actions 启动参数失败与修复

用户提供的新日志显示主进程报 `Unknown option -P`，初始选主等待因进程退出而失败。
CI 用 `--disable-lvs` 构建；2.3.3 的 `-P/--vrrp` 只在 VRRP 和 LVS 都启用时注册，
参见 [固定版本参数表](https://github.com/acassen/keepalived/blob/v2.3.3/keepalived/core/main.c#L1883)。
集成命令现使用 `-n -l -p -r -f`，由已编译的 VRRP 子系统正常启动。
控制包自身未使用 `-P`，本次没有改动其运行命令。

参数列表由同一函数生成，创建 namespace 前先将 `--help` 追加在该列表末尾交给实际二进制解析，
不支持的参数会立即失败并显示返回码与诊断。按固定源码的帮助处理，该预检不读取测试配置或打开 pidfile。
新增2项离线测试用 VRRP-only 参数契约夹具验证两实例的路径、完整参数解析、未知选项失败及诊断；
连同4项构建助手测试共6项通过；随后完整168项测试在 `/tmp` 和 dash 下通过，133.687秒。
此夹具不是真实 keepalived，原生参数预检及选主/切换仍待CI重跑。

## x86-ha 本地 LuCI 包配置失败与修复

用户提供的 Build firmware 日志显示五个本地应用及其中文翻译在 defconfig 后均为 n：
PPTP Server、Socat、Turbo ACC、V2Ray Server、wrtbwmon。
固定主树的 [include/scan.mk](https://github.com/immortalwrt/immortalwrt/blob/4fc16f2985a358bd43bb522e43f05395fcbd6ed5/include/scan.mk#L65)
先用 grep 查找含 `call BuildPackage` 等调用标记的 Makefile，再求值其 include。
这五份文件虽包含 luci.mk，却缺少官方 LuCI 包使用的扫描标记，因此连翻译定义也未进入包索引。

现补齐五份 Makefile 的签名，并在 validate 中检查本地包和主题包是否满足固定扫描规则。
4项新增测试覆盖无标记拒绝、原生注册/签名接受、下载前门禁及安装后使用真实 grep 规则发现全部8个本地包。
旧提交的五份 Makefile 在同一规则下全部未匹配，修复后全部匹配。
随后在大小写敏感的缓存源码中重新核对主树与5个 Feed 的固定 HEAD、应用对应 Profile 补丁，
运行真实 make defconfig；三个 Profile 的全部请求均通过严格相等检查。
x86-ha 的五个应用和五个中文包均存在于实际包元数据，且最终配置为 y。
本次配置解析未使用模拟 Kconfig、FORCE=1 或删除包选择；完整固件编译仍需 Actions 重跑。
日志与原始配置保存在 .work/package-discovery-audit/，摘要见 config-validation.json。

## 仍待完成的原生验收

Linux集成测试：sudo python3 tests/integration/keepalived_netns.py。
在临时namespace/veth/bridge和/run目录中运行两个真实keepalived，检查两个网段VIP的唯一主机、
WAN断开接管、x86恢复抢占、主进程停止接管。新增 --dual-path 覆盖两条独立链路、稳定 /32 路由、
仅心跳故障及仅 WAN 监测故障时保持原主。CI 从固定SHA256源码编译与固件一致的 keepalived 2.3.3；
UCI/netifd与应用服务是模拟接口，warm 模式用于隔离验证真实 VRRP，不模拟 SSH 或运营商PPPoE。
本机未运行真实Linux测试；此前原生日志已通过单路径配置检查，随后进程因 `-P` 退出；修复后的选主及切换详细结果待核对。

真实 V2Ray 核心配置校验入口为 `tests/integration/v2ray_generated.py --core <V2Ray-5.53.0>`，
提供12份配置及1份负向配置，临时证书和配置会在测试结束后清理。
本机Go 1.23.4可用，但 proxy.golang.org 的DNS查询失败，且没有同版本缓存，未构建/运行真实核心。
后端流程测试使用模拟核心/procd；真实配置解析、认证、传输握手与流量验收仍待执行。

仍待验收：make download、完整make、实际固件Manifest与SHA256产物生成、Linux选主/切换集成、
固件构建工作流、Release、刷机/启动、真实PPPoE切换、内存压力与吞吐测试。
用户已创建并推送 HoshinoNeko/ImmortalNeko，已运行静态检查及后续原生配置校验。
本次环境已可读写 Git、访问远程仓库并挂载配置验证映像；完整构建的修复结果仍需 Actions 验证。

## 完整目标的验收审计

| 需求 | 当前证据 | 仍缺的证据 |
| --- | --- | --- |
| 独立模块化工程 | 本地Git、用户已推送远程仓库、首次CI及错误日志 | 修复提交、推送及流水线通过 |
| 官方稳定分支与固定Commit/Feed | 锁文件、真实HEAD核对、三个defconfig | 全量编译与长期更新验证 |
| x86 Legacy/UEFI、ext4/SquashFS | 四类镜像选项通过真实解析、产物硬门禁 | 四类镜像实际生成与启动 |
| R619AC 128M支持 | 用户确认128MiB NAND / 512MiB RAM、当前配置解析通过 | 真实board/内存信息、启动/功能测试；设备目前不可访问 |
| 保留全部插件 | 当前680包快照、66项LuCI迁移清单 | 10项待确定迁移方案；全部条目的目标编译/运行验收，全部应用的实际编译和功能验证 |
| 网络/驱动/预配置 | 实时私有快照、多VIP与受管接口入口 | VLAN/端口/驱动映射、管理地址与VIP方案、IPv6及多WAN策略 |
| PPPoE接管/回落和主机恢复 | 已确认单会话、冷备、双路径释放查询、退避、模拟测试及当前defconfig | 真实Linux事件、运营商及双设备测试 |
| 独立1G心跳 | WAN DHCP + 专用心跳监测、单实例路由切换及分区限制 | 地址/租约/接线、真实双路径测试、断电/断线/分区演练及必要仲裁 |
| 512MiB RAM基本服务 | 用户硬件确认、明确软件包及角色服务入口 | 实机内存、并发峰值、OOM与吞吐 |
| 缓存、Manifest、SHA256与Release | 工作流/校验/元数据模块 | 实际缓存命中、产物、校验、下载与发布结果 |
| 凭据隔离和升级区别 | 私有目录权限/忽略、输入边界和扫描、生效快照/初始化标记 | 最终rootfs审查、首次启动与保留配置升级演练 |
| 内核/网络/LuCI扩展入口及文档 | 独立片段、覆盖/包/主题目录和文档 | 后续定制功能的目标验证 |

必须在实机覆盖主机掉电、WAN断开、认证失败、仅心跳/仅LAN故障、双机同时重启、主机恢复、
链路抖动、运营商会话释放延迟，以及DHCP租约冲突、IPv6 RA/PD、VPN/FRP/DDNS恢复时间和CPU/内存。
连接状态同步与DHCP租约同步仍未实现。全部证据齐备之前，目标保持active。

## 已确认输入与下一步

用户确认旧备份已过期，提供现役x86管理地址并授权只读采集；实时快照已经成为迁移依据。
R619AC当前不可用。当前网络为多VLAN/多WAN，不能把单网段模板当作现网方案。
用户已创建远程仓库，确认单会话 PPPoE 和 R619AC 的512MiB内存。双路径方案已落入本地控制包、模板和测试。
下一步重跑 Actions 完整构建并核对 Linux 集成结果；
继续逐项处理剩余10项插件迁移；已落实的11项替代/本地页面仍需实际目标验证。双机运行配置仍需管理地址/VIP、端口接线、两端DHCP保留租约、
心跳及稳定 /32 控制地址；R619AC可用后做实机验收。


本次新增的 PPTP UI/后端补丁、x86驱动列表及可选服务资产元数据采集仍未通过目标编译和实机验收。
PPTP测试对固定源的真实补丁进行应用，在临时路径执行实际Shell函数，使用模拟UCI/procd帮助函数；
验证账号格式、旧条目清理、凭据原子替换/权限、禁用默认值和旧DNS字段，未启动真实PPTP服务。
补充SSH资产采集失败，不能据此声称VPN证书、驱动绑定或全部服务数据已保存。


当前 x86-ha 已显式请求66项插件映射中的56项，已有定义却未显式请求的条目为0；
剩余10项还没有确定方案，56项仍须实际配置解析、Manifest 和运行验收。
已用固定源补丁移除 OpenVPN UI 对后端配置的重复打包、VPN 默认网络/防火墙修改及自动 PKI 生成，
IPsec 不再预设凭据/地址；Argon/Material 注册后保持当前主题。
首次安装禁用额外服务自启，保留配置升级尊重初始化标记；SyncDial 多拨/重拨入口和 HA 预检执行单会话限制。
这些变更通过临时目录中的真实补丁与脚本测试，尚未执行目标编译或实机测试。

Turbo ACC 使用本地中文页面、实际 firewall4 配置、独立 BBR 管理及官方 DNSProxy。
固定源补丁和真实 OpenWrt 配置帮助函数测试通过；BBR 恢复、手动改动保护、模块失败、私有状态及并发锁均使用模拟内核接口验证。
DNSProxy 参数边界、布尔开关、禁用/缺上游不启动均通过；页面测试确认旧 FullCone 值2不会被隐式归一化。
内核 sysctl、真实 DNS 核心、加密解析、NAT/卸载与 SQM/代理/统计的组合、实际吞吐均未运行。

WeChatPush 替代旧 Server酱通知插件，默认关闭且不导入旧配置。7项离线测试覆盖固定源补丁、严格启用开关、HA启动守卫和配置值原文读取；没有发送通知。
固定源中文PO的7组重复消息已由补丁修复，msgfmt及5个上游JS文件语法检查通过。
真实推送、认证、时序、登录防护、子进程停止及HA仍待验收；其旧wrtbwmon流量通知扩展未启用。
