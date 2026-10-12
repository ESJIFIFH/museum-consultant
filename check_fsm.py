import logging
from orchestrator import Orchestrator

logging.basicConfig(level=logging.INFO)

o = Orchestrator.__new__(Orchestrator)
o._state = {}

# Проверяем, правильно ли определяется интент сообщения.
phrases = [
    ("Как называется объект с инвентарным номером Ж-3335?", "question"),
    ("Из какого материала сделан портрет?", "question"),
    ("Перепроверь ответ и проверь источник.", "verify"),
    ("Ты уверен? Есть ли подтверждение в источнике?", "verify"),
    ("Помоги определить предмет, я не помню точное название.", "clarify"),
    ("Задай уточняющий вопрос, чтобы определить картину.", "clarify"),
    ("asdf qwerty", "question"),
]

print("ПРОВЕРКА ИНТЕНТОВ")

for i, (phrase, expected) in enumerate(phrases):
    intent = o.detect_intent(phrase)
    assert intent == expected, (
        f"Ожидался интент {expected}, получен {intent}"
    )

    role = o.route(f"phrase-{i}", intent)
    print(f"{phrase[:45]:<46} интент={intent:<8} роль={role}")


# Проверяем последовательную смену ролей в одной сессии.
print("\nПРОВЕРКА СМЕНЫ РОЛЕЙ")

session = "fsm-sequence"

sequence = [
    ("Как называется этот музейный предмет?", "analyst"),
    ("Перепроверь ответ и источник.", "verifier"),
    ("Помоги определить предмет, я не помню название.", "clarifier"),
    ("Что такое музейный предмет?", "analyst"),
]

for phrase, expected_role in sequence:
    intent = o.detect_intent(phrase)
    role = o.route(session, intent)

    assert role == expected_role, (
        f"Ожидалась роль {expected_role}, получена {role}"
    )

    print(f"интент={intent:<8} роль={role}")


# Проверяем, что запрещённый переход приводит к роли по умолчанию.
print("\nПРОВЕРКА ЗАПРЕЩЁННОГО ПЕРЕХОДА")

o.route("fsm-blocked", "question")
o.route("fsm-blocked", "verify")

role = o.route("fsm-blocked", "verify")

print("После повторного verify роль:", role)
assert role == o.FALLBACK_ROLE


# Проверяем обработку неизвестного интента.
print("\nПРОВЕРКА НЕИЗВЕСТНОГО ИНТЕНТА")

# Сначала переводим сессию в роль verifier.
o.route("fsm-unknown", "verify")

# Передаём неизвестный интент.
role = o.route("fsm-unknown", "unknown")

print("Роль после неизвестного интента:", role)

assert role == o.FALLBACK_ROLE, (
    f"Ожидалась роль по умолчанию {o.FALLBACK_ROLE}, получена {role}"
)


print("\nВсе проверки FSM пройдены.")
