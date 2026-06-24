# RSS do blog Maxfinance

Gera automaticamente um feed RSS a partir de https://www.maxfinance.pt/pt-pt/blog.
Corre uma vez por dia no GitHub Actions, sem custos.

## O que está aqui

- `generate_rss.py` — vai à página do blog, apanha os artigos e escreve o `rss.xml`.
- `.github/workflows/rss.yml` — corre o script todos os dias e faz commit do feed.
- `requirements.txt` — as dependências.

## Como pôr a funcionar (5 minutos)

1. Cria um repositório novo no GitHub (podes deixá-lo **público** para nem tocar na quota,
   ou **privado** — também fica de borla, gasta uns ~30 min/mês contra os 2.000 incluídos).

2. Mete lá estes ficheiros (arrasta para o site do GitHub ou usa `git push`).

3. Vai a **Settings → Actions → General**, secção *Workflow permissions*, e confirma que está em
   **Read and write permissions**. É o que deixa o robô gravar o `rss.xml` sozinho.

4. Vai ao separador **Actions**, escolhe o workflow e carrega em **Run workflow** para correr
   já uma vez à mão e gerar o primeiro `rss.xml`. Daí para a frente corre sozinho às 06:00 UTC.

## Onde fica o feed (o link para dar a quem precisa)

Depois da primeira corrida, o `rss.xml` aparece na raiz do repositório. Tens duas formas de o servir:

**Opção simples — link direto do GitHub:**
```
https://raw.githubusercontent.com/<o-teu-utilizador>/<o-repo>/main/rss.xml
```

**Opção mais limpa — GitHub Pages:**
Vai a **Settings → Pages**, escolhe a branch `main` e a pasta `/ (root)`, grava.
Passados uns minutos o feed fica em:
```
https://<o-teu-utilizador>.github.io/<o-repo>/rss.xml
```

## Mudar a hora

No `rss.yml`, a linha `- cron: "0 6 * * *"` é `minuto hora * * *`, **em UTC**.
Por exemplo, para correr às 08:00 de Lisboa no inverno mete `"0 8 * * *"`.
Nota: nas horas de pico o GitHub às vezes atrasa o arranque uns minutos — para um feed diário é irrelevante.

## Se um dia parar de funcionar

O site corre em Drupal e a estrutura é estável, mas se a Maxfinance mudar o layout do blog
o script pode deixar de apanhar os artigos (vais ver o erro "não encontrei artigos" no Actions).
Nesse caso é só ajustar os seletores no `generate_rss.py`.
