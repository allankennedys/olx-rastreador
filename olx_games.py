#!/usr/bin/env python3
"""Scraper de anúncios de video game da OLX na região de Feira de Santana (BA).

A OLX fica atrás do Cloudflare, então a requisição usa curl_cffi imitando o
Chrome. Os anúncios vêm no payload RSC do Next.js (self.__next_f.push), não no
HTML renderizado.
"""
import argparse
import csv
import json
import random
import re
import sys
import time
import unicodedata
from datetime import datetime
from pathlib import Path

from curl_cffi import requests

BASE = "https://www.olx.com.br"
REGIAO = "estado-ba/regiao-de-feira-de-santana-e-alagoinhas"
# a OLX passou a ignorar a região na URL e devolver a Bahia inteira; as regiões
# dela são por DDD, então os anúncios de fora são descartados aqui
DDD_REGIAO = "75"
CATEGORIAS = {
    "qualquer": "",  # toda a OLX, pega também quem anunciou fora de Games
    "todos": "games",
    "consoles": "games/consoles-de-video-game",
    "jogos": "games/jogos-de-video-game",
    "acessorios": "games/acessorios-de-video-game",
}
TERMOS_PADRAO = [
    "ps5", "playstation 5", "ps4", "playstation 4", "ps3", "ps2", "playstation",
    "xbox series", "xbox one", "xbox 360", "xbox", "nintendo switch", "switch",
    "nintendo", "video game", "videogame", "console",
    # controles; "controle" sozinho traz controle de TV e de portão
    "controle ps5", "dualsense", "controle ps4", "dualshock", "controle ps3",
    "controle xbox", "controle xbox series", "controle xbox one", "controle xbox 360",
    "controle switch", "joy-con", "joycon", "pro controller", "controle nintendo",
    "controle video game", "controle videogame", "controle playstation", "gamesir", "8bitdo",
]
NAVEGADORES = ["chrome", "edge", "safari"]  # o Cloudflare às vezes barra uma assinatura e libera outra
MAX_PAGINAS = 100  # a OLX não serve além da página 100
CAMPOS = [
    "id", "titulo", "termos", "preco", "preco_antigo", "categoria", "marca", "modelo",
    "condicao", "aceita_troca", "cidade", "bairro", "profissional",
    "publicado_em", "fotos", "url",
]


def montar_url(categoria, cidade, busca, pagina, recentes, preco_min, preco_max):
    partes = [BASE]
    if CATEGORIAS[categoria]:
        partes.append(CATEGORIAS[categoria])
    partes.append(REGIAO)
    if cidade:
        partes.append(cidade)
    params = {}
    if busca:
        params["q"] = busca
    if recentes:
        params["sf"] = "1"
    if preco_min is not None:
        params["ps"] = str(preco_min)
    if preco_max is not None:
        params["pe"] = str(preco_max)
    if pagina > 1:
        params["o"] = str(pagina)
    url = "/".join(partes)
    if params:
        url += "?" + "&".join(f"{k}={requests.utils.quote(v)}" for k, v in params.items())
    return url


def extrair_listagem(html):
    """Remonta o payload RSC e devolve o objeto que contém a lista de anúncios."""
    pedacos = re.findall(r"self\.__next_f\.push\((\[.*?\])\)</script>", html, re.S)
    flight = ""
    for p in pedacos:
        item = json.loads(p)
        if item[0] == 1:
            flight += item[1]
    inicio = flight.find('{"ads":[')
    if inicio < 0:
        return None
    obj, _ = json.JSONDecoder().raw_decode(flight, inicio)
    return obj


def normalizar(ad):
    props = {p["name"]: p["value"] for p in ad.get("properties") or []}
    loc = ad.get("locationDetails") or {}
    return {
        "id": ad["listId"],
        "titulo": ad["subject"].strip(),
        "preco": preco_para_numero(ad.get("price") or ad.get("priceValue")),
        "preco_antigo": preco_para_numero(ad.get("oldPrice")),
        "categoria": ad.get("category"),
        "marca": props.get("games_console_brand"),
        "modelo": props.get("games_consoles_model"),
        "condicao": props.get("condition_full") or props.get("condition"),
        "aceita_troca": props.get("exchange"),
        "cidade": loc.get("municipality"),
        "bairro": loc.get("neighbourhood"),
        "profissional": ad.get("professionalAd"),
        "publicado_em": datetime.fromtimestamp(ad["date"]).isoformat(timespec="minutes") if ad.get("date") else None,
        "fotos": [i["original"] for i in ad.get("images") or []],
        "url": ad["url"],
    }


