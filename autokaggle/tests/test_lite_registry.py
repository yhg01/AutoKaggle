import json
import pytest
from autokaggle import lite_release, lite_build

def test_legacy_release_is_not_described_as_fully_validated():
    public = lite_build._public({"id": "old", "status": "ready"})
    assert public["validation"]["contract_coverage"] == "unassessed"
    assert public["validation"]["research_data"] == "not_run"


def eligible():
    from autokaggle import lite
    item = {"id": "example", "title": "Example", "lite": {"contract": {"objective": "Measure performance", "task_kind": "generation"}}}
    build = {"status": "ready", "evaluator_version": 1, "contract_sha256": "b"*64, "evidence": {"commit": "a"*40},
             "validation": {**{k: "passed" for k in ("build", "contract_coverage", "code_review", "synthetic")},
                 "research_data": "validated", "research_evidence": {"commit": "a"*40, "contract_sha256": "b"*64,
                     "reference_sha256": "c"*64, "report_sha256": "d"*64, "checked_by": "trusted-validation-job"}},
             "human_approval": {"commit": "a"*40, "contract_sha256": "b"*64, "research_report_sha256": "d"*64, "approved_by": "account-id"},
             "published": {"commit": "a"*40, "url": "https://github.com/example/evaluator", "zip_url": "https://github.com/example/evaluator/archive/a.zip"}}
    build["contract_version"] = lite.version(item["lite"]["contract"], [])
    return item, build


@pytest.mark.parametrize("change", ["research_pending", "old_commit", "new_report", "no_approval", "old_tests", "unpublished"])
def test_registry_requires_current_research_validation_and_human_approval(change):
    item, build = eligible()
    assert lite_release.registry_payload(item, build)["destinations"] == ["problem_bank", "benchmarks"]
    if change == "research_pending": build["validation"]["research_data"] = "not_run"
    if change == "old_commit": build["validation"]["research_evidence"]["commit"] = "0"*40
    if change == "new_report": build["human_approval"]["research_report_sha256"] = "0"*64
    if change == "no_approval": build.pop("human_approval")
    if change == "old_tests": build["validation"]["contract_coverage"] = "unassessed"
    if change == "unpublished": build.pop("published")
    with pytest.raises(ValueError): lite_release.registry_payload(item, build)
    lite_release.queue_registration(item, build)
    assert build["registry"]["status"] == "not_eligible"


@pytest.mark.parametrize('scenario', ['ok', 'partial', 'wrong_commit', 'forbidden', 'timeout', 'bad_endpoint'])
def test_bold_registration_receipt_and_retry(monkeypatch, scenario):
    import httpx
    item, build = eligible()
    monkeypatch.setenv('AUTOKAGGLE_BOLD_REGISTRY_URL', 'https://europe-west2-bold-d7ff2.cloudfunctions.net/boldApi/v1/registerBenchmark')
    monkeypatch.setenv('AUTOKAGGLE_BOLD_REGISTRY_TOKEN', 'test-placeholder')
    calls = []
    class Store:
        def save(self, value): pass
    def handle(request):
        calls.append(request)
        payload = json.loads(request.content)
        assert request.headers['Idempotency-Key'] == payload['idempotency_key']
        if scenario == 'timeout': raise httpx.ReadTimeout('test', request=request)
        if scenario == 'forbidden': return httpx.Response(403)
        receipt = {'problem_id': 'problem-1', 'benchmark_id': 'benchmark-1', 'commit': payload['evaluator']['commit'], 'idempotency_key': payload['idempotency_key']}
        if scenario == 'partial': receipt.pop('benchmark_id')
        if scenario == 'wrong_commit': receipt['commit'] = '0'*40
        return httpx.Response(201, json=receipt)
    if scenario == 'bad_endpoint':
        monkeypatch.setenv('AUTOKAGGLE_BOLD_REGISTRY_URL', 'https://europe-west2-bold-d7ff2.cloudfunctions.net:bad/path')
    with httpx.Client(transport=httpx.MockTransport(handle)) as client:
        lite_release.deliver_registration(Store(), item, build, client=client)
        status = build['registry']['status']
        assert status == ('registered' if scenario == 'ok' else 'failed')
        first_key = build['registry']['idempotency_key']
        lite_release.deliver_registration(Store(), item, build, client=client)
        assert build['registry']['idempotency_key'] == first_key
        assert len(calls) == (0 if scenario == 'bad_endpoint' else 1 if scenario == 'ok' else 2)
        # A later scientific change removes eligibility even if the old version was registered.
        item['lite']['contract']['objective'] = 'A changed scientific objective'
        lite_release.deliver_registration(Store(), item, build, client=client)
        assert build['registry']['status'] == 'not_eligible'

