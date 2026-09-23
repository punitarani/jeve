#!/usr/bin/env python3
"""The deploy's secret staging and tracing gate, run against stubs (OPS-0004).

Both deploy jobs skip on a pull request, so CI never runs these scripts before
a push to main does it for real. This runs them against a stub `doppler`,
`flyctl` and `curl` on PATH, and checks what they do with each: which config
is read with which token, what is staged or unset on Fly, what lands in
$GITHUB_ENV, and that no value reaches the log unmasked.

Stdlib only; needs bash and jq, as the deploy job does.
"""

from __future__ import annotations

import json
import os
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
STAGE = ROOT / "scripts" / "stage-worker-secrets.sh"
VERIFY = ROOT / "scripts" / "verify-tracing.sh"

GRANT = "dp.st.prd.grant-token-value"
KEY = "sk-braintrust-key-value"
PROJECT = "7f1ad66e-c91d-4a3b-9e2f-000000000000"
NO_WAITING = {"GATE_S": "0", "SPAN_S": "0", "POLL_S": "0"}

# One program answers as all three tools: it logs every call, then replies
# from the scenario the test wrote.
STUB = textwrap.dedent(
    """\
    #!/usr/bin/env python3
    import json, os, sys
    tool = os.path.basename(sys.argv[0])
    args = sys.argv[1:]
    stdin = sys.stdin.read()
    with open(os.environ["STUB_LOG"], "a") as log:
        log.write(json.dumps({"tool": tool, "args": args, "stdin": stdin,
                              "token": os.environ.get("DOPPLER_TOKEN")}) + "\\n")
    scenario = json.load(open(os.environ["STUB_SCENARIO"]))

    def reply(answer):
        if answer is None:
            sys.stderr.write(tool + ": failed\\n")
            sys.exit(22 if tool == "curl" else 1)
        sys.stdout.write(answer if isinstance(answer, str) else json.dumps(answer))
        sys.exit(0)

    if tool == "doppler":
        reply(scenario["infra"] if "infra" in args else scenario["worker"])
    if tool == "flyctl":
        reply(scenario["fly_list"] if args[:2] == ["secrets", "list"] else "")
    if tool == "curl":
        url = next(a for a in args if a.startswith("http"))
        for part, answer in scenario["http"].items():
            if part in url:
                reply(answer)
        reply(None)
    """
)


class Harness:
    def __init__(self, scenario: dict[str, object]) -> None:
        self.dir = Path(tempfile.mkdtemp())
        bin_dir = self.dir / "bin"
        bin_dir.mkdir()
        for tool in ("doppler", "flyctl", "curl"):
            path = bin_dir / tool
            path.write_text(STUB)
            path.chmod(0o755)
        (self.dir / "scenario.json").write_text(json.dumps(scenario))
        self.log = self.dir / "calls.jsonl"
        self.env_file = self.dir / "github_env"
        self.env_file.touch()
        self.env = {
            "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}",
            "STUB_LOG": str(self.log),
            "STUB_SCENARIO": str(self.dir / "scenario.json"),
            "GITHUB_ENV": str(self.env_file),
            "DOPPLER_TOKEN": "dp.st.ci.infra-token",
        }

    def run(
        self, script: Path, extra: dict[str, str] | None = None
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(script)],
            cwd=ROOT,
            env=self.env | (extra or {}),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
        )

    def calls(self, tool: str) -> list[dict[str, Any]]:
        if not self.log.exists():
            return []
        rows = [json.loads(line) for line in self.log.read_text().splitlines()]
        return [row for row in rows if row["tool"] == tool]

    def fly_mutations(self) -> list[list[str]]:
        return [
            call["args"]
            for call in self.calls("flyctl")
            if call["args"][:2] != ["secrets", "list"]
        ]

    def github_env(self) -> dict[str, str]:
        lines = self.env_file.read_text().splitlines()
        return dict(line.split("=", 1) for line in lines)


def worker(**secrets: str | None) -> str:
    return json.dumps({name: {"computed": value} for name, value in secrets.items()})


def fly_list(*names: str) -> str:
    return json.dumps([{"name": name, "digest": "x"} for name in names])


