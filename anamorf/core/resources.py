"""ДИСЦИПЛИНА РЕСУРСОВ (ядро v2) — зовётся самой первой строкой main.

Замер 09.10.2026 через /api/diag/threads в тишине: Сайка ела 2.8 ядра,
из них ~2.5 — СЕМЬ безымянных нативных потоков по 36 % каждый. Это пул
ONNX Runtime с настройками по умолчанию: столько потоков, сколько ядер,
и «spinning» — поток не засыпает между задачами, а крутится вхолостую,
чтобы сэкономить микросекунды. Для сервера это разумно, для компаньона
на игровом ПК — нет: эти ядра нужны мозгу (эксперты MoE считаются на
процессоре) и самому человеку.

Что делаем для ВСЕХ моделей процесса разом, не трогая чужие пакеты:
  * ORT: intra_op ≤ core.ort_threads (2), без spinning;
  * torch: потоков ≤ core.torch_threads (2);
  * OpenMP: пассивное ожидание.
"""
import logging
import os

log = logging.getLogger("saika.core.res")
_DONE = {"ok": False}


def apply(cfg_get=None):
    if _DONE["ok"]:
        return
    _DONE["ok"] = True
    get = cfg_get or (lambda k, d: d)
    ort_n = int(get("core.ort_threads", 2))
    torch_n = int(get("core.torch_threads", 2))
    os.environ.setdefault("OMP_WAIT_POLICY", "PASSIVE")
    os.environ.setdefault("KMP_BLOCKTIME", "0")
    try:
        import onnxruntime as ort
        _orig = ort.InferenceSession.__init__

        def _init(self, path_or_bytes, sess_options=None, *a, **kw):
            so = sess_options or ort.SessionOptions()
            try:
                if not so.intra_op_num_threads or so.intra_op_num_threads > ort_n:
                    so.intra_op_num_threads = ort_n
                so.inter_op_num_threads = 1
                so.add_session_config_entry("session.intra_op.allow_spinning", "0")
                so.add_session_config_entry("session.inter_op.allow_spinning", "0")
            except Exception as e:
                log.debug("ORT опции: %s", e)
            return _orig(self, path_or_bytes, so, *a, **kw)
        ort.InferenceSession.__init__ = _init
        log.info("ресурсы: ONNX Runtime ≤ %d потоков, без холостого вращения", ort_n)
    except Exception as e:
        log.debug("ORT не тронут: %s", e)
    try:
        import torch
        if torch.get_num_threads() > torch_n:
            torch.set_num_threads(torch_n)
        log.info("ресурсы: torch ≤ %d потоков", torch_n)
    except Exception as e:
        log.debug("torch не тронут: %s", e)
