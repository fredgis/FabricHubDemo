"""Offline publication boundary tests; no credentials or cloud transport."""
from contextlib import contextmanager
from copy import deepcopy
from email.message import Message
import importlib
import io
import json
from types import SimpleNamespace
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.parse import unquote, urlparse
from urllib import request as urllib_request
from urllib.response import addinfourl


@contextmanager
def mocked_http(http):
    """Mock HTTPS I/O only; retain urllib's opener/error/redirect processing."""
    def respond(handler, request):
        try:
            response = http(request, request.timeout)
            status, headers, data = response.status, response.headers, response.read()
        except HTTPError as exc:
            status, headers, data = exc.code, exc.headers, exc.read()
        message = Message()
        for key, value in headers.items():
            message[key] = value
        response = addinfourl(io.BytesIO(data), message, request.full_url, status)
        response.msg = "offline fixture"
        return response

    with patch.object(urllib_request, "_opener", None), \
            patch.object(urllib_request.HTTPSHandler, "https_open", autospec=True, side_effect=respond), \
            patch("socket.create_connection", side_effect=AssertionError("Socket I/O prohibited")), \
            patch("socket.socket", side_effect=AssertionError("Socket I/O prohibited")):
        yield

from sources.sap.fabric_client import OneLakeFiles
from fabric.rest import DeploymentError
import os
from pathlib import Path
import tempfile
import unittest

from test_native_delta import baseline, added, NAME, NEXT, BRIDGE
from sources.sap import native, native_delta
from sources.sap.datasphere import digest, json_bytes
from sources.sap.schema import Object


def api():
    assert importlib.util.find_spec("sources.sap.native_delta_publish"), "publisher is missing"
    return importlib.import_module("sources.sap.native_delta_publish")


class MemoryStore:
    """Test double of OneLakeFiles.target/request/put, not a production API."""
    def __init__(self, target, files):
        self.target = deepcopy(target)
        self.client = SimpleNamespace(target=deepcopy(target))
        self.base = ("https://onelake.dfs.fabric.microsoft.com/"
                     f"{target['workspace_id']}/{target['landing_lakehouse_id']}/Files")
        self.files = dict(files)
        self.calls = []

    def request(self, method, path):
        self.calls.append((method, path))
        if method != "GET":
            raise AssertionError("Only GET belongs in request")
        return (200, {}, self.files[path]) if path in self.files else (404, {}, b"")

    def put(self, path, data):
        self.calls.append(("PUT", path))
        if path in self.files:
            if self.files[path] != data:
                raise ValueError("replacement prohibited")
            return "unchanged"
        self.files[path] = data
        return "created"


class NativeDeltaPublishTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory(prefix="native-publish-", dir=os.environ["TMPDIR"])
        self.addCleanup(temp.cleanup)
        self.scratch = Path(temp.name)
        self.base, schemas, _ = baseline(self.scratch)
        self.schemas = schemas
        bridge = Object(BRIDGE, (native.NativeField("ID", "CHAR", 20, key=True),), financial=True)
        self.package = self.scratch / "append"
        self.manifest = native_delta.write_package(
            self.base, {**schemas, BRIDGE: bridge}, {NAME: [added()], BRIDGE: [{"ID": "fixture-order"}]},
            NEXT, "publisher-fixture", self.package)
        self.target = {
            "tenant_id": "00000000-0000-4000-8000-000000000101",
            "subscription_id": "00000000-0000-4000-8000-000000000102",
            "workspace_id": "00000000-0000-0000-0000-000000000001",
            "landing_lakehouse_id": "00000000-0000-0000-0000-000000000002",
            "mirror_id": "00000000-0000-0000-0000-000000000003",
            "operator_id": "00000000-0000-0000-0000-000000000004",
            "source_system": "S4M", "system_suffix": "a1b2c3d4",
        }
        policy = patch('sources.sap.native_delta_publish._policy', return_value={
            'tenant_id': self.target['tenant_id'], 'subscription_id': self.target['subscription_id']})
        policy.start()
        self.addCleanup(policy.stop)
        self.approval = {
            "manifest_sha256": digest((self.package / "manifest.json").read_bytes()),
            "predecessor_manifest_sha256": digest((self.base / "manifest.json").read_bytes()),
            "target": deepcopy(self.target),
        }
        self.predecessors = {p.relative_to(self.base).as_posix(): p.read_bytes()
                             for p in (self.base / "datasphere").rglob("*") if p.is_file()}
        self.store = MemoryStore(self.target, self.predecessors)
        self.checkpoint = self.scratch / "evidence" / "checkpoint.json"
        self.coordination = {
            "approval": deepcopy(self.approval), "evidence_id": "offline-test-only",
            "schedule_paused": True, "ingestion_idle": True, "exclusive_source_writer": True,
        }

    def call(self, **kwargs):
        arguments = dict(approval=self.approval, store=self.store, checkpoint=self.checkpoint)
        arguments.update(kwargs)
        return api().publish(self.package, self.base, self.target, **arguments)

    def test_target_suffix_is_explicit_and_bound_not_live_default(self):
        api()._approval(self.target, self.approval)
        for suffix in (None, '', 'A1B2C3D4', 'a1b2c3d4/extra', 'a1b2c3d4?x'):
            target = {**self.target, 'system_suffix': suffix}
            with self.assertRaises(ValueError):
                api()._approval(target, {**self.approval, 'target': target})
        target = {**self.target, 'system_suffix': '1234abcd'}
        api()._approval(target, {**self.approval, 'target': target})
        with self.assertRaisesRegex(ValueError, 'binding'):
            api()._approval(target, self.approval)

    def test_approval_and_target_rejected_before_remote_io(self):
        for case in ("hash", "predecessor", "target", "source", "grammar", "scope", "missing"):
            with self.subTest(case=case):
                approval = deepcopy(self.approval)
                target = deepcopy(self.target)
                if case in {"hash", "predecessor"}:
                    approval["manifest_sha256" if case == "hash" else "predecessor_manifest_sha256"] = "0" * 64
                elif case == "target":
                    target["landing_lakehouse_id"] = target["workspace_id"]
                elif case in {"source", "grammar", "scope"}:
                    key, value = {"source": ("source_system", "ORACLE"),
                                  "grammar": ("workspace_id", "00000000000000000000000000000001"),
                                  "scope": ("tenant_id", target["workspace_id"])}[case]
                    target[key] = value
                    approval["target"] = target
                else:
                    approval.pop("manifest_sha256")
                with self.assertRaises(ValueError):
                    api().publish(self.package, self.base, target, approval=approval,
                                  apply=True, store=self.store, checkpoint=self.checkpoint,
                                  coordination=self.coordination)
                self.assertEqual(self.store.calls, [])
                self.assertFalse(self.checkpoint.exists())

    def test_approved_manifest_hash_gate_with_matching_coordination(self):
        approval = {**self.approval, "manifest_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "Append manifest hash mismatch"):
            self.call(apply=True, approval=approval,
                      coordination={**self.coordination, "approval": deepcopy(approval)})
        self.assertEqual(self.store.calls, [])
        self.assertFalse(self.checkpoint.exists())

    def test_approved_predecessor_hash_gate_with_matching_coordination(self):
        approval = {**self.approval, "predecessor_manifest_sha256": "0" * 64}
        with self.assertRaisesRegex(ValueError, "Baseline manifest hash differs"):
            self.call(apply=True, approval=approval,
                      coordination={**self.coordination, "approval": deepcopy(approval)})
        self.assertEqual(self.store.calls, [])
        self.assertFalse(self.checkpoint.exists())

    def test_package_predecessor_gate_with_matching_coordination(self):
        manifest = {**self.manifest, "predecessor_manifest_sha256": "0" * 64}
        (self.package / "manifest.json").write_bytes(json_bytes(manifest))
        approval = {**self.approval, "manifest_sha256": digest(json_bytes(manifest))}
        with self.assertRaisesRegex(ValueError, "Append predecessor hash mismatch"):
            self.call(apply=True, approval=approval,
                      coordination={**self.coordination, "approval": deepcopy(approval)})
        self.assertEqual(self.store.calls, [])
        self.assertFalse(self.checkpoint.exists())

    def test_apply_requires_explicit_boolean_coordination_and_bound_store(self):
        cases = [dict(apply=1), dict(apply="true"), dict(apply=True),
                 dict(apply=True, coordination={}),
                 dict(apply=True, coordination={**self.coordination, "ingestion_idle": False}),
                 dict(apply=True, coordination={**self.coordination, "approval": {}}),
                 dict(apply=True, coordination=self.coordination, checkpoint=None),
                 dict(apply=True, coordination=self.coordination,
                      store=MemoryStore({**self.target, "mirror_id": self.target["workspace_id"]}, {}))]
        for kwargs in cases:
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                self.call(**kwargs)
            self.assertEqual(self.store.calls, [])
            self.assertFalse(self.checkpoint.exists())

    def test_apply_reads_all_predecessors_before_ordered_payloads_and_final_evidence(self):
        result = self.call(apply=True, coordination=self.coordination)
        self.assertTrue(result["complete"])
        self.assertEqual(result["mode"], "apply")
        files = self.manifest["ordered_files"]
        self.assertEqual([n for op, n in self.store.calls if op == "PUT"], files)
        first_put = next(i for i, (op, _) in enumerate(self.store.calls) if op == "PUT")
        self.assertTrue(set(self.predecessors) <= {n for op, n in self.store.calls[:first_put] if op == "GET"})
        last_put = max(i for i, (op, _) in enumerate(self.store.calls) if op == "PUT")
        self.assertTrue(set(files) <= {n for op, n in self.store.calls[last_put + 1:] if op == "GET"})
        self.assertTrue(files[-1].endswith("/initial/_SUCCESS"))
        self.assertEqual(set(self.store.files), set(self.predecessors) | set(files))
        evidence = json.loads(self.checkpoint.read_bytes())
        self.assertTrue(evidence["complete"])
        self.assertEqual(evidence["approval"], self.approval)
        self.assertEqual(evidence["files"], [
            {"file": n, "sha256": self.manifest["files"][n], "state": "created"} for n in files])
        self.assertFalse(evidence["native_bps_ready"])
        self.assertFalse(list(self.checkpoint.parent.glob("*.tmp")))

    def test_predecessor_gets_are_start_and_end_only_independent_of_payload_count(self):
        smaller = self.scratch / "smaller-append"
        smaller_manifest = native_delta.write_package(
            self.base, self.schemas, {NAME: [added()]}, NEXT,
            "publisher-fixture", smaller)
        counts = []
        for package, manifest in ((smaller, smaller_manifest), (self.package, self.manifest)):
            counts.append(len(manifest["ordered_files"]))
            with self.subTest(payload_count=len(manifest["ordered_files"])):
                approval = {**self.approval,
                            "manifest_sha256": digest((package / "manifest.json").read_bytes())}
                store = MemoryStore(self.target, self.predecessors)
                result = api().publish(
                    package, self.base, self.target, approval=approval, apply=True,
                    store=store, checkpoint=self.scratch / (package.name + "-checkpoint.json"),
                    coordination={**self.coordination, "approval": deepcopy(approval)})
                self.assertTrue(result["complete"])
                predecessor_gets = [name for op, name in store.calls
                                    if op == "GET" and name in self.predecessors]
                self.assertEqual(len(predecessor_gets), 2 * len(self.predecessors))
                for name in self.predecessors:
                    self.assertEqual(predecessor_gets.count(name), 2)
                self.assertEqual(set(predecessor_gets[:len(self.predecessors)]), set(self.predecessors))
                self.assertEqual(set(predecessor_gets[len(self.predecessors):]), set(self.predecessors))
                first_put = next(i for i, (op, _) in enumerate(store.calls) if op == "PUT")
                last_put = max(i for i, (op, _) in enumerate(store.calls) if op == "PUT")
                self.assertFalse(any(name in self.predecessors
                                     for _, name in store.calls[first_put:last_put + 1]))
        self.assertNotEqual(*counts)

    def test_checkpoint_binding_is_validated_before_io_and_replay_is_idempotent(self):
        self.call(apply=True, coordination=self.coordination)
        self.store.calls.clear()
        evidence = json.loads(self.checkpoint.read_bytes())
        for field in ("target", "manifest_sha256", "predecessor_manifest_sha256", "file_hash"):
            altered = deepcopy(evidence)
            if field == "target":
                altered["approval"]["target"]["workspace_id"] = self.target["mirror_id"]
            elif field == "file_hash":
                altered["files"][0]["sha256"] = "0" * 64
            else:
                altered["approval"][field] = "0" * 64
            self.checkpoint.write_bytes(json_bytes(altered))
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.call(apply=True, coordination=self.coordination)
            self.assertEqual(self.store.calls, [])
            self.assertEqual(json.loads(self.checkpoint.read_bytes()), altered)
        self.checkpoint.write_bytes(json_bytes(evidence))
        result = self.call(apply=True, coordination=self.coordination)
        self.assertTrue(result["complete"])
        self.assertEqual([op for op, _ in self.store.calls if op == "PUT"], [])

    def test_existing_conflict_anywhere_is_rejected_before_first_put(self):
        last = self.manifest["ordered_files"][-1]
        self.store.files[last] = b"different existing marker"
        with self.assertRaisesRegex(ValueError, "differs"):
            self.call(apply=True, coordination=self.coordination)
        self.assertFalse(any(op == "PUT" for op, _ in self.store.calls))
        self.assertEqual(self.store.files[last], b"different existing marker")
        self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])

    def test_predecessor_missing_or_different_stops_before_put(self):
        name = next(iter(self.predecessors))
        for value in (None, b"drift"):
            self.store.calls.clear()
            if value is None:
                self.store.files.pop(name, None)
            else:
                self.store.files[name] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "predecessor"):
                self.call(apply=True, coordination=self.coordination)
            self.assertFalse(any(op == "PUT" for op, _ in self.store.calls))
            self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])

    def test_resume_rechecks_full_baseline_before_payloads_even_with_complete_checkpoint(self):
        self.call(apply=True, coordination=self.coordination)
        saved = self.checkpoint.read_bytes()
        for changed in (None, *self.predecessors):
            with self.subTest(changed=changed):
                self.checkpoint.write_bytes(saved)
                self.store.calls.clear()
                self.store.files.update(self.predecessors)
                if changed is None:
                    result = self.call(apply=True, coordination=self.coordination)
                    self.assertTrue(result["complete"])
                else:
                    self.store.files[changed] = b"changed since completed attempt"
                    with self.assertRaisesRegex(ValueError, "predecessor"):
                        self.call(apply=True, coordination=self.coordination)
                    self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])
                    self.assertTrue(all(name in self.predecessors for _, name in self.store.calls))
                    self.assertIn(("GET", changed), self.store.calls)
                self.assertFalse(any(op == "PUT" for op, _ in self.store.calls))
                if changed is None:
                    start = self.store.calls[:len(self.predecessors)]
                    self.assertEqual({name for op, name in start if op == "GET"}, set(self.predecessors))
                    for name in self.predecessors:
                        self.assertEqual(self.store.calls.count(("GET", name)), 2)

    def test_end_predecessor_mismatch_keeps_checkpoint_incomplete_after_all_payloads(self):
        files = self.manifest["ordered_files"]
        changed = next(iter(self.predecessors))
        original = self.store.put
        def drift_after_last_payload(name, data):
            result = original(name, data)
            if name == files[-1]:
                self.store.files[changed] = b"end predecessor drift"
            return result
        self.store.put = drift_after_last_payload
        with self.assertRaisesRegex(ValueError, "predecessor"):
            self.call(apply=True, coordination=self.coordination)
        self.assertEqual([name for op, name in self.store.calls if op == "PUT"], files)
        last_put = max(i for i, (op, _) in enumerate(self.store.calls) if op == "PUT")
        self.assertEqual(self.store.calls[last_put + 1:last_put + 1 + len(files)],
                         [("GET", name) for name in files])
        self.assertEqual(self.store.calls.count(("GET", changed)), 2)
        evidence = json.loads(self.checkpoint.read_bytes())
        self.assertFalse(evidence["complete"])
        self.assertEqual([entry["file"] for entry in evidence["files"]], files)

    def test_failure_resume_and_final_readback_drift_never_claim_complete(self):
        original = self.store.put
        files = self.manifest["ordered_files"]
        def fail(name, data):
            if name == files[2]:
                raise OSError("injected transport failure")
            return original(name, data)
        self.store.put = fail
        with self.assertRaises(OSError):
            self.call(apply=True, coordination=self.coordination)
        evidence = json.loads(self.checkpoint.read_bytes())
        self.assertFalse(evidence["complete"])
        self.assertEqual([r["file"] for r in evidence["files"]], files[:2])
        self.store.put = original
        self.store.calls.clear()
        result = self.call(apply=True, coordination=self.coordination)
        self.assertTrue(result["complete"])
        self.assertEqual([n for op, n in self.store.calls if op == "PUT"], files[2:])
        get = self.store.request
        reads = []
        def drift(method, name):
            reads.append(name)
            # Replay has preflight and per-file GET, then final GET.
            if name == files[0] and reads.count(name) == 3:
                return 200, {}, b"final drift"
            return get(method, name)
        self.store.request = drift
        with self.assertRaisesRegex(ValueError, "readback"):
            self.call(apply=True, coordination=self.coordination)
        self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])

    def test_concurrent_predecessor_drift_detected_at_final_verification_target_stops_next_put(self):
        original_put = self.store.put
        old = next(iter(self.predecessors))
        for drift in ("predecessor", "target"):
            self.store.files = dict(self.predecessors)
            self.store.target = deepcopy(self.target)
            self.store.calls.clear()
            if self.checkpoint.exists():
                self.checkpoint.unlink()
            def mutate(name, data):
                result = original_put(name, data)
                if drift == "predecessor":
                    self.store.files[old] = b"concurrent drift"
                else:
                    self.store.target["workspace_id"] = self.target["mirror_id"]
                return result
            self.store.put = mutate
            with self.subTest(drift=drift), self.assertRaisesRegex(ValueError, drift):
                self.call(apply=True, coordination=self.coordination)
            puts = [name for op, name in self.store.calls if op == "PUT"]
            files = self.manifest["ordered_files"]
            self.assertEqual(puts, files if drift == "predecessor" else files[:1])
            evidence = json.loads(self.checkpoint.read_bytes())
            self.assertFalse(evidence["complete"])
            if drift == "predecessor":
                self.assertEqual([entry["file"] for entry in evidence["files"]], files)
                last_put = max(i for i, (op, _) in enumerate(self.store.calls) if op == "PUT")
                self.assertTrue(set(files) <= {name for op, name in self.store.calls[last_put + 1:]
                                              if op == "GET"})

    def test_checkpoint_must_not_overlap_immutable_inputs(self):
        for path in (self.package / "manifest.json", self.base / "audit.json"):
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.call(apply=True, coordination=self.coordination, checkpoint=path)
            self.assertEqual(self.store.calls, [])

    def test_bytes_are_rechecked_after_verifier_before_any_remote_io(self):
        from unittest.mock import patch
        original = native_delta.verify_package
        first = self.manifest["ordered_files"][0]
        def changed(*args, **kwargs):
            verified = original(*args, **kwargs)
            (self.package / first).write_bytes(b"changed after verification")
            return verified
        with patch.object(native_delta, "verify_package", side_effect=changed):
            with self.assertRaisesRegex(ValueError, "hash"):
                self.call(apply=True, coordination=self.coordination)
        self.assertEqual(self.store.calls, [])
        self.assertFalse(self.checkpoint.exists())

    def test_transport_state_must_be_verified(self):
        original = self.store.put
        def bad_state(name, data):
            original(name, data)
            return "overwritten"
        self.store.put = bad_state
        with self.assertRaisesRegex(ValueError, "state"):
            self.call(apply=True, coordination=self.coordination)
        self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])
        self.assertEqual(sum(op == "PUT" for op, _ in self.store.calls), 1)

    def test_checkpoint_replace_failure_is_atomic_and_prevents_publication(self):
        from unittest.mock import patch
        self.call(apply=True, coordination=self.coordination)
        saved = self.checkpoint.read_bytes()
        self.store.calls.clear()
        with patch.object(api().os, "replace", side_effect=OSError("disk failure")):
            with self.assertRaises(OSError):
                self.call(apply=True, coordination=self.coordination)
        self.assertEqual(self.checkpoint.read_bytes(), saved)
        self.assertEqual(self.store.calls, [])
        self.assertFalse(list(self.checkpoint.parent.glob("*.tmp")))

    def test_package_changes_are_rejected_before_remote_io(self):
        original = (self.package / "manifest.json").read_bytes()
        altered = deepcopy(self.manifest)
        altered["ordered_files"] = list(reversed(altered["ordered_files"]))
        (self.package / "manifest.json").write_bytes(json_bytes(altered))
        approval = {**self.approval, "manifest_sha256": digest((self.package / "manifest.json").read_bytes())}
        with self.assertRaises(ValueError):
            self.call(approval=approval)
        (self.package / "manifest.json").write_bytes(original)
        (self.package / self.manifest["ordered_files"][0]).write_bytes(b"tampered")
        with self.assertRaises(ValueError):
            self.call()
        self.assertEqual(self.store.calls, [])
        self.assertFalse(self.checkpoint.exists())

    def real_transport(self):
        """Keep OneLakeFiles request/directory/put real; only HTTP is mocked."""
        endpoint = ("https://onelake.dfs.fabric.microsoft.com/"
                    f"{self.target['workspace_id']}/{self.target['landing_lakehouse_id']}/Files")
        client = SimpleNamespace(
            target=deepcopy(self.target), workspace=lambda: {},
            request=lambda *args: (200, {}, {"displayName": "MSFlixSAPLanding",
                                            "properties": {"oneLakeFilesPath": endpoint}}),
            token=lambda audience: "offline-test-placeholder")
        transport = OneLakeFiles(client)
        backing, requests = dict(self.predecessors), []

        class Response:
            def __init__(self, status, data=b"", headers=None):
                self.status, self.data, self.headers = status, data, headers or {}
            def read(self):
                return self.data
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False

        def http(request, timeout):
            requests.append(request)
            path = unquote(urlparse(request.full_url).path.split("/Files/", 1)[1])
            if request.method == "HEAD":
                return Response(200, headers={"x-ms-resource-type": "directory"})
            if request.method == "GET":
                if path not in backing:
                    raise HTTPError(request.full_url, 404, "absent", {}, io.BytesIO())
                return Response(200, backing[path])
            self.assertEqual(request.method, "PUT")
            self.assertEqual(request.get_header("If-none-match"), "*")
            if path in backing:
                raise HTTPError(request.full_url, 412, "collision", {}, io.BytesIO())
            backing[path] = request.data
            return Response(201)
        return transport, backing, requests, http

    def test_guarded_onelakefiles_rejects_all_redirects_before_second_request(self):
        for method in ("GET", "PUT"):
            for status in (301, 302, 303, 307, 308):
                for destination in ("cross_host", "wrong_workspace", "canonical"):
                    with self.subTest(method=method, status=status, destination=destination):
                        transport, _, _, _ = self.real_transport()
                        transport._publication_guard = lambda: api()._binding(transport, self.target)
                        base = transport.base.replace(".dfs.", ".blob.") if method == "PUT" else transport.base
                        location = base + "/datasphere/S4M/redirected"
                        if destination == "cross_host":
                            location = location.replace("onelake.", "unapproved.")
                        elif destination == "wrong_workspace":
                            location = location.replace(self.target["workspace_id"], self.target["mirror_id"])
                        requests = []
                        def redirect(request, timeout):
                            requests.append(request)
                            if len(requests) == 1:
                                raise HTTPError(request.full_url, status, "redirect fixture",
                                                {"Location": location}, io.BytesIO())
                            return SimpleNamespace(status=200, headers={}, read=lambda: b"redirected bytes")
                        with mocked_http(redirect):
                            with self.assertRaisesRegex(DeploymentError, f"HTTP {status}"):
                                transport.request(method, "datasphere/S4M/fixture", blob=method == "PUT",
                                                  data=b"payload" if method == "PUT" else None)
                        self.assertEqual(len(requests), 1)
                        self.assertEqual(requests[0].get_header("Authorization"),
                                         "Bearer offline-test-placeholder")

    def test_unguarded_onelakefiles_keeps_urllib_redirect_behavior(self):
        transport, _, _, _ = self.real_transport()
        location = transport.base + "/datasphere/S4M/redirected"
        requests = []
        def redirect(request, timeout):
            requests.append(request)
            if len(requests) == 1:
                raise HTTPError(request.full_url, 302, "redirect fixture",
                                {"Location": location}, io.BytesIO())
            return SimpleNamespace(status=200, headers={}, read=lambda: b"redirected bytes")
        with mocked_http(redirect):
            result = transport.request("GET", "datasphere/S4M/fixture")
        self.assertEqual(result, (200, {}, b"redirected bytes"))
        self.assertEqual(len(requests), 2)
        self.assertEqual(requests[1].full_url, location)
        self.assertFalse(hasattr(transport, "_publication_guard"))

    def test_publication_redirect_aborts_with_incomplete_checkpoint(self):
        transport, backing, requests, http = self.real_transport()
        def redirect(request, timeout):
            requests.append(request)
            raise HTTPError(request.full_url, 302, "redirect fixture",
                            {"Location": "https://unapproved.example/fixture"}, io.BytesIO())
        with mocked_http(redirect):
            with self.assertRaisesRegex(DeploymentError, "HTTP 302"):
                self.call(apply=True, coordination=self.coordination, store=transport)
        self.assertEqual(len(requests), 1)
        self.assertEqual(backing, self.predecessors)
        self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])
        self.assertFalse(hasattr(transport, "_publication_guard"))

    def test_real_onelakefiles_wrong_endpoint_rejected_without_remote_calls(self):
        transport, _, _, _ = self.real_transport()
        valid = transport.base
        wrong = [
            valid.replace(self.target["workspace_id"], self.target["mirror_id"]),
            valid.replace(self.target["landing_lakehouse_id"], self.target["mirror_id"]),
            valid.replace("https://", "http://"),
            valid.replace("onelake.dfs", "other.dfs"),
            valid.replace("onelake.dfs", "onelake.blob"),
            valid.replace("https://", "https://user@"),
            valid.replace(".com/", ".com:443/"),
            valid + "?redirect=other", valid + "#fragment", valid + "/",
            valid.replace("/Files", "/Tables"),
            valid.replace("/Files", "/ignored/../Files"),
            valid.replace("/Files", "//Files"),
            valid.replace("/Files", "/%46iles"),
        ]
        for endpoint in wrong:
            with self.subTest(endpoint=endpoint):
                transport, backing, requests, http = self.real_transport()
                transport.base = endpoint
                with mocked_http(http):
                    with self.assertRaisesRegex(ValueError, "endpoint"):
                        self.call(apply=True, coordination=self.coordination, store=transport)
                self.assertEqual(requests, [])
                self.assertEqual(backing, self.predecessors)
                self.assertFalse(self.checkpoint.exists())

    def test_real_onelakefiles_client_target_must_match_before_remote_io(self):
        for key in self.target:
            with self.subTest(key=key):
                transport, _, requests, http = self.real_transport()
                transport.client.target = {**self.target, key: "not-approved"}
                with mocked_http(http):
                    with self.assertRaisesRegex(ValueError, "target"):
                        self.call(apply=True, coordination=self.coordination, store=transport)
                self.assertEqual(requests, [])
                self.assertFalse(self.checkpoint.exists())

    def test_real_onelakefiles_client_mutation_during_read_fails_closed(self):
        transport, _, requests, http = self.real_transport()
        def mutate(request, timeout):
            response = http(request, timeout)
            transport.client.target = {**self.target, "operator_id": self.target["mirror_id"]}
            return response
        with mocked_http(mutate):
            with self.assertRaisesRegex(ValueError, "target"):
                self.call(apply=True, coordination=self.coordination, store=transport)
        self.assertEqual(len(requests), 1)
        self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])

    def test_real_onelakefiles_mutation_during_token_stops_before_http(self):
        for field in ("base", "client"):
            with self.subTest(field=field):
                transport, _, requests, http = self.real_transport()
                def token(audience):
                    if field == "base":
                        transport.base += "/wrong"
                    else:
                        transport.client.target = {**self.target, "tenant_id": self.target["mirror_id"]}
                    return "offline-test-placeholder"
                transport.client.token = token
                with mocked_http(http):
                    with self.assertRaisesRegex(ValueError, "endpoint|target"):
                        self.call(apply=True, coordination=self.coordination, store=transport)
                self.assertEqual(requests, [])
                self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])
                self.checkpoint.unlink()

    def test_real_onelakefiles_conditional_412_never_overwrites(self):
        transport, backing, requests, http = self.real_transport()
        first = self.manifest["ordered_files"][0]
        def collide(request, timeout):
            if request.method == "PUT":
                backing[first] = b"concurrent-writer"
            return http(request, timeout)
        with mocked_http(collide):
            with self.assertRaisesRegex(DeploymentError, "HTTP 412"):
                self.call(apply=True, coordination=self.coordination, store=transport)
        self.assertEqual(backing[first], b"concurrent-writer")
        self.assertEqual(set(backing), set(self.predecessors) | {first})
        self.assertEqual(sum(r.method == "PUT" for r in requests), 1)
        self.assertEqual(requests[-1].get_header("If-none-match"), "*")
        self.assertEqual(urlparse(requests[-1].full_url).netloc, "onelake.blob.fabric.microsoft.com")
        self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])

    def test_real_onelakefiles_endpoint_mutation_stops_at_request_boundary(self):
        for phase in ("predecessor", "put_get", "directory", "put", "final_payload", "final_predecessor"):
            with self.subTest(phase=phase):
                transport, backing, requests, http = self.real_transport()
                files = self.manifest["ordered_files"]
                changed_at = []
                reads = []
                def mutate(request, timeout):
                    missing = None
                    try:
                        response = http(request, timeout)
                    except HTTPError as exc:
                        missing = exc
                    path = unquote(urlparse(request.full_url).path.split("/Files/", 1)[1])
                    if request.method == "GET":
                        reads.append(path)
                    trigger = ((phase == "predecessor" and len(requests) == 1)
                               or (phase == "put_get" and path == files[0] and reads.count(path) == 3)
                               or (phase == "directory" and request.method == "HEAD")
                               or (phase == "put" and request.method == "PUT")
                               or (phase == "final_payload" and path == files[-1]
                                   and request.method == "GET" and len(backing) == len(self.predecessors) + len(files)
                                   and reads.count(path) == 5)
                               or (phase == "final_predecessor" and path == list(self.predecessors)[-1]
                                   and reads.count(files[-1]) == 5))
                    if trigger and not changed_at:
                        transport.base = transport.base.replace(self.target["workspace_id"], self.target["mirror_id"])
                        changed_at.append(len(requests))
                    if missing is not None:
                        raise missing
                    return response
                with mocked_http(mutate):
                    with self.assertRaisesRegex(ValueError, "endpoint"):
                        self.call(apply=True, coordination=self.coordination, store=transport)
                self.assertTrue(changed_at)
                self.assertEqual(len(requests), changed_at[0])
                self.assertFalse(json.loads(self.checkpoint.read_bytes())["complete"])
                self.checkpoint.unlink()

    def test_real_onelakefiles_put_contract_is_used_offline(self):
        transport, backing, requests, http = self.real_transport()
        with mocked_http(http):
            result = self.call(apply=True, coordination=self.coordination, store=transport)
        self.assertTrue(result["complete"])
        puts = [r for r in requests if r.method == "PUT"]
        self.assertEqual([unquote(urlparse(r.full_url).path.split("/Files/", 1)[1]) for r in puts],
                         self.manifest["ordered_files"])
        self.assertTrue(all(urlparse(r.full_url).netloc == "onelake.blob.fabric.microsoft.com" for r in puts))
        self.assertEqual(set(backing), set(self.predecessors) | set(self.manifest["ordered_files"]))

    def test_non_200_remote_read_is_not_treated_as_absent(self):
        self.store.request = lambda method, path: (503, {}, b"")
        with self.assertRaisesRegex(ValueError, "GET"):
            self.call(apply=True, coordination=self.coordination)
        self.assertFalse(any(op == "PUT" for op, _ in self.store.calls))

    def test_target_mutation_during_get_stops_before_another_request(self):
        request = self.store.request
        def drift(method, path):
            result = request(method, path)
            self.store.target["workspace_id"] = self.target["mirror_id"]
            return result
        self.store.request = drift
        with self.assertRaisesRegex(ValueError, "target"):
            self.call(apply=True, coordination=self.coordination)
        self.assertEqual(len(self.store.calls), 1)

    def test_default_preview_validates_without_store_or_checkpoint_io(self):
        result = self.call()
        self.assertEqual(result["mode"], "preview")
        self.assertFalse(result["complete"])
        self.assertEqual(result["ordered_files"], self.manifest["ordered_files"])
        self.assertEqual(result["predecessor_files"], len(self.predecessors))
        self.assertEqual(result["requires_bps_ui_registration"], [BRIDGE])
        self.assertFalse(result["native_bps_ready"])
        self.assertEqual(self.store.calls, [])
        self.assertFalse(self.checkpoint.parent.exists())
