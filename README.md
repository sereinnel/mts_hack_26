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

Укажите `AI_FUNCTION=src.energytool.consultant:consult` или другой **реальный** импортируемый путь и сделайте пакет доступным для Python (проекту может потребоваться добавить модули в Dockerfile и зависимости в requirements.txt). Функция может быть `def` или `async def`, принимает `question, history` и возвращает:

```python
{"answer": "...", "sources": ["22-askue.md"], "intent": "energy_accounting"}
```

Без AI_FUNCTION эндпоинт работает только в демонстрационном режиме и возвращает заглушку; реальные рекомендации отсутствуют.

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
