import asyncio
import random
import unittest

from app import texts
from app.config import ConfigError, Settings
from app.db import Database
from app.permissions import is_configured_admin, is_owner, status_is_admin
from app.runtime import Runtime
from app.scam import looks_like_admin, scan_message, verdict
from app.spam import Cooldown, FloodTracker, mute_minutes_for
from app.utils import (format_duration, parse_announcement, parse_duration, parse_target_token,
                       split_target_args, strip_command)
from app.validators import is_https_url, is_solana_address

WSOL = "So11111111111111111111111111111111111111112"  # public example address, NOT our CA
BASE_ENV = {"BOT_TOKEN": "123456789:" + "A" * 35, "ADMIN_IDS": "1,2"}
ALLOW = ("x.com", "pump.fun")


def run(coro):
    return asyncio.run(coro)


class Validators(unittest.TestCase):
    def test_solana(self):
        self.assertTrue(is_solana_address(WSOL))
        self.assertTrue(is_solana_address("1" * 32))
        for bad in ("", "abc", WSOL[:-1] + "0", WSOL + "1", "0" * 44, "send me sol", WSOL.replace("S", " ", 1)):
            self.assertFalse(is_solana_address(bad), bad)

    def test_https(self):
        self.assertTrue(is_https_url("https://x.com/BullShit_Solana"))
        for bad in ("http://x.com", "javascript:alert(1)", "https://", "https://a b.com", "https://u:p@x.com", ""):
            self.assertFalse(is_https_url(bad), bad)


class ConfigTests(unittest.TestCase):
    def test_ok_and_ca_empty(self):
        s = Settings.from_env(BASE_ENV)
        self.assertEqual(s.ca, "")
        self.assertEqual(s.owner_ids, frozenset({1, 2}))
        self.assertNotIn("AAAA", repr(s))  # token never in repr

    def test_coexist_mode_flag(self):
        self.assertFalse(Settings.from_env(BASE_ENV).coexist_mode)
        self.assertTrue(Settings.from_env({**BASE_ENV, "COEXIST_MODE": "true"}).coexist_mode)

    def test_missing_token(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({"ADMIN_IDS": "1"})

    def test_invalid_ca_stops_startup(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "BULLSHIT_CA": "definitelyNotAnAddress"})

    def test_valid_ca_and_bad_url(self):
        self.assertEqual(Settings.from_env({**BASE_ENV, "BULLSHIT_CA": WSOL}).ca, WSOL)
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "OFFICIAL_X": "http://x.com/a"})

    def test_bad_numbers(self):
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "ADMIN_IDS": "1,abc"})
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "WARN_MUTE_AT": "5", "WARN_BAN_AT": "3"})
        with self.assertRaises(ConfigError):
            Settings.from_env({**BASE_ENV, "FLOOD_MESSAGES": "x"})

    def test_tme_not_allowlisted_as_host(self):
        s = Settings.from_env({**BASE_ENV, "TELEGRAM_LINK": "https://t.me/bullshitherd"})
        self.assertNotIn("t.me", s.link_allowlist)
        self.assertIn("t.me/bullshitherd", s.link_allowlist)


class Permissions(unittest.TestCase):
    def test_rules(self):
        self.assertTrue(is_owner(1, frozenset({1})))
        self.assertFalse(is_owner(2, frozenset({1})))
        self.assertTrue(is_configured_admin(2, frozenset({1}), frozenset({2})))
        self.assertFalse(is_configured_admin(3, frozenset({1}), frozenset({2})))
        self.assertTrue(status_is_admin("creator") and status_is_admin("administrator"))
        self.assertFalse(status_is_admin("member") or status_is_admin("restricted"))


