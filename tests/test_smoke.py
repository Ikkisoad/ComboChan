import unittest
from unittest.mock import Mock

from combochan.bridge import Step, Trial
from combochan.core import FrameExecutor
from combochan.evaluate import repeatability
from combochan.policy import Policy
from combochan.smoke import run_smoke
from combochan.stub import StubAdapter


class SmokeTests(unittest.TestCase):
    def test_offline_slice(self):
        report = run_smoke()
        self.assertFalse(report["real_game_verified"])
        self.assertEqual(report["best"]["id"], "connected")
        self.assertEqual(report["best"]["damage"], 25)
        results = {r["id"]: r for r in report["results"]}
        self.assertIn("recovery_gap", results["gap"]["rejection_reasons"])
        self.assertIn("no_damage", results["whiff"]["rejection_reasons"])

    def test_laya_ordering_does_not_override_measured_score(self):
        policy = Policy()
        policy.mode = "laya"
        policy.agent = Mock()
        policy.agent.predict.return_value = {"answers": {"next": {
            "probabilities": {"0": 0.1, "1": 0.2, "2": 0.7}}}}
        report = run_smoke(policy)
        policy.agent.predict.assert_called_once()
        self.assertEqual(len(report["results"]), 3)
        self.assertEqual(report["best"]["id"], "connected")

    def test_restoration_and_repeated_execution(self):
        game = StubAdapter()
        game.step(Step(1, ("MP",)))
        snapshot = game.save_state()
        expected = game.observe()
        game.step(Step(20))
        game.load_state(snapshot)
        self.assertEqual(game.observe(), expected)
        # Held input is part of the snapshot; holding MP does not hit twice.
        self.assertEqual(game.step(Step(1, ("MP",)))[0]["p2"]["health"], 278)
        records = FrameExecutor(game).execute(snapshot, Trial("repeat", (Step(1), Step(1, ("HK",))), repeats=3, tail=300))
        self.assertTrue(repeatability(records)["repeat"]["identical"])
        self.assertEqual(len(records[0]["trace"]), 303)
        self.assertEqual(game.held, ())

    def test_release_on_adapter_failure(self):
        game = StubAdapter()
        snapshot = game.save_state()
        game.step = Mock(side_effect=RuntimeError("adapter failure"))
        game.release_inputs = Mock()
        with self.assertRaisesRegex(RuntimeError, "adapter failure"):
            FrameExecutor(game).execute(snapshot, Trial("failure", (Step(1),)))
        game.release_inputs.assert_called_once()


if __name__ == "__main__":
    unittest.main()
