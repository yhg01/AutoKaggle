# AutoKaggle Lite: five published-task workflow tests

Completed on 5 November 2026. All five cases passed the deployed HTTP workflow. No model training occurred. These are workflow tests with measured sample outputs, not reproductions of published scientific baselines.

The later [ZIP contents audit](LITE_ZIP_AUDIT_2026-11-05.md) found packaging gaps. These runs supplied code and assets from separate local fixtures. Three selected task evaluators are absent from the downloaded ZIPs. The workflow checks do not establish that a recipient can run from the ZIP alone.

The [submitted-result reproduction audit](LITE_REPRODUCTION_AUDIT_2026-11-05.md) replayed all seven saved submissions, including earlier versions. Their 50 seeded outcomes matched using retained local files and environments. The portal does not yet preserve complete, retrievable reproduction bundles.

Live service: [BOLD AutoKaggle Lite](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite). Sign in with the approved `boldcoscientist@gmail.com` account to open these sessions. Other lab members require membership and session access.

The tests ran source imports and interviews in parallel through OpenRouter `openai/gpt-6.1-sol`, with medium reasoning. Five active application jobs were observed together. Each case used the normal API for proposals, acceptance, package creation, downloads and submission. The tests did not write final contracts directly into storage.

| Challenge and saved session | Fixed seeds | Measured sample |
| --- | ---: | --- |
| [Fashion-MNIST](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite?project=1611b864-c60b-40d5-a453-9706ff2a1be2) | 3 | Frozen class-zero predictions; 10% accuracy on all 10,000 test images. |
| [MiniGrid](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite?project=32844306-36ba-4a15-9e8e-35b812052118) | 12 | Frozen random-action policy; 6/12 goals reached. Six episodes reached the step limit. |
| [Concrete strength](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite?project=03aea678-c6de-45e9-a174-37f26a25f1cd) | 5 | Frozen 30 MPa predictions; mean RMSE 17.3314 MPa across five 309-row assessments. |
| [Pendulum](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite?project=a1317f4d-035b-4239-819b-e1586355eae7) | 10 | Frozen zero-torque policy; mean return −875.3491 across ten 200-step episodes. |
| [NetHack](https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite?project=b94cc3da-192f-4ccc-a05b-8c366184a56b) | 5 | Frozen untrained WAIT checkpoint; zero ascensions. All five episodes reached the 100-step limit. |

Each final review returned no open decisions. The ZIP included README.md, AGENTS.md, contract.json, the runner, adapter interface and submission schemas. The separately downloaded config matched the ZIP bytes. Every assigned seed had one result. Rebuilding an unchanged accepted experiment kept its seeds. The server rejected missing and duplicate seeds. Cases also checked incorrect seeds, metric bounds or horizon violations as applicable. Repeated requests reused the saved result. Fresh requests confirmed persistence. Anonymous config downloads were denied.

The portal marks these reports `evidence_checked` and `independently_reproduced=false`. It checks the submitted structure, seed coverage, version, hashes and score rules. It does not fetch and execute the submitted artifact. The tests executed the downloaded runners on existing local CPU resources, then submitted the real measurements to Civo. No GPU training or new compute node was used.

Published sources:

