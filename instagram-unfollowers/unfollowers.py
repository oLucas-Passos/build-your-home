#!/usr/bin/env python3
"""
Quem não me segue de volta no Instagram?

Compara a lista de quem você segue com a lista de quem te segue e devolve,
em uma tabela, todos os perfis que não te seguem de volta.

Dois modos de coleta:

  export  Lê o arquivo oficial "Baixar suas informações" do Instagram
          (ZIP ou pasta, formato JSON ou HTML). Não precisa de senha e não
          tem risco de bloqueio. É o modo recomendado.

  login   Entra na sua conta com o Instaloader e baixa as listas direto do
          Instagram. É mais automático, mas o Instagram pode pedir
          verificação ou limitar a conta se for usado com frequência.

Exemplos:
  python unfollowers.py export instagram-seuusuario-2026-11-25.zip
  python unfollowers.py login seuusuario
  python unfollowers.py export pasta_do_export --csv resultado.csv --html resultado.html
"""

from __future__ import annotations

import argparse
import csv
import getpass
import html
import json
import re
import sys
import time
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Iterable

PROFILE_URL = "https://www.instagram.com/{}/"
USERNAME_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
HREF_RE = re.compile(
    r'href="https?://(?:www\.)?instagram\.com/(?:_u/)?([A-Za-z0-9._]{1,30})/?"'
)


# --------------------------------------------------------------------------- #
# Modelo
# --------------------------------------------------------------------------- #
@dataclass
class Profile:
    username: str
    full_name: str = ""
    since: datetime | None = None  # quando você começou a seguir (modo export)
    verified: bool | None = None
    private: bool | None = None

    @property
    def url(self) -> str:
        return PROFILE_URL.format(self.username)


@dataclass
class Result:
    owner: str
    following: dict[str, Profile]
    followers: dict[str, Profile]
    not_following_back: list[Profile] = field(default_factory=list)
    fans: list[Profile] = field(default_factory=list)  # te seguem, você não segue
    mutuals: int = 0


def compare(owner: str, following: dict[str, Profile], followers: dict[str, Profile]) -> Result:
    not_back = [p for u, p in following.items() if u not in followers]
    fans = [p for u, p in followers.items() if u not in following]
    # Mais antigos primeiro quando há data; senão ordem alfabética.
    not_back.sort(key=lambda p: (p.since is None, p.since or datetime.min, p.username))
    fans.sort(key=lambda p: p.username)
    mutuals = len(following.keys() & followers.keys())
    return Result(owner, following, followers, not_back, fans, mutuals)


# --------------------------------------------------------------------------- #
# Modo 1: export oficial do Instagram
# --------------------------------------------------------------------------- #
class ExportSource:
    """Acesso uniforme a um export em ZIP ou em pasta já extraída."""

    def __init__(self, path: Path):
        self.path = path
        if path.is_file() and zipfile.is_zipfile(path):
            self._zip = zipfile.ZipFile(path)
            self._names = [n for n in self._zip.namelist() if not n.endswith("/")]
        elif path.is_dir():
            self._zip = None
            self._names = [
                p.relative_to(path).as_posix() for p in path.rglob("*") if p.is_file()
            ]
        else:
            raise SystemExit(f"Erro: '{path}' não é um arquivo .zip nem uma pasta.")

    def find(self, pattern: str) -> list[str]:
        rx = re.compile(pattern, re.IGNORECASE)
        return sorted(n for n in self._names if rx.search(PurePosixPath(n).name))

    def read(self, name: str) -> str:
        if self._zip is not None:
            data = self._zip.read(name)
        else:
            data = (self.path / name).read_bytes()
        return data.decode("utf-8", errors="replace")


def _ts(value) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(value)) if value else None
    except (TypeError, ValueError, OSError):
        return None


def _username_from_href(href: str) -> str | None:
    m = re.search(r"instagram\.com/(?:_u/)?([A-Za-z0-9._]{1,30})", href or "")
    return m.group(1) if m else None


def _profiles_from_json(raw) -> Iterable[Profile]:
    """Aceita os diferentes formatos que o Instagram já usou no export."""
    if isinstance(raw, dict):
        # following.json -> {"relationships_following": [...]}
        lists = [v for v in raw.values() if isinstance(v, list)]
        entries = [e for lst in lists for e in lst]
    elif isinstance(raw, list):
        entries = raw  # followers_1.json -> [...]
    else:
        return []

    out = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        items = entry.get("string_list_data") or [{}]
        for item in items:
            username = (
                item.get("value")
                or entry.get("title")
                or _username_from_href(item.get("href", ""))
            )
            if username and USERNAME_RE.match(username):
                out.append(Profile(username=username.lower(), since=_ts(item.get("timestamp"))))
    return out


