# HA 部署与故障语义

本包由本仓库维护。它单独由 procd 启动 keepalived，显式关闭官方 keepalived init 实例，
避免同时有两个 VRRP 进程。读取 `/etc/config/firmware-ha`，运行配置只生成在 `/tmp/firmware-ha`。
没有 LAN/WAN、心跳地址或拨号密码的硬编码默认值，固件初次启动不启用 HA。

## 部署前必须确定的参数

两个节点须连接相同 LAN 广播域和可接管的上联。需要记录各自管理 IP、客户网关 VIP、
LAN 设备名、WAN netifd 接口名、WAN 物理设备名，以及 VRRP 发送源/对端 IP。
管理 IP 必须彼此不同且不同于 VIP，VIP 不得被现有网关或 DHCP 分配占用。
DHCP 应向客户发布 VIP 作为网关和 DNS；两端使用一致的租约策略。
IPv6 RA、前缀委派、静态路由、IPv6 防火墙须在真实配置下单独验证；这里只实现 IPv4 VIP。

## WAN DHCP 与专用心跳双路径

用户已确认运营商只允许一个 PPPoE 会话；新配置默认 `cold-pppoe`、
`pppoe_sessions=single`、`peer_mode=dual-path`，仍保持 `enabled=0`。
SyncDial 可保留配置页面，但默认单会话策略会拦截其多拨生成器、hotplug 入口及重拨按钮。
若迁移的旧设置已启用 SyncDial，HA 启动预检会报错，须先在设备本地关闭它。
同一 WAN 底层设备上另外配置 `wan_monitor_interface`，协议 DHCP，地址在
192.168.1.0/24；上游须为两台设备保留不同租约。设置 `auto=1`、`defaultroute=0`、
`peerdns=0`，使备用机也能保持监测网络，而不改变客户默认路由或触发拨号。
专用心跳口使用另一对静态地址；它不能与 LAN/WAN 共用 Linux 设备。
两端地址与端口名称尚未确定，模板保留空白，不自动修改现网。

每台还需在 lo 上预先配置一个独立、无冲突的静态 /32 控制地址，分别填入
`election_source`、`election_peer`，并设 `election_device=lo`。
它们仅作为稳定的 VRRP 端点，不是客户网关或 WAN DHCP 地址。
监测进程每轮并行探测 WAN DHCP 对端和心跳对端，优先使用专用心跳，保持当前可用路径，
路径失效时更新到控制对端的 /32 主机路由。两条路径都失效时安装 blackhole 主机路由，
阻止控制流量落入默认路由。只管理专用对端路由，协议标记为 186；不能占用已有主机路由。

