# 校园快递驿站取件助手

Vue 网页与 FastAPI 共用一个服务。SQLite 保存账号、登录会话、货架和包裹。驿站平面图与错峰预测的历史队列观测来自合成数据。

## Windows 启动

需要 Node.js 20.19+ 或 22.12+，以及支持依赖项的 64 位 Python（本项目使用 Python 3.12）。在项目目录打开 PowerShell，首次运行 `./start.ps1 -Install`，之后运行 `./start.ps1`。打开 [本地取件助手](http://127.0.0.1:8000)。可用 `-Port 8001` 更换端口，按 Ctrl+C 停止。

- 前端依赖包括 Vue、Vite、Vue 插件和 ZXing 浏览器扫码库。
- 后端依赖包括 FastAPI、Uvicorn、Pillow、RapidOCR、ONNX Runtime 和 NumPy。SQLite 和密码哈希使用 Python 标准库。

## 账号与包裹

1. 登录页面可注册普通账号。新密码至少 8 个字符。首次启动创建管理员，账号和初始密码均为 `admin`。导航栏提供修改密码与退出登录。密码存储为随机加盐的 scrypt 哈希。
2. 管理员在包裹管理页导入 UTF-8 CSV。收件用户须先注册，货架须存在，`code` 必须唯一，填入条码或二维码解码后的完整内容。层号为 1–2 位数字，尾号为 4 位数字，保留前导零。导入失败会回滚该批次。
3. 包裹列表可按用户名、货架、尾号和状态组合分页查询。丢弃会关闭待取记录，历史状态仍可查询。
4. 管理员可按平面图坐标和连接点新增货架。存在待取件的货架须先清空。删除货架后，经过该位置的通道仍可用于规划。
5. 普通用户登录后只会看到分配给当前账号的待取包裹。路线页可逐件记录查找进度，错峰计划按可到站时段推荐等待较短的时间。

```csv
username,code,shelf,level,suffix
student01,C2-01-6721,C2,01,6721
student01,A1-02-4513,A1,02,4513
```

## 手机使用

原生客户端位于 [mobile](mobile/README.md)。Android 使用 Kotlin 和原生 View，鸿蒙使用 ArkTS 和 ArkUI。两端使用同一组取件、预测与扫码接口。

在同一局域网内，使用 `./start.ps1 -Lan` 启动，手机浏览器打开电脑的局域网地址和服务端口。普通用户使用取件路线与错峰计划，管理员打开扫码取件，核对包裹后确认出库或丢弃。

实时相机扫码需要手机信任的 HTTPS 证书。例如使用 `./start.ps1 -Lan -Certificate ./cert.pem -PrivateKey ./key.pem`，再以证书对应的 HTTPS 地址访问。未启用实时相机时，可拍照识别面单或手动输入包裹码。

## 验证

运行 `./.venv/Scripts/python.exe -m unittest discover -s tests -v` 检查路线、错峰预测和截图识别。运行 `npm.cmd run build` 验证前端构建。