class ScamTests(unittest.TestCase):
    def score(self, t, **kw):
        return scan_message(t, ALLOW, **kw)

    def test_seed_request_deleted(self):
        r = self.score("Send me your seed phrase")
        self.assertEqual(verdict(r.score, delete_at=5, warn_at=3, ban_at=8), "delete")

    def test_warning_about_seed_is_not_flagged(self):
        for t in ("never share your seed phrase", "Do not send your private key to anyone",
                  "BULLSHIT admins will NEVER ask for your seed phrase"):
            self.assertEqual(self.score(t).score, 0, t)

    def test_negation_trick_still_caught(self):
        self.assertGreaterEqual(self.score("do not worry, send your seed phrase now").score, 5)

    def test_normal_chat_ok(self):
        for t in ("wen moon?", "gm bulls", "check the chart on pump.fun/coin/abc", "airdrop when?",
                  "my wallet is empty lol", "https://x.com/BullShit_Solana/status/1"):
            self.assertEqual(verdict(self.score(t).score, delete_at=5, warn_at=3, ban_at=8), "ok", t)

    def test_drainer_bait(self):
        r = self.score("Connect wallet to claim airdrop https://claim-bull.xyz")
        self.assertGreaterEqual(r.score, 8)

    def test_lookalike_and_spoof(self):
        self.assertTrue(any("lookalike" in x for x in self.score("visit https://phantom-wallet.top").reasons))
        self.assertTrue(any("spoof" in x for x in self.score("https://pump.fun.evil.com/x").reasons))
        self.assertTrue(any("lookalike:bullshit" in x for x in self.score("https://bullshit-airdrop.xyz").reasons))

    def test_userinfo_trick(self):
        r = self.score("https://pump.fun@evil.example.com/claim")
        self.assertTrue(r.unknown_links)

    def test_hidden_entity_url(self):
        r = self.score("click here", extra_urls=["https://bit.ly/abc"])
        self.assertGreaterEqual(r.score, 3)

    def test_fake_admin_dm(self):
        r = self.score("I am admin, dm me for support https://t.me/scammer")
        self.assertGreaterEqual(r.score, 5)

    def test_send_sol(self):
        self.assertGreaterEqual(self.score("send 1 SOL to receive 2 SOL back").score, 4)

    def test_allowlist_path(self):
        allow = ("t.me/bullshitherd",)
        self.assertEqual(scan_message("join t.me/bullshitherd", allow).unknown_links, [])
        self.assertTrue(scan_message("join t.me/scamgroup", allow).unknown_links)

    def test_impersonation(self):
        self.assertTrue(looks_like_admin(["Rob Pernama"], ["rob_pernama"]))
        self.assertTrue(looks_like_admin(["R0bbi Admin"], ["Robbi Admin"]))
        self.assertFalse(looks_like_admin(["Alex"], ["Alexa"]))
        self.assertFalse(looks_like_admin(["John Smith"], ["Robbi Admin"]))

    def test_verdict_levels(self):
        self.assertEqual(verdict(3, delete_at=5, warn_at=3, ban_at=8), "warn")
        self.assertEqual(verdict(9, delete_at=5, warn_at=3, ban_at=8), "ban")


class SpamTests(unittest.TestCase):
    def test_flood(self):
        t = FloodTracker(max_messages=3, window_seconds=5, repeat_limit=99)
        res = [t.check(1, 1, f"m{i}", float(i) * 0.1) for i in range(5)]
        self.assertEqual(res[:3], [None, None, None])
        self.assertEqual(res[3], "flood")

    def test_no_flood_when_slow(self):
        t = FloodTracker(max_messages=3, window_seconds=5, repeat_limit=99)
        self.assertTrue(all(t.check(1, 1, f"m{i}", i * 10.0) is None for i in range(10)))

    def test_repeat(self):
        t = FloodTracker(max_messages=99, window_seconds=5, repeat_limit=3)
        r = [t.check(1, 1, "buy my thing", i * 2.0) for i in range(3)]
        self.assertEqual(r[-1], "repeat")

    def test_users_isolated(self):
        t = FloodTracker(max_messages=2, window_seconds=5, repeat_limit=99)
        for i in range(2):
            t.check(1, 1, "a", i)
        self.assertIsNone(t.check(1, 2, "a", 2))

    def test_strike_escalation_and_decay(self):
        t = FloodTracker()
        self.assertEqual([t.strike(1, 1, n) for n in (0, 1, 2)], [1, 2, 3])
        self.assertEqual(t.strike(1, 1, 99999), 1)
        self.assertEqual([mute_minutes_for(s, 10) for s in (1, 2, 3, 20)], [10, 20, 40, 1440])

    def test_cooldown(self):
        c = Cooldown()
        self.assertTrue(c.hit("k", 10, 0))
        self.assertFalse(c.hit("k", 10, 5))
        self.assertTrue(c.hit("k", 10, 11))


