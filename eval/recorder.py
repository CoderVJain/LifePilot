"""Record what the model said, so the same check never costs twice.

Every ad-hoc probe so far spent a Bedrock call and threw the answer away. A recorded response is a
fixture: run it once against the real model, replay it for free in CI forever, and re-record
deliberately when a prompt changes. That turns "did this break?" from a question with a price into a
question with an answer.

Recordings are keyed by what actually determines the reply -- the model, the system prompt, the tool
schemas and the words said -- so changing any of them misses the cache and is recorded afresh rather
than silently replaying an answer to a different question.
"""

import hashlib
import json
from pathlib import Path
from typing import Any

CASSETTES = Path(__file__).resolve().parent / "cassettes"


def key_for(model: str, system: list[dict], tools: list[dict] | None, messages: list[dict]) -> str:
    """A fingerprint of everything that decides the answer."""
    digest = hashlib.sha256()
    digest.update(model.encode())
    digest.update(json.dumps(system, sort_keys=True).encode())
    digest.update(json.dumps(tools or [], sort_keys=True).encode())
    digest.update(json.dumps(messages, sort_keys=True).encode())
    return digest.hexdigest()[:16]


class Cassette:
    """Replays a recorded Bedrock reply, or records one if it has never been seen.

    `live=False` refuses to make a call for anything unrecorded. That is what keeps the offline
    suite honest: a missing recording is a failure that says which utterance is missing, not a
    silent trip to a paid API from a test run.
    """

    def __init__(self, name: str, live: bool = False):
        self.path = CASSETTES / f"{name}.json"
        self.live = live
        self.recorded: dict[str, Any] = {}
        self.added = 0
        self.replayed = 0
        if self.path.is_file():
            self.recorded = json.loads(self.path.read_text(encoding="utf-8"))

    def respond(self, key: str, call) -> dict:
        """The recorded reply for this key, recording one first if there is none."""
        if key in self.recorded:
            self.replayed += 1
            return self.recorded[key]["response"]

        if not self.live:
            raise LookupError(
                f"nothing recorded for {key} in {self.path.name}. "
                "Run the eval once with --with-llm to record it."
            )

        response = call()
        self.recorded[key] = {"response": response}
        self.added += 1
        return response

    def save(self) -> None:
        if not self.added:
            return
        CASSETTES.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(self.recorded, indent=2, sort_keys=True), encoding="utf-8"
        )

    def __str__(self) -> str:
        return f"{self.path.name}: {self.replayed} replayed, {self.added} recorded"
