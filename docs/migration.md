# LEDE 18.06 清单与配置迁移

使用 `opkg list-installed` 提供安装清单最准确；`opkg list` 可能只是所有可安装包，不能证明已安装。
如果提供的是后者，必须补充安装状态，不能全部装进新固件。

设备地址确认后，可在本地运行只读采集：

```sh
sh scripts/collect-legacy.sh root@YOUR_ROUTER private/legacy-new
```

采集脚本只执行查询和读取：安装清单、ubus board、内存/闪存/接口、etc/config 归档。
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
