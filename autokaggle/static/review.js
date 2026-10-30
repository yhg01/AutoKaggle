"use strict";
(() => {
  const open = document.getElementById("open-review");
  if (open) {
    const token = new URLSearchParams(location.hash.slice(1)).get("token") || "";
    history.replaceState(null, "", location.pathname);
    const status = document.getElementById("review-status");
    open.disabled = !token;
    if (!token) status.textContent = "Open the complete link from your invitation email.";
    open.addEventListener("click", async () => {
      open.disabled = true; status.textContent = "Opening your private review…";
      try {
        const response = await fetch("/api/review/exchange", {credentials: "same-origin", method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({token})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "The link could not be opened.");
        location.assign(data.redirect);
      } catch (error) { status.textContent = error.message; open.disabled = false; }
    });
  }
  const submit = document.getElementById("submit-predictions");
  if (submit) {
    const result = document.getElementById("submission-result");
    const container = document.getElementById("submission");
    const newAttempt = document.getElementById("new-submission-attempt");
    const attempts = new Map();
    const storageKey = () => `autokaggle-draft-upload:${container.dataset.project}:${container.dataset.version}`;
    function savedAttempt(key) {
      if (attempts.has(key)) return attempts.get(key);
      let saved = null;
      try {
        const value = JSON.parse(sessionStorage.getItem(key));
        if (typeof value?.fingerprint === "string" && typeof value?.id === "string") saved = value;
      } catch (_) {}
      attempts.set(key, saved);
      return saved;
    }
    function rememberAttempt(key, value) {
      // Memory remains authoritative if browser storage is blocked or full.
      attempts.set(key, value);
      try {
        if (value) sessionStorage.setItem(key, JSON.stringify(value));
        else sessionStorage.removeItem(key);
      } catch (_) {}
    }
    if (newAttempt) {
      newAttempt.hidden = true;
      newAttempt.addEventListener("click", () => {
        if (submit.disabled) return;
        rememberAttempt(storageKey(), null);
        newAttempt.hidden = true;
        result.textContent = "Ready for a new attempt. Your next submission will count toward today's allowance.";
      });
    }
    submit.addEventListener("click", async () => {
      const codeMode = container.dataset.type === "code";
      const file = document.getElementById("prediction-file").files[0];
      if (!file) { result.textContent = codeMode ? "Choose a Python file first." : "Choose a prediction CSV first."; return; }
      if (file.size > (codeMode ? 262144 : 5000000)) { result.textContent = codeMode ? "Python files must be at most 256 KiB." : "Prediction files must be at most 5 MB."; return; }
      submit.disabled = true;
      if (newAttempt) newAttempt.hidden = true;
      result.textContent = codeMode
        ? "Running the code on Civo. Storage setup and cleanup can take several minutes. Keep this page open for the result."
        : "Checking predictions and calculating the development score…";
      try {
        const csv = await file.text();
        const key = storageKey();
        const fingerprint = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(csv)))).map(x => x.toString(16).padStart(2,"0")).join("");
        const prior = savedAttempt(key);
        const request_id = prior?.fingerprint === fingerprint ? prior.id : crypto.randomUUID();
        rememberAttempt(key, {fingerprint, id: request_id});
        const response = await fetch(`/api/projects/${container.dataset.project}/workflow/${codeMode ? "code-submissions" : "submissions"}`, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify({request_id, [codeMode ? "source_code" : "predictions_csv"]: csv})});
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || "Submission failed.");
        result.textContent = data.status === "scored" ? `${data.metric}: ${data.score}. ${data.remaining_today} submissions remain today. ${data.detail}` : data.detail;
        if (newAttempt && ["scored", "invalid", "failed", "interrupted"].includes(data.status)) {
          newAttempt.hidden = false;
          result.textContent += " Choose New attempt to submit this file again. The next submission will count toward today's allowance.";
        }
      } catch (error) { result.textContent = error.message; } finally { submit.disabled = false; }
    });
  }
  const tokenButton = document.getElementById("create-submission-token");
  if (tokenButton) tokenButton.addEventListener("click", async () => {
    tokenButton.disabled = true;
    const output = document.getElementById("submission-token");
    try {
      const project = document.getElementById("submission").dataset.project;
      const response = await fetch(`/api/projects/${project}/workflow/access`, {method: "POST"});
      const data = await response.json();
      if (!response.ok) throw new Error(data.detail || "Access could not be created.");
      output.textContent = `AUTOKAGGLE_SUBMISSION_TOKEN=${data.token}\nSubmission URL: ${location.origin}${data.submission_url}\n${data.detail}`;
    } catch (error) { output.textContent = error.message; } finally { tokenButton.disabled = false; }
  });
})();
