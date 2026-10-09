"""Bad model answers must be visible and never silently repaired into facts."""
import pathlib
import sys


def run():
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / 'genome' / 'pipeline'))
    from model_checks import evidence_error, parse_evidence
    from research import object_response
    good = dict(g='soc.caring', v=.6, c=.6, subject='Karen', type='dialogue',
                quote='I can help you.', reason='Offers help')
    results = []
    def check(name, value, expected): results.append((name, value == expected, str(value)))
    for name, change, expected in [
        ('выдуманная цитата', {'quote':'I will destroy you.'}, 'quote_not_found'),
        ('чужой персонаж', {'subject':'Peter'}, 'wrong_subject'),
        ('несуществующий ген', {'g':'fake.gene'}, 'unknown_gene'),
        ('коэффициент 99 не обрезается до правды', {'v':99}, 'range_v'),
        ('уверенность 100 процентов не принимается', {'c':1}, 'range_c'),
        ('NaN не число для генома', {'v':float('nan')}, 'invalid_v'),
        ('булево не коэффициент', {'v':True}, 'invalid_v'),
        ('строка вместо числа видна', {'v':'0.6'}, 'invalid_v'),
        ('нет обоснования', {'reason':''}, 'missing_reason')]:
        check(name, evidence_error(dict(good, **change), 'Karen', 'Karen: I can help you.', {'soc.caring'}), expected)
    check('правильная улика проходит', evidence_error(good, 'Karen', 'Karen: I can help you.', {'soc.caring'}), None)
    check('массив вместо улики не роняет процесс', evidence_error([], 'Karen', '', set()), 'row_not_object')
    check('неполная улика', evidence_error({'g':'soc.caring'}, 'Karen', '', set()), 'missing_fields')
    for answer, expected in [('sorry', 'invalid_json'), ('[{}', 'invalid_json'), ('{}', 'expected_array'), ('[]', None), ('```json\n[]\n```', None)]:
        check('разбор '+answer, parse_evidence(answer)[1], expected)
    check('объект в ответе с пояснением читается', object_response('Вот результат:\n{"certain":true}\nСпасибо')['certain'], True)
    check('первый валидный объект берётся без жадной склейки', object_response('{"certain":true}\n{"bad"}')['certain'], True)
    return results
