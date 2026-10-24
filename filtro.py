"""Decide se um anúncio vale aviso: só consoles (inclusive com defeito), controles e
lotes de console + jogos. Jogo avulso, carta, cabo, fonte, VR, volante etc. ficam de fora.

A ideia é olhar o "objeto" do anúncio, que quase sempre é a primeira palavra do
título ("Fonte nintendo switch" é uma fonte, "Xbox 360 + 80 jogos" é um console),
junto com a categoria e o preço.
"""
import re

from olx_games import sem_acento

# vetado em qualquer lugar do título
VETO = re.compile(r"\b(" + "|".join([
    r"pokemon", r"cartas?", r"tcg", r"booster", r"yu-?gi-?oh",
    r"vr2?", r"psvr2?", r"realidade virtual", r"oculos", r"meta quest", r"quest [23]s?",
    r"volante", r"headset", r"fones?", r"pulse", r"cockpit", r"cadeira",
    r"balance board", r"strap", r"grip", r"remoto", r"portao",
    r"conserto de", r"manutencao", r"assistencia",
]) + r")\b")

# primeira palavra que diz que o anúncio é acessório, mídia ou jogo
ACESSORIO_NO_INICIO = re.compile(r"(" + "|".join([
    r"cabos?", r"fios?", r"fontes?", r"carregador\w*", r"bases?", r"suportes?", r"dock",
    r"skins?", r"capas?", r"case", r"pelicula\w*", r"adesivos?", r"bolsas?", r"mochila",
    r"adaptador\w*", r"conversor\w*", r"hd", r"ssd", r"cartao", r"memor\w* card", r"pen ?drive",
    r"jogos?", r"games? de", r"lote de jogos", r"cartuchos?", r"fitas?", r"cds?", r"dvds?",
    r"midias?", r"pecas?", r"botao", r"botoes", r"tampas?", r"caixas?", r"kinect", r"analogicos?", r"gatilhos?", r"carcaca", r"cooler",
    r"ventoinha", r"leitor", r"placa", r"tela", r"display", r"bateria",
]) + r")\b")

CONSOLE_NO_INICIO = re.compile(r"(" + "|".join([
    r"ps ?[1-5]", r"ps ?one", r"ps ?vita", r"psp", r"playstation", r"play ?station", r"play [1-5]\b",
    r"xbox", r"x-?box", r"nintendo", r"switch", r"wii", r"snes", r"super nintendo", r"nes", r"n64",
    r"game ?cube", r"game ?boy", r"gba", r"[23]ds", r"dsi?", r"mega ?drive", r"master system",
    r"dreamcast", r"sega", r"saturn", r"atari", r"steam deck", r"rog ally", r"legion go",
    r"video ?-?game", r"console", r"game stick", r"retro ?game",
]) + r")\b")

CONTROLE = re.compile(r"\b(" + "|".join([
    r"controles?", r"controladora?", r"joysticks?", r"gamepad", r"manete",
    r"dual ?sense", r"dual ?shock", r"joy-?cons?", r"pro controller",
    r"controller", r"game ?sir", r"8 ?bit ?do", r"flydigi", r"easysmx", r"machenike",
]) + r")\b")

DEFEITO = re.compile(r"\b(pecas|defeito|conserto|nao liga|queimad[oa]|problema|retirada|sucata)\b")

# palavras de enfeite antes do objeto: "Vendo", "(Promoção até 28/10)", "Oportunidade!", emoji
ENFEITE = re.compile(r"^(?:[^\w(]+|\([^)]*\)\s*|(?:vendo|vende-?se|vende|troco|oportunidade|promocao|oferta|"
                     r"lindo|linda|novo|nova|seminovo|semi-novo|meu|minha|um|uma|o|a)\b)+")

CONSOLE_BARATO = 250  # abaixo disso, "PS4 ..." fora da categoria Consoles costuma ser jogo


def motivo_veto(a):
    """None se o anúncio deve ser enviado; senão, uma palavra explicando o veto."""
    titulo = " ".join(sem_acento(a["titulo"]).split())
    objeto = ENFEITE.sub("", titulo)
    categoria = sem_acento(a.get("categoria"))
    preco = a.get("preco")
    defeito = bool(DEFEITO.search(titulo))

    if CONTROLE.match(objeto) and not re.search(r"\b(remoto|portao)\b", titulo):
        return None  # "Controle Xbox Pulse Red" é controle, não headset
    if categoria and "video game" not in categoria:
        return "fora de Games"  # "Switch Cisco", "Console Mesa de Som"
    if VETO.search(titulo):
        return "veto"
    if ACESSORIO_NO_INICIO.match(objeto):
        return "acessório/jogo"
    if CONSOLE_NO_INICIO.match(objeto):
        if categoria.startswith("consoles") or defeito or CONTROLE.search(objeto) or preco is None or preco >= CONSOLE_BARATO:
            return None
        return "barato demais p/ console"
    if CONTROLE.search(titulo):
        return None
    if categoria.startswith("consoles") and (defeito or preco is None or preco >= 120):
        return None
    return "não é console nem controle"
