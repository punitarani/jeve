"""The eval harness: realism, depth and quality as numbers (EVAL-0001).

`make evals` runs the same world under several *arms* — the rules twin, Jev,
Jev with one LLM role added — over dev seeds and held-out seeds, each on a
database of its own, and measures every world the same way:

* **plausibility** — stylized facts against stated real-world priors, each
  with its source (`priors.py`);
* **depth** — whether traits, memory and conversation change what people do
  (`metrics.py`, reusing the field report's detectors);
* **believability** — a blinded pairwise judge from a different model family,
  on transcripts rendered from typed records, validated first on planted
  defects (`transcripts.py`, `judge.py`);
* **non-regression** — the soak's invariants, determinism, and cost per
  sim-day.

It sits outside the layers (CORE-0008): it drives `sim`'s one run loop, reads
`api`'s detectors and calls models through `llm`, and nothing imports it. No
number it writes is ever read back by the world.
"""