def _profiles_from_html(text: str) -> Iterable[Profile]:
    seen = set()
    for m in HREF_RE.finditer(text):
        u = m.group(1).lower()
        if u not in seen:
            seen.add(u)
            yield Profile(username=u)


def _load_lists(src: ExportSource, pattern: str, label: str) -> dict[str, Profile]:
    files = src.find(pattern + r"\.json$") or src.find(pattern + r"\.html$")
    if not files:
        raise SystemExit(
            f"Erro: não encontrei o arquivo de {label} no export.\n"
            "Confira se você pediu 'Seguidores e seguindo' em 'Baixar suas informações'."
        )
    profiles: dict[str, Profile] = {}
    for name in files:
        text = src.read(name)
        parsed = (
            _profiles_from_json(json.loads(text))
            if name.lower().endswith(".json")
            else _profiles_from_html(text)
        )
        for p in parsed:
            profiles.setdefault(p.username, p)
    return profiles


def collect_from_export(path: Path) -> tuple[str, dict[str, Profile], dict[str, Profile]]:
    src = ExportSource(path)
    # followers_1.json, followers_2.json ... e following.json
    followers = _load_lists(src, r"^followers(_\d+)?", "seguidores")
    following = _load_lists(src, r"^following", "quem você segue")
    owner = ""
    m = re.match(r"instagram-([A-Za-z0-9._]+?)-\d{4}", path.name)
    if m:
        owner = m.group(1)
    return owner, following, followers


# --------------------------------------------------------------------------- #
# Modo 2: login com Instaloader
# --------------------------------------------------------------------------- #
def collect_from_login(
    username: str, session_file: str | None, delay: float
) -> tuple[str, dict[str, Profile], dict[str, Profile]]:
    try:
        import instaloader
    except ImportError:
        raise SystemExit("Erro: instale o Instaloader primeiro:  pip install instaloader")

    L = instaloader.Instaloader(
        quiet=True,
        download_pictures=False,
        download_videos=False,
        save_metadata=False,
        max_connection_attempts=3,
    )

    try:
        L.load_session_from_file(username, session_file)
        print(f"Sessão salva carregada para @{username}.")
    except FileNotFoundError:
        password = getpass.getpass(f"Senha do Instagram de @{username} (não é salva): ")
        try:
            L.login(username, password)
        except instaloader.TwoFactorAuthRequiredException:
            code = input("Código de verificação em duas etapas: ").strip()
            L.two_factor_login(code)
        except instaloader.BadCredentialsException:
            raise SystemExit("Erro: usuário ou senha incorretos.")
        except instaloader.ConnectionException as exc:
            raise SystemExit(
                f"Erro ao entrar: {exc}\n"
                "Se o Instagram pediu verificação (checkpoint), confirme o acesso no "
                "app e tente de novo, ou use o modo 'export'."
            )
        L.save_session_to_file(session_file)
        print("Login feito. Sessão salva para as próximas execuções.")

    profile = instaloader.Profile.from_username(L.context, username)

    def fetch(iterator, total: int, label: str) -> dict[str, Profile]:
        out: dict[str, Profile] = {}
        for i, p in enumerate(iterator, 1):
            out[p.username.lower()] = Profile(
                username=p.username.lower(),
                full_name=p.full_name or "",
                verified=p.is_verified,
                private=p.is_private,
            )
            print(f"\r  {label}: {i}/{total}", end="", flush=True)
            if delay and i % 50 == 0:
                time.sleep(delay)  # pausa para não estourar o limite do Instagram
        print()
        return out

    print(f"Baixando listas de @{username}...")
    try:
        following = fetch(profile.get_followees(), profile.followees, "Seguindo  ")
        followers = fetch(profile.get_followers(), profile.followers, "Seguidores")
    except instaloader.InstaloaderException as exc:
        raise SystemExit(
            f"\nErro: o Instagram interrompeu o download ({exc}).\n"
            "Espere algumas horas antes de tentar de novo, ou use o modo 'export'."
        )
    return username, following, followers


