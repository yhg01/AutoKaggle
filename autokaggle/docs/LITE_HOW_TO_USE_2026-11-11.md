# AutoKaggle Lite: how to use it

For Kaito. 11 November 2026.

Lite turns a paper or repository into a tested evaluator that any collaborator can run. You describe the experiment, accept a contract, and Lite builds scoring code for it. A collaborator then clones one repository, supplies their own predictions, policy, or checkpoint, and runs one command to get the fitness.

## Where it runs

| | Hosted Lite on Civo | Lite on your own machine |
| --- | --- | --- |
| Interview, contract, research package, result upload | Yes | Yes |
| Build evaluator | No. Builds need Docker and the hosted server has none | Yes |
| Publish to GitHub | No. It needs a built evaluator first | Yes |

Use your own machine for anything that involves an evaluator. The hosted site is at <https://lite.ecc962fa-2f4c-4a3f-96c4-179af273fb7a.k8s.civo.com/lite>. It still runs the 9 November release, which has no Evaluator control.

## Access you need from Yuhe

1. Read access to `yhg01/AutoKaggle`. The work is on the branch `internal-autokaggle-lite`, in pull request 16.
2. A model provider key, shared through a password manager. DeepSeek is the one that has been run live.
3. For hosted Lite only: your lab email on the Lite member list. Signing in with a verified email is not enough by itself.
4. To see the two example evaluators: collaborator access to the private repositories named under **Examples**.

## Set up on your machine

You need Python 3.11 or later, Git, Docker running, and the `gh` command signed in to GitHub.

```sh
git clone https://github.com/yhg01/AutoKaggle.git && cd AutoKaggle
git checkout internal-autokaggle-lite
python -m venv .venv && . .venv/bin/activate
python -m pip install -r autokaggle/requirements.txt
```

Create a file named `.env` in the repository root with one line, `DEEPSEEK_API_KEY=` followed by the key. Git ignores this file. Keep the key out of chat, documents, and commits.

Start Lite:

```sh
AUTOKAGGLE_LITE_PROVIDER=deepseek AUTOKAGGLE_LITE_GITHUB_OWNER=YOUR_GITHUB_NAME python -m autokaggle.run --port 8877 --env-file .env
```

Open <http://127.0.0.1:8877/lite>. Leave out `AUTOKAGGLE_LITE_GITHUB_OWNER` if you do not want the publishing control.

## From a paper to a scored artifact

1. **Start a session.** Select **Start a research session**, enter your email, and accept storage.
2. **Give it the sources.** Add a paper link, a text PDF, a public repository, or several. State the research question.
3. **Review the proposed contract.** It covers six groups: objective, data or environment, submitted artifact, evaluation, resources, and reproduction. Correct anything wrong in the chat. Select **Accept** when it is right. Nothing is fixed until you accept.
4. **Build the evaluator.** Open **Evaluator** and select **Build evaluator**. A coding agent writes the scoring code in a disposable container, then Lite tests it from a fresh clone. Expect 3 to 5 minutes. The first build on a machine also prepares the container image, which takes a few more minutes.
5. **Read the outcome.**
   - **Ready:** the release passed all ten fresh-clone checks. The dialog shows the commit, the example artifact, and its expected and measured fitness.
   - **Draft, a decision is needed:** the contract leaves a scoring question open. Answer it in the chat, accept the updated contract, and build again.
   - **Draft, the build did not pass:** the dialog states the cause. Build again after fixing it.
6. **Publish.** Select **Publish to GitHub**. Lite creates one private repository for the problem under the owner you set, pushes the tested commit unchanged, and shows the address. Publishing again after a rebuild adds the new version to the same repository.
7. **Score an artifact.** Anyone with access to the repository runs the commands in its README:

   ```sh
   git clone REPOSITORY_ADDRESS evaluator && cd evaluator && git checkout v1
   python -m venv .venv && . .venv/bin/activate
   python -m pip install -r requirements.lock
   python fetch_assets.py
   python evaluate.py --artifact PATH --output results.json
   ```

   The last output line is JSON with `fitness`. Exit status 0 means a complete score, 2 means no completed score, and 1 means the release or inputs are not usable. Run it from an unmodified clone.
8. **Report the result.** Upload `results.json` through **Results** in the same Lite session.

## Examples

Two problems have been taken through every step, including a clone from GitHub. Both repositories are private under `yhg01` and are trial copies.

| Problem | Artifact | Repository | Sample and fitness |
| --- | --- | --- | --- |
| Fashion-MNIST test accuracy | Prediction CSV | `yhg01/lite-eval-fashion-mnist-f72b6091`, `v3` | All class zero: 0.1 |
| Pendulum mean return | Policy JSON | `yhg01/lite-eval-pendulum-f1db9f76`, `v2` | Zero torque: -1134.5449 |

## Things to know before you rely on it

- **A changed contract needs a new build.** The evaluator is bound to one contract version. After a correction, the old release is kept and marked as belonging to the earlier contract.
- **Check each example's basis.** The expected scores come from a separate calculation written in the same build. Both examples above were also checked by hand, but a new problem has only the build's own check until someone repeats it.
- **Only simple problems have been run.** A checkpoint with real model weights, a custom environment, and large or private assets are untested.
- **The seeds are visible.** Lite is for trusted lab work. A matching score does not show how an artifact was trained.
- **A build costs model tokens.** A build has used 0.7 to 1.0 million input tokens. The limits are 30 minutes and 150 model requests.
- **Nothing is published under `bold-lab-ai` yet.** Repository access for collaborators, the lab template, and the BOLD OS Problem Bank link are not built.
- **OpenRouter has not been run live for builds.** Leave out `AUTOKAGGLE_LITE_PROVIDER` and use `OPENROUTER_API_KEY` to select it.

## Where to read more

- `autokaggle/docs/LITE.md`: the full Lite reference, including **Build evaluator**, **Publish to GitHub**, and the API.
- `autokaggle/docs/LITE_EVALUATOR_BUILD_2026-11-10.md`: what was tested live, with commits and scores.
- `autokaggle/deploy/LITE_WEB.md`: the hosted deployment.