- Fashion-MNIST: [paper](https://arxiv.org/abs/1708.07747), [official repository](https://github.com/zalandoresearch/fashion-mnist). Public test answers were disclosed. The three seeds change evaluation order; they are not three independent training experiments.
- MiniGrid: [paper](https://arxiv.org/abs/2306.13831), [official repository](https://github.com/Farama-Foundation/Minigrid). The test used MiniGrid-Empty-Random-5x5-v0 and an explicit Python random-number generator for its fixed random policy.
- Concrete: [Yeh 1998 paper](https://doi.org/10.1016/S0008-8846(98)00165-3), [UCI dataset](https://archive.ics.uci.edu/dataset/165/concrete+compressive+strength), [official UCI client](https://github.com/uci-ml-repo/ucimlrepo). UCI metadata and the actual data were available. The paper landing page and author abstract did not supply usable text to the importer. The record states this limit. The five random subsets overlap and use public answers.
- Pendulum: [Gymnasium paper](https://arxiv.org/abs/2407.17032), [official repository](https://github.com/Farama-Foundation/Gymnasium). The protocol used Pendulum-v1, Gymnasium 1.2.0 and an explicit 200-step evaluation horizon.
- NetHack: [NLE paper](https://arxiv.org/abs/2006.13760), [official repository](https://github.com/NetHack-LE/nle). The test used released NLE 1.3.0, a saved PyTorch checkpoint and core/disp seeds. It required natural termination. Its five cutoffs correctly received zero success credit.

Changes made and deployed:

1. Added a separate config download. It uses the same access and stale-version checks as the ZIP.
2. Added a general finite-horizon policy. Pendulum exposed that a valid finite-horizon evaluation needs to complete at its declared step count. Early truncation and timeouts still fail. This change does not depend on an environment name.
3. Fixed the Lite deployment to supply the OpenRouter environment variable. The first five import requests stopped before a model response. Retry reused their saved sources and messages after the repair.
4. Added explicit open-decision tracking. MiniGrid exposed that text containing an unresolved RNG choice could previously count as complete. The agent now records the gap and reason. The UI shows them and permits partial progress. Builds and downloads remain blocked until resolution. Compatible updates cannot silently clear a gap. Optional baselines never block readiness.
5. Updated the prompt to use the actual manifest and result fields. Extra diagnostic fields belong in external logs, not unsupported JSON fields.
6. Added the Lite host default, preserved Lite destinations after sign-in, and configured five bounded workers. Each project retains its own write lock.

Friction and responsibility:

- MiniGrid initially had too little startup time for a cold dependency import. The test protocol increased the per-episode limit from five to fifteen seconds. This was a resource-setting correction.
- Proposed runtime details must match the actual machine. The tests corrected MiniGrid platform/package values and NetHack Python 3.12.16 through the interview before acceptance. The initial NetHack Python 3.11 description was a test-input error.
- URL import can be limited by publisher access. The Concrete case used the official dataset metadata and retained the citation without claiming to have read the full paper.
- Custom batch tasks still require a researcher-supplied adapter. The package generates its interface; it does not generate and validate arbitrary scientific evaluation code.
- An interview model can miss a scientific gap. The explicit gap gate prevents known unresolved choices from passing. Human review still matters.

Validation: 1,281 Python tests and 58 Lite/login client tests passed. Three existing numeric edge-case warnings were reported. The final deployment preserved all five sessions and their earlier reports. Full retained its existing deployment. The readiness release source digest is `6c008a62f2f31bb118b78a3103c57a281ad1095f89ed264886f08bb247264cc0`.

Live browser testing remains blocked. The browser site-permission gate rejected the local and deployed pages, including after chat approval. No sign-in email was sent. HTTP workflow tests and client behavior tests passed, but they do not establish a visual browser check or email delivery.

The fixed Lite seeds are visible. Public dataset answers remain public. These tests do not establish blind evaluation, resistance to adversarial submissions, or independent reproduction.

Final versions and evidence:

| Case | Contract version | Saved result |
| --- | --- | --- |
| Fashion-MNIST | `cea4a37f8eefcc1a7c78443d` | `1d5507f90152d06c24620188` |
| MiniGrid | `e7ae542ef58aef87ead994dc` | `7eb1f485b73f00e23912fc4d` |
| Concrete strength | `469e9260d27d04b0962cdc35` | `7a4735e1964dc2dd8d01eb43` |
| Pendulum | `1a86f041b1ee05d2cdde7495` | `88241752573d6ceba88e6c8c` |
| NetHack | `62ad65c42847d867f70a3d11` | `98ffa827d521503ee106e819` |

Exact fixed seeds:

- Fashion-MNIST: 728929402, 118263552, 293234673.
- MiniGrid: 41028856, 144095439, 240415069, 300878532, 840684539, 886049285, 855971907, 273998285, 422740862, 588764554, 727987351, 638499159.
- Concrete strength: 24714824, 682007614, 913729866, 906209262, 395976268.
- Pendulum: 950767408, 55130222, 478447348, 543376795, 289923140, 320940338, 150598842, 414053649, 857140802, 896947461.
- NetHack: 345749047, 591502173, 199952960, 670337150, 620767787.

Per-case receipts, measured records, archives and configs are saved under `autokaggle/test-results/lite-five-2026-11-05/`. That directory is ignored by Git and contains private test material. Do not publish it as a whole. Source and deployment instructions are in `autokaggle/docs/LITE.md` and `autokaggle/deploy/LITE_WEB.md`. No commit or push was made for this test task.
