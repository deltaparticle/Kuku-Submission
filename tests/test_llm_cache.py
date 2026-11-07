"""LLM client behaviour that needs no network: caching, fresh stages, model fallback order, dead-model skip."""
import time

from promofinder.llm import LLM

CFG = {
    "providers": {"p": {"base_url": "http://x", "api_key_env": "NOPE", "retries": 1, "min_interval_s": 0}},
    "stages": {"score": {"provider": "p", "model": "m1", "fallback_models": ["m2"], "temperature": 0.0}},
}


class _Msg:
    def __init__(self, t): self.content = t


class _Resp:
    def __init__(self, t):
        self.choices = [type("C", (), {"message": _Msg(t)})()]
        self.usage = type("U", (), {"prompt_tokens": 3, "completion_tokens": 2})()


class FakeClient:
    def __init__(self, fail_models=()):
        self.calls, self.fail_models = [], set(fail_models)
        outer = self
        class _C:
            def create(self, **kw):
                outer.calls.append(kw["model"])
                if kw["model"] in outer.fail_models:
                    e = RuntimeError("busy"); e.status_code = 503; raise e
                return _Resp('{"ok": true}')
        self.chat = type("Chat", (), {"completions": _C()})()


def make(tmp_path, client, **kw):
    llm = LLM(CFG, cache_dir=tmp_path, **kw)
    llm._clients["p"] = client
    return llm


MSGS = [{"role": "user", "content": "hi"}]


def test_second_identical_call_is_served_from_cache(tmp_path):
    c = FakeClient(); llm = make(tmp_path, c)
    llm._raw("score", MSGS, 0.0); llm._raw("score", MSGS, 0.0)
    assert c.calls == ["m1"] and [x["cached"] for x in llm.calls] == [False, True]


def test_fresh_stage_bypasses_cache_but_other_stages_would_not(tmp_path):
    c = FakeClient(); make(tmp_path, c)._raw("score", MSGS, 0.0)      # populate cache
    c2 = FakeClient(); llm = make(tmp_path, c2, fresh_stages={"score"})
    llm._raw("score", MSGS, 0.0)
    assert c2.calls == ["m1"]                                          # called again despite the cache


def test_falls_back_to_next_model_and_caches_under_it(tmp_path):
    c = FakeClient(fail_models={"m1"}); llm = make(tmp_path, c)
    llm._raw("score", MSGS, 0.0)
    assert c.calls == ["m1", "m2"] and llm.calls[-1]["model"] == "m2"
    c2 = FakeClient(); llm2 = make(tmp_path, c2)                       # new process, same cache: no calls needed
    llm2._raw("score", MSGS, 0.0)
    assert c2.calls == [] and llm2.calls[-1]["cached"]


def test_dead_model_is_skipped(tmp_path):
    c = FakeClient(); llm = make(tmp_path, c)
    llm._dead["m1"] = time.time() + 3600
    llm._raw("score", MSGS, 0.0)
    assert c.calls == ["m2"]


def test_no_credit_stops_the_run_with_a_plain_message(tmp_path):
    import pytest
    from promofinder.llm import FatalProviderError

    class NoCredit(FakeClient):
        def __init__(self):
            super().__init__()
            outer = self

            class _C:
                def create(self, **kw):
                    outer.calls.append(kw["model"])
                    e = RuntimeError("Your prepayment credits are depleted."); e.status_code = 402; raise e
            self.chat = type("Chat", (), {"completions": _C()})()

    c = NoCredit(); llm = make(tmp_path, c)
    with pytest.raises(FatalProviderError, match="no credit left"):
        llm._raw("score", MSGS, 0.0)
    assert c.calls == ["m1"]                    # no retries, no fallback model: an account problem is not transient
    assert not issubclass(FatalProviderError, RuntimeError)   # so the stages cannot swallow it