class TextTests(unittest.TestCase):
    def test_welcome_default_and_vars(self):
        out = texts.render_welcome(texts.WELCOME_DEFAULT, first_name="Rob", username=None, user_id=5, group_name="G")
        self.assertIn("Welcome, Rob.", out)
        self.assertIn("BULLSHIT DETECTED", out)

    def test_welcome_escapes_and_no_injection(self):
        out = texts.render_welcome("hi {first_name} {mention}", first_name="<b>{mention}</b>", username="u",
                                   user_id=7, group_name="g")
        self.assertNotIn("<b>{", out)
        self.assertIn("&lt;b&gt;", out)
        self.assertEqual(out.count("tg://user?id=7"), 1)

    def test_rules(self):
        self.assertIn("10. Listen to moderators.", texts.RULES_DEFAULT)
        self.assertIn("STAY STUPID", texts.RULES_DEFAULT)

    def test_ca_not_configured(self):
        out = texts.build_ca("")
        self.assertIn("COMING SOON", out)
        self.assertNotIn("<code>", out)
        self.assertIn("CA: COMING SOON", texts.build_about(x="", website="", ca=""))

    def test_ca_configured(self):
        self.assertIn(f"<code>{WSOL}</code>", texts.build_ca(WSOL))

    def test_stats_omits_unknown_members(self):
        self.assertNotIn("Members", texts.build_stats(members=None, messages=1, warnings=0, new_members=2))
        self.assertIn("Members", texts.build_stats(members=10, messages=1, warnings=0, new_members=2))

    def test_personality(self):
        rng = random.Random(1)
        self.assertEqual(texts.pick_reply("wen moon?", rng)[0], "wen")
        self.assertEqual(texts.pick_reply("What's the thesis?")[1], "bull.\n\nshit.\n\nthat's the thesis.")
        self.assertIn("Absolutely not", texts.pick_reply("is this financial advice?")[1])
        self.assertIsNone(texts.pick_reply("hello"))
        self.assertTrue(texts.CA_QUESTION_RE.match("ca?"))
        self.assertFalse(texts.CA_QUESTION_RE.match("ca is a state"))

    def test_no_profit_promises_in_copy(self):
        blob = " ".join([texts.WELCOME_DEFAULT, texts.RULES_DEFAULT, texts.HELP_TEXT, *texts.WEN_REPLIES,
                         *texts.BULLSHIT_REPLIES, texts.build_about(x="", website="", ca="")]).lower()
        for banned in ("100x", "guaranteed profit", "will moon", "to the moon", "listed on", "partnership"):
            self.assertNotIn(banned, blob)


class UtilTests(unittest.TestCase):
    def test_duration(self):
        self.assertEqual(parse_duration("10m"), 600)
        self.assertEqual(parse_duration("2h"), 7200)
        self.assertEqual(parse_duration("1d"), 86400)
        for bad in ("", "10", "5s", "m10", "-5m", "99999d", "spam"):
            self.assertIsNone(parse_duration(bad), bad)
        self.assertEqual(format_duration(7200), "2h")

    def test_targets(self):
        self.assertEqual(split_target_args("@bob spamming", False), ("@bob", "spamming"))
        self.assertEqual(split_target_args("spamming", True), (None, "spamming"))
        self.assertEqual(parse_target_token("@bobby"), (None, "bobby"))
        self.assertEqual(parse_target_token("123"), (123, None))
        self.assertEqual(parse_target_token("bob; drop table"), (None, None))

    def test_strip_command(self):
        self.assertEqual(strip_command("/setwelcome@MyBot hello there"), "hello there")
        self.assertEqual(strip_command("/setwelcome"), "")

    def test_announcement(self):
        body, btns = parse_announcement("Big news\n[Site|https://example.com]\n[Bad|http://example.com]\n[X|javascript:1]")
        self.assertEqual(btns, [("Site", "https://example.com")])
        self.assertIn("[Bad|http://example.com]", body)


