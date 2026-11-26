# 校园驿站原生客户端

两端共用项目根目录的 FastAPI 服务。普通用户可注册、登录、查看本人待取包裹和站内路线、记录查找进度并查询错峰推荐。管理员可通过设备相机扫描条码或二维码，核对包裹后确认取件或丢弃。两种账号均可修改密码和退出。服务器地址保存在设备上，登录会话保留在内存中。

## Android

用 Android Studio 打开 `mobile/android`，使用 JDK 17 和 Android SDK 34。也可在该目录运行 `./gradlew.bat assembleDebug`。调试 APK 输出到 `app/build/outputs/apk/debug/app-debug.apk`。应用以 Android 14（API 34）为目标，扫码使用 ZXing Android Embedded。

## 鸿蒙

用 DevEco Studio 打开 `mobile/harmony`。工程使用 Stage 模型，声明的最低兼容版本为 HarmonyOS 5.0.0（API 12）。在签名配置中为测试设备配置调试签名，然后选中 Mate 80 或兼容设备运行 `entry` 模块。扫码使用系统 Scan Kit。

## 连接后端

- Android 模拟器连接同一台电脑时可填 `http://10.0.2.2:8000`。
- 鸿蒙和 Android 真机与电脑连接同一个局域网。先在项目根目录执行 `./start.ps1 -Lan -Port 8001`，再在登录页填入电脑的局域网地址，例如 `http://192.168.1.10:8001`。示例中的 IP 需换成电脑的实际地址。Android 调试版允许 HTTP，发布版要求 HTTPS。
- 扫码前，在 Web 管理端把包裹分配给已经注册的收件账号。CSV 中的 `code` 对应面单条码或二维码解码后的内容。
