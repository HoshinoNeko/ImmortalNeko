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
没有配置值。66个 LuCI 应用/协议/主题中，21项尚无直接匹配；其余条目目前只证明包定义存在或有映射，
仍需目标选择、编译和功能检查。全包的私有迁移报告还包含旧依赖、旧内核模块等待核对项，
不能把这些数目当成已完成保留的插件数。不要将所有旧ABI库直接装入新系统。

配置目录中的 .bak、.new、.clear 等文件是历史副本，不能作为当前 UCI 设置自动应用。
最新配置包含多个 VLAN 和多 WAN；HA 多 VIP 支持已预留，实际管理地址、心跳口、
备用机 VLAN 映射和拨号策略仍待确定。没有把任何现网配置或凭据复制进固件覆盖层。
R619AC 当前不可访问，硬件与运行功能尚未验证。
