# 第三方组件与源码

端侧智能体第一版集成 Termux 0.118.3，作为 GPL-3.0-only 应用分发。项目许可证全文见 [LICENSE](LICENSE)。Termux 原有版权及其组件例外保留，不能将本应用声称为 Termux 官方产品。

| 组件 | 版本 / 来源 | 许可与来源 |
| --- | --- | --- |
| Termux app / 终端源码 | v0.118.3 | [Termux 源码](https://github.com/termux/termux-app/tree/v0.118.3)，GPL-3.0-only；终端视图/模拟器保留上游 Apache-2.0 例外 |
| Termux 官方 ARM64 APK | v0.118.3 GitHub | [官方发布](https://github.com/termux/termux-app/releases/tag/v0.118.3)，SHA-256 `72fdb596045116bf5ba1b5bdf5b26fddb9acc0bd074ad9f2da9eb0ae85e83a4e` |
| 内置 bootstrap | 从上述 APK 提取 | SHA-256 `c8d702b6f742935001c37cda81b8ac69504a95d5cf28f2899532dd8cd4b057eb`；包内各软件版权和许可随 bootstrap 保留 |
| PTY JNI libtermux.so | 与上述版本匹配 | SHA-256 `41fad4b73caa033dc4b3de113f743efbd0039af6889ae7dd40ecb739fef17242`；对应 native 源码随 Termux 源码提供 |
| CPython | Chaquopy 内置 3.13 | [PSF License](https://docs.python.org/3/license.html) |
| Chaquopy | 17.1.0 | [官方仓库](https://github.com/chaquo/chaquopy)，MIT；Python 依赖各自保留上游许可 |
| Shizuku API / Provider | 13.1.5 | [官方仓库](https://github.com/RikkaApps/Shizuku-API)，MIT |
| AndroidX / Jetpack | 以 Gradle 固定依赖为准 | Apache-2.0 |
| Lottie Web | 5.12.2 | [官方仓库](https://github.com/airbnb/lottie-web)，MIT；仅用于本地 eZ 欢迎动画 |

修改的应用源码、构建脚本及固定版本原始终端源码包含于交付源码包。完整 Termux 源码位于 `android/vendor/termux/source/termux-app-0.118.3/`。源码包与 APK 应一同分发，保留版权、许可证和对应二进制来源信息。

Termux bootstrap 中各二进制包的对应源码构建配方位于 [termux-packages](https://github.com/termux/termux-packages)，具体版本见内置 dpkg 数据库，包版权说明保留于 `usr/share/doc/`。再次分发时应遵守每个包的对应源码及许可义务。

## 云琥品牌与欢迎动画

应用名称固定为云琥（Yunhu）。[项目提供的原始图标](<图标.ico>)是品牌图像来源；[生成脚本](<scripts/generate_brand_assets.py>)仅提取最高帧、缩放并添加启动图标所需的安全留白，不以第三方产品图像替换。来源说明不构成新增第三方商标或素材授权声明。

1.3.2 起欢迎页使用项目工作区提供的 [eZ.json](<eZ.json>)，原样打包至 [欢迎动画资源](<android/app/src/main/assets/welcome/eZ.json>)。本应用不将该素材声明为原创，也不据此推定额外素材授权；中英文逐字交替文字由本应用实现。Lottie Web 5.12.2 使用 MIT 许可，完整文本见 [Lottie 许可](<android/app/src/main/assets/licenses/Lottie-MIT.txt>)；渲染器来自 [cdnjs 固定版本](https://cdnjs.cloudflare.com/ajax/libs/lottie-web/5.12.2/lottie.min.js)。早期版本的手写 Hello 路径已被替换。

本应用由现有项目继续开发，与 Termux、Shizuku、Magisk、KernelSU、APatch 等上游项目不存在官方从属关系。
