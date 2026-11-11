# МТС EnergyTool — единый контракт команды

Версия: 0.1 (зафиксировано по стартовому backend-шаблону).  
Репозиторий: `https://github.com/sereinnel/mts_hack_26`  
Ветки: `main` (интеграция), `feature/backend`, `feature/ai`, `feature/frontend`.

## 1. Статус

**Уже реализовано:** FastAPI в `backend/main.py`, SQLite в `backend/db.py`, тестовый AI-адаптер в `backend/ai_adapter.py`.

**Реализовано отдельно от HTTP API:** синхронная функция `ai.consultant.answer_turn`, расширенный AI-ответ, локальный поиск и извлечение подтверждённого фрагмента. См. [AI_MODULE.md](AI_MODULE.md).

Подготовлен необязательный модельный режим и семантический Critic. Проверены на заглушках; реальный API пока не подключён. Публичный контракт `answer_turn` не изменён. Готовая задача интеграции backend: [BACKEND_AI_TASK.md](BACKEND_AI_TASK.md).

**Пока НЕ реализовано в backend:** подключение `answer_turn`, HTTP-поля `stage`, `suggested_action`, `diagnostics`, сохранение `session_facts`, дедупликация заявок, конкурсный `solution.py`.

Не изменять контракты API и публичные имена функций без согласования всей команды. При любых изменениях обновлять этот файл вместе с кодом.

## 2. Текущий HTTP API (работает сейчас)

Базовый URL при локальном запуске: `http://127.0.0.1:8000`  
Swagger/OpenAPI: `http://127.0.0.1:8000/docs`

### `GET /health`

Возвращает `{"status":"ok","ai_mode":"mock"}` без подключённой AI-функции. `configured` означает, что `AI_FUNCTION` задана, **а не** что модель обязательно доступна.

### `POST /api/sessions`

Без тела запроса. Статус `201`.

```json
{"id":"uuid-сессии","created_at":"ISO timestamp"}
```

### `GET /api/sessions`

Массив объектов `{"id", "created_at", "closed_at"}`. В текущем прототипе нет пользовательской авторизации: не публиковать endpoint без защиты.

### `GET /api/sessions/{session_id}/messages`

Массив сообщений в порядке создания:

```json
{
  "id": 1,
  "role": "user",
  "content": "Текст",
  "sources": [],
  "intent": null,
  "created_at": "ISO timestamp",
  "sources_json": null
}
```

`role` принимает `user` или `assistant`. Поле `sources_json` — служебная особенность текущего прототипа; frontend должен использовать `sources`.

### `POST /api/sessions/{session_id}/close`

Помечает старую сессию закрытой, возвращает `{"closed": true}`. Для «Нового диалога» frontend создаёт *новую* сессию через `POST /api/sessions`. История закрытой сессии сохраняется.

### `POST /api/chat`

Существующий запрос (оба поля обязательны):

```json
{"session_id":"uuid-сессии", "message":"Хотим снизить расходы на электричество"}
```

Существующий ответ (статус `200`):

```json
{
  "session_id": "uuid-сессии",
  "answer": "Ответ (пока заглушка)",
  "sources": [],
  "intent": "mock",
  "latency_ms": 0
}
```

`latency_ms` — пример; фактическое значение измеряется сервером. Если сессии нет или она закрыта, сервер возвращает `404`.

### `POST /api/leads`

Запрос:

```json
{
  "session_id": "uuid-сессии",
  "full_name": "Иван Иванов",
  "phone": "+79990000000",
  "company": "ООО Тест",
  "consent_to_contact": true
}
```

Статус `201`, ответ:

```json
{"id":"uuid-заявки", "session_id":"uuid-сессии", "summary":"...", "created_at":"ISO timestamp"}
```

Если `consent_to_contact=false`, запрос отклоняется статусом `400`. Использовать только вымышленные персональные данные. Дедупликация заявок ещё не реализована.

### `GET /api/leads`

Административный маршрут. Требует переменной `ADMIN_TOKEN` на сервере и заголовка `X-Admin-Token` в запросе. Если переменная не задана, статус `503`; при неверном заголовке `403`. **Frontend не должен хранить административный токен.**

## 3. Согласованный AI-контракт (реализован автономно, подключение к backend впереди)

Владелец AI: `ai/consultant.py`, имя функции `answer_turn`.

```python
def answer_turn(
    message: str,
    history: list[dict],
    session_facts: dict,
    debug: bool = False,
) -> dict:
    ...
```

Структура ответа `answer_turn`:

```python
{
    "answer": "Текст ответа",
    "stage": "discover",     # discover|qualify|recommend|handoff
    "source_ids": [],       # реальные идентификаторы из БЗ
    "route": "simple",     # baseline: simple|rag|clarify|handoff
    "updated_facts": {},
    "proposed_action": None, # например, offer_lead
    "debug": None,
}
```

Это **не текущий интерфейс** `backend/ai_adapter.py`: сейчас он вызывает функцию `consult(question, history)` через переменную `AI_FUNCTION`. Backend-разработчик отвечает за адаптацию после согласования. AI-модуль не должен использовать FastAPI или SQLite и не должен создавать заявки.

`updated_facts` — полный независимый снимок переданных фактов, не частичный патч. В первой версии новые факты автоматически не извлекаются. `source_ids` содержит исходные относительные пути использованных документов БЗ. Без использованного подтверждённого фрагмента список пуст. `debug=False` даёт `debug=None`; диагностические поля не включаются в существующий HTTP-ответ автоматически.

## 4. Будущее расширение HTTP API (пока НЕ использовать как существующее)

Планируемые поля ответа `POST /api/chat`: `message_id`, `stage`, `suggested_action`, `diagnostics`. Их схемы и правила выдачи debug необходимо отдельно утвердить. Существующие поля `session_id`, `answer`, `sources`, `intent`, `latency_ms` по возможности сохранять для совместимости.

## 5. Командные правила

- `main` — интеграционная ветка; новые функции поступают через Pull Request.
- `feature/backend` — FastAPI, SQLite, заявки, Docker, конкурсный `solution.py`.
- `feature/ai` — поиск, индексы, planner/consultant/critic и импортируемый AI-сервис.
- `feature/frontend` — только папка `frontend/`, веб-чат, формы, UI и пользовательские тесты.
- Не создавать внутри подпапок дополнительные Git-репозитории (`git init`).
- Не коммитить `.env`, ключи, закрытую базу знаний, SQLite-данные, `.venv` или `node_modules`.
- API-несовместимые изменения обсуждать до Pull Request.
- Текущий источник истины для *реально реализованных* HTTP-маршрутов — Swagger `/docs` и `backend/main.py`.
- Конкурсный `solution.py` должен использовать то же AI-ядро без зависимости от HTTP и общей SQLite; точные требования сверять с официальным примером организаторов.
