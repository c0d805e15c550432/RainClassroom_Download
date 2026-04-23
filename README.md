# RainClassroom_Download

## 功能简介

基于Python中同步playwright框架，监听雨课堂页面接口，自动下载课件并合成为 PDF。
支持正在上课时获取完整课件，以及课程回顾时下载完整课件（即使老师将课程设为不可查看）。
基于荷塘·雨课堂制作，其余雨课堂适配情况未知，可自行测试。

## 环境要求

- Python 3.10 及以上（建议）

## 安装依赖

在项目根目录执行：

```bash
pip install -r requirements.txt
```

安装 Playwright 浏览器内核（首次必需）：

```bash
playwright install chromium
```

## 使用方法

1. 进入项目目录
2. 启动程序

```bash
python main.py
```

或直接双击运行：

- `run.bat`

3. 首次使用时需手动完成登录
4. 在浏览器窗口中打开所需下载课件的课程页面，随后将自动开始下载

## 主要配置说明

- `OUTPUT_DIR`: PDF 输出位置
- `OUTPUT_DIR/<课件名>/`: 临时图片目录
- `DELETE_IMAGES_AFTER_PDF`: 合成 PDF 后是否删除临时图片（默认是）
- `VERIFY_SSL`: 是否验证ssl证书（默认否，若开启fiddler、reqable等代理请务必设为否）
- `MAX_WORKERS`: 下载图片时最大线程数
- `MAX_RETRIES`: 下载图片时最大重试数
