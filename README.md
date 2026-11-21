# Google Pixel 工厂镜像自动提取器

GitHub Actions 自动从 Google 官方工厂镜像页面（developers.google.com/android/images）：

1. **解析页面** → 按设备代号（codename）找到该设备的全部官方工厂包
2. **选定版本** → 支持三种方式：最新 / 指定日期（≤ 该日期的最新版）/ 精确版本号
3. **断点续传下载** → 从 dl.google.com 拉取完整工厂包（zip 完整性校验）
4. **解压提取** → 解出 `boot.img` / `init_boot.img` / `vendor_boot.img` / `dtbo.img` / `vbmeta*.img` / `system.img` 等全部分区镜像
5. **有效性验证** → 结构化解析每个镜像（Android boot header v0–v4、AVB header/footer、dt_table、sparse），并计算 SHA256
6. **发布 Release** → 镜像作为附件上传，Release 页面与 `links.md` 提供**每个镜像的下载地址**（外加 Google 官方工厂包直链）

## 使用方法

### 手动触发（推荐）

`Actions → build → Run workflow`，参数：

| 参数 | 说明 | 示例 |
|---|---|---|
| `devices` | 设备代号，空格分隔可一次处理多台 | `panther husky` |
| `date` | 目标日期 `YYYYMMDD`，选 ≤ 该日期的最新版本；留空 = 最新 | `20250105` |
| `build_id` | 精确版本号（优先于 date） | `AP4A.250105.002` |
| `upload_images` | 上传到 Release 的镜像过滤正则 | `^(init_boot\|boot\|vbmeta.*)\.img$` |
| `keep_factory` | 同时上传完整工厂包（>2GiB 可能超出单附件上限，默认只给直链） | `false` |

### 定时构建

默认每周一 03:30 UTC 自动构建 `DEFAULT` 设备的最新版（见 `build.yml` 中 cron 与 DEVICES 环境变量，可自行修改设备列表）。

### 产物

每个「设备 + 版本」生成一个 Release，tag 形如 `panther-AP4A.250105.002`，附件包括：

- 各分区镜像（默认：`init_boot` `boot` `vendor_boot` `dtbo` `vbmeta*`，可用 `upload_images` 改）
- `SHA256SUMS` — 全部镜像与工厂包的 SHA256
- `links.md` — 全部下载地址清单（Release 附件直链 + Google 官方直链）
- `verify.json` / `resolve.json` — 验证报告与版本解析结果（也在 Actions Artifacts 里）

## 有效性验证说明

| 对象 | 校验内容 |
|---|---|
| 工厂包 zip | HTTP 断点续传 + `unzip -t` 完整性测试 + 最小体积检查 |
| `boot` / `init_boot` / `vendor_boot` / `recovery` | `ANDROID!` 魔数；header v0–v4 字段（kernel/ramdisk 大小、page size、os_version 解码）；按 page 对齐推算的最小体积与实际体积一致性；AVB footer |
| `vbmeta*` | `AVB0` 头：libavb 版本、签名算法、rollback_index、flags、release_string、描述符链（hashtree/chain 覆盖的分区） |
| 带 AVB footer 的镜像（system/vendor 等） | `AvBf` footer：`original_image_size`、`vbmeta_offset/size` 越界检查，指向的 vbmeta 头魔数 |
| `dtbo.img` | `dt_table` 魔数 `0xd7b7ab1e` 与表头字段 |
| sparse 镜像（system/vendor/product…） | sparse 魔数 `0x3aff26ed` 与块头字段（footer 尽力校验） |
| `bootloader-*` / `radio-*` | 厂商格式不做结构解析，仅记录 SHA256 |
| 全部文件 | SHA256（写入 `SHA256SUMS`） |

镜像均为**官方包原样解出，未做任何字节修改**。

## 常见设备代号（以官方页面实际列表为准，`resolve_build.py --list` 可随时列出）

| 设备 | 代号 | | 设备 | 代号 |
|---|---|---|---|---|
| Pixel 7 | `cheetah` | | Pixel 8 | `shiba` |
| Pixel 7 Pro | `panther` | | Pixel 8 Pro | `husky` |
| Pixel 7a | `lynx` | | Pixel 8a | `akita` |
| Pixel Fold | `felix` | | Pixel 9 | `tokay` |
| Pixel Tablet | `tangorpro` | | Pixel 9 Pro | `caiman` |
| Pixel 6 | `oriole` | | Pixel 9 Pro XL | `komodo` |
| Pixel 6 Pro | `raven` | | Pixel 9 Pro Fold | `comet` |
| Pixel 6a | `bluejay` | | Pixel 9a | `tegu` |

> Android 13 起的设备（Pixel 7 系列及以后、Pixel 6/6a/6 Pro 升级 13 后）才有 `init_boot.img`（GKI 通用内核 init ramdisk，Magisk/KernelSU 刷补丁用的就是它）。

## 本地运行

```bash
bash scripts/run_pipeline.sh panther                # 最新
bash scripts/run_pipeline.sh panther 20250105       # ≤2025-01-05 的最新版
bash scripts/run_pipeline.sh panther "" AP4A.250105.002   # 精确版本
```

依赖：`python3`、`unzip`、`curl`（`aria2c` 可选，更快）。生成 Release 需要 `gh` 且设置 `GH_TOKEN`。

## 已知限制

- GitHub Release 单附件上限 2 GiB，`system.img` 等大镜像默认不上传（官方包直链里都有，`SHA256SUMS` 也含其哈希）；把 `upload_images` 设为 `.*` 可尝试全部上传。
- 版本号里的日期为 Google 构建日期（如 `AP4A.250105` = 2025-01-05），"指定日期"按此匹配。
