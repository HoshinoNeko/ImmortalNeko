# LEDE 18.06 清单与配置迁移

使用 `opkg list-installed` 提供安装清单最准确；`opkg list` 可能只是所有可安装包，不能证明已安装。
如果提供的是后者，必须补充安装状态，不能全部装进新固件。

设备地址确认后，可在本地运行只读采集：

```sh
sh scripts/collect-legacy.sh root@YOUR_ROUTER private/legacy-new
```

兼容入口会调用 Python 只读采集器；非默认 SSH 端口或指定现有密钥可用：

```sh
python3 scripts/collect_device.py --host root@YOUR_ROUTER --port 2222 \
  --identity /path/to/existing-key --output private/device-new
```

使用已知服务器密钥和 BatchMode，不接收命令行密码，不更改 SSH 信任规则。
采集器只执行固定查询：安装清单、ubus board、内存/闪存、接口/地址/路由、网络运行状态和 etc/config 归档。
每份文件权限为600，私有目录为700；保存校验和与 snapshot.json。
SSH失败、超时、JSON错误或不安全归档都会留下 status=failed，不能当成完整快照。
不自动解包归档，不重启或修改设备。
原始归档可能包含宽带密码、无线密钥、DDNS Token、VPN 凭据，只保存在权限受限且忽略的 private/。
不要将其上传到 Issue、聊天、Git 或 Release。不要为采集扫描未知网段或猜设备 SSH 地址。

在 Linux 上 prepare 目标源码，获得 tmp/.packageinfo 后：

```sh
python3 scripts/import_legacy.py   --installed private/legacy-new/opkg-list-installed.txt   --available .work/source/tmp/.packageinfo   --config-dir private/legacy-unpacked/etc/config   --output private/migration-x86-new
```

配置目录是可选参数。若需解包原始归档，应先查看归档列表、验证没有绝对路径/父目录跳转，
再在权限为700的 private/ 子目录内解包，不直接在工程根目录解包。

输出 report.json 与 proposed.list。报告逐个列出 keep/replace/review 与替代包的可用性；
配置部分只包含文件名、section 类型和 option 名，不含值。
退出码2表示存在未解决映射，退出码1表示输入错误，退出码0也仍需人工确认语义。
脚本不改动正式 Profile，不拷贝旧 UCI 到固件。

ddns-scripts/luci-app-ddns 已提供 ddns-go 替代建议；不是兼容旧配置的原位升级。
旧内核模块需按新硬件与内核重新选择；18.06 的 iptables、firewall、swconfig 配置不能直接映射到 nftables/DSA。
代理客户端、订阅格式、分流规则和 LuCI 页面须在拿到旧包清单后逐项保留或提供确认的替代方案。
旧源已不存在的包，保留 unresolved 直到替代方案获确认，禁止静默忽略。

每个目标单独审阅 proposals，再将确认的应用包纳入独立 list，并给 Profile 添加引用。
运行 defconfig 验证后还要核对实际产物 Manifest 和设备服务功能，才算完成迁移。

## 当前迁移基线（2026-11-06）

用户确认下载目录和 smb 项目里的文件是旧备份。现已通过用户指定的现役 x86 只读 SSH
采集当前680个安装包和80个配置文件；原始数据在 private/x86-current-20261105/，
以 snapshot.json 的实际 UTC 时间为准。11项采集产物已校验，完整归档仅在私有目录安全解包。
旧文件只作历史参考，不作为生产配置。当前较旧包清单新增 tailscale。

公开的 [current-plugin-plan.json](../migration/current-plugin-plan.json) 只保存包名和兼容性状态，
没有配置值。66个 LuCI 应用/协议/主题中，原先缺少方案的21项已有11项落实替代或本地页面，尚余10项；
已有方案的56项已显式加入 x86-ha，仍需当前目标配置解析、编译和功能检查。
全包的私有迁移报告还包含旧依赖、旧内核模块等待核对项，
不能把这些数目当成已完成保留的插件数。不要将所有旧ABI库直接装入新系统。