def preco_para_numero(texto):
    if not texto:
        return None
    digitos = re.sub(r"[^\d,]", "", texto).replace(",", ".")
    return float(digitos) if digitos else None


def buscar(categoria="todos", cidade=None, busca=None, paginas=1, recentes=True,
           preco_min=None, preco_max=None, pausa=(1.5, 3.5), log=print):
    def nova_sessao(navegador):
        s = requests.Session(impersonate=navegador)
        s.headers.update({"Accept-Language": "pt-BR,pt;q=0.9"})
        return s

    sessao = nova_sessao("chrome")
    vistos, anuncios = set(), []
    for pagina in range(1, min(paginas, MAX_PAGINAS) + 1):
        url = montar_url(categoria, cidade, busca, pagina, recentes, preco_min, preco_max)
        for tentativa in range(4):
            try:
                r = sessao.get(url, timeout=30)
                status = r.status_code
            except requests.errors.RequestsError as e:
                status = type(e).__name__
            if status == 200:
                break
            log(f"  HTTP {status} em {url}, tentando de novo...")
            if status == 403:
                sessao = nova_sessao(NAVEGADORES[(tentativa + 1) % len(NAVEGADORES)])
            time.sleep(5 * (tentativa + 1))
        else:
            if anuncios:
                # a OLX às vezes dá 504 no meio; fica com as páginas que já vieram
                log(f"  desisti da página {pagina}, mantendo {len(anuncios)} anúncios")
                break
            raise RuntimeError(f"OLX bloqueou ou falhou: HTTP {status} em {url}")

        dados = extrair_listagem(r.text)
        if dados is None:
            raise RuntimeError(f"Não achei a lista de anúncios em {url} (layout da OLX mudou?)")
        novos = [a for a in dados["ads"] if a.get("subject") and a.get("listId") not in vistos]
        if pagina == 1:
            log(f"{dados.get('totalOfAds', '?')} anúncios encontrados")
        log(f"  página {pagina}: {len(novos)} anúncios")
        if not novos:
            break
        for ad in novos:
            vistos.add(ad["listId"])
            if (ad.get("locationDetails") or {}).get("ddd") != DDD_REGIAO:
                continue
            anuncio = normalizar(ad)
            anuncio["posicao"] = len(anuncios)
            anuncios.append(anuncio)
        if len(dados["ads"]) < dados.get("pageSize", 50):
            break
        time.sleep(random.uniform(*pausa))
    return anuncios


def sem_acento(texto):
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).casefold().strip()


def lista(texto):
    """'Centro, Tomba' -> {'centro', 'tomba'}; None/'' -> None (sem filtro)."""
    itens = {sem_acento(x) for x in (texto or "").split(",") if x.strip()}
    return itens or None


def filtrar_local(anuncios, cidades=None, bairros=None):
    """A OLX só filtra até a cidade; bairro e várias cidades são filtrados aqui."""
    return [
        a for a in anuncios
        if (not cidades or sem_acento(a["cidade"]) in cidades)
        and (not bairros or sem_acento(a["bairro"]) in bairros)
    ]


def buscar_varios(termos, ordem="recentes", cidades=None, bairros=None, log=print, **kwargs):
    """Roda uma busca por termo e junta tudo sem repetir anúncio.

    Em "relevancia", cada anúncio fica com a melhor posição que teve em
    qualquer uma das buscas; em "recentes", ordena pela data de publicação.
    """
    juntos = {}
    for termo in termos:
        log(f"[{termo or 'sem termo'}]")
        try:
            resultado = buscar(busca=termo, recentes=(ordem == "recentes"), log=log, **kwargs)
        except RuntimeError as e:
            log(f"  pulando: {e}")
            continue
        for a in resultado:
            existente = juntos.get(a["id"])
            if existente:
                existente["termos"].append(termo)
                existente["posicao"] = min(existente["posicao"], a["posicao"])
            else:
                a["termos"] = [termo]
                juntos[a["id"]] = a
        log(f"  total acumulado: {len(juntos)} anúncios únicos")
    anuncios = filtrar_local(list(juntos.values()), cidades, bairros)
    if cidades or bairros:
        log(f"  {len(anuncios)} de {len(juntos)} dentro das cidades/bairros escolhidos")
    if ordem == "recentes":
        anuncios.sort(key=lambda a: a["publicado_em"] or "", reverse=True)
    else:
        anuncios.sort(key=lambda a: (a["posicao"], -len(a["termos"])))
    for a in anuncios:
        del a["posicao"]
    return anuncios


