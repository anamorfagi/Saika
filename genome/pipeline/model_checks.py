"""Deterministic diagnostics, not an LLM judge or a claim of semantic truth."""
import json
import math
import re


def parse_evidence(answer):
    """Строгий json_mode отдаёт объект, свободный режим — массив. Принимаем оба,
    но по-прежнему ничего не чиним: сломанный ответ остаётся сломанным."""
    if not isinstance(answer, str):
        return [], 'response_not_text'
    # A valid array is often followed by a prose explanation. Read the first
    # independently valid array but never repair any of its evidence rows.
    decoder = json.JSONDecoder(); saw_object = False
    broken_array = answer.lstrip().startswith('[')
    for match in re.finditer(r'[\[{]', answer):
        try: value, _ = decoder.raw_decode(answer[match.start():])
        except ValueError: continue
        if isinstance(value, list): return value, None
        if isinstance(value, dict):
            # {"evidence": [...]} — законная обёртка строгого режима, а не промах модели
            for key in ('evidence', 'items', 'rows', 'result', 'data'):
                if isinstance(value.get(key), list): return value[key], None
            saw_object = True
    return [], 'invalid_json' if broken_array else ('expected_array' if saw_object else 'invalid_json')


def голое(строка):
    """Только буквы и цифры в нижнем регистре.

    «J.A.R.V.I.S.» и «JARVIS» — один персонаж, но точное сравнение их не сводит.
    18.09 из-за этого улики по Джарвису отбраковывались пачками: модель писала
    имя так, как оно стоит в сценарии, а фильтр ждал имя из карточки.
    """
    return re.sub(r'[^0-9a-zA-Zа-яёА-ЯЁ]+', '', строка or '').lower()


def подписан_в_тексте(text, ключи):
    """Есть ли в источнике строка, подписанная этим персонажем."""
    for подпись in re.findall(r'(?m)^[\s\-—*:>\[]{0,4}([^\n:：—]{1,40})[:：—]', text):
        подпись = re.sub(r'\([^)]{0,40}\)', '', подпись)
        if голое(подпись) in ключи:
            return True
    return False


def evidence_error(e, subject, text, allowed, имена=None):
    if not isinstance(e, dict): return 'row_not_object'
    if not {'g', 'v', 'c', 'quote', 'reason', 'subject', 'type'} <= e.keys(): return 'missing_fields'
    if not isinstance(e['g'], str) or e['g'] not in allowed: return 'unknown_gene'
    ключи = {голое(n) for n in (имена or [subject]) if n}
    if голое(e['subject']) not in ключи: return 'wrong_subject'
    if e['type'] not in ('dialogue', 'behavior', 'description'): return 'unknown_evidence_type'
    if not isinstance(e['reason'], str) or not e['reason'].strip(): return 'missing_reason'
    q = e['quote']
    if not isinstance(q, str) or not 8 <= len(q.strip()) <= 400: return 'quote_length'
    if ' '.join(q.split()).casefold() not in ' '.join(text.split()).casefold(): return 'quote_not_found'
    if e['type'] == 'dialogue':
        # Model-declared subject is not speaker attribution. Accept dialogue
        # only when the source itself labels this speaker.
        if not подписан_в_тексте(text, ключи): return 'unattributed_dialogue'
    for field, lo, hi in [('v', -1, 1), ('c', .1, .7)]:
        val = e[field]
        if isinstance(val, bool) or not isinstance(val, (float, int)) or not math.isfinite(val): return 'invalid_' + field
        if not lo <= val <= hi: return 'range_' + field
    return None


LABELS = {
    'response_not_text': 'ответ не является текстом', 'invalid_json': 'сломанный JSON',
    'expected_array': 'вместо массива другая структура', 'row_not_object': 'улика не является объектом',
    'missing_fields': 'не хватает обязательных полей', 'unknown_gene': 'несуществующий ген',
    'wrong_subject': 'другой персонаж', 'unknown_evidence_type': 'неизвестный тип улики',
    'missing_reason': 'нет объяснения связи с геном', 'quote_length': 'неподходящая длина цитаты',
    'quote_not_found': 'цитаты нет в данном фрагменте', 'invalid_v': 'коэффициент не число',
    'invalid_c': 'уверенность не число', 'range_v': 'коэффициент вне −1…1',
    'range_c': 'уверенность вне 0.1…0.7', 'unattributed_dialogue': 'у реплики нет разметки говорящего в источнике',
    'duplicate': 'повтор уже принятой улики'}
