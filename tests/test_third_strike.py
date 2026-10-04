import unittest
from combochan.games import ThirdStrike, get_game
from combochan.dashboard import Dashboard, validate_rules
from combochan.game_profile import validate_profile, template


class ThirdStrikeTests(unittest.TestCase):
    def test_builtin_identity_and_telemetry(self):
        game = get_game('street-fighter-iii-third-strike')
        self.assertIsInstance(game, ThirdStrike)
        self.assertEqual(game.rom, 'sfiii3nr1')
        self.assertEqual(game.telemetry['players']['p2']['health']['address'], 0x020691A3)
        self.assertEqual(game.telemetry['players']['p1']['x']['address'], 0x02068CD0)
        self.assertEqual(game.telemetry['inputs']['HK']['p2'], 'P2 Strong Kick')
        self.assertIn(game.profile_sha256, game.session_script())
        self.assertEqual(game.profile_sha256, ThirdStrike().profile_sha256)
        self.assertFalse(game.vsav_ordering)
        self.assertFalse(game.public()['combo_validated'])

    def test_unsupported_verification_and_partial_meter_cap(self):
        game = ThirdStrike()
        rules = validate_rules({'true_combo': False}, game)
        self.assertEqual(len(game.search_actions(rules)), 40)
        with self.assertRaisesRegex(ValueError, 'calibration'):
            validate_rules({'true_combo': True}, game)
        with self.assertRaisesRegex(ValueError, 'partial meter'):
            validate_rules({'true_combo': False, 'resources': 'cap'}, game)
        with self.assertRaisesRegex(ValueError, '0-160'):
            game.validate_initial({'p1': {'health': 161}, 'p2': {'health': 160}})

    def test_builtin_id_cannot_be_overwritten(self):
        data = template()
        data['id'] = ThirdStrike.id
        with self.assertRaisesRegex(ValueError, 'reserved'):
            validate_profile(data)


if __name__ == '__main__':
    unittest.main()