计划另列 `profile_request_coverage`，区分已有定义和实际构建请求。
当前 x86-ha 显式请求56项插件映射，已有定义却未显式请求的条目为0，另有10项无确定方案。
最终必须检查 Manifest 并验收功能，不能把56项构建请求理解成56项已完成迁移。
新增的 Profile 专用 Feed 补丁处理 OpenVPN 配置所有权、VPN 默认脚本及主题注册，见下文。


配置目录中的 .bak、.new、.clear 等文件是历史副本，不能作为当前 UCI 设置自动应用。
最新配置包含多个 VLAN 和多 WAN；HA 多 VIP 支持已预留，实际管理地址、心跳口、
备用机 VLAN 映射和拨号策略仍待确定。没有把任何现网配置或凭据复制进固件覆盖层。
R619AC 当前不可访问，硬件与运行功能尚未验证。

## 已落实到选择清单的组件

| 旧插件/组件 | 当前选择 | 迁移边界 |
| --- | --- | --- |
| luci-app-filetransfer | luci-app-filemanager | 提供上传/下载；使用新版页面，权限按该管理器的上游实现 |
| luci-app-wireguard | luci-proto-wireguard + kmod-wireguard | 协议包自带配置、Peer 状态、菜单和 RPC；私钥只在设备本地配置 |
| luci-proto-bonding | luci-mod-network + kmod-bonding | 新版将 bonding 作为设备类型；旧 proto=bonding 须转换，不能原样恢复 |
| luci-app-ntpc / ntpclient | BusyBox sysntpd + luci-mod-system | 使用系统时间同步页面，保留 NTPD；原候选服务器需转到 system.ntp，频率/漂移字段不直接复制 |
| luci-app-socat | 本仓库维护的 luci-app-socat + 官方 socat | 原 enable/SocatOptions/user 字段保留；页面同时支持字符串与 UCI list 参数，不覆盖官方配置/init |
| luci-app-pptp-server | 本仓库维护的页面 + 官方 pptpd + Feed 补丁 | 保留 service/login、地址池、MPPE、logwtmp、remotedns；默认无账号/地址且关闭 |
| luci-app-accesscontrol | 官方 luci-app-firewall 的 Traffic Rules / Time Restrictions | 使用 src_mac、weekdays、start_time、stop_time；不自动导入或启用规则，须核对时区和链顺序 |
| luci-app-wrtbwmon | 本地只读流量页面 + 官方 nlbwmon | 保留按设备查看累计值、IPv4/IPv6、筛选/排序和采样速率；旧数据库格式不能直接恢复 |
| luci-app-v2ray-server | 本地 UI + neko-v2ray-server + 官方 v2ray-core 5.53.0 | 保留 global/user 配置结构；显式选择监听地址，不自动写防火墙；未知启用字段报错 |
| tailscale | tailscale | 当前实时清单中存在，已加入 x86-ha；不把节点身份复制进镜像或另一台设备 |

这些是构建选择与源码实现，不是实机功能验收。`x86-ha` 引用独立
[组件清单](../packages/x86-retained.list)；R619AC 保持基本服务范围。
两种 HA Profile 都选择 [代理包清单](../packages/proxy.list)，包含官方 HomeProxy/Sing-box、
中文 UI、dnsmasq-full 和 nftset 支持，但 **SSR Plus 仍标记 review**：
节点协议、WS/gRPC、TLS/REALITY、订阅、GFW 分流、旁路规则与服务端功能必须逐项迁移和测试。
不把旧 shadowsocksr 配置直接当作 HomeProxy 配置，也不将原配置嵌入镜像。
在开启 HA 前先完成代理本地配置；只把 homeproxy 交给 HA，不同时开启独立 sing-box init 实例。
R619AC 的压缩镜像大小、内存峰值和吞吐尚待实际编译与测试。

