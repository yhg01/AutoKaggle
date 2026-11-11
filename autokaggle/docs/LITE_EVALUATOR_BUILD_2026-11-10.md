# Lite evaluator build — 10 and 11 November 2026

The build and test workflow for Lite evaluators is implemented. Two live builds by the coding agent passed on 11 November, using DeepSeek. The OpenRouter route is kept as the default and was not exercised live: its account had about $2 of credit left, and its calls returned HTTP 401 on 10 November. GitHub publishing and the BOLD OS pages are not started.

## Live builds — 11 November

Entry path: local Lite server with `AUTOKAGGLE_LITE_PROVIDER=deepseek`. For each case, `onboard.py` sent the saved 5 November contract as a researcher message, the live interview proposed it, the accept request recorded it, and `POST .../lite/evaluator/build` started the build. The Pendulum artifact text was edited to describe only the policy file, because the evaluator release now supplies the loader. Model for the interview and the coding agent: `deepseek-v4-pro`, medium reasoning (DeepSeek `high`), thinking enabled. Coding agent: opencode 1.19.5 in the Docker build runtime.

| | Fashion-MNIST | Pendulum |
| --- | --- | --- |
| Artifact | Prediction CSV | Policy JSON, read by the release's `loader.py` |
| Contract version | `4472258c4cb748e47db2f8d8` | `e49a7e29c9282ca55a8fcb04` |
| Release | `v2`, commit `32166f1d90fc7284ae73c8cf1aa059d8de26f62f`; `v1` is `f75b81b3132aa62ea370b5ea9a0da35f21382e35` | `v1`, commit `b06bb94b72db2dee8ec1bc91cd1db4475a3189ac` |
| Agent run | `v1`: 219 s, 23 model requests. `v2`: 170 s, 21 requests | 302 s, 26 model requests |
| Dependencies and assets | Standard library; official files pinned at the contract commit (`v1` declares images and labels, `v2` labels only) | Five pinned packages; no assets |
| Valid example | All class zero: expected 0.1, fresh clone scored 0.1 | Zero torque: expected and scored −1134.544858079839 |
| Wrong example | All labels wrong: expected 0.0, scored 0.0 | Torque 2.0: expected and scored −1525.05644812013 |
| Invalid example | `v1`: wrong row count. `v2`: a label outside 0 to 9. No score | Torque outside [−2, 2]: no score |
| Fresh-clone test | 10 of 10 checks passed, Python 3.12.16, Linux arm64 container | 10 of 10 checks passed, same runtime |

The contract versions and seeds differ from 5 November, because these sessions have no imported source records. The two Fashion-MNIST builds made different implementation choices for the same contract and gave the same scores. Agent output varies between runs; the fresh-clone test is what makes a release acceptable.

### Independent check

The expected scores above were written by the same build job. These checks were made separately, from a new clone of each downloaded release on macOS with python.org Python 3.12:

- **Fashion-MNIST, both releases.** Each declared asset has the MD5 value named in the contract. The class-zero prediction file retained from 5 November scored 0.1, its saved result. A file made here with exactly 5,000 correct labels scored 0.5. A one-row file received no score.
- **Pendulum.** A separate Gymnasium rollout, run in the Python environment retained from 5 November and using none of the release files, was compared on the contract's ten seeds. Zero torque: −1134.5448580798482 from both. Torque 2.0: −1525.0564481201336 from both. Torque −0.5: −1277.2386274060827 from both. Torque 5 and a non-JSON file received no score. macOS and the Linux container agree to about 1e-11.

### Found and fixed during the live check

- `fetch_assets.py` failed on a python.org Python with no certificate store. It now also tries the certificate bundle shipped with pip, then the system `curl`. Certificates are always verified and every route keeps the SHA-256 check. The first Fashion-MNIST release predates this fix. The rebuilt `v2` downloaded its asset with its own `fetch_assets.py` on the Python that had failed.
- With the `zero` failure rule, `evaluate.py` printed fitness 0.0 for an artifact on which no seed completed. It now prints no fitness and the status `no_completed_seed`.
- The container and image names used the `USER` variable, which was wrong under the local service launcher. They now use the account that owns the process.

## Automated tests

- The complete Python suite passed, with 17 tests in `tests/test_lite_build.py`. 61 Lite and login client checks passed.
- With a stand-in agent that only writes the evaluator files, the pipeline passed in the local and Docker runtimes. Draft states, a contract change, the release file rules, the gateway limits, and provider selection are covered.
- Browser, 10 November: accepted contract, a blocker, a failed build with the provider's 401, and a ready release with working downloads. That contract was seeded and that release came from the stand-in agent.

## Not tested

- **The OpenRouter route, live.** It is unchanged code and its tests pass. A live interview or build with `openai/gpt-6.1-sol` still needs credit on that account.
- **A checkpoint with model weights.** The loader path worked for a JSON policy. No PyTorch case was run.
- **A browser view of a live build.** The live builds were started through the HTTP API.
- **Larger or private assets, source builds of dependencies, GitHub, and BOLD OS.**

## Repeat the live check

Put the provider key in the ignored `.env`, start Docker, then run from the repository root:

```sh
AUTOKAGGLE_LITE_PROVIDER=deepseek python -m autokaggle.run --port 8877 --env-file .env
python autokaggle/test-results/lite-build-2026-11-10/onboard.py fashion_mnist
python autokaggle/test-results/lite-build-2026-11-10/onboard.py pendulum
python autokaggle/test-results/lite-build-2026-11-10/status.py --wait
```

Omit `AUTOKAGGLE_LITE_PROVIDER` to use OpenRouter. Scripts, receipts, bundles, and local data are in the ignored `autokaggle/test-results/lite-build-2026-11-10/` directory.