# --------------------------------------------------------------------------- #
# Saída
# --------------------------------------------------------------------------- #
def _rows(profiles: list[Profile]) -> tuple[list[str], list[list[str]]]:
    has_since = any(p.since for p in profiles)
    has_name = any(p.full_name for p in profiles)
    has_flags = any(p.verified is not None for p in profiles)

    header = ["#", "Usuário"]
    if has_name:
        header.append("Nome")
    if has_since:
        header.append("Você segue desde")
    if has_flags:
        header += ["Verificado", "Privado"]
    header.append("Link")

    rows = []
    for i, p in enumerate(profiles, 1):
        row = [str(i), "@" + p.username]
        if has_name:
            row.append(p.full_name)
        if has_since:
            row.append(p.since.strftime("%d/%m/%Y") if p.since else "")
        if has_flags:
            row += ["sim" if p.verified else "não", "sim" if p.private else "não"]
        row.append(p.url)
        rows.append(row)
    return header, rows


def print_table(title: str, profiles: list[Profile]) -> None:
    header, rows = _rows(profiles)
    try:
        from rich.console import Console
        from rich.table import Table

        table = Table(title=title, header_style="bold magenta", show_lines=False)
        for h in header:
            table.add_column(h, justify="right" if h == "#" else "left", overflow="fold")
        for r in rows:
            table.add_row(*r)
        Console().print(table)
        return
    except ImportError:
        pass

    widths = [max(len(h), *(len(r[i]) for r in rows)) if rows else len(h)
              for i, h in enumerate(header)]
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    line = lambda cells: "| " + " | ".join(c.ljust(w) for c, w in zip(cells, widths)) + " |"
    print(f"\n{title}")
    print(sep)
    print(line(header))
    print(sep.replace("-", "="))
    for r in rows:
        print(line(r))
    print(sep)


def save_csv(path: Path, profiles: list[Profile]) -> None:
    header, rows = _rows(profiles)
    with path.open("w", newline="", encoding="utf-8-sig") as f:  # utf-8-sig abre certo no Excel
        w = csv.writer(f, delimiter=";")
        w.writerow(header)
        w.writerows(rows)


def save_xlsx(path: Path, profiles: list[Profile]) -> None:
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, PatternFill
    except ImportError:
        raise SystemExit("Erro: para salvar em .xlsx instale:  pip install openpyxl")
    header, rows = _rows(profiles)
    wb = Workbook()
    ws = wb.active
    ws.title = "Não seguem de volta"
    ws.append(header)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF")
        c.fill = PatternFill("solid", fgColor="C13584")
    link_col = len(header)
    for r in rows:
        r = [int(r[0])] + r[1:]
        ws.append(r)
        cell = ws.cell(row=ws.max_row, column=link_col)
        cell.hyperlink = cell.value
        cell.style = "Hyperlink"
    for col in ws.columns:
        ws.column_dimensions[col[0].column_letter].width = min(
            60, max(len(str(c.value or "")) for c in col) + 2
        )
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    wb.save(path)


def save_html(path: Path, result: Result) -> None:
    header, rows = _rows(result.not_following_back)
    link_idx = len(header) - 1
    body = []
    for r in rows:
        cells = []
        for i, c in enumerate(r):
            if i == link_idx:
                cells.append(f'<td><a href="{html.escape(c)}" target="_blank" rel="noopener">abrir perfil</a></td>')
            else:
                cells.append(f"<td>{html.escape(c)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")

    owner = f"@{html.escape(result.owner)}" if result.owner else "sua conta"
    doc = f"""<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Não seguem de volta</title>
<style>
  :root {{ --bg:#fafafa; --fg:#262626; --muted:#737373; --card:#fff; --line:#dbdbdb; --accent:#c13584; }}
  @media (prefers-color-scheme: dark) {{ :root {{ --bg:#000; --fg:#f5f5f5; --muted:#a8a8a8; --card:#121212; --line:#363636; }} }}
  body {{ margin:0; padding:24px 16px; background:var(--bg); color:var(--fg);
         font:15px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }}
  main {{ max-width:900px; margin:0 auto; }}
  h1 {{ font-size:22px; margin:0 0 4px; }}
  p.sub {{ color:var(--muted); margin:0 0 20px; }}
  .stats {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom:20px; }}
  .stat {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; }}
  .stat b {{ display:block; font-size:20px; }}
  .stat span {{ color:var(--muted); font-size:13px; }}
  input {{ width:100%; box-sizing:border-box; padding:10px 12px; margin-bottom:12px; border-radius:8px;
          border:1px solid var(--line); background:var(--card); color:var(--fg); font-size:15px; }}
  .wrap {{ overflow-x:auto; background:var(--card); border:1px solid var(--line); border-radius:10px; }}
  table {{ border-collapse:collapse; width:100%; }}
  th, td {{ text-align:left; padding:9px 12px; border-bottom:1px solid var(--line); white-space:nowrap; }}
  th {{ font-size:13px; color:var(--muted); font-weight:600; }}
  tr:last-child td {{ border-bottom:0; }}
  a {{ color:var(--accent); }}
</style></head><body><main>
<h1>Quem não segue {owner} de volta</h1>
<p class="sub">Gerado em {datetime.now():%d/%m/%Y %H:%M}</p>
<div class="stats">
  <div class="stat"><b>{len(result.following)}</b><span>você segue</span></div>
  <div class="stat"><b>{len(result.followers)}</b><span>seguidores</span></div>
  <div class="stat"><b>{result.mutuals}</b><span>se seguem</span></div>
  <div class="stat"><b>{len(result.not_following_back)}</b><span>não seguem de volta</span></div>
</div>
<input id="q" type="search" placeholder="Filtrar por usuário..." aria-label="Filtrar">
<div class="wrap"><table>
<thead><tr>{"".join(f"<th>{html.escape(h)}</th>" for h in header)}</tr></thead>
<tbody id="t">{"".join(body)}</tbody>
</table></div>
<script>
  document.getElementById('q').addEventListener('input', e => {{
    const q = e.target.value.toLowerCase();
    for (const tr of document.querySelectorAll('#t tr'))
      tr.hidden = !tr.textContent.toLowerCase().includes(q);
  }});
</script>
</main></body></html>
"""
    path.write_text(doc, encoding="utf-8")


