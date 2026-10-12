
"""
orchestrator.py — ядро системы: конечный автомат, переключающий роли агентов.

Практика 3:
  1. Описаны роли с разными зонами ответственности.
  2. Настроены INTENT_TO_ROLE и TRANSITIONS.
  3. Реализовано детерминированное определение интента.

Сквозной ответ будет реализован на П4.
"""

import logging

import guardrails
import memory
import prompts
from contracts import Chunk
from llm_client import build_client
from mcp_client import MCPTools

log = logging.getLogger(__name__)

BLOCKED_REPLY = (
    "Запрос отклонён слоем безопасности. "
    "Переформулируйте вопрос по существу темы."
)


class Orchestrator:
    """Оркестратор ролей на конечном автомате."""

    # Роли с разными зонами ответственности.
    ROLES: dict[str, dict] = {
        "analyst": {
            "description": (
                "Ищет сведения о музейных предметах в базе знаний, "
                "отвечает на вопросы о названии, инвентарном номере, "
                "материале, стране, периоде и описании объекта. "
                "Использует найденные фрагменты и указывает источники. "
                "Не подтверждает сведения, отсутствующие в найденных фрагментах."
            ),
            "temperature": 0.2,
            "filters": {},
        },
        "verifier": {
            "description": (
                "Проверяет, подтверждается ли конкретное утверждение "
                "о музейном предмете найденными фрагментами базы знаний. "
                "Отделяет подтверждённые сведения от неподтверждённых. "
                "Не выдаёт предположение за установленный факт "
                "и не подменяет проверку новым общим ответом."
            ),
            "temperature": 0.1,
            "filters": {},
        },
        "clarifier": {
            "description": (
                "Помогает уточнить, какой музейный предмет имеется в виду, "
                "если описания недостаточно для однозначного определения. "
                "Формулирует один конкретный уточняющий вопрос. "
                "Не угадывает предмет и не выдаёт неподтверждённые сведения."
            ),
            "temperature": 0.3,
            "filters": {},
        },
    }

    INITIAL_ROLE = "analyst"
    FALLBACK_ROLE = "analyst"

    # Граф разрешённых переходов между ролями.
    # Повторный переход verifier -> verifier запрещён.
    # Повторный переход clarifier -> clarifier запрещён.
    TRANSITIONS: dict[str, set[str]] = {
        "analyst": {"analyst", "verifier", "clarifier"},
        "verifier": {"analyst", "clarifier"},
        "clarifier": {"analyst", "verifier"},
    }

    # Интенты не совпадают с названиями ролей.
    INTENT_TO_ROLE: dict[str, str] = {
        "question": "analyst",
        "verify": "verifier",
        "clarify": "clarifier",
    }

    def __init__(self):
        self.tools = MCPTools()
        self.llm = build_client()
        memory.create_schema()
        self._state: dict[str, str] = {}
        self._context: dict[str, list[Chunk]] = {}
        self.usage: list[dict] = []

    def detect_intent(self, text: str) -> str:
        """
        Определяет интент реплики по ключевым словам.
        Не обращается к LLM, поэтому работает детерминированно.

        Возвращает один из интентов:
        question, verify, clarify.

        Для нераспознанной фразы возвращает question.
        """

        low = " ".join(text.lower().split())

        # Запросы на проверку и подтверждение фактов.
        verify_words = (
            "перепроверь",
            "перепроверьте",
            "проверь источник",
            "проверь источники",
            "проверь ответ",
            "проверьте ответ",
            "ты уверен",
            "вы уверены",
            "точно ли",
            "верно ли",
            "подтверди",
            "подтвердите",
            "есть ли подтверждение",
            "не ошибся",
            "не ошиблись",
        )

        if any(word in low for word in verify_words):
            return "verify"

        # Запросы на уточнение музейного предмета.
        clarify_words = (
            "помоги определить предмет",
            "помогите определить предмет",
            "не помню название",
            "не помню точное название",
            "не знаю, какой предмет",
            "не знаю какой предмет",
            "какой именно предмет",
            "какая именно картина",
            "задай уточняющий вопрос",
            "задайте уточняющий вопрос",
            "нужно уточнить, какой",
            "нужно уточнить какой",
            "не могу определить предмет",
        )

        if any(word in low for word in clarify_words):
            return "clarify"

        # Все остальные запросы обрабатываются аналитиком.
        return "question"

    def route(self, session_id: str, intent: str) -> str:
        """Переводит автомат в новое состояние и возвращает активную роль."""

        current = self._state.get(session_id, self.INITIAL_ROLE)
        target = self.INTENT_TO_ROLE.get(intent, self.FALLBACK_ROLE)

        allowed = self.TRANSITIONS.get(
            current,
            {self.FALLBACK_ROLE},
        )

        rolled_back = target not in allowed

        if rolled_back:
            log.warning(
                "Переход %s -> %s запрещён, откат в %s",
                current,
                target,
                self.FALLBACK_ROLE,
            )
            target = self.FALLBACK_ROLE

        if target != current:
            log.info(
                "Сессия %s: роль %s -> %s (интент %s%s)",
                session_id,
                current,
                target,
                intent,
                ", откат" if rolled_back else "",
            )

        self._state[session_id] = target
        return target

    def handle(self, session_id: str, text: str) -> str:
        """
        Единственная точка входа.
        Конвейер: guardrail -> память -> интент -> роль -> поиск через MCP ->
        сборка промпта -> LLM -> память -> ответ.
        """

        verdict = guardrails.check(text)

        if not verdict.allowed:
            guardrails.log_attempt(session_id, text, verdict)
            log.warning(
                "Сессия %s: запрос заблокирован (%s)",
                session_id,
                verdict.reason,
            )
            return BLOCKED_REPLY

        previous_role = self._state.get(
            session_id,
            self.INITIAL_ROLE,
        )

        intent = self.detect_intent(text)
        role = self.route(session_id, intent)
        role_config = self.ROLES[role]

        # Поиск выполняется через MCP-клиент.
        filters = role_config.get("filters") or {}

        if filters:
            chunks = self.tools.search_filtered(text, filters)
        else:
            chunks = self.tools.search(text)

        # Перенос найденного контекста при переключении роли.
        if role != previous_role:
            known = {
                (c.source, c.page, c.text[:80])
                for c in chunks
            }

            chunks = chunks + [
                c
                for c in self._context.get(session_id, [])
                if (c.source, c.page, c.text[:80]) not in known
            ]

        self._context[session_id] = chunks

        history = memory.window(session_id)

        # Сохраняем сообщение пользователя после чтения истории.
        memory.save(session_id, "user", text)

        messages = prompts.build_messages(
            role,
            text,
            chunks,
            history,
        )

        prompt_size = self.llm.count_tokens(
            "\n".join(m["content"] for m in messages)
        )

        log.info(
            "Сессия %s: роль %s, чанков %d, промпт ~%d токенов",
            session_id,
            role,
            len(chunks),
            prompt_size,
        )

        answer = self.llm.generate(
            messages,
            temperature=role_config["temperature"],
        )

        # Раздельный учёт входных и выходных токенов.
        self.usage.append(
            {
                "session_id": session_id,
                "role": role,
                "prompt_tokens": prompt_size,
                "completion_tokens": self.llm.count_tokens(answer),
            }
        )

        memory.save(session_id, "assistant", answer)
        return answer

    def reset(self, session_id: str) -> None:
        """Сбрасывает состояние автомата, контекст и историю сессии."""

        self._state.pop(session_id, None)
        self._context.pop(session_id, None)
        memory.clear(session_id)

    def close(self) -> None:
        """Закрывает MCP-клиент."""

        self.tools.close()