"""Regression: query is not the name; quotes must exist; sources are observable."""
import json
import pathlib
import sys
import tempfile


def run():
    root = pathlib.Path(__file__).resolve().parents[1] / 'genome'
    sys.path.insert(0, str(root / 'pipeline'))
    from research import ResearchJob, VALID
    results = []
    text = 'Karen: I can help you work through this problem calmly.\n' * 12

    class Model:
        def chat(self, system, user, **kwargs):
            if 'Распознай' in system:
                return json.dumps({'name':'Karen','aliases':['Карен'],'work':'Test film','kind':'ии',
                                   'certain':True,'queries':['Karen Test film transcript']})
            if 'Выбери релевантные' in system: return '{"indices":[0]}'
            if 'Проверь, что' in system:
                return json.dumps({'relevant':True,'quote':'Karen: I can help you work through this problem calmly.'})
            if 'Сформируй до трёх' in system: return '{"queries":[],"reason":"already resolved"}'
            if 'следующий шаг' in system: return '{"reason":"No new scenes","queries":[]}'
            if 'Составь краткий' in system:
                return '{"claims":[{"text":"Предлагает помощь в решении задачи.","evidence":[0]}]}'
            return json.dumps([
                {'g':'soc.caring','v':.6,'c':.6,'subject':'Karen','type':'dialogue','quote':text.splitlines()[0],'reason':'Offers help'},
                {'g':'soc.caring','v':1,'c':1,'subject':'Karen','type':'dialogue','quote':'This quote does not exist in the source','reason':'Invented'}])

    with tempfile.TemporaryDirectory() as folder:
        job = ResearchJob('ИИ в костюме, а не настоящее имя', root=folder, client=Model(),
                          search=lambda q:[{'url':'https://example.org/script','title':'Script','snippet':'Karen'}], fetch=lambda u:text)
        initial = job.snapshot()
        results.append(('запрос не становится именем персонажа', initial['card']['meta']['name'] != job.query, 'пока идёт поиск, имя неизвестно'))
        job.run()
        snap = job.snapshot()
        results.append(('малый корпус не публикуется как персонаж', snap['state']=='insufficient' and not (pathlib.Path(folder)/'share'/f'{job.id}.genome.json').exists(), snap['state']))
        results.append(('выдуманная цитата не становится уликой', len(job.evidence)==1, str(len(job.evidence))))
        results.append(('живой журнал содержит поиск, чтение, улику и проверку пробелов', {'search','fetch','source','evidence','gaps','insufficient'} <= {e['stage'] for e in snap['events']}, 'настоящие события тестового конвейера'))
        results.append(('каноническое имя приходит из распознавания', snap['card']['meta']['name']=='Karen', snap['card']['meta']['name']))
        results.append(('подтверждённое описание попадает в компилятор', 'Предлагает помощь в решении задачи.' in snap['card']['meta']['identity'], 'identity содержит тезис с уликой'))
        results.append(('образец речи использует поле компилятора t', snap['card']['meta']['samples'][0]['t']==text.splitlines()[0], 'цитата сохранена без пересказа'))
        results.append(('курсор не повторяет уже выданные события', not job.snapshot(snap['next'])['events'], 'последующий опрос пуст'))
        q2 = 'I can help you work through this problem calmly.'
        job.accept({'g':'soc.caring','v':.5,'c':.6,'subject':'Karen','type':'dialogue','quote':q2,'reason':'Offers help'}, job.sources[0], text, VALID)
        results.append(('два фрагмента одной страницы не удваивают уверенность', job.card['genome']['soc.caring'][1]==.6, str(job.card['genome']['soc.caring'][1])))
        before = len(job.evidence)
        job.accept({'g':'soc.caring','v':.9,'c':.7,'subject':'Peter','type':'dialogue','quote':q2}, job.sources[0], text, VALID)
        results.append(('реплика другого персонажа отклоняется', len(job.evidence)==before, 'subject не совпадает'))
        job.audit_batch('not json', job.sources[0], text, VALID)
        job.audit_batch('[]', job.sources[0], text, VALID)
        results.append(('ошибка JSON видна в диагностике', job.quality['errors'].get('invalid_json') == 1, str(job.quality)))
        results.append(('пустой ответ учитывается отдельно', job.quality['empty'] >= 1, str(job.quality['empty'])))
        reports = [json.loads(line) for line in (job.directory/'model_checks.jsonl').read_text(encoding='utf-8').splitlines()]
        results.append(('сохранены ответ модели и исходный фрагмент', reports[-2]['response']=='not json' and reports[-2]['source_text']==text, 'воспроизводимая диагностика'))
        stopped = ResearchJob('test', root=folder, client=Model(), search=lambda q:[], fetch=lambda u:text)
        stopped.cancelled.set(); stopped.run()
        results.append(('остановка завершается без придуманного результата', stopped.state=='cancelled' and stopped.done, stopped.state))
        class AmbiguousModel(Model):
            def __init__(self): self.identifications = 0
            def chat(self, system, user, **kwargs):
                if 'Распознай' in system:
                    self.identifications += 1
                    if self.identifications == 1: return '{"certain":false,"reason":"too broad"}'
                    return json.dumps({'name':'Karen','aliases':['Карен'],'work':'Test film','kind':'ии','certain':True,'queries':[]})
                if 'Сформируй до трёх' in system: return '{"queries":["Karen Test film AI transcript"],"reason":"narrowed"}'
                return super().chat(system, user, **kwargs)
        ambiguous = ResearchJob('AI in Spider suit', root=folder, client=AmbiguousModel(),
                                search=lambda q:[{'url':'https://example.org/second','title':'Transcript','snippet':'Karen'}], fetch=lambda u:text)
        ambiguous.run()
        stages = {e['stage'] for e in ambiguous.events}
        results.append(('неоднозначный запрос получает второй поиск до отказа', ambiguous.state=='insufficient' and 'disambiguate' in stages, ambiguous.state))
    return results