只有一个 VRRP 实例和一组 VIP。其单播源/目的始终是两端的稳定 /32 地址，
不把实例绑定到某一个物理口；所有 VIP 显式指定设备。
因此正常运行时，任一条监测路径中断，另一条仍能承载同一次选举。
`down_timer_adverts=10` 给路径切换留出时间，两端必须一致；监测器死亡或状态超过6秒未更新时，
健康检查撤销本机资格。实际时序及抖动仍需 Linux/实机验证。
这种不绑定接口的单播方式及计时参数见
[keepalived 2.3.3 手册](https://raw.githubusercontent.com/acassen/keepalived/v2.3.3/doc/man/man5/keepalived.conf.5.in)。

两条路径均须允许对端 ICMP Echo、专用 SSH 状态查询，以及源/目的为控制 /32 地址的
IP 协议 **112**（VRRP，不是 TCP/UDP 端口）。防火墙只放行实际对端与对应输入接口，
不要向公网开放整个 WAN 管理区域。输入接口应使用 loose rp_filter=2 或禁用严格反向路径过滤；
启动检查会拒绝严格模式，不会自动放宽现网防火墙/sysctl。
WAN 的 masquerade/SNAT 还必须排除本机控制 /32 地址的 VRRP 流量，确保线上报文仍保持
`election_source -> election_peer`；否则对端源地址校验会丢弃它。只增加针对控制地址的例外，
保留客户上网所需 NAT，并抓包验证两条路径的实际源/目的地址。
监测地址、控制地址和 VIP 必须彼此不同；WAN 不得直接桥接进客户 LAN。

旧配置没有 `peer_mode` 时保留原单路径行为以便迁移；本次双路径与释放确认只在
`peer_mode=dual-path` 启用。部署本方案必须补齐新参数后重新验证，不可沿用旧单路径配置验收。

## 两种外网策略

`warm`：两端可同时保持自身外网，例如运营商确认允许双会话或各有不同上联。
备用机保持 WAN，只有本机 WAN 已拨通并能从其 WAN L3 接口探测成功才参与竞选。
x86 连续恢复检查通过后，等待 preempt_delay 再抢占。`ping -I 本机WAN` 防止误把经备用机转发当作自身恢复。

`cold-pppoe`：共享单会话 PPPoE 账号，仅 MASTER 执行 ifup。BACKUP/FAULT/STOP
执行 ifdown 并停止受管服务。启用前必须在两端本地配置 PPPoE 凭据，并显式设 `network.<wan>.auto=0`；
控制器会验证这些条件，但不写入账号，也不改变 WAN 物理/VLAN 定义。
WAN6 或绑定 WAN 的隧道接口不能自行触发拨号，需按真实配置禁用其自动启动并随主机管理。

单会话下，新 MASTER 在拨号前会通过两条路径查询对端：只有已退到 BACKUP/FAULT/STOP、
完成角色清理、PPPoE `up=false` 且 `pending=false` 时，对端才报告 `HA1 RELEASED`。
任一路报告 BUSY/UNKNOWN 均阻止拨号；认证、身份校验或状态查询失败而监测链路仍通时也不允许接管。
等待默认最多30秒，获得释放确认后再等3秒；等待中失去本机 VIP 就取消拨号。
这包含 x86 恢复后的延迟抢占：旧备用机先释放 PPPoE，x86 再重拨。
超时不拨号，退避从300秒翻倍至3600秒；此类可恢复失败不会让事件处理器永久 inhibit。拨通后的外网探测宽限仍为90秒。

`unreachable_takeover=1` 允许两条路径连续至少3轮探测失败、两路状态查询也无响应时接管，
用于对端断电；接管延迟期间若链路返回会撤销该判断。
**两节点无法仅凭失联证明对端已停拨**：同时隔离两条链路而旧主仍在线时仍可能双主和抢拨。
必须通过断电、双线断开、过滤 ICMP、单向隔离演练验证此策略。
若必须在任意分区下严格禁止并发拨号，设 `unreachable_takeover=0`，代价是失联时不自动拨号；
完整可用性与强制单会话保证需增加外部仲裁/可靠的设备隔离。

冷备在不接管的情况下不能证明自己的 PPPoE 已恢复。因此 x86 自动回切仍可能带来短暂中断；
不能宣传无中断或连接状态无损。以上只控制本包管理的拨号；外部手工拨号、WAN6/热插拔触发
必须在部署时排除。

## 对端状态查询的本地身份配置

两端分别在设备本地生成专用客户端身份，不能把身份材料提交进仓库或覆盖层：

```sh
umask 077
mkdir -p /etc/firmware-ha
ssh-keygen -t ed25519 -N '' -C firmware-ha-peer -f /etc/firmware-ha/peer_client
```

通过可信的本地会话核对对端主机指纹，把对端主机公钥保存为
`/etc/firmware-ha/peer_known_hosts` 中的 `firmware-ha-peer <公钥类型> <公钥内容>`。
不要盲目信任网络扫描结果，不复用客户端私有身份。SSH 默认端口22，可通过 peer_status_port 改变。
将本机的 peer_client.pub 放入对端 Dropbear authorized_keys，并为这一行加以下限制前缀：

```text
no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty,command="/usr/libexec/firmware-ha/peer-status.sh" <客户端公钥类型> <客户端公钥内容>
```

先在隔离环境验证两条路径上的 `firmware-ha-status-v1` 查询。强制命令只接受该协议，
只返回 RELEASED/BUSY/UNKNOWN，不返回配置值或执行传入命令。
两端均需配置身份、可信主机记录和强制命令；缺少本地身份会拒绝启动/拨号。
将 `/etc/firmware-ha/` 加入本地 sysupgrade 保留清单，备份按敏感资料管理；它不属于固件构建输入。

## 角色和服务

两个节点以 state BACKUP 启动，优先级 primary=200、backup=100，未设置 nopreempt。
健康脚本 weight=0，失败直接进入 FAULT；连续失败3次、连续恢复5次、检测间隔2秒，
再叠加 VRRP 选举时间与默认30秒抢占延迟。双路径选举超时10秒，拨号前另有释放确认等待。
实际延迟需在设备、交换机和运营商环境测量。

MASTER 启动 dnsmasq、odhcpd、OpenVPN、ddns-go、ZeroTier、frpc、HomeProxy；BACKUP 停止这些服务。
两端都须先配好对应服务并在首次启动后明确授权交由 HA 管理。控制器将禁用这些服务的自主开机启动。
部分 OpenWrt init 脚本即使没有启动进程也返回0，配置错误未必由返回码暴露，必须检查实际进程与功能。
WireGuard 由 netifd 管理；用 list managed_interface 在本地指定需要随角色启停的隧道接口。
控制器只接受 proto=wireguard 的接口，须同时关闭这些接口的自动启动，避免备用机独立拉起。
默认列表为空，不猜测或停止 LAN/WAN 等其他接口。

HomeProxy 的上游停止脚本会重启 dnsmasq，因此不能只按原服务顺序停止。
本工程先停止代理/其他服务及受管接口，最后停止 dnsmasq、odhcpd。
主树和 LuCI Feed 补丁为 dnsmasq、odhcpd、HomeProxy 加入启动角色检查：只有列入 HA 受管列表、
本机为 MASTER、持有 VIP、事件处理器存活且 phase=active 时，才允许受管服务启动。
接管等待使用 acquiring、停止/失败清理使用 releasing，防止取得 PPPoE 之前或清理过程中
被代理脚本/热插拔重新拉起 DHCP。未启用且没有生效快照的普通单机保留上游行为。
HomeProxy 补丁还使不存在 TUN 设备时的清理返回成功，并在首次停止时建立日志目录；
真实删除失败仍会报错。补丁先核对固定源再应用，不覆盖已安装包的同名文件。

代理节点、DNS 与分流必须预先在两台设备本地配置并验证。HA 控制的是 homeproxy 服务；
不要另行启动 sing-box init，也要让监测/心跳/SSH 对端地址直接走本地链路，避免被代理策略截获。
新版代理目前是基础能力候选，不能视为已经完成 SSR Plus 配置和全部功能的迁移。


HA 并不复制进程/连接状态：PPPoE 公网 IP 可能改变，NAT/TCP 会话、VPN 会话、ZeroTier 路由
和 FRP 连接可能中断并重建。不要复制相同 ZeroTier identity 或 WireGuard 私钥到两台设备。
DDNS 更新为新公网地址后的 TTL 传播也不是瞬时完成。
DHCP 租约同步尚未实现，需按现网决定静态租约或经认证的同步方式；否则应测试切换后的地址冲突。


## 多 VLAN 与有序事件

主 VIP 使用 vip 和 lan_device；额外网关使用显式的 `list extra_vip 'IPv4/prefix@设备名'`。
默认额外列表为空，不导入或猜测现网地址。所有网关在同一 VRRP 实例内共同接管，
对应 Linux 接口都会加入链路检查。重复地址、非法设备名和配置片段注入会被拒绝。
这为现有多个 VLAN 保留了迁移入口；R619AC 的 VLAN/DSA 端口关系仍需按实际硬件确认。

角色事件使用 keepalived 原生 vrrp_notify_fifo，由一个进程顺序执行。
服务启动较慢时收到 BACKUP，退让事件会留在队列中处理；不再依赖多个并发通知脚本争用锁。
健康检查同时要求事件处理进程存活，退出时执行清理；原生 shutdown_script 提供额外的停止清理。
procd 为正常退出预留45秒；这不是服务故障或网络分区的无中断保证。

启动时把通过验证的 UCI 设置保存到权限受限的运行目录。后续即使 enabled 已关闭、
服务列表或 WAN 名字被修改，停止过程也按旧的生效设置释放拨号与服务。
停止某个服务报错时仍继续清理其他服务及受管接口，并设置 inhibit、报告错误。
不要同时手工执行多份角色处理脚本；并发手工调用会明确失败。

官方 FIFO 行为见 [keepalived 配置手册](https://raw.githubusercontent.com/acassen/keepalived/v2.3.3/doc/man/man5/keepalived.conf.5.in)。
以上脚本行为已进行模拟回归；真实 Linux 事件与多网段切换仍须通过集成和实机测试。

## 本地启用顺序

1. 核对两端型号、固件校验和；备份旧配置，先在隔离环境启动。
2. 为两个节点配置不同管理地址和统一 VIP 网关方案；逐项迁移网络/防火墙/服务。
3. 在两端填写 `/etc/config/firmware-ha`。role 分别 primary/backup，probe 使用2至3个你认可且可 ICMP 探测的 IPv4 地址。
4. cold 模式设置 WAN `auto=0`；为同一底层口建立独立 DHCP 监测接口并保留租约，配置心跳、lo /32、防火墙、rp_filter 和两端查询身份；确认没有其他触发拨号的接口。
5. 保持 `enabled=0`，审阅配置；确认好后本地设置为1，运行 `/etc/init.d/firmware-ha start`。
6. 启动前自动执行只读前置检查和 keepalived --config-test；失败保持报错。不要在生产机跳过隔离演练。
7. 通过 `firmware-ha-status`、`logread -e firmware-ha`、`ip address`、服务进程和客户端测试核对状态。
8. 先演练接管/回切，验收后再 `/etc/init.d/firmware-ha enable`。

`/tmp/firmware-ha/inhibit` 存在时本机不参与竞选。受管服务启停失败会设置该标志，
需要排查日志并修复后在本地清除，不能无条件循环重启。HA 停止后不会自动把所有服务恢复自主启动；
退回单机需明确选择节点、停掉对端 HA，确认 keepalived 和事件处理器完全退出后，仅在选定的单机节点移除
`/tmp/firmware-ha/config/firmware-ha` 生效快照，再恢复 WAN auto 和需要的服务 enable，避免两台同时服务。
快照保留期间，角色保护会继续拒绝备用/停止节点的受管服务启动。

现网开箱即用配置仍需用户的真实接线与服务设置，且必须通过 [验证计划](validation.md)。
