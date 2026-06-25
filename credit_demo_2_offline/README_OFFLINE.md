# credit_demo_2_offline

`credit_demo_2` 的离线迁移副本，目标是内网运行与内网 API 对接，不改业务逻辑。

## 目录约定

- `credit_demo_2_offline/`：离线专用后端与页面
- `offline_test/requirements_py311_offline.txt`：离线依赖主清单
- `offline_test/requirements_py311_offline.lock.txt`：离线依赖全量锁定清单（含传递依赖）
- `offline_test/build_wheelhouse.sh`：外网下载离线包脚本
- `offline_test/install_vendor.sh`：内网安装到 vendor 脚本
- `offline_test/wheelhouse/`：外网下载的离线包
- `offline_test/vendor/`：内网 `--target` 安装目录
- `run.sh`：在 `credit_demo_2_offline` 内启动
- `../run_credit_demo_2_offline.sh`：在仓库根目录下启动

## 启动方式

在 `credit_demo_2_offline/` 目录：

```bash
bash run.sh
```

或在仓库根目录：

```bash
bash run_credit_demo_2_offline.sh
```

默认监听：`127.0.0.1:8000`

共享访问：

```bash
BACKEND_HOST=0.0.0.0 BACKEND_PORT=18080 bash run.sh
```

如需统一数据目录入口（默认 `credit_demo_2_offline/data`）：

```bash
CREDIT_DEMO_2_DATA_ROOT=/path/to/credit_demo_2_data bash run.sh
```

## 可选模型配置

若内网模型接口是 OpenAI 兼容 `/chat/completions`，可配置：

```bash
export QWEN_API_BASE="http://your-inner-api/v1"
export QWEN_API_KEY="your_api_key"
export QWEN_MODEL="your_model_name"
```

未配置时，系统会退化到本地有限规则路径。