def print_summary(result: Result) -> None:
    who = f"@{result.owner}" if result.owner else "Sua conta"
    print()
    print(f"{who}")
    print(f"  Você segue ............ {len(result.following)}")
    print(f"  Seguidores ............ {len(result.followers)}")
    print(f"  Se seguem (mútuos) .... {result.mutuals}")
    print(f"  Não seguem de volta ... {len(result.not_following_back)}")
    print(f"  Você não segue de volta {len(result.fans)}")


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Mostra em uma tabela quem você segue no Instagram e não te segue de volta.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Exemplos:" + __doc__.split("Exemplos:")[1],
    )
    sub = ap.add_subparsers(dest="mode", required=True)

    e = sub.add_parser("export", help="usar o arquivo 'Baixar suas informações' do Instagram")
    e.add_argument("path", type=Path, help="arquivo .zip do export ou pasta extraída")

    l = sub.add_parser("login", help="entrar na conta e baixar as listas (Instaloader)")
    l.add_argument("username", help="seu usuário do Instagram, sem @")
    l.add_argument("--session-file", help="onde salvar/carregar a sessão (padrão do Instaloader)")
    l.add_argument("--delay", type=float, default=2.0,
                   help="segundos de pausa a cada 50 perfis (padrão: 2)")

    for p in (e, l):
        p.add_argument("--csv", type=Path, help="salvar a tabela em CSV")
        p.add_argument("--xlsx", type=Path, help="salvar a tabela em Excel (.xlsx)")
        p.add_argument("--html", type=Path, help="salvar a tabela em uma página HTML")
        p.add_argument("--ignore", type=Path,
                       help="arquivo .txt com usuários para ignorar (um por linha), ex.: famosos")
        p.add_argument("--fans", action="store_true",
                       help="também listar quem te segue e você não segue de volta")
        p.add_argument("--no-table", action="store_true", help="não imprimir a tabela no terminal")
    return ap


def load_ignore(path: Path | None) -> set[str]:
    if not path:
        return set()
    names = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip().lstrip("@").lower()
        if line:
            names.add(line)
    return names


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.mode == "export":
        owner, following, followers = collect_from_export(args.path)
    else:
        owner, following, followers = collect_from_login(
            args.username.lstrip("@"), args.session_file, args.delay
        )

    if not following:
        print("Nenhum perfil encontrado na lista de quem você segue.", file=sys.stderr)
        return 1

    result = compare(owner, following, followers)

    ignored = load_ignore(args.ignore)
    if ignored:
        before = len(result.not_following_back)
        result.not_following_back = [p for p in result.not_following_back if p.username not in ignored]
        print(f"{before - len(result.not_following_back)} perfil(is) ignorado(s) pela lista.")

    print_summary(result)

    if not args.no_table:
        if result.not_following_back:
            print_table("Não te seguem de volta", result.not_following_back)
        else:
            print("\nTodo mundo que você segue te segue de volta!")
        if args.fans and result.fans:
            print_table("Te seguem, mas você não segue de volta", result.fans)

    if args.csv:
        save_csv(args.csv, result.not_following_back)
        print(f"CSV salvo em {args.csv}")
    if args.xlsx:
        save_xlsx(args.xlsx, result.not_following_back)
        print(f"Planilha salva em {args.xlsx}")
    if args.html:
        save_html(args.html, result)
        print(f"Página salva em {args.html}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
