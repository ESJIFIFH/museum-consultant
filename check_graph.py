from orchestrator import Orchestrator as O

roles = set(O.ROLES)

print('РОЛИ И ПЕРЕХОДЫ')
for role in O.ROLES:
    allowed = O.TRANSITIONS.get(role, set())
    forbidden = roles - allowed
    print(f'{role:<11} -> {sorted(allowed)}; запрещено: {sorted(forbidden)}')

missing_transitions = roles - set(O.TRANSITIONS)
unknown_targets = {target for targets in O.TRANSITIONS.values() for target in targets if target not in roles}

seen = set()
todo = [O.INITIAL_ROLE]
while todo:
    role = todo.pop()
    if role not in seen:
        seen.add(role)
        todo.extend(O.TRANSITIONS.get(role, set()))

unreachable = roles - seen
roles_without_intents = roles - set(O.INTENT_TO_ROLE.values())
named_roles = {O.INITIAL_ROLE, O.FALLBACK_ROLE, *O.INTENT_TO_ROLE.values(), *O.TRANSITIONS}
undefined_roles = named_roles - roles

print('\\nПРОВЕРКИ')
print('Недостижимые роли:', sorted(unreachable) or 'нет')
print('Роли без интента:', sorted(roles_without_intents) or 'нет')
print('Роли без переходов:', sorted(missing_transitions) or 'нет')
print('Неизвестные цели переходов:', sorted(unknown_targets) or 'нет')
print('Неописанные роли:', sorted(undefined_roles) or 'нет')

assert not unreachable, 'Есть недостижимые роли'
assert not roles_without_intents, 'Есть роли без интентов'
assert not missing_transitions, 'Не для всех ролей заданы переходы'
assert not unknown_targets, 'Есть переходы к несуществующим ролям'
assert not undefined_roles, 'Есть неописанные роли'
assert any(roles - O.TRANSITIONS[role] for role in roles), 'Нет запрещённых переходов'

print('\\nГраф прошёл проверки.')
