# 宿舍与家庭的二层 VPN

`r619ac-basic`、`r619ac-ha` 和 `x86-ha` 共用 `packages/l2-vpn.list`。
宿舍 basic 版包含 LuCI 中文、WireGuard、L2TPv3 Ethernet、VXLAN、完整 ip/bridge 工具和 Xray 26.3.27；
HA 控制器、keepalived 及家里的附加服务仍由 HA Profile 选择；本维护分支的四个 Profile
都包含 HomeProxy/Sing-box 与 ddns-go，但 `x86-basic` 不包含二层 VPN。
R619AC 新 Profile 沿用 `p2w_r619ac-128m`，对应128MiB NAND；
用户已确认宿舍 R619AC 同样为128MiB NAND／512MiB RAM；basic 版使用 `p2w_r619ac-128m` 目标。实机启动与刷写验收仍待完成。

所有隧道默认未配置，VLESS 转发默认关闭。软件包安装不会修改 LAN/WAN、DHCP、防火墙或创建网桥。
网络地址、WireGuard 密钥、VLESS UUID、证书及 REALITY 参数均在设备上填写。

## 两种承载

```mermaid
flowchart LR
  A[宿舍专用端口或 SSID] --- B[R619AC 的专用网桥]
  B <-->|L2TPv3 或 VXLAN，经 WireGuard 加密| C[家庭 OpenWrt 的指定网桥]
  C --- D[家庭指定 VLAN 或设备]
```

WireGuard 的外层可直接走 UDP，也可通过宿舍本机 Xray 的 UDP 端口映射走 VLESS/TLS 或 VLESS/REALITY。
直连时关闭“网络 → 二层 VPN”中的 VLESS 转发，将 WireGuard 对端指向家里的公网地址与 UDP 端口。
VLESS 模式的层次为：以太网帧 → L2TPv3/VXLAN → 内核 WireGuard → Xray/VLESS → 家里。
这不会占用第二个家庭 PPPoE 拨号会话；宿舍继续使用自己的上联。