依据是已锁定的官方源文件，路径与 SHA256 见
[source-evidence.json](../migration/source-evidence.json)。本地 Socat 表单的往返测试执行真实 JS，
覆盖旧字符串、含空格的逐项参数和格式切换；未在真实 LuCI 浏览器/设备上验收。

公开计划可以由私有安装清单重新生成，脚本只读取包名，不读取 UCI 配置：

```sh
python3 scripts/migration_plan.py \
  --installed private/x86-current-20261105/packages-installed.txt \
  --metadata .work-config-audit/evidence/packageinfo.gz
```

计划区分包定义、本地移植、Profile 显式选择与未解决条目；生成器不会将这些证据标为
运行功能已保留。即使某项有替代包，仍须通过目标 defconfig、构建 Manifest 和实机验收。

## 已有官方插件的安装行为

`x86-ha` 的独立清单包含56项映射对应的软件包及可用中文翻译，根分区扩为2048MiB。
下载、容器、共享、代理转发等额外服务在首次安装时禁用自动启动；应用设置仍需在设备本地迁移。
列表位于 `files/x86-ha/etc/firmware-ha/retained-services`，不关闭网络、防火墙、管理服务或系统时间同步。
初始化标记已存在的保留配置升级不重新改变服务启动标记。R619AC 不安装这些额外应用。

OpenVPN 服务端 UI 不再打包后端拥有的 `/etc/config/openvpn`；只在缺少 myvpn 时建立禁用的服务器节，
不预设地址池、外部域名或防火墙规则，也不在首次启动生成证书。用户主动创建 PKI 前会保存旧材料，
此操作会创建新 CA，现有客户端需要重新导入配置。导出先验证端点/协议/端口和文件，
以600权限生成客户端配置，下载后删除临时副本；实际证书生成和 VPN 连接仍待目标验收。
IPsec 默认关闭，无预设账号、共享密钥或地址，也不自动写网络/防火墙。
这些变更应用于源代码，不把本地页面与上游后端的配置文件重复打包。

Argon 和 Material 保留主题注册，移除自动切换 mediaurlbase 的默认动作，主题视觉资源未修改。
SyncDial 的生成器、两个 hotplug 入口和重拨按钮在执行网络动作前检查 PPPoE 会话策略；默认 single 会拒绝多拨和结束 PPP 进程。
若旧配置已经启用 SyncDial，HA 预检会要求先关闭，避免破坏运营商单会话限制。

上述测试对固定源的真实补丁执行临时目录应用、准备钩子、UCI 模拟与 Shell/Lua 解析，
不等同于软件包编译、LuCI 运行或真实网络服务验收。

## 访问时间控制和设备流量

