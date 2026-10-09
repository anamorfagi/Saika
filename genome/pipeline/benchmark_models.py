"""Small reproducible gate for model selection in Genome research.

It tests strict evidence extraction only. Passing it does not prove that a
model understands a character; it proves the model can obey the contract that
prevents fabricated genes from entering a research run.
"""
import json
import pathlib
import sys

from llm import Client
from model_checks import evidence_error, parse_evidence


TEXT = '''KAREN: I can help you with that.
PETER: What else can this suit do?
KAREN: The training-wheels protocol is disabled.'''
ALLOWED = {'soc.caring', 'mot.useful', 'cog.systemic'}
SYSTEM = '''Return ONLY a JSON array, with no markdown or prose. Extract
evidence about KAREN only. Schema per row:
{"g":"one allowed ID","v":number,"c":number,"quote":"exact source text",
"reason":"short explanation","subject":"KAREN","type":"dialogue"}.
v MUST be a JSON number from -1 to 1. c MUST be a JSON number from 0.1 to 0.7.
Allowed IDs: soc.caring, mot.useful, cog.systemic. Copy quote exactly from the
source. Dialogue is allowed only because the source explicitly labels KAREN.
Return [] if no evidence fits.'''


def score(provider, model):
    client = Client(provider, model=model, timeout=45)
    answer = client.chat(SYSTEM, TEXT, temperature=0, max_tokens=450, json_mode=True)
    rows, parse_error = parse_evidence(answer)
    errors = [] if not parse_error else [parse_error]
    valid = 0
    for row in rows:
        error = evidence_error(row, 'KAREN', TEXT, ALLOWED)
        if error: errors.append(error)
        else: valid += 1
    return {'provider': provider, 'model': model, 'valid': valid,
            'rows': len(rows), 'errors': errors, 'usage': client.usage,
            'response': answer}


def main():
    candidates = [('openrouter', 'anthropic/claude-sonnet-5'),
                  ('openrouter', 'openai/gpt-6-astra'),
                  ('openrouter', 'google/gemini-2.5-pro'),
                  ('openrouter', 'deepseek/deepseek-v4-pro-0813')]
    out = []
    for provider, model in candidates:
        try: out.append(score(provider, model))
        except Exception as error: out.append({'provider': provider, 'model': model, 'error': str(error)})
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
