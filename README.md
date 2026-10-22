# OLX Games — Feira de Santana

Busca anúncios de video game na OLX (região de Feira de Santana e Alagoinhas).

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt

.venv/bin/python olx_games.py ps5                              # imprime no terminal
.venv/bin/python olx_games.py ps5 -c consoles --so-feira --max 3000
.venv/bin/python olx_games.py -c jogos -p 10 -o jogos.csv      # 10 páginas → CSV
.venv/bin/python olx_games.py xbox -o xbox.json
.venv/bin/python olx_games.py ps4 --novos estado.json          # só anúncios ainda não vistos
```

Opções: `-c todos|consoles|jogos|acessorios`, `--so-feira`, `-p N` (50/página, máx 100),
`--min/--max` (R$), `--relevancia` (padrão é mais recentes), `-o arquivo.csv|.json`, `--novos ESTADO`.

Como funciona: `curl_cffi` imita o TLS do Chrome para passar pelo Cloudflare, e os anúncios
são lidos do payload RSC do Next.js (`self.__next_f.push`) na página de listagem.

## Vários termos de uma vez

Sem termos, usa a lista padrão (ps5, ps4, xbox, switch, video game, console...) e percorre todas as páginas:

```bash
.venv/bin/python olx_games.py -o games.csv                       # tudo, mais recentes primeiro
.venv/bin/python olx_games.py --ordem relevancia -o games.csv
.venv/bin/python olx_games.py ps5 "xbox series" -o novos.csv     # termos próprios
```

## Aviso no Telegram (monitor.py)

1. Crie um bot com o @BotFather e copie o token.
2. Mande qualquer mensagem para o bot e pegue seu chat id em
   `https://api.telegram.org/bot<TOKEN>/getUpdates` (campo `chat.id`).
3. Crie o `.env`:
   ```
   TELEGRAM_TOKEN=123456:ABC...
   TELEGRAM_CHAT_ID=123456789
   ```
4. `.venv/bin/python monitor.py --teste` manda um anúncio para conferir.
5. `.venv/bin/python monitor.py` uma vez para registrar o que já existe (não notifica).
6. Cron de hora em hora (`crontab -e`):
   ```
   0 * * * * cd /home/kennedy/olx-games-scraper && .venv/bin/python monitor.py >> monitor.log 2>&1
   ```
