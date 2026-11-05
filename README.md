# ImmortalWrt 自定义固件工程

独立配置仓库，不 Fork 或提交完整 ImmortalWrt 源码。源码使用官方稳定分支
`openwrt-25.12` 的发布版 **v25.12.2**，固定 Commit
`4fc16f2985a358bd43bb522e43f05395fcbd6ed5`；5 个官方 Feed 同样固定完整 Commit。
25.12 使用 apk，旧 LEDE 18.06 的 opkg 软件包与 UCI 配置必须经过迁移。

当前交付包括源码构建流水线、三个 Profile、配置验证、缓存、产物与发布、
旧配置清单分析工具和本地 keepalived 控制包。**完整固件编译及实机切换仍待验证**。
尚未取得旧机 `/etc/config` 和软件包清单，不能声称已保留其全部插件。
网络代理实现尚待旧机清单确认，未擅自安装额外代理插件。没有更改默认主题或指定 LAN/WAN 地址。

## 目录

```text
.github/workflows/   静态检查、手动完整构建与草稿 Release
config/             源码/Feed 锁、通用/目标/内核 Kconfig 片段
profiles/           目标、包清单、覆盖层、必需产物声明
packages/           base.list、用户已要求的 ha.list
local-packages/     本仓库维护的软件包；firmware-ha 含 HA 控制逻辑
files/              common 与各 Profile 的根文件系统覆盖层
patches/            common 与各 Profile 的 series 补丁序列
themes/             主题软件包与 LuCI 覆盖扩展入口；默认不安装额外主题
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
| `x86-basic` | x86/64；Legacy/UEFI × ext4/SquashFS 四种镜像 | 上游默认 + LuCI 中文、CA |
| `x86-ha` | 同上 | 基础 + 下列已要求服务 + HA 控制包 |
| `r619ac-ha` | ipq40xx/generic，`p2w_r619ac-128m`，NAND SquashFS | 同 HA 服务集，保留上游目标驱动默认值 |

HA 服务集：DHCP/DNS（上游 dnsmasq/odhcpd）、OpenVPN、WireGuard、ddns-go、
ZeroTier、FRP 客户端、keepalived。WireGuard 由 netifd 管理；在设备本地用 HA 的 managed_interface
列表指定需要随角色启停的 WireGuard 接口，默认不选择接口，不停止整个 network 服务。
软件包选择不等同于具备可工作的 VPN/DDNS 配置；凭据须刷机后在设备本地填写。

`p2w_r619ac-128m` 的 128M 是 **NAND 闪存规格**。内存仍须通过 `free -m` 核实；
不能将名称相近的设备或 64M NAND 固件混刷。上述服务可构建不代表在 128 MiB RAM
同时满载可用，必须测量内存、吞吐与 OOM。详见 [硬件与服务验证](docs/validation.md)。

## GitHub Actions

将这个配置仓库推送到自己的 GitHub 仓库，进入 Actions → Build firmware → Run workflow：
选择 Profile；默认只构建 `x86-basic`。`all` 根据 `profiles/*.json` 自动生成矩阵。
默认只上传 Actions Artifacts；勾选 `publish` 才生成一个包含所选 Profile 的**草稿 Release**。
发布任务仅在全部构建成功后运行，自动校验 SHA256，再打包每个 Profile，避免同名产物覆盖。
首次全量构建可能需要数小时；日志在失败后也会上传。修改配置或扩展包无需改主工作流。

流水线使用 Ubuntu 24.04，先安装构建依赖，再拉取锁定源码、安装锁定 Feed、应用补丁、
安装本地包、叠加系统文件、执行 `make defconfig`。任何请求的包或 Kconfig 选项被静默移除，
都会直接失败并输出差异。随后 `make download`、完整 `make`、验证镜像与 Manifest，最后打包。
失败不会降级为成功；没有使用 `make ... || true` 掩盖错误。

缓存只有下载目录与 ccache；不共享 build_dir/staging_dir，避免 ABI 混用。
缓存键包含目标与配置/软件包内容，实际源码和 Feed Commit 总在使用前核对。
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
  每个补丁先 `git apply --check`，失败即停止。补丁只作用于主源码树；Feed 修改宜使用锁定定制 Feed。
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
`ddns-scripts` → `ddns-go` 的规则已准备，但域名、API 提供商、认证方式需重新配置。

## 双机与 PPPoE

参见 [HA 部署和故障行为](docs/ha.md)。控制包默认关闭；你尚未确认的端口与地址均留空。
两个节点都以 BACKUP 状态启动，x86 优先级 200、R619AC 100，允许延迟抢占。
`cold-pppoe` 为单会话账号接管；`warm` 适用于两端可同时保持独立外网的环境。

这不是已验收的开箱即用现网固件：还缺旧机配置、准确硬件与接线、宽带会话策略、
实际编译与设备演练。待这些资料到齐后，可在现有入口完成最终配置，无需重写工作流。

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
