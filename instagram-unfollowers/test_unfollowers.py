"""Testes com exports falsos nos formatos que o Instagram já usou.

Rodar:  python -m unittest test_unfollowers.py
"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

import unfollowers as uf

BASE = "connections/followers_and_following/"


def follower(u, ts=1700000000):
    return {"title": "", "media_list_data": [], "string_list_data": [
        {"href": f"https://www.instagram.com/{u}", "value": u, "timestamp": ts}]}


def following_old(u, ts=1700000000):
    return follower(u, ts)


def following_new(u, ts=1700000000):
    # Formato mais recente: o usuário vem em "title" e não há "value".
    return {"title": u, "string_list_data": [
        {"href": f"https://www.instagram.com/_u/{u}", "timestamp": ts}]}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())

    def make_zip(self, files):
        path = self.tmp / "instagram-lucas.teste-2026-11-25-abc.zip"
        with zipfile.ZipFile(path, "w") as z:
            for name, content in files.items():
                z.writestr(BASE + name, content)
        return path

    def test_json_zip_new_format_with_pagination(self):
        path = self.make_zip({
            "followers_1.json": json.dumps([follower("ana"), follower("Bia")]),
            "followers_2.json": json.dumps([follower("carlos")]),
            "following.json": json.dumps({"relationships_following": [
                following_new("ana"), following_new("bia"),
                following_new("famoso", 1600000000), following_new("dani", 1650000000)]}),
        })
        owner, following, followers = uf.collect_from_export(path)
        r = uf.compare(owner, following, followers)
        self.assertEqual(owner, "lucas.teste")
        self.assertEqual([p.username for p in r.not_following_back], ["famoso", "dani"])
        self.assertEqual([p.username for p in r.fans], ["carlos"])
        self.assertEqual(r.mutuals, 2)

    def test_json_folder_old_format(self):
        d = self.tmp / "export" / BASE
        d.mkdir(parents=True)
        (d / "followers_1.json").write_text(json.dumps([follower("ana")]))
        (d / "following.json").write_text(json.dumps(
            {"relationships_following": [following_old("ana"), following_old("zeca")]}))
        _, following, followers = uf.collect_from_export(self.tmp / "export")
        r = uf.compare("", following, followers)
        self.assertEqual([p.username for p in r.not_following_back], ["zeca"])

    def test_html_export(self):
        link = '<a target="_blank" href="https://www.instagram.com/{0}">{0}</a>'
        path = self.make_zip({
            "followers_1.html": "<html>" + link.format("ana") + "</html>",
            "following.html": "<html>" + link.format("ana") + link.format("beto") + "</html>",
        })
        _, following, followers = uf.collect_from_export(path)
        r = uf.compare("", following, followers)
        self.assertEqual([p.username for p in r.not_following_back], ["beto"])

    def test_cli_outputs_and_ignore(self):
        path = self.make_zip({
            "followers_1.json": json.dumps([follower("ana")]),
            "following.json": json.dumps({"relationships_following": [
                following_new("ana"), following_new("beto"), following_new("neymarjr")]}),
        })
        ignore = self.tmp / "ignorar.txt"
        ignore.write_text("@NeymarJr  # famoso\n")
        out = {ext: self.tmp / f"r.{ext}" for ext in ("csv", "xlsx", "html")}
        code = uf.main(["export", str(path), "--ignore", str(ignore),
                        "--csv", str(out["csv"]), "--xlsx", str(out["xlsx"]),
                        "--html", str(out["html"]), "--no-table"])
        self.assertEqual(code, 0)
        csv_text = out["csv"].read_text(encoding="utf-8-sig")
        self.assertIn("@beto", csv_text)
        self.assertNotIn("neymarjr", csv_text)
        self.assertIn("@beto", out["html"].read_text(encoding="utf-8"))
        self.assertTrue(out["xlsx"].stat().st_size > 0)

    def test_missing_files(self):
        path = self.make_zip({"outra_coisa.json": "{}"})
        with self.assertRaises(SystemExit):
            uf.collect_from_export(path)


if __name__ == "__main__":
    unittest.main()
