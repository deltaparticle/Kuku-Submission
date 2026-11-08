"""A model that hangs must not hold up the run: the client switches to the fallback after one timeout and skips the
hung model for the rest of the run (this is what kept the free-key web demo stuck on the story bible)."""
from pathlib import Path

from snipdeck.llm import LLM, HTTPError, load_config

ROOT = Path(__file__).resolve().parents[1]


def test_timeout_switches_model_at_once_and_is_remembered(tmp_path):
    cfg = load_config(ROOT / "config.yaml", "free_tier")
    cfg["providers"]["gemini"]["min_interval_s"] = 0
    llm = LLM(cfg, cache_dir=tmp_path, api_keys={"gemini": "test"}, log=lambda m: None)
    tried = []

    async def fake_transport(prov, pcfg, kwargs):
        tried.append(kwargs["model"])
        if kwargs["model"] == "gemini-3.8-flash":
            raise HTTPError(None, "request timed out after 90 s")
        return '{"ok": true}', 1, 1, 2

    llm._transport = fake_transport
    msgs = [{"role": "user", "content": "first"}]
    assert llm._raw("bible", msgs, 0.0) == '{"ok": true}'
    assert tried == ["gemini-3.8-flash", "gemini-3.7-flash"]      # one timeout, no retries on the hung model

    tried.clear()
    llm._raw("bible", [{"role": "user", "content": "second"}], 0.0)
    assert tried == ["gemini-3.7-flash"]                          # the hung model is skipped for the rest of the run