def unmasked(output: str, *values: str) -> list[str]:
    """Lines that show a value outside the `::add-mask::` that hides it."""

    return [
        line
        for line in output.splitlines()
        if not line.startswith("::add-mask::") and any(v in line for v in values)
    ]


class Stage(unittest.TestCase):
    def scenario(self, **overrides: object) -> dict[str, object]:
        base: dict[str, object] = {
            "infra": json.dumps({"DOPPLER_WORKER_TOKEN": {"computed": GRANT}}),
            "worker": worker(BRAINTRUST_API_KEY=KEY, BRAINTRUST_PROJECT_ID=PROJECT),
            "fly_list": fly_list("OPENROUTER_API_KEY"),
            "http": {},
        }
        return base | overrides

    def test_both_names_are_read_with_the_grant_and_staged(self) -> None:
        h = Harness(self.scenario())
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)

        infra, read = h.calls("doppler")
        self.assertEqual(infra["token"], "dp.st.ci.infra-token")
        self.assertEqual(read["token"], GRANT)
        self.assertEqual(
            read["args"][:4],
            ["secrets", "get", "BRAINTRUST_API_KEY", "BRAINTRUST_PROJECT_ID"],
        )
        self.assertIn("-p worker -c prd", " ".join(read["args"]))

        (imported,) = [a for a in h.fly_mutations() if a[:2] == ["secrets", "import"]]
        self.assertIn("--stage", imported)
        (stdin,) = [c["stdin"] for c in h.calls("flyctl") if c["args"] == imported]
        self.assertEqual(
            stdin,
            f'BRAINTRUST_API_KEY="{KEY}"\nBRAINTRUST_PROJECT_ID="{PROJECT}"\n',
        )
        env = h.github_env()
        self.assertEqual(env["WORKER_SECRETS_STAGED"], "1")
        self.assertEqual(env["BRAINTRUST_API_KEY"], KEY)
        # Masked before they reach $GITHUB_ENV, where later steps can echo them.
        for value in (GRANT, KEY, PROJECT):
            self.assertIn(f"::add-mask::{value}", result.stdout.splitlines())
        output = result.stdout + result.stderr
        self.assertEqual(unmasked(output, KEY, PROJECT, GRANT), [])

    def test_no_grant_ships_the_code_and_stages_nothing(self) -> None:
        h = Harness(self.scenario(infra="{}"))
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("DOPPLER_WORKER_TOKEN", result.stdout)
        self.assertIn("::error", result.stdout)
        self.assertEqual(len(h.calls("doppler")), 1)
        self.assertEqual(h.calls("flyctl"), [])
        self.assertEqual(h.github_env(), {"WORKER_SECRETS_STAGED": "0"})

    def test_a_grant_that_cannot_read_worker_changes_nothing_on_fly(self) -> None:
        h = Harness(self.scenario(worker=None))
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("cannot read Doppler worker/prd", result.stdout)
        self.assertEqual(h.fly_mutations(), [])
        self.assertEqual(h.github_env()["WORKER_SECRETS_STAGED"], "0")

    def test_a_name_gone_from_doppler_is_unset_on_fly(self) -> None:
        h = Harness(
            self.scenario(
                worker=worker(BRAINTRUST_API_KEY=KEY),
                fly_list=fly_list("BRAINTRUST_API_KEY", "BRAINTRUST_PROJECT_ID"),
            )
        )
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        unset = [a for a in h.fly_mutations() if a[:2] == ["secrets", "unset"]]
        self.assertEqual(len(unset), 1)
        self.assertIn("--stage", unset[0])
        self.assertEqual(unset[0][-1], "BRAINTRUST_PROJECT_ID")

    def test_a_name_absent_from_both_is_left_alone(self) -> None:
        h = Harness(self.scenario(worker=worker(BRAINTRUST_API_KEY=KEY)))
        self.assertEqual(h.run(STAGE).returncode, 0)
        self.assertEqual([a[:2] for a in h.fly_mutations()], [["secrets", "import"]])

    def test_no_key_in_doppler_is_carried_and_reported(self) -> None:
        h = Harness(
            self.scenario(
                worker=worker(BRAINTRUST_PROJECT_ID=PROJECT),
                fly_list=fly_list("BRAINTRUST_API_KEY"),
            )
        )
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::error title=No BRAINTRUST_API_KEY", result.stdout)
        unset = ["secrets", "unset", "--stage", "--config", "fly.toml"]
        self.assertIn([*unset, "BRAINTRUST_API_KEY"], h.fly_mutations())

    def test_an_unreadable_value_unsets_nothing(self) -> None:
        h = Harness(
            self.scenario(
                worker=worker(BRAINTRUST_API_KEY=None, BRAINTRUST_PROJECT_ID=PROJECT),
                fly_list=fly_list("BRAINTRUST_API_KEY"),
            )
        )
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(h.fly_mutations(), [])
        self.assertEqual(h.github_env()["WORKER_SECRETS_STAGED"], "0")

    def test_a_value_import_cannot_carry_is_refused(self) -> None:
        h = Harness(self.scenario(worker=worker(BRAINTRUST_API_KEY='sk-"quoted"')))
        result = h.run(STAGE)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(h.fly_mutations(), [])
        self.assertEqual(h.github_env()["WORKER_SECRETS_STAGED"], "0")