锁定的 [firewall4 规则模板](https://github.com/openwrt/firewall4/blob/b6e5157527d361f99ad52eaa6da273cb0f2dfd59/root/usr/share/firewall4/templates/rule.uc)
支持 MAC、星期和起止时间匹配，官方 Firewall / Traffic Rules 页面已有相应编辑项。
访问控制方案复用这些入口，不添加第二套防火墙服务，也不写入示例 MAC、接口或时段。
迁移现有规则时要验证实际时区、跨午夜边界、IPv4/IPv6、已建立连接及 flow offload 路径，
页面上的选项存在不能证明既有连接会立刻断开。

本地 `luci-app-wrtbwmon` 复用锁定的 [nlbwmon](https://github.com/jow-/nlbwmon) 及官方查询包装脚本，
按同一 MAC 汇总多个 IPv4/IPv6 地址；未解析到 MAC 的不同地址保持独立。
页面只允许固定的统计查询命令和主机提示读取，不允许配置写入、启动服务或数据库重置。
采样间隔不短于配置中的后端刷新间隔；速率为两个已观察计数的平均差值，
首次采样、计数下降、设备重新出现或读取失败后重新建立基线，不把历史总量当作当前速率。
无法识别刷新间隔时仍显示累计值，停用速率显示。修改后端设置后需重新打开页面。

旧 wrtbwmon 的 `persist` 和数据库不能直接当成 nlbwmon 配置或数据库。
需要另行保存旧数据；新统计使用 nlbwmon 的统计周期、监测网段和数据库目录。
默认 `/var/lib/nlbwmon` 可能位于临时存储，重启后持久化需要在设备本地选择真实存储目录，
本工程不猜测磁盘挂载点。还须核对代理、硬件卸载及双机切换时的计数覆盖，尚无跨节点统计同步。

IPTV 助手仍未解决：[原项目](https://github.com/riverscn/openwrt-iptvhelper) 包含机顶盒连接目标学习、
用于策略路由的集合维护和 DNS 重定向；omcproxy / udpxy 不能单独替代这些功能。
MWAN3 Helper 的运营商地址集合与特殊域名 DNS 分流也不能只用 MWAN3 页面代替；这两项继续标记 review。

## Server酱通知迁移

`x86-ha` 选择固定官方 LuCI Feed 中的 `luci-app-wechatpush` 3.6.12 及中文翻译。
其页面和脚本包含 Server酱、IPv4/IPv6 变动、设备上下线、CPU负载/温度和定时通知入口，
源码及补丁哈希见 [source-evidence.json](../migration/source-evidence.json)。R619AC 基本配置不包含此额外服务。
现役快照只有一个 `serverchan` 节、8个字段，且 `serverchan_enable=0`；本工程没有导入配置或发送通知。

旧配置在设备本地按下表迁移，通知渠道、凭据、监听网段、探测接口及温度阈值须另行确认。

| 旧字段 | 新设置 |
| --- | --- |
| serverchan_enable | wechatpush.config.enable；默认保持关闭 |
| sleeptime | sleeptime |
| serverchan_ipv6 | 重新选择 get_ipv6_mode 及接口，不沿用旧枚举 |
| serverchan_up / serverchan_down | device_notification 的 online / offline |
| cpuload_enable / cpuload | cpu_notification 的 load / cpu_load_threshold |
| temperature_enable | cpu_notification 的 temp，并设置实际阈值 |

首次安装禁用自启，保留配置升级尊重初始化标记。补丁先校验启用值，只有1才创建 procd 实例；
若被列为 HA 受管服务，启动入口同样检查角色及接管阶段。配置及 JSON 结果的变量读取改用
Bash `printf -v` 并校验变量名，保留引号、换行及命令文本，不将这些值再次作为 Shell 源码求值。
自定义 API 和其他高级功能继续沿用上游实现；这不是整个通知脚本的安全或功能验收。
同一补丁移除固定源中文 PO 的7组重复消息，保留首条等价翻译，修复 `msgfmt` 的重复定义错误。

上游内置流量通知依赖旧 wrtbwmon，在锁定 Makefile 中标记为 BROKEN，本工程不启用。
独立 nlbwmon 流量页面不能替代该通知链路；当前8字段旧配置也没有对应设置。
离线测试覆盖补丁应用、配置读取和 procd 启动入口，不运行推送循环、不联系服务商。
当前目标编译、真实 LuCI、服务商认证/送达、阈值/延迟、登录防护规则、子进程停止及 HA 行为仍待验收。

## Turbo ACC 加速配置迁移

`x86-ha` 使用本地 `luci-app-turboacc` 中文页面，组合官方 firewall4、内核 BBR 与 DNSProxy 0.83.0。
页面本身不拥有后端配置或 init；BBR 的 `turboacc` 配置和服务由独立 `neko-bbr` 包拥有，
DNSProxy 继续使用官方配置、procd 用户及 jail。R619AC 基本配置不加入这些额外依赖。

现役快照中 Turbo ACC 的软件/硬件卸载标志均为1，firewall 对应值却均为0；
两处 FullCone 旧值均为2。这些只是配置值，没有据此判断实时内核状态。
新页面分别显示旧参考值与实际防火墙配置，“保持当前设置”不写入防火墙；
仅明确选择策略时写入新的卸载标志及 FullCone 布尔值，不把旧高性能模式2自动转换成1。
SFE 功能由 nftables 流量卸载承担，性能和兼容性需重新验收；MediaTek WED 不适用于这两个目标。
开启卸载后必须核对实际驱动支持、SQM、代理分流、流量统计和 NAT 行为。

BBR 默认关闭，x86-ha 补丁移除了模块安装时强制选择 BBR 的 sysctl。
显式启用时确认模块已注册 BBR，锁定操作并以700/600权限记录运行目录与原算法；
关闭时仅在当前仍为受管 BBR 时恢复原值，已手动改为其他算法则保留手动选择。
原算法暂不可用时返回错误并保留恢复记录，不猜测 cubic。
原算法若已经是 BBR，关闭管理后仍会恢复为 BBR。记录位于易失运行目录，重启后从本次启动的当前算法重新记录。
按 [Linux 内核说明](https://www.kernel.org/doc/html/latest/networking/ip-sysctl.html)，
默认拥塞算法作用于本机新建 TCP 连接；转发客户端使用自身协议栈的算法。
页面中的内核算法是加载页面时的只读快照，应用配置后需重新加载查看。

DNSProxy 默认关闭，移除了预设公共上游和安装时全局提高 UDP 缓冲区上限的动作。
启用前必须配置至少一个上游；补丁保留 URL 中的空格及通配字符为单个参数，布尔开关不附加空参数。
监听、上游、引导解析、备用服务器、缓存及错误响应过滤可在页面配置，
加密域名上游需要核对引导解析，避免循环依赖。DHCP/DNS 的转发实例在设备本地另行配置，页面不自动改写它们。
首次安装关闭 DNSProxy 自启；保留配置升级尊重初始化标记。
如将其加入 HA 的 service 列表，官方服务的启动入口也检查当前接管阶段；R619AC 如需此服务须另外安装并配置。

固定源补丁应用、实际配置帮助函数、模拟 sysctl/procd 与页面保存测试在临时目录运行。
当前目标 defconfig/编译、真实 LuCI、内核与 DNS 核心、NAT/卸载、加密解析和吞吐验收仍待执行。

## V2Ray Server 页面与适配层

`x86-ha` 选择本地 `luci-app-v2ray-server`、独立 `neko-v2ray-server` 后端及锁定的官方
V2Ray 5.53.0。UI 仅拥有页面、UCI ACL 和自身 reload 注册；后端拥有 `v2ray_server` 配置及 init，
不覆盖官方通用服务的 `/etc/config/v2ray` 或 `/etc/init.d/v2ray`。
Python 仅在生成配置时运行，代理进程由官方核心承担；R619AC 基本配置不加入这些依赖。

保留旧 `global` / `user` 结构及已核对的字段。提供 Shadowsocks、VMess、VLESS、Trojan、SOCKS、HTTP
配置入口和 TCP、WebSocket、HTTP/2、KCP、QUIC、gRPC 传输设置，TLS 引用设备本地的证书文件。
禁用条目和当前协议未使用的字段在页面中保留。启用条目的未知字段、未支持的旧加密方式或
Xray 专有设置会报错，须单独迁移，不能直接把 REALITY/XTLS 设置用于此后端。
现有快照的一个 user 条目处于禁用状态，本地解析审计保持其禁用；没有启动或修改路由器服务。

首次安装默认关闭，未预设监听地址、用户或凭据。启用条目须选择监听 IP；
`bind_local=1` 限制为回环地址并保留隐藏的原监听字段。通用 V2Ray 服务开启时，适配层拒绝同时启动。
防火墙端口与接口在设备本地单独配置。`accept_lan` 控制核心的私有地址路由规则，
实际网段、防火墙隔离及 DNS 解析路径仍需核对。渲染器按 UCI 引用及数据类型生成 JSON，
不把值拼成 Shell 命令；运行目录权限700、配置权限600，原子写入后执行核心配置校验，
成功才向 procd 注册进程。核心校验的原始输出不写入公共日志。

14项后端/进程流程模拟测试和实际JS表单测试已通过，覆盖六种协议/传输的数据结构、
UCI 引号/多行值、凭据转义、监听冲突、TLS 文件引用、配置权限及失败不启动。
这些测试中的核心和 procd 是模拟接口。另提供真实核心校验入口：

```sh
python3 tests/integration/v2ray_generated.py --core /path/to/v2ray
```

它要求同版本核心，用临时测试证书验证12份生成配置和1份应拒绝的配置。
本机的核心下载因 proxy.golang.org 的 DNS 查询失败而中止，此项未运行。
目标编译、真实 LuCI、协议握手、认证、TCP/UDP 流量、私有地址规则及代理服务端 HA 均待验收。
R619AC 基本配置不含此服务；若需双机接管，要在两端另行安装、配置并纳入 HA 的 service 列表。

## PPTP 页面与后端兼容

`x86-ha` 选择本地 PPTP 页面和中文翻译；R619AC 基本配置不加入 PPTP。
页面沿用 `/etc/config/pptpd` 的 `service` / `login` 字段，隐藏的禁用项保留原值，
凭据控件遮蔽显示；只有用户在设备本地填写地址、账号和防火墙规则后才启用。
不为镜像内置示例账号、服务地址或客户端地址池。上游包仍拥有配置/init 文件，
补丁更改其安装模板，避免与 UI 包争用同名文件。

后端兼容补丁把旧 `remotedns` 值转换为 PPP 的 `ms-dns` 选项；
生成 CHAP 条目时正确引用空格、引号和反斜杠，拒绝控制字符。
重载先在临时文件生成新条目，再原子替换；仅移除 PPTP 服务器条目，保留其他 PPP 协议行，
生成文件权限600。规则依据 [pppd 官方手册](https://ppp.samba.org/pppd.html)。
这些构造/解析测试不等同于真实 PPP 身份认证、GRE/NAT 转发或客户端兼容测试。

若需让 PPTP 随 HA 接管，须在两端安装并完成配置，再明确加入 HA 的 service 列表；
当前 R619AC 基本 Profile 不包含它，因此不能宣称 PPTP 已具备双机接管能力。

## 驱动与服务文件补充清单

已根据实时安装清单为 x86-ha 独立选择27项网卡、USB及存储模块名，见
[驱动计划](../migration/driver-plan.json)。它们按锁定源的新内核重新编译，不复制旧 .ko，
也不应用到 R619AC。现役设备具体使用哪个模块、MMC/SDHCI 是否承担启动盘、全部硬件是否可用，
仍需驱动绑定信息和启动验证，不能仅凭安装清单推断。

`/etc/config` 归档不包含所有 VPN 证书、私钥、节点身份或应用数据。
采集器新增可选的元数据补充命令：

```sh
python3 scripts/collect_device.py --host root@YOUR_ROUTER \
  --output private/device-with-extra-inventory --extra-inventory
```

它只记录网卡驱动路径以及固定服务目录下的文件名和目录类型，不读取证书/身份内容、
不跟随符号链接、不打包数据，也不扫描全部磁盘。路径清单本身仍留在权限受限的 private/。
证书引用、目录链接、目录外自定义路径和需要迁移的身份材料须逐项核对；
ZeroTier/Tailscale 等身份不得在两台设备间直接克隆。
本次补充 SSH 尝试被执行环境以 Operation not permitted 拒绝，状态记录为 failed；
没有把它当成新快照或完整服务数据备份。
