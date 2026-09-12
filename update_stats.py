#!/usr/bin/env python3
"""
Atualiza os números de seguidores da página de links.

    python3 update_stats.py --tiktok 50208 --instagram 99475 --youtube 14600

O que faz:
  1. Valida cada número (inteiro > 0 e não menor que 80% do valor anterior —
     protege contra a API devolver 0 ou lixo). Use --force para ignorar.
  2. Reescreve stats.json (lido pela página em tempo real).
  3. Atualiza os números fixos de fallback dentro do index.html
     (texto "NN,NK", data-target e o total "+NNN mil seguidores").

Sai com código 0 se atualizou, 3 se nada mudou, 1/2 em erro.
Não faz git — quem chama decide commitar.
"""
import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATS = HERE / "stats.json"
HTML = HERE / "index.html"
NETWORKS = ("tiktok", "instagram", "youtube")
MIN_RATIO = 0.80  # queda maior que 20% numa semana = provavelmente erro de API


def fmt_k(n: int) -> str:
    """50208 -> '50,2K' (vírgula pt-BR, 1 casa decimal)."""
    return f"{n / 1000:.1f}K".replace(".", ",")


def round_100(n: int) -> int:
    return int(round(n / 100.0)) * 100


def load_prev() -> dict:
    if STATS.exists():
        try:
            return json.loads(STATS.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {}


def validate(new: dict, prev: dict, force: bool) -> list[str]:
    problems = []
    for net in NETWORKS:
        v = new[net]
        if not isinstance(v, int) or v <= 0:
            problems.append(f"{net}: valor inválido {v!r} (precisa ser inteiro > 0)")
            continue
        p = prev.get(net)
        if isinstance(p, int) and p > 0 and v < p * MIN_RATIO and not force:
            problems.append(
                f"{net}: {v} é menor que {MIN_RATIO:.0%} do anterior ({p}) — "
                "parece erro de API; confira e use --force se for real"
            )
    return problems


def patch_html(html: str, new: dict) -> str:
    for net in NETWORKS:
        n = new[net]
        pattern = re.compile(
            r'(<div class="proof-number" data-network="' + net + r'" data-target=")'
            r'\d+("\s+data-suffix="K">)[^<]*(</div>)'
        )
        html, count = pattern.subn(
            lambda m: f"{m.group(1)}{round_100(n)}{m.group(2)}{fmt_k(n)}{m.group(3)}", html
        )
        if count != 1:
            raise RuntimeError(f"index.html: esperava 1 bloco para {net}, achei {count}")

    total_k = new["total"] // 1000
    html, count = re.subn(
        r'(<strong id="reach-total">)[^<]*(</strong>)',
        lambda m: f"{m.group(1)}+{total_k} mil seguidores{m.group(2)}",
        html,
    )
    if count != 1:
        raise RuntimeError(f"index.html: esperava 1 <strong id=\"reach-total\">, achei {count}")
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for net in NETWORKS:
        ap.add_argument(f"--{net}", type=int, required=True, help=f"seguidores atuais no {net}")
    ap.add_argument("--force", action="store_true", help="ignora a trava de queda > 20%%")
    ap.add_argument("--dry-run", action="store_true", help="só mostra o que faria")
    args = ap.parse_args()

    prev = load_prev()
    new = {net: getattr(args, net) for net in NETWORKS}
    problems = validate(new, prev, args.force)
    if problems:
        print("ERRO — nada foi alterado:", file=sys.stderr)
        for p in problems:
            print("  -", p, file=sys.stderr)
        return 2

    new["total"] = sum(new[net] for net in NETWORKS)
    new["updated"] = date.today().isoformat()
    new["source"] = "windsor.ai"

    if all(prev.get(net) == new[net] for net in NETWORKS):
        print("Sem mudança — números iguais aos de", prev.get("updated", "?"))
        return 3

    html = patch_html(HTML.read_text(encoding="utf-8"), new)

    def br(n: int) -> str:  # 50208 -> '50.208'
        return f"{n:,}".replace(",", ".")

    for net in NETWORKS:
        p = prev.get(net)
        delta = f" ({new[net] - p:+d})" if isinstance(p, int) else ""
        print(f"  {net:<10} {br(new[net]):>8}  → {fmt_k(new[net])}{delta}")
    print(f"  {'total':<10} {br(new['total']):>8}  → +{new['total'] // 1000} mil")

    if args.dry_run:
        print("(dry-run: nada gravado)")
        return 0

    STATS.write_text(json.dumps(new, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    HTML.write_text(html, encoding="utf-8")
    print("stats.json e index.html atualizados.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print("ERRO:", e, file=sys.stderr)
        sys.exit(1)