class Verify(unittest.TestCase):
    def run_verify(
        self, http: dict[str, object], **env: str
    ) -> tuple[Harness, subprocess.CompletedProcess[str]]:
        h = Harness({"http": http})
        base = {
            "JEVE_API": "https://api.example/",
            "DEPLOY_STARTED": "2026-09-23T00:00:00Z",
            "WORKER_SECRETS_STAGED": "1",
            "BRAINTRUST_API_KEY": KEY,
            "BRAINTRUST_PROJECT_ID": PROJECT,
        }
        return h, h.run(VERIFY, base | NO_WAITING | env)

    @staticmethod
    def state(tracing: bool) -> str:
        return json.dumps({"health": {"tracing": tracing}})

    def test_not_staged_fails_before_asking_anything(self) -> None:
        h, result = self.run_verify({}, WORKER_SECRETS_STAGED="0")
        self.assertEqual(result.returncode, 1)
        self.assertIn("not staged", result.stdout)
        self.assertEqual(h.calls("curl"), [])

    def test_tracing_off_fails(self) -> None:
        _, result = self.run_verify({"/state": self.state(False)})
        self.assertEqual(result.returncode, 1)
        self.assertIn("health.tracing=false", result.stdout)

    def test_an_unreachable_api_fails(self) -> None:
        _, result = self.run_verify({"/state": None})
        self.assertEqual(result.returncode, 1)
        self.assertIn("health.tracing=unknown", result.stdout)

    def test_a_span_after_the_deploy_is_a_notice(self) -> None:
        h, result = self.run_verify(
            {
                "/state": self.state(True),
                "/btql": {"data": [{"id": "a", "created": "2026-09-23T00:01:00Z"}]},
            }
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::notice", result.stdout)
        (btql,) = [c for c in h.calls("curl") if any("/btql" in a for a in c["args"])]
        body = json.loads(btql["args"][btql["args"].index("-d") + 1])
        self.assertIn(f"project_logs('{PROJECT}')", body["query"])
        self.assertIn("created > '2026-09-23T00:00:00Z'", body["query"])
        self.assertEqual(unmasked(result.stdout + result.stderr, KEY), [])

    def test_no_span_only_warns(self) -> None:
        _, result = self.run_verify({"/state": self.state(True), "/btql": {"data": []}})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning", result.stdout)

    def test_braintrust_down_only_warns(self) -> None:
        _, result = self.run_verify({"/state": self.state(True), "/btql": None})
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("::warning", result.stdout)

    def test_no_project_id_resolves_the_default_project(self) -> None:
        h, result = self.run_verify(
            {
                "/state": self.state(True),
                "/v1/project": {"objects": [{"id": "resolved-id"}]},
                "/btql": {"data": [{"id": "a", "created": "t"}]},
            },
            BRAINTRUST_PROJECT_ID="",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("project resolved-id", result.stdout)
        urls = [a for c in h.calls("curl") for a in c["args"] if a.startswith("http")]
        self.assertIn("https://api.braintrust.dev/v1/project?project_name=jeve", urls)


if __name__ == "__main__":
    unittest.main(verbosity=2)
