# МТС EnergyTool — единый контракт команды

Версия: 0.1 (зафиксировано по стартовому backend-шаблону).  
Репозиторий: `https://github.com/sereinnel/mts_hack_26`  
Ветки: `main` (интеграция), `feature/backend`, `feature/ai`, `feature/frontend`.

## 1. Статус

**Уже реализовано:** FastAPI в `backend/main.py`, SQLite в `backend/db.py`, AI-адаптер в `backend/ai_adapter.py` с mock-режимом и вызовом `ai.consultant.answer_turn` через `AI_FUNCTION`.

**Реализовано отдельно от HTTP API:** синхронная функция `ai.consultant.answer_turn`, расширенный AI-ответ, локальный поиск и извлечение подтверждённого фрагмента. См. [AI_MODULE.md](AI_MODULE.md).

Подготовлен необязательный модельный режим и семантический Critic. Проверены на заглушках; реальный API модели пока не подключён. Публичный контракт `answer_turn` не изменён.

**Реализовано в backend:** хранение `session_facts` (полного снимка `updated_facts`) отдельно для каждой сессии в SQLite; передача этих фактов AI при следующих сообщениях.

**Реализовано в AI:** извлечение явно сообщённых типа организации (`industry`) и цели (`goal`); backend сохраняет полный снимок из `updated_facts` без изменения HTTP-контракта.

**Пока НЕ реализовано в backend:** HTTP-поля `stage`, `suggested_action`, `diagnostics`, дедупликация заявок, конкурсный `solution.py`.

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
{"session_id":"uuid-сессии", "message":"Хотим снизить расходы на электричество", "debug":false}
```

Существующий ответ (статус `200`):

```json
{
  "session_id": "uuid-сессии",
  "answer": "Ответ (пока заглушка)",
  "sources": [],
  "intent": "mock",
  "latency_ms": 0,
  "source_ids": [],
  "stage": null,
  "route": "mock",
  "suggested_action": null
}
```

`latency_ms` — пример; фактическое значение измеряется сервером. Если сессии нет или она закрыта, сервер возвращает `404`.

`source_ids` — алиас `sources` для нового контракта AI, `stage` — стадия диалога, `route` — выбранный маршрут, `suggested_action` — предложенное действие (или `null`). Старые поля сохранены для совместимости с frontend.

**Диагностика:** для внутренней отладки в запросе передать `"debug": true` и заголовок `X-Admin-Token` с тем же серверным секретом, который используется для `GET /api/leads`. При валидном токене в ответ добавляется `diagnostics` — безопасные диагностические данные, которые предоставляет AI (`retrieved_chunk_ids`, `used_chunk_ids`, `critic`, `mode` и т. п.). Поле `latency_ms` всегда содержит полное время вызова AI на стороне backend. Для обычных запросов `diagnostics` отсутствует, а в AI передаётся `debug=False`. Без настроенного `ADMIN_TOKEN` запрос с `debug=true` возвращает `503`, с неправильным токеном — `403`. Никогда не передавать `ADMIN_TOKEN` из публичного frontend и не логировать его.

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

Если `consent_to_contact=false`, запрос отклоняется статусом `400`. Использовать только вымышленные персональные данные.

**Повторная отправка заявки:** одна сессия создаёт не более одной новой заявки. Если повторить запрос с теми же `session_id`, `full_name`, `phone`, `company`, сервер возвращает **`200 OK`** и исходный `id` и `summary`, без новой записи в SQLite. Если попытаться отправить другие контактные данные в ту же сессию, сервер возвращает **`409 Conflict`** и не перезаписывает исходную заявку. Первая отправка по-прежнему возвращает `201 Created`. Для новой заявки нужно создать новую сессию.

Дедупликация выполняется в транзакции SQLite, чтобы два одновременных запроса не создавали дубликаты. Старые записи в БД не удаляются.

### `GET /api/leads`

Административный маршрут. Требует переменной `ADMIN_TOKEN` на сервере и заголовка `X-Admin-Token` в запросе. Если переменная не задана, статус `503`; при неверном заголовке `403`. **Frontend не должен хранить административный токен.**

## 3. Согласованный AI-контракт (подключён через backend/ai_adapter.py)

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

`backend/ai_adapter.py` вызывает `answer_turn(message, history, session_facts, debug=False)` при `AI_FUNCTION=ai.consultant:answer_turn`. Если `AI_FUNCTION` не задана, используется mock. AI-модуль не должен использовать FastAPI или SQLite и не должен создавать заявки.

`updated_facts` — полный независимый снимок переданных фактов, не частичный патч. AI добавляет явно сообщённые `industry` и `goal`, сохраняет неизвестные ему поля и учитывает явные исправления; backend сохраняет то, что вернул AI. Для «У нас производственное предприятие. Хотим снизить расходы на электричество» результат содержит `{"industry": "manufacturing", "goal": "reduce_energy_costs"}`. Ограничения извлечения описаны в [AI_MODULE.md](AI_MODULE.md#факты-клиента). `source_ids` содержит исходные относительные пути использованных документов БЗ. Без использованного подтверждённого фрагмента список пуст. `debug=False` даёт `debug=None`; диагностические поля не включаются в существующий HTTP-ответ автоматически.

Для конкурсного скрипта добавлен отдельный текстовый интерфейс `answer_question(question, knowledge_base) -> str`, канонически в `ai/submission.py`. Плоский экспорт в корень ZIP предоставляет `from energytool_ai import answer_question`. Обработка CSV и упаковка архива остаются у backend-разработчика; HTTP-контракт и сигнатура `answer_turn` не меняются. См. [SUBMISSION_AI.md](SUBMISSION_AI.md).

## 4. Будущие расширения HTTP API

Планируемое, но пока не реализованное поле ответа: `message_id`. Остальные поля диагностики описаны в §2; правила выдачи `debug` реализованы с обязательной проверкой `X-Admin-Token`.

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
