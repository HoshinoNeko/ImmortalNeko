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

`election_device` 可以选 LAN 设备，也可以是独立 1G 心跳接口；VIP 始终挂在 `lan_device`。
心跳 IP 和所需防火墙规则由部署配置单独建立，不由控制包猜测。
VRRP 是 IP 协议 **112**，不是 TCP/UDP 端口；在正确防火墙区域只允许指定对端。
管理 IP、VIP 与 WAN 防火墙/NAT 关系均需核实，不要将上游拨号口直接桥入 LAN。

只有两个节点、单根独立心跳线时，断线与对端故障不能可靠区分：可能双主，或因
keepalived 接口故障两端均退到 FAULT。特别是直连心跳口随主机断电失去 carrier，不能假设还能接管。
生产部署建议 VRRP 走公共 LAN，专用端口接管理/监控；若必须将其用于独立选举，
需要冗余链路或外部仲裁/隔离机制并实际测试。此版本不声称能在任意网络分区下避免双主。

## 两种外网策略

`warm`：两端可同时保持自身外网，例如运营商确认允许双会话或各有不同上联。
备用机保持 WAN，只有本机 WAN 已拨通并能从其 WAN L3 接口探测成功才参与竞选。
x86 连续恢复检查通过后，等待 preempt_delay 再抢占。`ping -I 本机WAN` 防止误把经备用机转发当作自身恢复。

`cold-pppoe`：共享单会话 PPPoE 账号，仅 MASTER 执行 ifup。BACKUP/FAULT/STOP
执行 ifdown 并停止受管服务。启用前必须在两端本地配置 PPPoE 凭据，并显式设 `network.<wan>.auto=0`；
控制器会验证这些条件，但不写入账号，也不改变 WAN 物理/VLAN 定义。
WAN6 或绑定 WAN 的隧道接口不能自行触发拨号，需按真实配置禁用其自动启动并随主机管理。

单会话下，备用 x86 无法在不接管拨号的前提下证明自己的 PPPoE 已恢复。
本实现使用有冷却时间的接管试探：物理链路正常、冷却到期后允许高优先级 x86 抢占；
允许 acquire_grace（默认 90 秒）等待旧会话释放/新拨号；失败则退让，退避从 300 秒翻倍至 3600 秒。
这会产生周期性恢复试探和短暂中断；不能宣传为无中断自动回切。
若要求仅在证明拨号成功后回切，须运营商双拨能力或增加可协调的外部拨号/仲裁设备。

## 角色和服务

两个节点以 state BACKUP 启动，优先级 primary=200、backup=100，未设置 nopreempt。
健康脚本 weight=0，失败直接进入 FAULT；连续失败3次、连续恢复5次、检测间隔2秒，
再叠加 VRRP 选举时间与默认30秒抢占延迟。接管拨号最多额外等待 acquire_grace。
实际延迟需在设备、交换机和运营商环境测量。

MASTER 启动 dnsmasq、odhcpd、OpenVPN、ddns-go、ZeroTier、frpc；BACKUP 停止这些服务。
两端都须先配好对应服务并在首次启动后明确授权交由 HA 管理。控制器将禁用这些服务的自主开机启动。
部分 OpenWrt init 脚本即使没有启动进程也返回0，配置错误未必由返回码暴露，必须检查实际进程与功能。
WireGuard 由 netifd 管理；用 list managed_interface 在本地指定需要随角色启停的隧道接口。
控制器只接受 proto=wireguard 的接口，须同时关闭这些接口的自动启动，避免备用机独立拉起。
默认列表为空，不猜测或停止 LAN/WAN 等其他接口。

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
4. cold 模式设置 WAN `auto=0`，确认无其他接口或热插拔脚本会触发拨号；warm 模式先单独确认两端外网。
5. 保持 `enabled=0`，审阅配置；确认好后本地设置为1，运行 `/etc/init.d/firmware-ha start`。
6. 启动前自动执行 keepalived --config-test；失败保持报错，不忽略。
7. 通过 `firmware-ha-status`、`logread -e firmware-ha`、`ip address`、服务进程和客户端测试核对状态。
8. 先演练接管/回切，验收后再 `/etc/init.d/firmware-ha enable`。

`/tmp/firmware-ha/inhibit` 存在时本机不参与竞选。受管服务启停失败会设置该标志，
需要排查日志并修复后在本地清除，不能无条件循环重启。HA 停止后不会自动把所有服务恢复自主启动；
退回单机需明确选择节点、停掉对端 HA，恢复 WAN auto 和需要的服务 enable，避免两台同时服务。

现网开箱即用配置仍需用户的真实接线与服务设置，且必须通过 [验证计划](validation.md)。
