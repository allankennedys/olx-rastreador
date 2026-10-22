#!/usr/bin/env python3
"""Verifica anúncios novos de video game na OLX e avisa no Telegram.

Feito para rodar de hora em hora (cron). Na primeira execução só registra o que
já existe, sem notificar, para não chegar mil mensagens de uma vez.

Configuração em .env (mesma pasta):
    TELEGRAM_TOKEN=123456:ABC...
    TELEGRAM_CHAT_ID=123456789,987654321   (vários destinatários, separados por vírgula)
"""
import argparse
import html
import json
import os
import sys
import time
from pathlib import Path

from curl_cffi import requests

from olx_games import CATEGORIAS, TERMOS_PADRAO, buscar_varios, lista, sem_acento

PASTA = Path(__file__).resolve().parent
ESTADO = PASTA / "vistos.json"


def carregar_env():
    env = PASTA / ".env"
    if env.exists():
        for linha in env.read_text().splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, valor = linha.split("=", 1)
                os.environ.setdefault(chave.strip(), valor.strip().strip('"'))


def legenda(a):
    preco = f"R$ {a['preco']:,.0f}".replace(",", ".") if a["preco"] else "sem preço"
    local = ", ".join(x for x in (a["bairro"], a["cidade"]) if x)
    linhas = [
        f"<b>{html.escape(a['titulo'])}</b>",
        f"💰 {preco}" + (f" (antes {a['preco_antigo']:,.0f})".replace(",", ".") if a["preco_antigo"] else ""),
        f"📍 {html.escape(local)}",
    ]
    if a["condicao"]:
        linhas.append(f"📦 {html.escape(a['condicao'])}")
    if a["aceita_troca"] == "Sim":
        linhas.append("🔄 Aceita troca")
    linhas.append(f'\n<a href="{html.escape(a["url"])}">Ver anúncio na OLX</a>')
    return "\n".join(linhas)


def assinatura(a):
    """Identifica o mesmo anúncio apagado e repostado (ganha id novo, mas o resto é igual)."""
    titulo = " ".join(sem_acento(a["titulo"]).split())
    return f"{titulo}|{a['preco']}|{sem_acento(a['cidade'])}|{sem_acento(a['bairro'])}"


def enviar(token, chat_id, a):
    api = f"https://api.telegram.org/bot{token}"
    texto = legenda(a)
    if a["fotos"]:
        r = requests.post(f"{api}/sendPhoto", data={
            "chat_id": chat_id, "photo": a["fotos"][0], "caption": texto, "parse_mode": "HTML",
        }, timeout=30)
        if r.ok:
            return
    # sem foto, ou o Telegram não conseguiu baixar a imagem
    r = requests.post(f"{api}/sendMessage", data={
        "chat_id": chat_id, "text": texto, "parse_mode": "HTML",
    }, timeout=30)
    if r.status_code == 429:
        espera = r.json().get("parameters", {}).get("retry_after", 30)
        time.sleep(espera)
        return enviar(token, chat_id, a)
    if not r.ok:
        raise RuntimeError(f"Telegram respondeu {r.status_code}: {r.text[:200]}")


def main():
    p = argparse.ArgumentParser(description="Avisa no Telegram sobre anúncios novos de video game na OLX.")
    p.add_argument("termos", nargs="*", help="termos de busca (padrão: lista de consoles)")
    p.add_argument("-c", "--categoria", choices=CATEGORIAS, default="todos",
                   help="todos = categoria Games (padrão); qualquer = toda a OLX, traz switch de rede, teclado etc.")
    p.add_argument("--cidades", help='só essas cidades, separadas por vírgula, ex: "Feira de Santana, Serrinha"')
    p.add_argument("--bairros", help='só esses bairros, ex: "Centro, Tomba, Santa Mônica"')
    p.add_argument("--so-feira", action="store_true")
    p.add_argument("--min", type=int, dest="preco_min")
    p.add_argument("--max", type=int, dest="preco_max")
    p.add_argument("-p", "--paginas", type=int, default=2,
                   help="páginas por termo; como ordena por recentes, 2 cobre bem uma hora (padrão 2)")
    p.add_argument("--teste", action="store_true", help="manda o anúncio mais recente para testar o bot")
    args = p.parse_args()

    carregar_env()
    token = os.environ.get("TELEGRAM_TOKEN")
    chats = [c.strip() for c in os.environ.get("TELEGRAM_CHAT_ID", "").split(",") if c.strip()]
    if not token or not chats:
        sys.exit("Defina TELEGRAM_TOKEN e TELEGRAM_CHAT_ID no arquivo .env")

    log = lambda msg: print(msg, file=sys.stderr)
    primeira_vez = not ESTADO.exists()
    anuncios = buscar_varios(
        args.termos or TERMOS_PADRAO,
        ordem="recentes",
        categoria=args.categoria,
        cidade="feira-de-santana" if args.so_feira else None,
        cidades=lista(args.cidades),
        bairros=lista(args.bairros),
        paginas=100 if primeira_vez else args.paginas,
        preco_min=args.preco_min,
        preco_max=args.preco_max,
        log=log,
    )

    if not anuncios and not (args.cidades or args.bairros):
        sys.exit("A OLX não devolveu nenhum anúncio (bloqueio do Cloudflare?)")

    if args.teste:
        for chat_id in chats:
            enviar(token, chat_id, anuncios[0])
        log(f"mensagem de teste enviada para {len(chats)} contato(s)")
        return

    # vistos guarda ids (int) e assinaturas (str) no mesmo conjunto
    vistos = set(json.loads(ESTADO.read_text())) if not primeira_vez else set()
    for a in anuncios:
        if a["id"] in vistos:
            vistos.add(assinatura(a))  # completa o registro antigo, que só tinha ids
    novos = [a for a in anuncios if a["id"] not in vistos]

    if primeira_vez:
        vistos |= {a["id"] for a in novos} | {assinatura(a) for a in novos}
        log(f"primeira execução: {len(novos)} anúncios registrados, sem notificar")
    else:
        # mais antigo primeiro, assim o mais recente fica no fim da conversa
        enviados = 0
        for a in reversed(novos):
            if assinatura(a) in vistos:
                log(f"  repostagem ignorada: {a['titulo']} ({a['id']})")
                vistos.add(a["id"])
                continue
            entregues = 0
            for chat_id in chats:
                try:
                    enviar(token, chat_id, a)
                    entregues += 1
                except Exception as e:
                    log(f"falha ao enviar {a['id']} para {chat_id}: {e}")
            if not entregues:
                continue  # fica fora dos vistos e tenta de novo na próxima hora
            vistos |= {a["id"], assinatura(a)}
            enviados += 1
            salvar_estado(vistos)  # a cada envio, para não repetir se o PC desligar no meio
            time.sleep(1.2)
        log(f"{enviados} anúncios novos notificados")

    salvar_estado(vistos)


def salvar_estado(vistos):
    # grava num temporário e renomeia: se cair a energia no meio, o arquivo antigo continua inteiro
    tmp = ESTADO.with_suffix(".tmp")
    tmp.write_text(json.dumps(sorted(vistos, key=str)))
    tmp.replace(ESTADO)


if __name__ == "__main__":
    main()
