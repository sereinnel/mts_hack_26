# EnergyTool — AI-консультант по энергетике

Веб-приложение для консультаций бизнеса по энергоснабжению, учёту электроэнергии и снижению затрат. Разработано в рамках кейса МТС на Hack&Change 2026. Ответы строятся на базе знаний EnergyTool с использованием RAG.

## Возможности

- Поиск по базе знаний и ответы с указанием источников.
- Диалог с сохранением истории и контекста отдельной сессии.
- Сбор заявок на консультацию с согласием на обратную связь и защитой от дубликатов.
- Диагностика AI: использованные документы, маршрут обработки и время ответа.

## Стек

**Frontend:** HTML, CSS, JavaScript.  
**Backend:** Python, FastAPI, SQLite.  
**AI:** RAG, Planner / Consultant / Critic, OpenAI-совместимый API.  
**Инфраструктура:** Docker Compose.

## Запуск

Нужны Docker Compose, Node.js и файл `knowledge-base.zip` из материалов кейса.

```bash
git clone https://github.com/sereinnel/mts_hack_26.git
cd mts_hack_26
cp .env.example .env
mkdir -p data
```

Поместите базу знаний в `data/knowledge-base.zip` и задайте в `.env`:

```dotenv
AI_FUNCTION=ai.consultant:answer_turn
AI_MODE=extractive
AI_KB_PATH=/app/data/knowledge-base.zip
```

Запустите backend:

```bash
docker compose up -d --build
```

В отдельном терминале запустите интерфейс:

```bash
cd frontend
npm run dev
```

**Веб-интерфейс:** http://127.0.0.1:5173  
**Swagger API:** http://127.0.0.1:8000/docs

Для работы через LLM задайте `AI_MODE=llm`, `LLM_BASE_URL`, `LLM_API_KEY` и `LLM_MODEL` в `.env`.

Документация по API: [docs/API_CONTRACT.md](docs/API_CONTRACT.md). В репозитории также находится `solution.py` для обработки вопросов из CSV.

База знаний, локальные данные и ключи доступа в публичный репозиторий не включены.
