"""Explicit synthetic decisions for workflow integration fixtures."""
from autokaggle import conversation
from autokaggle.readiness import REQUIRED_FIELDS, REQUIREMENTS, SERVER_FIELDS


DECISIONS = {
    "question": {
        "scope": "Predict stable versus unstable for synthetic material samples before the stress test; clinical use is outside scope.",
        "value": "The benchmark tests whether composition can reduce the number of simulated stress tests.",
        "success": "A balanced accuracy of at least 0.75 on independent material samples is a useful result.",
    },
    "task": {
        "inputs": "Each row describes one synthetic material using numeric composition fractions and its measured density; sample_id is not a feature.",
        "outputs": "Return one binary stable class label, zero or one, for every material input ID.",
        "metric": "Maximize balanced accuracy, the arithmetic mean of recall for the two stable classes.",
    },
    "data": {
        "source": "The fixture uses the versioned synthetic materials generator in https://example.org/materials-generator; its CSV is attached to this test.",
        "outcomes": "Stable equals one if the generated material survives the specified simulated stress test, and zero otherwise; each label covers that one test.",
        "permission": "The fixture author permits benchmark use and distribution of generated participant input data under CC0.",
    },
    "methodology": {
        "methods": "Any statistical or machine learning method is allowed.",
        "resources": "Only supplied training data may be used; external data, pretrained models, and external services are prohibited.",
    },
    "deployment": {
        "setting": "This is an offline synthetic research benchmark.",
        "information": "At each prediction the method receives only the declared material features and fitted training artifacts; target labels are unavailable.",
        "timing": "There is one batch evaluation with no later model updates, persistent state, or real-time latency requirement.",
        "limits": "Use the platform's fixed CPU, memory, and runtime limits; no network access or GPU is required.",
        "outcome": "The predicted stable class is compared directly with the simulated stress outcome; balanced accuracy estimates material screening performance.",
    },
    "evaluation": {
        "population": "Evaluate new independently generated material compositions from the same declared generator.",
        "independence": "Each material sample is independent; duplicate sample IDs must not cross split boundaries.",
        "holdout": "For this prototype use the implemented 80/20 outer split and separate training-derived development feedback; final answers and scores remain private.",
        "uncertainty": "Use all available validation rows and report the row count; estimate score uncertainty with a bootstrap across independent material samples.",
        "workflow": "Score binary labels against fixed stress-test outcomes and aggregate with balanced accuracy over every validation ID.",
    },
    "leakage": {
        "related_samples": "The generator produces independent samples; the data audit must reject duplicate samples across boundaries.",
        "exposure": "The generated answer key is private and never distributed with participant inputs.",
        "preprocessing": "Fit normalization and feature selection only on local training data; never fit them on validation or final outcomes.",
    },
    "protocol": {"restrictions": "There are no additional scientific restrictions beyond the recorded data and method policies."},
    "review": {
        "owner": "The organizer is responsible for scientific review.",
        "status": "Review is pending; the organizer will check the draft, source data, and measured pipeline results before release.",
    },
    "plan": {
        "compute_budget": "The credible attempt has an estimated compute budget of USD 20.",
        "token_budget": "The separate model-token budget is estimated at USD 5.",
        "ownership": "The organizer owns both budgets, which are hard spending limits.",
        "schedule": "Allow one day for an attempt; no public competition deadline is set.",
    },
    "entry": {
        "participants": "Participation is limited to invited research agents during this private trial.",
        "prerequisites": "Participants need Python and basic supervised learning knowledge; the package explains the synthetic material task.",
    },
    "support": {
        "contact": "Participants send task questions through the private organizer review chat.",
        "rules": "There are no prizes or participant deadlines during the private trial.",
        "results": "The organizer will inspect the development results and unresolved issues in the review page before a new revision.",
    },
}


def complete_definition(project):
    """Fill each mandatory record explicitly; leave the reference optional."""
    state = conversation.ensure_conversation(project)
    for field in REQUIRED_FIELDS:
        if field in SERVER_FIELDS:
            continue
        decisions = DECISIONS[field]
        item = state["items"][field]
        item.update(status="answered", value=" ".join(decisions.values()), gap="")
        item["requirements"] = {
            requirement["id"]: {"status": "recorded", "value": decisions[requirement["id"]],
                                "evidence": [decisions[requirement["id"]]], "reason": ""}
            for requirement in REQUIREMENTS[field]
        }
    state["items"]["difficulty"].update(status="deferred", value="No functional reference is known for this new task.", gap="", requirements={})
    return state
