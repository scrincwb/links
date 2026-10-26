#!/usr/bin/env python3
"""
Atualiza os números de seguidores da página de links.

    python3 update_stats.py --tiktok 50208 --instagram 99475 --youtube 14600

O que faz:
  1. Valida cada número (inteiro > 0 e não menor que 80% do valor anterior —
     protege contra a API devolver 0 ou lixo). Use --force para ignorar.
  2. Reescreve stats.json (lido pela página em tempo real).
  3. Atualiza os números fixos de fallback dentro do index.html
     (texto "+NN mil", data-target e o total "+NNN mil seguidores").

Formato (igual ao JS da página): 2 algarismos significativos, sempre para
baixo, "+N mil" / "+N milhões". REGRA ABSOLUTA: nunca exibir 13. Depois de
formatar, se os dígitos tiverem "13", desce uma unidade do último algarismo
exibido até sumir (136.282 → 130 → "+120 mil"; 213.554 → "+210 mil").

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


def tem_13(s: str) -> bool:
    return "13" in re.sub(r"\D", "", s)


def _dec(v: float) -> str:
    """12.0 -> '12' · 3.7 -> '3,7' (vírgula pt-BR)."""
    t = f"{round(v, 1):.1f}"
    if t.endswith(".0"):
        t = t[:-2]
    return t.replace(".", ",")


def fmt_seg(n: int) -> str:
    """Número exibido na página, sempre para baixo e sem 13.

    213554 -> '+210 mil' · 136282 -> '+120 mil' · 62272 -> '+62 mil'
    15000 -> '+15 mil' · 8153459 -> '+8 milhões' · 3702793 -> '+3,7 milhões'
    """
    n = int(n)
    if n >= 1_000_000:
        v, step = (n // 100_000) / 10, 0.1
        if v >= 5:
            v, step = float(int(v)), 1.0
        unit = lambda x: " milhão" if x < 2 else " milhões"
    elif n >= 1000:
        k = n / 1000
        if k >= 100:
            v, step = float(int(k // 10) * 10), 10.0
        elif k >= 10:
            v, step = float(int(k)), 1.0
        else:
            v, step = int(k * 10) / 10, 0.1
        unit = lambda x: " mil"
    else:
        v, step = float(n), 1.0
        unit = lambda x: ""
    while v > 0 and tem_13(_dec(v)):
        v = round(v - step, 1)
    return f"+{_dec(v)}{unit(v)}"


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
            r'(<span class="proof-number[^"]*" data-network="' + net + r'" data-target=")'
            r'\d+(">)[^<]*(</span>)'
        )
        html, count = pattern.subn(
            lambda m: f"{m.group(1)}{n}{m.group(2)}{fmt_seg(n)}{m.group(3)}", html
        )
        if count != 1:
            raise RuntimeError(f"index.html: esperava 1 bloco para {net}, achei {count}")

    html, count = re.subn(
        r'(<strong id="reach-total"[^>]*>)[^<]*(</strong>)',
        lambda m: f"{m.group(1)}{fmt_seg(new['total'])} seguidores{m.group(2)}",
        html,
    )
    if count != 1:
        raise RuntimeError(f"index.html: esperava 1 <strong id=\"reach-total\">, achei {count}")
    return html


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    for net in NETWORKS:
        ap.add_argument(f"--{net}", type=int, required=True, help=f"seguidores atuais no {net}")
    ap.add_argument("--views", type=int, default=0, help="views nos últimos 30 dias (IG+TikTok+YouTube) — opcional, vai só para o stats.json")
    ap.add_argument("--alcance", type=int, default=0, help="contas únicas alcançadas no Instagram em 90 dias — opcional, vai só para o stats.json")
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
    # views/alcance (lidos pelo site principal): se não vierem, mantém os anteriores
    new["views_30d"] = args.views if args.views > 0 else int(prev.get("views_30d") or 0)
    new["reach_90d"] = args.alcance if args.alcance > 0 else int(prev.get("reach_90d") or 0)
    new["updated"] = date.today().isoformat()
    new["source"] = "windsor.ai"

    if all(prev.get(net) == new[net] for net in NETWORKS) and prev.get("views_30d") == new["views_30d"] and prev.get("reach_90d") == new["reach_90d"]:
        print("Sem mudança — números iguais aos de", prev.get("updated", "?"))
        return 3

    html = patch_html(HTML.read_text(encoding="utf-8"), new)

    def br(n: int) -> str:  # 50208 -> '50.208'
        return f"{n:,}".replace(",", ".")

    for net in NETWORKS:
        p = prev.get(net)
        delta = f" ({new[net] - p:+d})" if isinstance(p, int) else ""
        print(f"  {net:<10} {br(new[net]):>8}  → {fmt_seg(new[net])}{delta}")
    print(f"  {'total':<10} {br(new['total']):>8}  → {fmt_seg(new['total'])}")
    if new["views_30d"]:
        print(f"  {'views 30d':<10} {br(new['views_30d']):>8}")
    if new["reach_90d"]:
        print(f"  {'alcance90d':<10} {br(new['reach_90d']):>8}")

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
