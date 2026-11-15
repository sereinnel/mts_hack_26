# EnergyTool Backend — стартовый шаблон для участника №2

Это минимальный **рабочий backend с MOCK AI**, а не готовое решение МТС и не конкурсный сабмит. Он показывает API, хранение истории, формы заявок и точки интеграции с RAG.

## Локальный запуск

```bash
python -m venv .venv
source .venv/bin/activate     # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
uvicorn backend.main:app --reload
```

Swagger: http://localhost:8000/docs

Или через Docker:

```bash
cp .env.example .env          # задайте длинный ADMIN_TOKEN
# Linux/macOS: mkdir -p data
docker compose up --build
```

## HTTP API

- `GET /health`
- `POST /api/sessions` — создаёт новую историю
- `GET /api/sessions` — список сессий (в демо без аутентификации)
- `GET /api/sessions/{id}/messages` — история
- `POST /api/sessions/{id}/close` — закрывает диалог, не удаляя историю
- `POST /api/chat` — `{"session_id":"...", "message":"..."}`
- `POST /api/leads` — `{"session_id":"...", "full_name":"...", "phone":"...", "company":"...", "consent_to_contact":true}`
- `GET /api/leads` — заголовок `X-Admin-Token: <ADMIN_TOKEN>`; без заданного ADMIN_TOKEN endpoint недоступен

## Подключение RAG участника №1

`backend/ai_adapter.py` подключён к согласованному синхронному `ai.consultant.answer_turn(message, history, session_facts, debug=False)`. Для включения задайте `AI_FUNCTION=ai.consultant:answer_turn` и путь к приватной БЗ/индексу. Адаптер передаёт историю и факты сессии, а в существующий HTTP-ответ преобразует:

```python
{"answer": "...", "sources": ["relative/document.md"], "intent": "unknown"}
```

Без AI_FUNCTION эндпоинт работает только в демонстрационном режиме и возвращает заглушку; реальные рекомендации отсутствуют.

Доступен локальный RAG baseline без дополнительных зависимостей. AI извлекает явно сообщённые тип организации и цель, а backend сохраняет полный `updated_facts` в SQLite по сессии. Прямой импорт, построение индекса и ограничения извлечения описаны в [документации AI-модуля](docs/AI_MODULE.md).

Для backend подготовлена [задача интеграции с критериями приёмки](docs/BACKEND_AI_TASK.md). Необязательная генерация и семантический Critic пока проверены на заглушках; предварительный разбор качества и команды будущего прогона на API описаны в [AI_QUALITY.md](docs/AI_QUALITY.md).

Для конкурсного `solution.py` доступен `answer_question(question, knowledge_base) -> str`. AI-модули экспортируются в плоскую структуру через `python -m scripts.export_ai_modules --output data/submission_ai`. Импорт из корня конкурсного ZIP: `from energytool_ai import answer_question`. Подробнее: [SUBMISSION_AI.md](docs/SUBMISSION_AI.md).

## Проверка

```bash
pip install pytest httpx
python -m pytest -q
```

## Важно для хакатона

- Конкурсный `solution.py` — отдельная точка входа из образца организаторов. Он читает `DATA_DIR/questions.csv`, `DATA_DIR/knowledge-base.zip`, формирует `submission.csv` и **не использует состояние SQLite между вопросами**.
- Не публикуйте базу знаний или ключи в открытом репозитории.
- Используйте только вымышленные контакты.
- Это демо: маршруты просмотра сессий не имеют авторизации, поэтому не размещайте его публично с реальными данными.
- Для production понадобятся авторизация, защита от злоупотреблений, полноценная политика обработки ПДн, механизм доставки заявок, retention и наблюдаемость.