class DbTests(unittest.TestCase):
    def setUp(self):
        self.db = Database(":memory:")
        run(self.db.init())

    def test_warnings_and_stats(self):
        self.assertEqual(run(self.db.add_warning(5, "2026-10-05")), 1)
        self.assertEqual(run(self.db.add_warning(5, "2026-10-05")), 2)
        self.assertEqual(run(self.db.get_stats("2026-10-05"))["warnings"], 2)
        run(self.db.clear_warnings(5))
        self.assertEqual(run(self.db.get_warnings(5)), 0)

    def test_settings_and_logs(self):
        run(self.db.set_setting("ca", WSOL))
        self.assertEqual(run(self.db.get_setting("ca")), WSOL)
        run(self.db.del_setting("ca"))
        self.assertIsNone(run(self.db.get_setting("ca")))
        run(self.db.log_mod(1, 9, 5, "ban", "r"))
        self.assertEqual(run(self.db.recent_logs(5))[0]["action"], "ban")

    def test_join_and_message(self):
        run(self.db.upsert_user(7, "bob", "Bob", 1000, joined=True))
        self.assertEqual(run(self.db.record_message(7, "bob", "Bob", 2000, "d")), 1000)
        self.assertIsNone(run(self.db.record_message(8, "x", "X", 2000, "d")))
        self.assertEqual(run(self.db.get_stats("d"))["messages"], 2)
        self.assertEqual(run(self.db.find_user_by_username("@BOB"))["user_id"], 7)

    def test_pending_verification(self):
        run(self.db.add_pending(1, 2, 3, 100))
        self.assertEqual(run(self.db.due_pending(50)), [])
        self.assertEqual(len(run(self.db.due_pending(100))), 1)
        self.assertIsNotNone(run(self.db.pop_pending(1, 2)))
        self.assertIsNone(run(self.db.pop_pending(1, 2)))

    def test_bad_stat_field_rejected(self):
        with self.assertRaises(ValueError):
            run(self.db.bump("d", "messages; DROP TABLE users"))


class RuntimeTests(unittest.TestCase):
    def make(self):
        db = Database(":memory:")
        run(db.init())
        s = Settings.from_env(BASE_ENV)
        rt = Runtime(settings=s, db=db, tracker=FloodTracker())
        run(rt.load())
        return rt

    def test_ca_override_and_fallback(self):
        rt = self.make()
        self.assertEqual(run(rt.get_ca()), "")
        run(rt.db.set_setting("ca", WSOL))
        self.assertEqual(run(rt.get_ca()), WSOL)

    def test_thresholds(self):
        rt = self.make()
        self.assertIsNone(run(rt.set_threshold("flood_messages", 10)))
        self.assertEqual(rt.tracker.max_messages, 10)
        self.assertIn("between", run(rt.set_threshold("flood_messages", 1000)))
        self.assertIn("greater", run(rt.set_threshold("warn_ban_at", 3)))
        self.assertEqual(run(rt.set_threshold("nope", 1)), "Unknown setting.")

    def test_admin_check_fails_closed(self):
        rt = self.make()

        class Boom:
            async def get_chat_member(self, *a):
                raise RuntimeError("api down")

        self.assertTrue(run(rt.is_admin(Boom(), 1, 1)))      # configured admin
        self.assertFalse(run(rt.is_admin(Boom(), 1, 999)))   # unknown => denied

    def test_admin_check_uses_telegram_status(self):
        rt = self.make()

        class Member:
            status = "administrator"

        class Bot:
            async def get_chat_member(self, *a):
                return Member()

        self.assertTrue(run(rt.is_admin(Bot(), 1, 999)))


if __name__ == "__main__":
    unittest.main()
