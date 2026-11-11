import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from compare_motion_runs import compare


class MotionComparisonTests(unittest.TestCase):
    def test_browser_worker_join_and_historical_coverage(self):
        with TemporaryDirectory() as temp:
            directory = Path(temp)
            browser = directory / "turn-events.jsonl"
            worker = directory / "ditto-affect-applied.jsonl"
            def row(event, second, **details):
                return {"turn_id": "a", "event": event, "details": details,
                        "at": f"2026-11-11T00:00:{second:02d}+00:00"}
            ui = [row("motion_cue", 1, cue_id="1", phase="requested"),
                  row("motion_cue", 2, cue_id="1", phase="painted", painted_frames=1),
                  row("motion_cue", 2, cue_id="2", phase="head_busy"),
                  row("live_control", 3, seq=1, phase="requested", client_ms=400, transcript="private-phrase"),
                  row("live_control", 4, seq=1, phase="control.applied"),
                  row("live_control", 5, seq=1, phase="displayed", client_ms=1150),
                  row("playback_interrupted", 6)]
            browser.write_text("\n".join(json.dumps(r) for r in ui) + "\n{", encoding="utf-8")
            worker.write_text(json.dumps({"event": "ditto.affect_applied", "turn_id": "a",
                                          "avatar_id": "demo", "expression": "sad", "at": 10}), encoding="utf-8")
            report = compare(directory, None, "demo", 1)
            run = report["runs"][0]
            self.assertEqual(run["head_busy_gates"], 1)
            self.assertEqual(len(run["cues"][0]["events"]), 2)
            self.assertEqual(run["worker"]["scheduled"]["expression"], "sad")
            command = run["control_commands"][0]
            self.assertEqual(command["request_to_applied"], {"clock": "api_receipt", "ms": 1000})
            self.assertEqual(command["request_to_displayed"], {"clock": "browser_monotonic", "ms": 750})
            self.assertEqual(run["playback_outcome"], "playback_interrupted")
            self.assertNotIn("private-phrase", json.dumps(report))
            worker.unlink()
            runs = compare(directory, ["missing", "a"], None, 1)["runs"]
            self.assertFalse(runs[0]["found"])
            self.assertEqual(runs[1]["worker"], {})


if __name__ == "__main__":
    unittest.main()