L2TPv3 是静态 Ethernet pseudowire，使用两端对应的 tunnel/session ID；这里不使用 PPP 拨号账号。
依据：[Linux L2TP 子系统](https://docs.kernel.org/networking/l2tp.html#unmanaged-l2tpv3-tunnels)。
Xray 使用固定 Feed 的26.3.27字段，UDP 映射为 `dokodemo-door` 的 `network: udp`；
最新在线文档中的 `tunnel` 命名不直接套用到此固定版本。
依据：[固定版本配置定义](https://github.com/XTLS/Xray-core/blob/v26.3.27/infra/conf/dokodemo.go)。

## 先部署 WireGuard 和 L2TPv3

模板位于 `templates/l2vpn/`，只供逐段合并，不覆盖整个 `/etc/config/network`。
`network-home.uci.example` 与 `network-dorm.uci.example` 中的地址均为示例；
先选择与两处现有网络不冲突的隧道地址、专用二层网段、实际端口/VLAN/SSID，再对应替换。

1. 在两端生成各自的 WireGuard 密钥并交换公钥。LuCI“网络 → 接口”支持 WireGuard。
   家庭示例 `wghome` 为192.0.2.1/32，宿舍 `wgdorm` 为192.0.2.2/32。
   各自 Allowed IPs 只包含另一端的 /32，开启对端路由；二层流量在这两个地址之间封装。
   宿舍配置25秒 keepalive。先用直连 UDP 验证隧道两端可以互相 ping。
2. 添加协议为“通过 WireGuard 承载 L2TPv3”的接口。家庭示例 `l2home`，宿舍 `l2dorm`。
   家庭 ID 为 tunnel=101、session=201，对端为102、202；宿舍反向填写。
   同一台机器上每个 L2TPv3 session ID 必须唯一。接口名最多11个字母、数字或下划线。
3. 二层设备分别为 `nl2-l2home`、`nl2-l2dorm`。将其加入选定的专用网桥，
   再添加需要延伸的 VLAN/以太网端口，或将专用 SSID 绑定到这个网桥的网络。
   模板不选择物理端口；宿舍 WAN 和本地管理 LAN 保持独立。
4. 在家庭二层网段安排一个 DHCP 服务；宿舍同一广播域不再提供 DHCP、DHCPv6 或 IPv6 RA。
   家庭决定是否提供网关、DNS 和 IPv6 RA。延伸设备通过家里网关上网时，流量也会经过隧道。
   在 LuCI 中确认 DHCP/RA 及防火墙区域后，再接入终端。

示例 WireGuard MTU 为1420，二层 MTU 为1360。L2TPv3 的 IPv4/UDP 及以太网封装预留50字节，
适配层会拒绝超过 WireGuard MTU 的设置。IPv6 载荷可以通过这个以太网隧道传输，
L2TPv3 两端的承载地址在当前适配器中使用 IPv4。
接入的终端/VLAN/SSID 也需要一致或可正常探测的 MTU：IPv4 DHCP 可按需提供 MTU 选项，
IPv6 RA 可公布链路 MTU；仅修改 TCP MSS 不能解决 UDP 和二层大帧问题。

静态 L2TPv3 生命周期由 netifd 管理，重载或下线时按运行时保存的 ID 清理。
启动前检查内核 WireGuard 设备、源地址、对端路由和 MTU；已有同 ID 的外部隧道不会被启动失败的回滚删除。

## 再选择 VLESS 外层

家庭使用 `vless-home.uci.example`，宿舍使用 `vless-dorm.uci.example`，
或在“网络 → 二层 VPN”填写同样字段。此页面只管理专用 Xray 进程，独立于 HomeProxy 与 V2Ray Server。

* TLS：两端使用相同 UUID 与 SNI，家庭填本地证书和私钥路径；宿舍默认验证公共 CA，
  私有 CA 则填写对应 CA 证书文件。没有跳过证书验证的开关。
* REALITY：两端选择 REALITY。运行 `xray x25519` 生成密钥，
  家庭将私钥单独保存到权限600的本地文件，界面只填写路径；宿舍填写公钥。
  此版本命令输出的 `Password (PublicKey)` 即客户端要填的公钥。
  配置相同 short ID 和相容的 server name；家庭另填实际 REALITY target host:port。
  需要 Vision 时两端均选择 XTLS Vision。没有预置目标网站、密钥或账号。
* 宿舍选择实际 WAN Linux 设备，例如已有拨号产生的 PPP 设备，或 DHCP 上联设备。
  Xray 的外连绑定此设备。保证 VLESS 端点及必要的 DNS 解析继续走宿舍上联。
* 宿舍 WireGuard 的家庭 peer endpoint 改为 `127.0.0.1:51821`；
  这个端口是宿舍 Xray 的本地 UDP 入口。
  两端 Xray 的“家庭 WireGuard 目标 IP/UDP端口”保持相同：
  如果 Xray 就在家里的 OpenWrt 上，通常为 `127.0.0.1:51820`。

填妥后启用并重启 `neko-l2vpn` 服务。服务先运行 `xray run -test`，
成功后才交给 procd 启动，运行配置保存在权限600的临时文件中。
家庭服务端只放行指定 IP、指定 UDP 端口的 WireGuard 目标，其他代理请求默认丢弃。

防火墙按实际拓扑配置：直连时开放家里 WireGuard UDP 端口；VLESS 模式开放家里对应 TCP 监听端口。
WireGuard 逻辑接口区域允许两个隧道地址之间的 L2TPv3 UDP1701 或 VXLAN UDP4789。
L2TPv3/VXLAN 无需直接开放到公网。专用二层 LAN 所属区域、DHCP/DNS及转发权限由用户显式选择。
Xray/VLESS 不会自动解决两端均无入站地址的问题：仍需可达的家庭公网 IPv4/IPv6，或额外的中转/反向连接方案。

VLESS 外层若使用 TCP，丢包时可能增加排队和重传影响；能直连 UDP 时可省去这层。
依据：[WireGuard 对 TCP 承载的说明](https://www.wireguard.com/known-limitations/#tcp-mode)。

## VXLAN 选项

两端“网络 → 接口”已包含官方 VXLAN 协议及内核模块。
用两端 WireGuard 地址作 local/remote VTEP，绑定对应 WireGuard 接口，设置相同 VNI 和目的 UDP 端口，
把 VXLAN 设备代替 `nl2-*` 放入专用网桥；不要将两条二层通道同时接到同一个广播域形成环路。
VXLAN 与 L2TPv3 共用下层 WireGuard，因而支持同样的直连/VLESS 切换。
依据：[Linux VXLAN 文档](https://docs.kernel.org/networking/vxlan.html)。

## 家庭 HA 与验收

宿舍 basic 版独立运行。家庭若启用 HA，按已有 HA 文档将家庭 WireGuard 接口加入 `managed_interface`，
关闭其自身自动启动，并将 `neko-l2vpn` 加入 HA 的 `service` 列表；两台家庭路由均需保存相容的本地配置。
L2TPv3 通过 netifd 依赖 WireGuard。跨地域二层 VPN 不作为家庭 VRRP 心跳口。

排查入口：`wg show`、`ip l2tp show tunnel`、`ip l2tp show session`、
`ip -d link show`、`bridge link`、`logread -e neko-l2vpn`。
端到端验收包含 ARP/NDP、DHCP/RA、IPv4/IPv6、大包 MTU、UDP与TCP吞吐、断线恢复，以及家庭 HA 切换。
Linux namespace 集成已通过真实 WireGuard、L2TPv3/VXLAN、VLESS/TLS、IPv4/IPv6、MTU、物理 WAN 断开恢复，
以及按 netifd 生命周期恢复路由和二层设备的 WireGuard 重建测试。
这些结果不能替代 R619AC 实机性能、家庭公网和宿舍网络测试。
