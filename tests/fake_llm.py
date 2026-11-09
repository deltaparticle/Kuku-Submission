"""Deterministic stand-in for LLM so the pipeline wiring can be tested without an API key."""
import re

from snipdeck.heuristics import propose
from snipdeck.schemas import (CandidateBatch, MontageBatch, RankItem, RankResult, ScoreBatch, ScoreItem)
from snipdeck.stages import ShowSummary


class FakeLLM:
    def __init__(self, eps, rules):
        self.eps = {e.num: e for e in eps}
        self.rules = rules
        self.calls = []

    def json(self, stage, system, user, schema, **kw):
        self.calls.append(stage)
        if schema is ShowSummary:
            return ShowSummary(premise="synthetic show")
        if schema is CandidateBatch:
            nums = [int(n) for n in re.findall(r"=== EPISODE (\d+)", user)]
            cands = [c for n in nums for c in propose(self.eps[n], self.rules, per_episode=2)]
            return CandidateBatch(candidates=cands)
        if schema is ScoreBatch:
            ids = re.findall(r"^### ((?:P|M)\d+)", user, flags=re.M)
            return ScoreBatch(scores=[ScoreItem(id=i, hook_3s=3 + k % 3, standalone=4, cliffhanger=3 + k % 2,
                                                intensity=3, plot_relevance=4, trope_fit=4,
                                                ad_policy_risk=(k == 0))
                                      for k, i in enumerate(ids)])
        if schema is RankResult:
            ids = re.findall(r"^(P\d+) \|", user, flags=re.M)
            return RankResult(ranking=[RankItem(id=i, reason="fake") for i in sorted(ids)])
        if schema is MontageBatch:
            return MontageBatch(montages=[])
        if schema.__name__ == "_Payoffs":
            return schema(late_payoffs=[])
        raise AssertionError(schema)

    def summary(self):
        return {"total_calls": len(self.calls), "cache_hits": 0, "by_stage": {}}
