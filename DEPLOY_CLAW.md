部署到 Claw Cloud（使用 GitHub Actions 构建并推送镜像）

概述

该项目已包含 `Dockerfile`，并在仓库中添加了 GitHub Actions 工作流：`.github/workflows/build-and-push.yml`。工作流在向 `main` 分支推送时会构建镜像并将其推送到你指定的镜像仓库。

所需 GitHub Secrets（在仓库 Settings -> Secrets 中添加）

- `REGISTRY`：镜像仓库域名，例如 `docker.io` 或 `ghcr.io`
- `REGISTRY_USERNAME`：仓库用户名
- `REGISTRY_PASSWORD`：仓库密码或访问令牌
- `IMAGE_NAME`：镜像名，例如 `youruser/audio-converter` 或 `yourorg/audio-converter`

工作流行为

- 在 `main` 分支有新提交时触发。
- 构建多平台镜像（linux/amd64, linux/arm64），并推送两个 tag：`latest` 与当前 `git sha`。

在 Claw Cloud 上部署（示例）

1. 在 Claw Cloud 控制台选择“从镜像部署”。
2. 填写镜像地址，例如：
   - Docker Hub: `docker.io/youruser/audio-converter:latest`
   - GitHub Container Registry: `ghcr.io/yourorg/audio-converter:latest`
3. 配置端口：将外部访问端口映射到容器端口 `8080`（镜像内服务监听该端口）。
4. 如需持久化上传或输出，请配置卷或对象存储；当前服务使用临时目录 `/tmp`，若平台短暂重启会丢失文件。

触发与验证流程

1. 在本地提交并推送到 GitHub `main`：

```bash
git add .
git commit -m "Add CI build/push workflow"
git push origin main
```

2. 在 GitHub Actions 页面查看构建/推送结果。成功后，使用镜像地址在 Claw Cloud 填写部署并启动。

3. 验证：访问 Claw Cloud 分配的外部地址（或负载均衡域名）`/ui` 查看上传界面，或调用 `GET /` 健康检查端点。

可选：我可以帮助你

- 将工作流改为仅在打标签或创建 release 时推镜像（便于版本管理）。
- 提供针对 Docker Hub 或 GHCR 的示例 Secrets 设置说明（Token 创建方式）。
- 根据 Claw Cloud 的具体控制台设置，给出精确的部署字段映射。

如要我继续操作，请告诉我：

- 你想推到哪个仓库（`docker.io` 还是 `ghcr.io` 等），并告知镜像名（或我可使用 `youruser/audio-converter` 作为模板）。
- 是否需要我改为只在 tag/release 时构建并推送。
