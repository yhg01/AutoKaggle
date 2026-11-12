# Lite ZIP contents audit — 5 November 2026

All five downloaded archives are valid and internally consistent. They are not complete, self-contained research bundles. Three omit the selected task evaluator. The earlier successful runs supplied extra files from local test folders.

This audit inspected the actual ZIP bytes saved by the five live workflows. It did not infer package contents from the generator or the website. No accepted challenge, deployed package, or saved result was changed.

| Challenge | Files | Seeds | Selected evaluator in ZIP | Exact dependency lock | Return link to portal |
| --- | ---: | ---: | --- | --- | --- |
| Fashion-MNIST | 12 | 3 | Missing: `fashion_adapter.py` | External | Missing |
| MiniGrid | 12 | 12 | Missing: `minigrid_adapter.py` | External | Missing |
| Concrete strength | 12 | 5 | Missing: `concrete_adapter.py` | External | Missing |
| Pendulum | 12 | 10 | Included: `gym_adapter.py` | External | Missing |
| NetHack | 12 | 5 | Included: `gym_adapter.py` | External | Missing |

Every archive contains:

```text
README.md
AGENTS.md
contract.json
ENVIRONMENT.md
run.py
gym_adapter.py
adapter.py
manifest.example.json
manifest.schema.json
results.example.json
results.schema.json
decision-evidence.json
```

The README records the objective, input/output contract, metric, failure rules, resource limits, sources and exposure policy. `contract.json` records the fixed seeds, contract version and evaluator digests. The examples contain explicit placeholders; they are not measured submissions. `adapter.py` is an implementation template that raises `NotImplementedError`.

Checks passed for every archive: ZIP integrity, safe relative member paths, exact expected member set, JSON parsing, Python syntax, schema syntax, contract digest, runner digests, unique seed coverage, and byte equality with the separate downloaded config. A scan found no known private key values, common credential patterns or email addresses. This scan is a bounded check, not proof against every possible secret format.

The material gaps are:

1. **Missing task evaluators.** Fashion-MNIST, MiniGrid and Concrete select custom adapter modules. Those modules were supplied from separate local test fixtures. They are absent from the ZIP and have no accessible pinned implementation reference in it. A recipient must obtain or implement them. Merely including the generic adapter template does not supply these evaluators.
2. **Conflicting setup instructions.** The generic batch instructions say to implement `adapter:evaluate`, but the batch contracts select other module names. The generic Gymnasium instruction points MiniGrid to `gym_adapter.py`, although its accepted protocol uses a custom adapter. Instructions must follow the selected entrypoint.
3. **Misleading manifest defaults.** Prediction examples still use `model.bin` and `policy:load`. These should reflect the selected artifact type. Concrete's example uses a dataset page as `code_repository`; that page is not a code checkout.
4. **No route back to the submission.** Each README says to use the Lite results control, but the ZIP has no session URL, project ID or API route. A saved package should identify its destination without carrying a login token.
5. **Manual environment preparation.** `ENVIRONMENT.md` records versions and explicitly says it is not an installable lock. The runner checks the supplied lock hash, but it does not install or compare the actual environment. A tested evaluator bundle needs a suitable lock and setup instructions, or an accessible pinned environment artifact.

Some external files are expected. Researchers supply their own predictions, policy or checkpoint, loading code, code commit and provenance. Large datasets can remain external when their source and version are explicit. Their absence does not make the archive corrupt. A challenge-owned evaluator is different: it should be supplied and tested so each recipient does not have to recreate the scoring implementation.

The next packaging change should include or pin the selected evaluator, add accurate setup and submission instructions, and generate examples for the selected artifact type. Then test from a fresh directory using only the downloaded package, declared external sources and a sample participant artifact. Do not use hidden local fixture files in that acceptance test. Keep a scoped contract distinct from a tested executable bundle.

Detailed inventory and hashes are in `autokaggle/test-results/lite-zip-audit-2026-11-05/inventory.json`. The original workflow results remain valid as tests with separately supplied local code and artifacts. They do not establish that the ZIP alone was sufficient.

A fresh live OpenRouter call used the current Lite agent with `openai/gpt-6.1-sol` at medium reasoning. Given the actual inventory and missing-adapter evidence, it retained the scientific protocol and flagged the unavailable evaluator. This was a review-only check. Its proposal was not applied to any live session. The response is saved as `live-model-review.json` beside the inventory. The model response supports the workflow check; the file audit above is the direct evidence.
