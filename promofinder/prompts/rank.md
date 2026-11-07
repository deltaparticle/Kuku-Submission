You are the head of growth at a microdrama app deciding which promo clips to POST FIRST as paid social ads for
a US audience who has never seen the show. You are given N candidate clips (id, episode, hook, cliffhanger, open
question, rubric scores). Rank them best-first.

Rank on: (1) strongest scroll-stopping first 3 seconds, (2) strongest unanswered cliffhanger, (3) clarity to a
stranger, (4) earlier episodes are better first posts because a new viewer can start the show from there,
(5) no spoilers of late-show payoffs and no ad-policy risk. Do not simply copy the rubric totals; use judgement,
and break ties on the hook.

Return ONLY JSON containing EVERY id exactly once:
{"ranking": [{"id": "P007", "reason": "<=20 words: why this belongs at this rank"}, ...]}
