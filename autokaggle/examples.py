"""Small synthetic fixtures with known intent, not scientific claims."""
from pathlib import Path
import numpy as np
import pandas as pd


def load_example(project, name, path: Path):
    rng = np.random.default_rng(713)
    n = 600
    temperature = rng.normal(600, 60, n)
    concentration = rng.uniform(0.1, 1, n)
    pressure = rng.normal(5, 0.7, n)
    score = (temperature - 600) / 60 + 2 * (concentration - 0.5) + rng.normal(0, 0.5, n)
    target = (score > 0).astype(int)
    frame = pd.DataFrame({"sample_id": [f"S{i:04d}" for i in range(n)],
                          "temperature_k": temperature.round(3), "concentration": concentration.round(5),
                          "pressure_bar": pressure.round(4), "stable": target})
    project["title"] = "Predict material stability"
    project["brief"] = ("This synthetic demonstration asks whether a material will remain stable after a standard stress test. "
        "Predict one outcome per independent material sample from temperature, concentration, and pressure measured before the test. "
        "A balanced accuracy of at least 0.75 on new samples would be useful. The simulated labels have not been publicly released. "
        "We estimate USD 20 for compute and USD 5 for model tokens for one credible attempt, including final evaluation.")
    project["answers"] = {"objective": "Predict material stability before the stress test.",
        "prediction_unit": "One independent material sample; one measurement per sample.",
        "success_criterion": "Balanced accuracy of at least 0.75 on new samples.",
        "data_origin": "synthetic", "labels_public": "no", "rights": "yes", "compute_budget": "USD 20", "token_budget": "USD 5"}
    project["design"] = {"target": "stable", "task": "classification", "metric": "balanced_accuracy", "split": "random",
        "group_column": "", "time_column": "", "exclude_columns": ["sample_id"], "test_fraction": 0.2}
    if name == "leakage":
        frame["post_test_result"] = target
        project["title"] = "Find the leaked answer"
        project["brief"] += " A post_test_result column was added after the outcome was measured. It must not be used as an input."
    elif name == "noise":
        frame["stable"] = rng.integers(0, 2, n)
        project["title"] = "Random-label control"
        project["brief"] = ("This synthetic control has independent random binary labels. Its purpose is to test the onboarding audit and leakage controls. "
            "There is no predictive signal by construction. Chance accuracy is 50% in expectation, not a hard upper bound. "
            "Treat it as a control, not a scientific discovery task.")
        project["answers"]["objective"] = "Test leakage controls using an intentionally unpredictable synthetic task."
        project["answers"]["success_criterion"] = "Expected chance performance near 50%; investigate large deviations with repeated controlled trials."
        project["design"]["metric"] = "accuracy"
    elif name != "materials":
        raise ValueError("Unknown example")
    frame.to_csv(path, index=False)