def salvar(anuncios, caminho):
    caminho = Path(caminho)
    if caminho.suffix == ".json":
        caminho.write_text(json.dumps(anuncios, ensure_ascii=False, indent=2))
    else:
        with caminho.open("w", newline="", encoding="utf-8-sig") as f:
            w = csv.DictWriter(f, fieldnames=CAMPOS)
            w.writeheader()
            for a in anuncios:
                w.writerow({**a, "fotos": " ".join(a["fotos"]), "termos": ", ".join(a["termos"])})


def filtrar_ja_vistos(anuncios, arquivo_estado):
    """Mantém só anúncios que não apareceram em execuções anteriores."""
    estado = Path(arquivo_estado)
    vistos = set(json.loads(estado.read_text())) if estado.exists() else set()
    novos = [a for a in anuncios if a["id"] not in vistos]
    estado.write_text(json.dumps(sorted(vistos | {a["id"] for a in anuncios})))
    return novos


def main():
    p = argparse.ArgumentParser(description="Busca video games à venda na OLX (região de Feira de Santana).")
    p.add_argument("termos", nargs="*", help='termos de busca, ex: ps5 "xbox series s" (padrão: lista de consoles)')
    p.add_argument("-c", "--categoria", choices=CATEGORIAS, default="qualquer",
                   help="qualquer = toda a OLX (padrão); todos = só a categoria Games")
    p.add_argument("--cidades", help='só essas cidades, separadas por vírgula, ex: "Feira de Santana, Serrinha"')
    p.add_argument("--bairros", help='só esses bairros, ex: "Centro, Tomba, Santa Mônica"')
    p.add_argument("--so-feira", action="store_true", help="só a cidade de Feira de Santana (padrão: região toda)")
    p.add_argument("-p", "--paginas", type=int, default=MAX_PAGINAS, help="páginas por termo, 50 anúncios cada (padrão: todas, máx 100)")
    p.add_argument("--min", type=int, dest="preco_min", help="preço mínimo em R$")
    p.add_argument("--max", type=int, dest="preco_max", help="preço máximo em R$")
    p.add_argument("--ordem", choices=["recentes", "relevancia"], default="recentes")
    p.add_argument("-o", "--saida", help="arquivo .csv ou .json (padrão: imprime no terminal)")
    p.add_argument("--novos", metavar="ESTADO", help="arquivo de estado; mostra só anúncios ainda não vistos")
    args = p.parse_args()

    log = lambda msg: print(msg, file=sys.stderr)
    anuncios = buscar_varios(
        args.termos or TERMOS_PADRAO,
        ordem=args.ordem,
        categoria=args.categoria,
        cidade="feira-de-santana" if args.so_feira else None,
        cidades=lista(args.cidades),
        bairros=lista(args.bairros),
        paginas=args.paginas,
        preco_min=args.preco_min,
        preco_max=args.preco_max,
        log=log,
    )
    log(f"{len(anuncios)} anúncios únicos no total")
    if args.novos:
        anuncios = filtrar_ja_vistos(anuncios, args.novos)
        log(f"{len(anuncios)} anúncios novos desde a última execução")

    if args.saida:
        salvar(anuncios, args.saida)
        log(f"{len(anuncios)} anúncios salvos em {args.saida}")
    else:
        for a in anuncios:
            preco = f"R$ {a['preco']:,.0f}".replace(",", ".") if a["preco"] else "sem preço"
            print(f"{(a['publicado_em'] or '')[:16]:<16}  {preco:>11}  {a['titulo'][:55]:<55}  {a['cidade'] or ''}/{a['bairro'] or ''}")
            print(f"{'':>29}  {a['url']}")


if __name__ == "__main__":
    main()
