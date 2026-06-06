# Git-like AI Chat 後端

這是專案的 Flask 後端，提供 Git-like 對話節點 API，供前端選擇模型、送出聊天內容，並用 `parent_id` 建立分支。後端目前支援 Ollama 與 Gemini 兩種 Provider。

## 主要架構

- `main.py`：Flask app 入口，建立並啟動 `create_app()` 回傳的 app。
- `app/__init__.py`：Flask app factory，集中初始化資料庫、CORS 與 blueprint 註冊。
- `app/blueprints/health.py`：健康檢查 API。
- `app/blueprints/providers.py`：模型清單與 Ollama 模型偵測 API。
- `app/blueprints/conversations.py`：對話樹、節點、上下文與清空資料 API。
- `app/blueprints/chat.py`：聊天送出 API。
- `app/config.py`：環境變數與預設 Provider 設定。
- `app/database.py`：SQLAlchemy engine、session 與 schema 初始化。
- `app/models.py`：SQLAlchemy model，目前主要為 `MessageNode`。
- `app/http.py`：統一 API 回應格式。
- `app/services/message_nodes.py`：對話節點序列化、上下文重建、分支儲存與樹狀 payload 組裝。
- `app/services/providers.py`：Ollama/Gemini HTTP 呼叫、模型回覆與訊息正規化。
- `core/web.py`：既有回應格式工具。
- `core/general.py`、`core/log.py`：既有通用工具與紀錄工具。
- `pyproject.toml`：Python 專案與相依套件設定。

## API

- `GET /api/health`：檢查後端狀態。
- `GET /api/models`：回傳前端模型選單所需的 Provider 與 Model 清單。
- `GET /api/ollama/models?base_url=http://localhost:11434`：讀取 Ollama `/api/tags`，回傳已拉取的模型名稱。
- `GET /api/context/<node_id>`：回傳指定節點往根節點追溯後的完整線性上下文。
- `GET /api/nodes`：回傳所有訊息節點、root 節點，以及每個節點的 children id。
- `DELETE /api/nodes`：清空所有訊息節點，回傳刪除筆數。
- `GET /api/tree`：同 `GET /api/nodes`，供前端樹狀視覺化使用。
- `GET /api/nodes/<node_id>/children`：回傳指定節點的直接 children。
- `POST /api/chat`：接收 `provider`、`model`、`message`、`parent_id`，由後端重建上下文、呼叫指定模型，並將 user 訊息與 assistant 回覆儲存為同一個 exchange 節點。若 provider 為 Ollama，可額外傳入 `ollama_base_url`。

`POST /api/chat` payload 範例：

```json
{
  "provider": "ollama",
  "model": "llama3.1",
  "ollama_base_url": "http://localhost:11434",
  "parent_id": 12,
  "system_prompt": "You are a concise assistant.",
  "message": "Continue from this branch."
}
```

`parent_id` 可為 `null`，代表從新的 root 對話開始。回應中的 `current_node_id` / `currentNodeId` 是 exchange 節點 id，前端下一次送訊息時應作為新的 `parent_id`。

為了相容舊前端，`POST /api/chat` 仍可接收 `messages` 陣列；此模式會直接使用前端傳入的上下文呼叫模型，並將最後一則 user 訊息與 assistant 回覆儲存在同一個 exchange 節點。

## Provider 設定

- Ollama：預設使用 `http://localhost:11434`，可用前端傳入的 `ollama_base_url` 或環境變數 `OLLAMA_BASE_URL` 覆蓋。
- Gemini：需設定 `GEMINI_API_KEY` 後再啟動後端。

## 資料庫

- 預設使用 SQLite：`data/chat.db`。
- 可用 `DATABASE_URL` 覆蓋，例如 `sqlite:///data/chat.db`。
- `MessageNode` 欄位包含 `id`、`parent_id`、`role`、`content`、`user_content`、`assistant_content`、`created_at`。
- 新對話節點使用 `role = "exchange"`，同一筆 node 同時保存 `user_content` 與 `assistant_content`。

## 開發指令

```bash
uv sync
uv run python main.py
```

開發伺服器預設為 `http://127.0.0.1:5000/`。
